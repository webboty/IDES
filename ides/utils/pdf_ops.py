from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

import fitz
from pdf2image import convert_from_bytes, convert_from_path
from PIL import Image


def split_pdf_to_pages(pdf_path: str | Path) -> list[bytes]:
    doc = fitz.open(str(pdf_path))
    pages = []
    for i in range(len(doc)):
        page_doc = fitz.open()
        page_doc.insert_pdf(doc, from_page=i, to_page=i)
        buf = io.BytesIO()
        page_doc.save(buf)
        pages.append(buf.getvalue())
        page_doc.close()
    doc.close()
    return pages


def pdf_page_to_image(
    pdf_path: str | Path,
    page_num: int,
    dpi: int = 200,
) -> bytes:
    images = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        first_page=page_num,
        last_page=page_num,
    )
    if not images:
        raise ValueError(f"Could not convert page {page_num} to image")
    buf = io.BytesIO()
    images[0].save(buf, format="PNG")
    return buf.getvalue()


def pdf_bytes_to_page_image(
    pdf_bytes: bytes,
    page_num: int,
    dpi: int = 200,
) -> bytes:
    images = convert_from_bytes(
        pdf_bytes,
        dpi=dpi,
        first_page=page_num,
        last_page=page_num,
    )
    if not images:
        raise ValueError(f"Could not convert page {page_num} to image")
    buf = io.BytesIO()
    images[0].save(buf, format="PNG")
    return buf.getvalue()


def image_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode()


def get_page_count(pdf_path: str | Path) -> int:
    doc = fitz.open(str(pdf_path))
    count = len(doc)
    doc.close()
    return count


def parse_page_range(pages_str: str, total_pages: int) -> list[int]:
    if pages_str.lower() == "all":
        return list(range(1, total_pages + 1))
    result = []
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            result.extend(range(int(start), int(end) + 1))
        else:
            result.append(int(part))
    return [p for p in result if 1 <= p <= total_pages]
