from __future__ import annotations

import json
from typing import Any


def get_available_layers(storage_path: str, page_num: int) -> list[str]:
    from pathlib import Path

    layers_dir = Path(storage_path) / "layers"
    available = []
    for layer in ["text_layer", "ocr", "vision"]:
        ext = "md" if layer == "vision" else "json"
        fpath = layers_dir / f"page_{page_num:03d}_{layer}.{ext}"
        if fpath.exists():
            available.append(layer)
    return available


def get_all_page_layers(storage_path: str, total_pages: int) -> dict[int, list[str]]:
    result = {}
    for p in range(1, total_pages + 1):
        result[p] = get_available_layers(storage_path, p)
    return result


def analyze_failure_simple(error: str, retry_history: list[dict] | None = None) -> dict:
    error_lower = error.lower()
    diagnosis = "Unknown error"
    adjusted_plan = None

    if "timeout" in error_lower:
        diagnosis = "LLM request timed out"
        adjusted_plan = {"use_fewer_layers": True, "skip_vision": True}
    elif "ocr" in error_lower or "tesseract" in error_lower:
        diagnosis = "OCR extraction failed"
        adjusted_plan = {"skip_ocr": True, "use_vision_fallback": True}
    elif "pdf" in error_lower or "page" in error_lower:
        diagnosis = "PDF processing error"
        adjusted_plan = {"skip_problematic_pages": True}

    return {
        "diagnosis": diagnosis,
        "adjusted_plan": adjusted_plan,
        "confidence": 0.5,
        "explanation": diagnosis,
    }
