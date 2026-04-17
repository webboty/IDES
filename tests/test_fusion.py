from __future__ import annotations

import pytest

from ides.agent.brain import (
    validate_numbers,
    normalize_number,
    extract_numbers,
    FusionAgent,
)
from ides.fusion.rules import text_layer_only, text_with_ocr_verify, vision_only
from ides.models import TextLayerResult, OCRResult, VisionResult


pytestmark = pytest.mark.asyncio


class TestNumberValidation:
    def test_extract_numbers(self):
        text = "Total: 1.234,56 EUR Tax: 234,56 EUR"
        nums = extract_numbers(text)
        assert "1.234,56" in nums
        assert "234,56" in nums

    def test_normalize_number(self):
        assert normalize_number("1.234,56") == "1.234,56"
        assert normalize_number("€1.234,56") == "1.234,56"
        assert normalize_number(" 123.45 ") == "123.45"

    def test_validate_numbers_all_agree(self):
        sources = {
            "text_layer": "Total: 1234.56",
            "ocr": "Total: 1234.56",
        }
        result = validate_numbers(sources)
        assert "1234.56" in result
        assert result["1234.56"]["confidence"] == "high"

    def test_validate_numbers_disagree(self):
        sources = {
            "text_layer": "Total: 1234.56",
            "ocr": "Total: 1234.57",
        }
        result = validate_numbers(sources)
        assert "1234.56" in result
        assert result["1234.56"]["confidence"] == "high"
        assert result["1234.56"]["recommended"] == "1234.56"

    def test_validate_numbers_ocr_only(self):
        sources = {
            "ocr": "Amount: 99.99",
        }
        result = validate_numbers(sources)
        assert "99.99" in result
        assert result["99.99"]["confidence"] == "medium"

    def test_validate_numbers_vision_only(self):
        sources = {
            "vision": "Total 1234.56 EUR",
        }
        result = validate_numbers(sources)
        assert "1234.56" in result
        assert result["1234.56"]["confidence"] == "low"

    def test_validate_numbers_empty_source(self):
        sources = {"text_layer": ""}
        result = validate_numbers(sources)
        assert len(result) == 0

    def test_validate_numbers_none_source(self):
        sources = {"text_layer": None}
        result = validate_numbers(sources)
        assert len(result) == 0


class TestFusionRules:
    def test_text_layer_only(self):
        result = TextLayerResult(text="Hello", markdown="Hello", tables=[], char_map=[])
        md = text_layer_only(result)
        assert md == "Hello"

    def test_text_with_ocr_verify(self):
        text_result = TextLayerResult(
            text="Hello", markdown="Hello", tables=[], char_map=[]
        )
        ocr_result = OCRResult(text="Hello")
        md = text_with_ocr_verify(text_result, ocr_result)
        assert md == "Hello"

    def test_vision_only(self):
        result = VisionResult(markdown="# Title\nContent")
        md = vision_only(result)
        assert "# Title" in md


class TestFusionAgent:
    async def test_fuse_page_text_only_no_agent(self):
        from ides.fusion.llm_merge import fuse_page

        layer_results = {
            "text_layer": {"text": "Invoice #123", "markdown": "Invoice #123"},
        }
        result = await fuse_page("text_only", layer_results, agent=None, page_num=1)
        assert "Invoice #123" in result

    async def test_fuse_page_boilerplate(self):
        from ides.fusion.llm_merge import fuse_page

        result = await fuse_page("boilerplate", {}, agent=None, page_num=1)
        assert result == ""

    async def test_fuse_page_structured_text(self):
        from ides.fusion.llm_merge import fuse_page

        layer_results = {
            "text_layer": {"markdown": "# Table\n| A | B |\n|---|---|"},
        }
        result = await fuse_page(
            "structured_text", layer_results, agent=None, page_num=1
        )
        assert "Table" in result

    async def test_fuse_page_scanned_no_agent(self):
        from ides.fusion.llm_merge import fuse_page

        layer_results = {
            "vision": {"markdown": "Scanned content"},
            "ocr": {"text": "Scanned content"},
        }
        result = await fuse_page("scanned", layer_results, agent=None, page_num=1)
        assert "Scanned content" in result
