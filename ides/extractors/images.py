from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import fitz

from ides.llm.client import LLMClient
from ides.llm.prompts import IMAGE_DESCRIBE_PROMPT
from ides.models import ImageExtractResult


class ImageExtractor:
    def __init__(self, llm_client: LLMClient, min_image_size: int = 100):
        self.llm_client = llm_client
        self.min_image_size = min_image_size

    def extract_images(
        self,
        pdf_path: str,
        page_num: int,
        output_dir: str | Path,
    ) -> ImageExtractResult:
        doc = fitz.open(pdf_path)
        page = doc[page_num - 1]
        images = page.get_images(full=True)

        img_dir = Path(output_dir)
        img_dir.mkdir(parents=True, exist_ok=True)

        results = []
        for idx, img in enumerate(images):
            xref = img[0]
            try:
                base_image = doc.extract_image(xref)
            except Exception:
                continue
            if base_image["width"] < self.min_image_size:
                continue
            img_path = img_dir / f"img_{idx}.png"
            img_path.write_bytes(base_image["image"])
            results.append({"index": idx, "path": str(img_path)})

        doc.close()
        return ImageExtractResult(images=results)

    async def describe_images(
        self,
        images: list[dict],
        model_config: dict,
    ) -> list[dict]:
        descriptions = []
        for img in images:
            img_path = Path(img["path"])
            if not img_path.exists():
                descriptions.append({**img, "description": "Image not found"})
                continue
            b64 = base64.b64encode(img_path.read_bytes()).decode()
            try:
                desc = await self.llm_client.chat_with_image(
                    model_config, b64, IMAGE_DESCRIBE_PROMPT
                )
            except Exception as e:
                desc = f"Description failed: {e}"
            descriptions.append({**img, "description": desc})
        return descriptions
