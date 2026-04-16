from __future__ import annotations

from typing import Any

import pdfplumber

from ides.extractors.base import BaseExtractor
from ides.models import TextLayerResult


class TextLayerExtractor(BaseExtractor):
    async def extract(
        self, pdf_path: str, page_num: int, **kwargs: Any
    ) -> TextLayerResult:
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[page_num - 1]
            text = page.extract_text() or ""
            tables = page.extract_tables() or []
            chars = [
                {
                    "text": c["text"],
                    "x0": c["x0"],
                    "y0": c["top"],
                    "x1": c["x1"],
                    "y1": c["bottom"],
                }
                for c in page.chars
            ]

            table_markdown = []
            for table in tables:
                if not table or not table[0]:
                    continue
                header = "| " + " | ".join(str(c or "") for c in table[0]) + " |"
                sep = "| " + " | ".join("---" for _ in table[0]) + " |"
                rows = [
                    "| " + " | ".join(str(c or "") for c in row) + " |"
                    for row in table[1:]
                ]
                table_markdown.append(header + "\n" + sep + "\n" + "\n".join(rows))

            markdown = text
            if table_markdown:
                markdown += "\n\n" + "\n\n".join(table_markdown)

            return TextLayerResult(
                text=text,
                tables=tables,
                char_map=chars,
                markdown=markdown,
            )
