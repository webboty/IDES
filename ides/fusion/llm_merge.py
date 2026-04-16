from __future__ import annotations

from typing import Any

from ides.agent.brain import FusionAgent
from ides.fusion.rules import (
    text_layer_only,
    text_with_ocr_verify,
    ocr_with_vision,
    vision_only,
)


async def fuse_page(
    classification: str,
    layer_results: dict[str, Any],
    agent: FusionAgent | None = None,
    page_num: int = 1,
) -> str:
    if classification == "boilerplate":
        return ""

    if classification == "structured_text" and "text_layer" in layer_results:
        tl = layer_results["text_layer"]
        if isinstance(tl, dict):
            return tl.get("markdown", "")
        return text_layer_only(tl).markdown

    if classification == "text_only":
        if agent and len(layer_results) > 1:
            return await agent.fuse_page(page_num, layer_results)
        tl = layer_results.get("text_layer")
        if tl:
            if isinstance(tl, dict):
                return tl.get("markdown", "")
            return tl.markdown
        return ""

    if classification in ("scanned", "mixed", "image_only"):
        if agent:
            return await agent.fuse_page(page_num, layer_results)

        if "vision" in layer_results and "ocr" in layer_results:
            vision = layer_results["vision"]
            ocr = layer_results["ocr"]
            if isinstance(vision, dict) and isinstance(ocr, dict):
                return vision.get("markdown", ocr.get("text", ""))
            return ""

        if "vision" in layer_results:
            v = layer_results["vision"]
            return v.get("markdown", "") if isinstance(v, dict) else v.markdown

        if "ocr" in layer_results:
            o = layer_results["ocr"]
            return o.get("text", "") if isinstance(o, dict) else o.text

        if "text_layer" in layer_results:
            tl = layer_results["text_layer"]
            return tl.get("markdown", "") if isinstance(tl, dict) else tl.markdown

    return ""
