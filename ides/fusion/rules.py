from __future__ import annotations

from typing import Any

from ides.models import TextLayerResult, OCRResult, VisionResult


def text_layer_only(result: TextLayerResult) -> str:
    return result.markdown


def text_with_ocr_verify(text_result: TextLayerResult, ocr_result: OCRResult) -> str:
    base = text_result.markdown
    ocr_text = ocr_result.text.strip()
    if not ocr_text:
        return base
    return base


def ocr_with_vision(ocr_result: OCRResult, vision_result: VisionResult) -> str:
    if vision_result.markdown.strip():
        return vision_result.markdown
    return ocr_result.text


def vision_only(vision_result: VisionResult) -> str:
    return vision_result.markdown


def all_layers(
    text_result: TextLayerResult | None,
    ocr_result: OCRResult | None,
    vision_result: VisionResult | None,
) -> dict[str, Any]:
    result = {}
    if text_result:
        result["text_layer"] = {
            "text": text_result.text,
            "markdown": text_result.markdown,
        }
    if ocr_result:
        result["ocr"] = {"text": ocr_result.text}
    if vision_result:
        result["vision"] = {"markdown": vision_result.markdown}
    return result
