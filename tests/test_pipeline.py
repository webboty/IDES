from __future__ import annotations

import json

import pytest

from ides.pipeline.prefilter import classify_all_pages
from ides.pipeline.page_plan import classify_page, get_layers_for_classification
from ides.utils.pdf_ops import get_page_count, parse_page_range, split_pdf_to_pages


pytestmark = pytest.mark.asyncio


class TestPDFOps:
    def test_get_page_count(self, sample_pdf_path):
        count = get_page_count(sample_pdf_path)
        assert count == 2

    def test_parse_page_range_all(self):
        result = parse_page_range("all", 10)
        assert result == list(range(1, 11))

    def test_parse_page_range_specific(self):
        result = parse_page_range("1,3,5", 10)
        assert result == [1, 3, 5]

    def test_parse_page_range_range(self):
        result = parse_page_range("1-5", 10)
        assert result == [1, 2, 3, 4, 5]

    def test_parse_page_range_mixed(self):
        result = parse_page_range("1-3,7,9-10", 10)
        assert result == [1, 2, 3, 7, 9, 10]

    def test_parse_page_range_out_of_bounds(self):
        result = parse_page_range("1,15,20", 10)
        assert result == [1]

    def test_split_pdf_to_pages(self, sample_pdf_path):
        pages = split_pdf_to_pages(sample_pdf_path)
        assert len(pages) == 2
        assert all(isinstance(p, bytes) for p in pages)
        assert all(len(p) > 0 for p in pages)


class TestPipelinePrefilter:
    async def test_classify_all_pages(self, sample_pdf_path, config):
        classifications = await classify_all_pages(sample_pdf_path, config)
        assert len(classifications) == 2

        page1 = classifications[0]
        assert page1.page_num == 1
        assert page1.classification in ("text_only", "structured_text", "mixed")
        assert page1.char_count > 0

    async def test_classify_detects_boilerplate(self, sample_pdf_path, config):
        classifications = await classify_all_pages(sample_pdf_path, config)
        page2 = classifications[1]
        assert page2.classification == "boilerplate" or "Allgemeine" in (
            await _get_text(sample_pdf_path, 2)
        )

    async def test_classify_respects_config(self, sample_pdf_path, config):
        config.extraction.skip_boilerplate = False
        classifications = await classify_all_pages(sample_pdf_path, config)
        assert len(classifications) == 2


async def _get_text(pdf_path, page_num):
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        return pdf.pages[page_num - 1].extract_text() or ""


class TestFileStore:
    async def test_create_job_dir(self, file_store):
        jd = file_store.create_job_dir("test-job-1")
        assert jd.exists()
        assert (jd / "pages").exists()
        assert (jd / "layers").exists()
        assert (jd / "fusion").exists()
        assert (jd / "result").exists()

    async def test_save_and_load_meta(self, file_store):
        file_store.create_job_dir("test-job-2")
        meta = {"filename": "test.pdf", "page_count": 5}
        file_store.save_meta("test-job-2", meta)

        loaded = file_store.load_meta("test-job-2")
        assert loaded == meta

    async def test_save_and_load_classification(self, file_store):
        file_store.create_job_dir("test-job-3")
        classifications = [
            {"page_num": 1, "classification": "text_only"},
            {"page_num": 2, "classification": "boilerplate"},
        ]
        file_store.save_classification("test-job-3", classifications)

        loaded = file_store.load_classification("test-job-3")
        assert len(loaded) == 2
        assert loaded[0]["classification"] == "text_only"

    async def test_save_and_load_layer_result(self, file_store):
        file_store.create_job_dir("test-job-4")
        data = {"text": "Hello", "markdown": "Hello"}
        file_store.save_layer_result("test-job-4", 1, "text_layer", data)

        loaded = file_store.load_layer_result("test-job-4", 1, "text_layer")
        assert loaded["text"] == "Hello"

    async def test_save_and_load_fusion(self, file_store):
        file_store.create_job_dir("test-job-5")
        file_store.save_fusion_page("test-job-5", 1, "# Merged content")

        loaded = file_store.load_fusion_page("test-job-5", 1)
        assert "# Merged content" in loaded

    async def test_save_and_load_final(self, file_store):
        file_store.create_job_dir("test-job-6")
        file_store.save_final_result(
            "test-job-6",
            "# Final Document",
            {"job_id": "test-job-6", "status": "completed"},
        )

        md = file_store.load_final_markdown("test-job-6")
        assert "# Final Document" in md

        detail = file_store.load_result_detail("test-job-6")
        assert detail["status"] == "completed"

    async def test_load_nonexistent(self, file_store):
        assert file_store.load_meta("nonexistent") is None
        assert file_store.load_final_markdown("nonexistent") is None
        assert file_store.load_result_detail("nonexistent") is None
        assert file_store.load_classification("nonexistent") == []
        assert file_store.load_layer_result("nonexistent", 1, "text_layer") is None
        assert file_store.load_fusion_page("nonexistent", 1) is None

    async def test_save_original(self, file_store, sample_pdf_bytes):
        file_store.create_job_dir("test-job-7")
        path = file_store.save_original("test-job-7", sample_pdf_bytes)
        assert path.exists()
        assert path.stat().st_size > 0
