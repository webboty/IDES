from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from ides.agent.brain import FusionAgent
from ides.agent.tools import analyze_failure_simple
from ides.config import AppConfig
from ides.extractors.images import ImageExtractor
from ides.extractors.ocr import OCRExtractor
from ides.extractors.text_layer import TextLayerExtractor
from ides.extractors.vision import VisionExtractor
from ides.fusion.llm_merge import fuse_page
from ides.llm.client import LLMClient
from ides.models import ExtractionError, ExtractOptions
from ides.pipeline.prefilter import classify_all_pages
from ides.storage.file_store import FileStore
from ides.storage.job_store import (
    append_retry_history,
    get_job,
    store_result_summary,
    update_job,
)
from ides.utils.pdf_ops import get_page_count, parse_page_range, split_pdf_to_pages

import aiosqlite


def _fallback_fuse(classification: str, layer_results: dict[str, Any]) -> str:
    if classification == "boilerplate":
        return ""
    tl = layer_results.get("text_layer")
    if tl and isinstance(tl, dict) and tl.get("markdown"):
        return tl["markdown"]
    ocr = layer_results.get("ocr")
    if ocr and isinstance(ocr, dict) and ocr.get("text"):
        return ocr["text"]
    vis = layer_results.get("vision")
    if vis and isinstance(vis, dict) and vis.get("markdown"):
        return vis["markdown"]
    if tl and isinstance(tl, dict) and tl.get("text"):
        return tl["text"]
    return ""


async def run_pipeline(
    job: dict,
    config: AppConfig,
    file_store: FileStore,
    llm_client: LLMClient,
    db: aiosqlite.Connection,
    override_plan: dict | None = None,
) -> dict:
    job_id = job["id"]
    storage_path = job["storage_path"]
    options_raw = job.get("options")
    options = (
        ExtractOptions(**json.loads(options_raw)) if options_raw else ExtractOptions()
    )

    pdf_path = str(file_store.job_dir(job_id) / "original.pdf")
    total_pages = get_page_count(pdf_path)
    page_range = parse_page_range(options.pages, total_pages)

    await update_job(db, job_id, progress_total=len(page_range))

    ocr_extractor = OCRExtractor(
        dpi=config.extraction.dpi.ocr,
        languages=options.lang or config.extraction.ocr_languages,
    )
    text_extractor = TextLayerExtractor()
    vision_extractor = VisionExtractor(llm_client, dpi=config.extraction.dpi.vision)
    image_extractor = ImageExtractor(
        llm_client, min_image_size=config.thresholds.min_image_size
    )

    vision_provider = config.models.vision.provider
    merge_provider = options.agent_provider or config.models.merge.provider
    vision_ok = llm_client.is_available(vision_provider)
    merge_ok = llm_client.is_available(merge_provider)

    effective_llm_client = llm_client if merge_ok else None

    classifications = await classify_all_pages(
        pdf_path, config, ocr_extractor, effective_llm_client
    )
    classifications = [c for c in classifications if c.page_num in page_range]

    if override_plan and "page_overrides" in override_plan:
        for pc in classifications:
            override = override_plan["page_overrides"].get(str(pc.page_num))
            if override:
                pc.layers_needed = override.get("layers", pc.layers_needed)
                pc.skipped = override.get("skipped", pc.skipped)

    class_data = [c.model_dump() for c in classifications]
    file_store.save_classification(job_id, class_data)

    model_config = {
        "provider": options.agent_provider or config.models.merge.provider,
        "name": options.agent_model or config.models.merge.name,
        "max_tokens": config.models.merge.max_tokens,
    }
    vision_model = {
        "provider": config.models.vision.provider,
        "name": config.models.vision.name,
        "max_tokens": config.models.vision.max_tokens,
    }
    image_model = {
        "provider": config.models.image_describe.provider,
        "name": config.models.image_describe.name,
        "max_tokens": config.models.image_describe.max_tokens,
    }

    fusion_agent = (
        FusionAgent(
            llm_client,
            model_config,
            system_prompt=options.merge_prompt,
        )
        if merge_ok
        else None
    )

    pages_skipped = 0
    layers_stats: dict[str, int] = {}
    all_images: list[dict] = []
    page_details: list[dict] = []
    start_time = time.time()

    for idx, pc in enumerate(classifications):
        await update_job(db, job_id, progress_current=idx + 1)

        if pc.skipped:
            pages_skipped += 1
            page_details.append(
                {
                    "page": pc.page_num,
                    "classification": pc.classification,
                    "layers_used": [],
                    "skipped": True,
                    "layer_results": {"text_layer": None, "ocr": None, "vision": None},
                    "markdown": "",
                }
            )
            continue

        layer_results: dict[str, Any] = {}

        if "text_layer" in pc.layers_needed:
            try:
                tl = await text_extractor.extract(pdf_path, pc.page_num)
                layer_results["text_layer"] = {
                    "text": tl.text,
                    "markdown": tl.markdown,
                    "char_count": len(tl.text),
                    "tables_found": len(tl.tables),
                }
                file_store.save_layer_result(
                    job_id, pc.page_num, "text_layer", tl.model_dump()
                )
                layers_stats["text_layer"] = layers_stats.get("text_layer", 0) + 1
            except Exception as e:
                layer_results["text_layer_error"] = str(e)

        if "ocr" in pc.layers_needed:
            try:
                ocr = await ocr_extractor.extract(
                    pdf_path,
                    pc.page_num,
                    languages=options.lang or config.extraction.ocr_languages,
                )
                layer_results["ocr"] = {"text": ocr.text}
                file_store.save_layer_result(
                    job_id, pc.page_num, "ocr", ocr.model_dump()
                )
                layers_stats["ocr"] = layers_stats.get("ocr", 0) + 1
            except Exception as e:
                layer_results["ocr_error"] = str(e)

        if "vision" in pc.layers_needed and vision_ok:
            try:
                vis = await vision_extractor.extract(
                    pdf_path,
                    pc.page_num,
                    model_config=vision_model,
                    prompt=options.prompt,
                )
                layer_results["vision"] = {"markdown": vis.markdown}
                file_store.save_layer_result(
                    job_id, pc.page_num, "vision", vis.markdown
                )
                layers_stats["vision"] = layers_stats.get("vision", 0) + 1
            except Exception as e:
                layer_results["vision_error"] = str(e)

        try:
            img_dir = file_store.get_page_images_dir(job_id, pc.page_num)
            img_result = image_extractor.extract_images(pdf_path, pc.page_num, img_dir)
            if img_result.images:
                file_store.save_layer_result(
                    job_id, pc.page_num, "images", {"images": img_result.model_dump()}
                )
                all_images.extend(
                    [{"page": pc.page_num, **img} for img in img_result.images]
                )
        except Exception:
            pass

        page_markdown = ""
        try:
            page_markdown = await fuse_page(
                pc.classification, layer_results, fusion_agent, pc.page_num
            )
        except Exception:
            page_markdown = _fallback_fuse(pc.classification, layer_results)

        file_store.save_fusion_page(job_id, pc.page_num, page_markdown)

        page_details.append(
            {
                "page": pc.page_num,
                "classification": pc.classification,
                "layers_used": pc.layers_needed,
                "skipped": False,
                "layer_results": {
                    "text_layer": layer_results.get("text_layer"),
                    "ocr": layer_results.get("ocr"),
                    "vision": layer_results.get("vision"),
                },
                "markdown": page_markdown,
            }
        )

    final_markdown = "\n\n---\n\n".join(
        pd["markdown"] for pd in page_details if pd["markdown"]
    )

    total_time = time.time() - start_time

    detail = {
        "job_id": job_id,
        "status": "completed",
        "markdown": final_markdown,
        "pages": page_details,
        "images": all_images,
        "metadata": {
            "pages_processed": len(classifications) - pages_skipped,
            "pages_skipped": pages_skipped,
            "layers_stats": layers_stats,
            "total_time_seconds": round(total_time, 2),
            "storage_path": storage_path,
        },
    }

    file_store.save_final_result(job_id, final_markdown, detail)
    return detail


async def run_with_retry(
    job: dict,
    config: AppConfig,
    file_store: FileStore,
    llm_client: LLMClient,
    db: aiosqlite.Connection,
) -> None:
    job_id = job["id"]
    max_attempts = job.get("max_attempts", config.retry.max_attempts)

    for attempt in range(1, max_attempts + 1):
        try:
            status = "processing" if attempt == 1 else "retrying"
            await update_job(db, job_id, status=status, attempt=attempt)

            override_plan = None
            if attempt == 3 and job.get("last_error"):
                await update_job(db, job_id, status="recovering")
                recovery = analyze_failure_simple(
                    job["last_error"],
                    json.loads(job.get("retry_history") or "[]"),
                )
                await update_job(db, job_id, agent_recovery_plan=json.dumps(recovery))
                override_plan = recovery.get("adjusted_plan")

            result = await run_pipeline(
                job, config, file_store, llm_client, db, override_plan
            )
            await store_result_summary(db, job_id, result.get("metadata", {}))
            await update_job(
                db,
                job_id,
                status="completed",
                pages_skipped=result.get("metadata", {}).get("pages_skipped", 0),
                layers_stats=json.dumps(
                    result.get("metadata", {}).get("layers_stats", {})
                ),
            )
            return

        except Exception as e:
            from datetime import datetime, timezone

            error_record = {
                "attempt": attempt,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await append_retry_history(db, job_id, error_record)
            await update_job(db, job_id, last_error=str(e))

            if attempt < max_attempts:
                await asyncio.sleep(config.retry.backoff_base * attempt)
                job = await get_job(db, job_id) or job
                continue

    analysis = analyze_failure_simple(
        job.get("last_error", "Unknown"),
        json.loads(job.get("retry_history") or "[]"),
    )
    await update_job(
        db,
        job_id,
        status="failed",
        error_analysis=analysis.get("explanation", "No analysis available"),
    )
