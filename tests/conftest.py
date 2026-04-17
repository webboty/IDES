from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ides.config import (
    AppConfig,
    ModelsConfig,
    ProviderConfig,
    QueueConfig,
    RetryConfig,
    ServerConfig,
    StorageConfig,
    ThresholdConfig,
    ExtractionConfig,
    DPIConfig,
)
from ides.storage.database import init_database, close_database
from ides.storage.file_store import FileStore
from ides.storage import job_store

import aiosqlite


@pytest.fixture(scope="session")
def tmp_data_dir():
    d = tempfile.mkdtemp(prefix="ides_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def config(tmp_data_dir):
    return AppConfig(
        server=ServerConfig(master_admin_key="test-admin-key-123"),
        storage=StorageConfig(base_path=tmp_data_dir),
        providers={
            "local": ProviderConfig(
                base_url="http://localhost:11435/v1",
                api_key="not-needed",
                timeout=30,
            ),
            "openai": ProviderConfig(
                base_url="https://api.openai.com/v1",
                api_key="test-key",
                timeout=30,
            ),
        },
        models=ModelsConfig(),
        extraction=ExtractionConfig(
            dpi=DPIConfig(vision=200, ocr=300),
            ocr_languages="deu+eng",
            max_pages=50,
            skip_boilerplate=True,
            boilerplate_patterns=[
                "(?i)allgemeine.{0,5}geschäft",
                "(?i)terms.{0,5}(and|&)conditions",
                "(?i)datenschutz",
                "(?i)impressum",
                "(?i)privacy.{0,5}policy",
            ],
        ),
        thresholds=ThresholdConfig(
            text_rich=500,
            text_moderate=200,
            text_sparse=50,
            min_image_size=100,
        ),
        retry=RetryConfig(max_attempts=2, backoff_base=1),
        queue=QueueConfig(
            max_concurrent_jobs=2, job_timeout=60, worker_poll_interval=1
        ),
    )


@pytest_asyncio.fixture
async def db(tmp_data_dir, config) -> AsyncGenerator[aiosqlite.Connection, None]:
    db_path = os.path.join(tmp_data_dir, "test.db")
    conn = await init_database(db_path)
    yield conn
    await close_database(conn)


@pytest.fixture
def file_store(config):
    return FileStore(config.storage.base_path)


@pytest.fixture
def sample_pdf_path() -> str:
    return _create_sample_pdf()


def _create_sample_pdf() -> str:
    import fitz

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Rechnung Nr. 2024-001")
    page.insert_text((72, 100), "Datum: 15.01.2024")
    page.insert_text((72, 130), "Gesamtbetrag: 1.234,56 EUR")
    page.insert_text((72, 160), "MwSt: 234,56 EUR")
    page.insert_text((72, 200), "Vielen Dank für Ihren Auftrag.")

    page2 = doc.new_page()
    page2.insert_text((72, 72), "Allgemeine Geschäftsbedingungen")
    page2.insert_text((72, 100), "1. Geltungsbereich")
    page2.insert_text((72, 130), "Diese AGB gelten für alle Verträge...")

    doc.save(tmp.name)
    doc.close()
    return tmp.name


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    import fitz
    import io

    buf = io.BytesIO()
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Test Invoice #12345")
    page.insert_text((72, 100), "Amount: 99.99 EUR")
    doc.save(buf)
    doc.close()
    return buf.getvalue()


@pytest.fixture
def sample_pdf_base64(sample_pdf_bytes) -> str:
    import base64

    return base64.b64encode(sample_pdf_bytes).decode()
