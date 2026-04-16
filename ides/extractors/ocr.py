from __future__ import annotations

from typing import Any

import pytesseract
from pdf2image import convert_from_path

from ides.extractors.base import BaseExtractor
from ides.models import OCRResult
from ides.utils.image_ops import preprocess_for_ocr


class OCRExtractor(BaseExtractor):
    def __init__(self, dpi: int = 300, languages: str = "deu+eng+rus"):
        self.dpi = dpi
        self.languages = languages

    async def extract(self, pdf_path: str, page_num: int, **kwargs: Any) -> OCRResult:
        languages = kwargs.get("languages", self.languages)
        dpi = kwargs.get("dpi", self.dpi)

        images = convert_from_path(
            pdf_path,
            dpi=dpi,
            first_page=page_num,
            last_page=page_num,
        )
        if not images:
            return OCRResult(text="")

        image = images[0]
        preprocessed = preprocess_for_ocr(self._pil_to_bytes(image))
        from PIL import Image
        import io

        processed_image = Image.open(io.BytesIO(preprocessed))

        text = pytesseract.image_to_string(processed_image, lang=languages)
        return OCRResult(text=text)

    @staticmethod
    def _pil_to_bytes(image: Any) -> bytes:
        import io

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    async def quick_ocr(self, pdf_path: str, page_num: int) -> str:
        try:
            images = convert_from_path(
                pdf_path,
                dpi=150,
                first_page=page_num,
                last_page=page_num,
            )
            if not images:
                return ""
            text = pytesseract.image_to_string(images[0], lang=self.languages)
            return text
        except Exception:
            return ""
