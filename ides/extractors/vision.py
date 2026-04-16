from __future__ import annotations

import base64
import io
from typing import Any

from pdf2image import convert_from_path

from ides.extractors.base import BaseExtractor
from ides.llm.client import LLMClient
from ides.llm.prompts import DEFAULT_VISION_PROMPT
from ides.models import VisionResult


class VisionExtractor(BaseExtractor):
    def __init__(self, llm_client: LLMClient, dpi: int = 200):
        self.llm_client = llm_client
        self.dpi = dpi

    async def extract(
        self,
        pdf_path: str,
        page_num: int,
        model_config: dict | None = None,
        prompt: str | None = None,
        **kwargs: Any,
    ) -> VisionResult:
        images = convert_from_path(
            pdf_path,
            dpi=self.dpi,
            first_page=page_num,
            last_page=page_num,
        )
        if not images:
            return VisionResult(markdown="")

        image = images[0]
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()

        effective_prompt = prompt or DEFAULT_VISION_PROMPT
        cfg = model_config or {}

        result = await self.llm_client.chat_with_image(cfg, b64, effective_prompt)
        return VisionResult(markdown=result)
