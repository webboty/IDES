from __future__ import annotations

import re
from typing import Any

from ides.config import AppConfig
from ides.models import PageClassification


def classify_page(
    char_count: int,
    has_tables: bool,
    thresholds: Any = None,
) -> str:
    text_rich = 500
    text_moderate = 200
    text_sparse = 50
    if thresholds:
        text_rich = getattr(thresholds, "text_rich", 500)
        text_moderate = getattr(thresholds, "text_moderate", 200)
        text_sparse = getattr(thresholds, "text_sparse", 50)

    if char_count > text_rich and has_tables:
        return "structured_text"
    if char_count > text_moderate:
        return "text_only"
    if char_count > text_sparse:
        return "mixed"
    return "scanned"


def get_layers_for_classification(classification: str) -> list[str]:
    mapping = {
        "boilerplate": [],
        "structured_text": ["text_layer"],
        "text_only": ["text_layer", "ocr"],
        "scanned": ["ocr", "vision"],
        "image_only": ["vision"],
        "mixed": ["text_layer", "ocr", "vision"],
    }
    return mapping.get(classification, ["text_layer", "ocr", "vision"])


def is_boilerplate(text: str, patterns: list[str]) -> bool:
    if not text:
        return False
    sample = text[:1000]
    for pattern in patterns:
        try:
            if re.search(pattern, sample):
                return True
        except re.error:
            continue
    return False
