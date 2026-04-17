from __future__ import annotations

import pytest

from ides.extractors.text_layer import TextLayerExtractor
from ides.pipeline.page_plan import (
    classify_page,
    get_layers_for_classification,
    is_boilerplate,
)
from ides.models import TextLayerResult


pytestmark = pytest.mark.asyncio


class TestTextLayerExtractor:
    async def test_extract_text(self, sample_pdf_path):
        extractor = TextLayerExtractor()
        result = await extractor.extract(sample_pdf_path, 1)
        assert isinstance(result, TextLayerResult)
        assert "Rechnung" in result.text
        assert "2024-001" in result.text
        assert "1.234,56" in result.text

    async def test_extract_page_2(self, sample_pdf_path):
        extractor = TextLayerExtractor()
        result = await extractor.extract(sample_pdf_path, 2)
        assert "Allgemeine Geschäftsbedingungen" in result.text


class TestPageClassification:
    def test_structured_text(self):
        result = classify_page(600, True)
        assert result == "structured_text"

    def test_text_only(self):
        result = classify_page(300, False)
        assert result == "text_only"

    def test_mixed(self):
        result = classify_page(100, False)
        assert result == "mixed"

    def test_scanned(self):
        result = classify_page(10, False)
        assert result == "scanned"

    def test_custom_thresholds(self):
        class MockThresholds:
            text_rich = 1000
            text_moderate = 500
            text_sparse = 100

        result = classify_page(600, True, MockThresholds())
        assert result == "text_only"

    def test_get_layers_structured_text(self):
        layers = get_layers_for_classification("structured_text")
        assert layers == ["text_layer"]

    def test_get_layers_text_only(self):
        layers = get_layers_for_classification("text_only")
        assert layers == ["text_layer", "ocr"]

    def test_get_layers_scanned(self):
        layers = get_layers_for_classification("scanned")
        assert layers == ["ocr", "vision"]

    def test_get_layers_image_only(self):
        layers = get_layers_for_classification("image_only")
        assert layers == ["vision"]

    def test_get_layers_mixed(self):
        layers = get_layers_for_classification("mixed")
        assert layers == ["text_layer", "ocr", "vision"]

    def test_get_layers_boilerplate(self):
        layers = get_layers_for_classification("boilerplate")
        assert layers == []


class TestBoilerplateDetection:
    def test_detect_agb(self):
        assert is_boilerplate(
            "Allgemeine Geschäftsbedingungen", ["(?i)allgemeine.{0,5}geschäft"]
        )

    def test_detect_terms(self):
        assert is_boilerplate("Terms and Conditions", ["(?i)terms.{0,10}conditions"])

    def test_detect_datenschutz(self):
        assert is_boilerplate("Datenschutzerklärung", ["(?i)datenschutz"])

    def test_detect_impressum(self):
        assert is_boilerplate("Impressum: Firma GmbH", ["(?i)impressum"])

    def test_not_boilerplate(self):
        assert not is_boilerplate("Rechnung Nr. 2024-001", ["(?i)datenschutz"])

    def test_empty_text(self):
        assert not is_boilerplate("", ["(?i)test"])

    def test_multiple_patterns(self):
        patterns = [
            "(?i)allgemeine.{0,5}geschäft",
            "(?i)datenschutz",
            "(?i)impressum",
        ]
        assert is_boilerplate("Datenschutz", patterns)
        assert not is_boilerplate("Invoice #123", patterns)
