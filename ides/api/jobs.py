from __future__ import annotations

import base64
import json
import uuid
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from ides.models import (
    ExtractOptions,
    ExtractRequestJSON,
    JobDetailResponse,
    JobResponse,
    JobResultResponse,
    JobStatusResponse,
    MetadataInfo,
    PageDetail,
    ProgressInfo,
)
from ides.storage.file_store import FileStore
from ides.utils.pdf_ops import get_page_count

import aiosqlite

router = APIRouter()


def _get_deps(request: Request) -> tuple[aiosqlite.Connection, FileStore, Any]:
    db = request.app.state.db
    file_store = request.app.state.file_store
    config = request.app.state.config
    return db, file_store, config


@router.post("/extract", response_model=JobResponse)
async def extract_pdf(request: Request):
    db, file_store, config = _get_deps(request)
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        body = await request.json()
        data = ExtractRequestJSON(**body)
        pdf_bytes = base64.b64decode(data.file_base64)
        filename = data.filename
        options = ExtractOptions(
            pages=data.pages,
            prompt=data.prompt,
            merge_prompt=data.merge_prompt,
            lang=data.lang,
            skip_boilerplate=data.skip_boilerplate,
            agent_model=data.agent_model,
            agent_provider=data.agent_provider,
            opencode_skills=data.opencode_skills,
        )
    else:
        form = await request.form()
        file = form.get("file")
        if not file or not hasattr(file, "read"):
            raise HTTPException(400, "No file provided")
        pdf_bytes = await file.read()
        filename = getattr(file, "filename", "document.pdf") or "document.pdf"
        options = ExtractOptions(
            pages=form.get("pages", "all")
            if isinstance(form.get("pages"), str)
            else "all",
            prompt=form.get("prompt") if isinstance(form.get("prompt"), str) else None,
            merge_prompt=form.get("merge_prompt")
            if isinstance(form.get("merge_prompt"), str)
            else None,
            lang=form.get("lang") if isinstance(form.get("lang"), str) else None,
            skip_boilerplate=form.get("skip_boilerplate", "true").lower() == "true"
            if form.get("skip_boilerplate")
            else True,
            agent_model=form.get("agent_model")
            if isinstance(form.get("agent_model"), str)
            else None,
            agent_provider=form.get("agent_provider")
            if isinstance(form.get("agent_provider"), str)
            else None,
            opencode_skills=json.loads(form["opencode_skills"])
            if form.get("opencode_skills")
            and isinstance(form.get("opencode_skills"), str)
            else [],
        )

    if not pdf_bytes:
        raise HTTPException(400, "Empty file")

    max_bytes = config.extraction.max_file_size_mb * 1024 * 1024
    if len(pdf_bytes) > max_bytes:
        raise HTTPException(
            400,
            f"File too large: {len(pdf_bytes) // (1024 * 1024)} MB, "
            f"max is {config.extraction.max_file_size_mb} MB",
        )

    try:
        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_count = len(doc)
        doc.close()
    except Exception:
        raise HTTPException(400, "Invalid PDF file")

    if page_count > config.extraction.max_pages:
        raise HTTPException(
            400, f"PDF has {page_count} pages, max is {config.extraction.max_pages}"
        )

    job_id = uuid.uuid4().hex[:24]
    storage_path = file_store.create_job_dir(job_id)
    file_store.save_original(storage_path, pdf_bytes)
    file_store.save_meta(
        storage_path,
        {
            "filename": filename,
            "options": options.model_dump(),
            "page_count": page_count,
        },
    )

    from ides.storage.job_store import create_job

    await create_job(
        db,
        job_id,
        filename,
        storage_path,
        options.model_dump(),
        config.retry.max_attempts,
    )

    return JobResponse(job_id=job_id, status="pending")


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str, request: Request):
    db, file_store, config = _get_deps(request)

    from ides.storage.job_store import get_job as _get_job

    job = await _get_job(db, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    retry_history = json.loads(job.get("retry_history") or "[]")
    layers_stats = json.loads(job.get("layers_stats") or "{}")

    return JobStatusResponse(
        job_id=job["id"],
        status=job["status"],
        attempt=job.get("attempt", 1),
        max_attempts=job.get("max_attempts", 3),
        progress=ProgressInfo(
            current_page=job.get("progress_current", 0),
            total_pages=job.get("progress_total", 0),
            pages_skipped=job.get("pages_skipped", 0),
            layers_stats=layers_stats,
        ),
        retry_history=retry_history,
        opencode_session_id=job.get("opencode_session_id"),
        created_at=job.get("created_at", ""),
        updated_at=job.get("updated_at", ""),
    )


@router.get("/jobs/{job_id}/result", response_model=JobResultResponse)
async def get_job_result(job_id: str, request: Request):
    db, file_store, config = _get_deps(request)

    from ides.storage.job_store import get_job as _get_job

    job = await _get_job(db, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if job["status"] != "completed":
        return JobResultResponse(
            job_id=job_id,
            status=job["status"],
            markdown="",
            metadata=MetadataInfo(),
        )

    markdown = file_store.load_final_markdown(job["storage_path"]) or ""
    summary = json.loads(job.get("result_summary") or "{}")

    return JobResultResponse(
        job_id=job_id,
        status="completed",
        markdown=markdown,
        metadata=MetadataInfo(
            pages_processed=summary.get("pages_processed", 0),
            pages_skipped=summary.get("pages_skipped", 0),
            total_time_seconds=summary.get("total_time_seconds", 0),
            opencode_session_id=job.get("opencode_session_id"),
        ),
    )


@router.get("/jobs/{job_id}/detail", response_model=JobDetailResponse)
async def get_job_detail(job_id: str, request: Request):
    db, file_store, config = _get_deps(request)

    from ides.storage.job_store import get_job as _get_job

    job = await _get_job(db, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if job["status"] != "completed":
        return JobDetailResponse(job_id=job_id, status=job["status"])

    detail = file_store.load_result_detail(job["storage_path"])
    if not detail:
        return JobDetailResponse(job_id=job_id, status=job["status"])

    pages = [PageDetail(**p) for p in detail.get("pages", [])]
    images = detail.get("images", [])

    return JobDetailResponse(
        job_id=job_id,
        status="completed",
        markdown=detail.get("markdown", ""),
        pages=pages,
        images=images,
        opencode_session_id=job.get("opencode_session_id"),
        metadata=detail.get("metadata", {}),
    )
