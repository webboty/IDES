from __future__ import annotations

from typing import Any

import pdfplumber

from ides.config import AppConfig
from ides.models import PageClassification
from ides.pipeline.page_plan import (
    classify_page,
    get_layers_for_classification,
    is_boilerplate,
)


async def classify_all_pages(
    pdf_path: str,
    config: AppConfig,
    ocr_extractor: Any = None,
    llm_client: Any = None,
) -> list[PageClassification]:
    results: list[PageClassification] = []

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            tables = page.extract_tables() or []
            char_count = len(text.strip())
            has_tables = len(tables) > 0

            classification = classify_page(char_count, has_tables, config.thresholds)

            if classification != "boilerplate":
                if is_boilerplate(text, config.extraction.boilerplate_patterns):
                    classification = "boilerplate"

            skipped = classification == "boilerplate"
            layers_needed = get_layers_for_classification(classification)

            results.append(
                PageClassification(
                    page_num=i + 1,
                    classification=classification,
                    char_count=char_count,
                    has_tables=has_tables,
                    layers_needed=layers_needed,
                    skipped=skipped,
                )
            )

    if ocr_extractor:
        for pc in results:
            if pc.classification in ("scanned",) and not pc.skipped:
                try:
                    ocr_text = await ocr_extractor.quick_ocr(pdf_path, pc.page_num)
                    if len(ocr_text.strip()) < 10:
                        pc.classification = "image_only"
                        pc.layers_needed = get_layers_for_classification("image_only")
                except Exception:
                    pass

    if config.extraction.skip_boilerplate and llm_client:
        from ides.llm.prompts import BOILERPLATE_PROMPT

        for pc in reversed(results):
            if pc.skipped:
                continue
            try:
                text = _get_page_text(pdf_path, pc.page_num)
                if not text:
                    break
                prompt = BOILERPLATE_PROMPT.format(content=text[:500])
                model_cfg = {
                    "provider": config.models.filter.provider,
                    "name": config.models.filter.name,
                    "max_tokens": config.models.filter.max_tokens,
                }
                response = await llm_client.chat(
                    model_cfg, [{"role": "user", "content": prompt}]
                )
                if "BOILERPLATE" in response.upper():
                    pc.skipped = True
                    pc.classification = "boilerplate"
                    pc.layers_needed = []
                else:
                    break
            except Exception:
                break

    return results


def _get_page_text(pdf_path: str, page_num: int) -> str:
    try:
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[page_num - 1]
            return page.extract_text() or ""
    except Exception:
        return ""
