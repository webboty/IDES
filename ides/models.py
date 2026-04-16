from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ExtractOptions(BaseModel):
    pages: str = "all"
    prompt: str | None = None
    merge_prompt: str | None = None
    lang: str | None = None
    skip_boilerplate: bool = True
    agent_model: str | None = None
    agent_provider: str | None = None
    opencode_skills: list[str] = Field(default_factory=list)


class ExtractRequestJSON(BaseModel):
    file_base64: str
    filename: str = "document.pdf"
    pages: str = "all"
    prompt: str | None = None
    merge_prompt: str | None = None
    lang: str | None = None
    skip_boilerplate: bool = True
    agent_model: str | None = None
    agent_provider: str | None = None
    opencode_skills: list[str] = Field(default_factory=list)


class JobResponse(BaseModel):
    job_id: str
    status: str


class ProgressInfo(BaseModel):
    current_page: int = 0
    total_pages: int = 0
    pages_skipped: int = 0
    layers_stats: dict[str, int] = Field(default_factory=dict)


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    attempt: int = 1
    max_attempts: int = 3
    progress: ProgressInfo = ProgressInfo()
    retry_history: list[dict[str, Any]] = Field(default_factory=list)
    opencode_session_id: str | None = None
    created_at: str = ""
    updated_at: str = ""


class MetadataInfo(BaseModel):
    pages_processed: int = 0
    pages_skipped: int = 0
    total_time_seconds: float = 0.0
    opencode_session_id: str | None = None


class JobResultResponse(BaseModel):
    job_id: str
    status: str
    markdown: str = ""
    metadata: MetadataInfo = MetadataInfo()


class LayerResult(BaseModel):
    text_layer: dict | None = None
    ocr: dict | None = None
    vision: dict | None = None


class PageDetail(BaseModel):
    page: int
    classification: str = ""
    layers_used: list[str] = Field(default_factory=list)
    skipped: bool = False
    layer_results: LayerResult = LayerResult()
    markdown: str = ""


class ImageDetail(BaseModel):
    page: int
    index: int
    description: str = ""


class JobDetailResponse(BaseModel):
    job_id: str
    status: str
    markdown: str = ""
    pages: list[PageDetail] = Field(default_factory=list)
    images: list[ImageDetail] = Field(default_factory=list)
    opencode_session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class APIKeyCreate(BaseModel):
    name: str
    owner: str
    allowed_ips: list[str] | None = None


class APIKeyResponse(BaseModel):
    id: str
    key: str
    key_prefix: str
    name: str
    owner: str


class APIKeyInfo(BaseModel):
    id: str
    key_prefix: str
    name: str
    owner: str
    is_active: bool = True
    allowed_ips: list[str] | None = None
    last_used_at: str | None = None
    expires_at: str | None = None


class PageClassification(BaseModel):
    page_num: int
    classification: str = "unknown"
    char_count: int = 0
    has_tables: bool = False
    layers_needed: list[str] = Field(default_factory=list)
    skipped: bool = False


class TextLayerResult(BaseModel):
    text: str = ""
    tables: list[list[list[str | None]]] = Field(default_factory=list)
    char_map: list[dict] = Field(default_factory=list)
    markdown: str = ""


class OCRResult(BaseModel):
    text: str = ""


class VisionResult(BaseModel):
    markdown: str = ""


class ImageExtractResult(BaseModel):
    images: list[dict[str, Any]] = Field(default_factory=list)


class ExtractionError(Exception):
    pass
