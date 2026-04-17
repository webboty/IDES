from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ides.main import create_app
from ides.config import AppConfig, ServerConfig, StorageConfig
from ides.security import generate_api_key, hash_key
from ides.storage import job_store


@pytest.fixture
def test_config(tmp_data_dir):
    return AppConfig(
        server=ServerConfig(master_admin_key="test-admin-key"),
        storage=StorageConfig(base_path=tmp_data_dir),
    )


@pytest.fixture
def app(test_config):
    return create_app(test_config)


@pytest.fixture
def api_key():
    return generate_api_key()


@pytest_asyncio.fixture
async def client(app, db, api_key, file_store, test_config):
    app.state.db = db
    app.state.file_store = file_store
    app.state.config = test_config
    raw, key_hash, prefix = api_key
    key_id = f"test-key-{uuid.uuid4().hex[:8]}"
    await job_store.create_api_key(db, key_id, key_hash, prefix, "test", "test")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def admin_headers():
    return {"X-Admin-Key": "test-admin-key"}


def api_headers(key: str):
    return {"X-API-Key": key}


pytestmark = pytest.mark.asyncio


class TestHealthEndpoint:
    async def test_health(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestAdminAuth:
    async def test_admin_no_key(self, client):
        response = await client.get("/admin/keys")
        assert response.status_code == 401

    async def test_admin_wrong_key(self, client):
        response = await client.get("/admin/keys", headers={"X-Admin-Key": "wrong"})
        assert response.status_code == 401

    async def test_admin_correct_key(self, client):
        response = await client.get("/admin/keys", headers=admin_headers())
        assert response.status_code == 200


class TestAdminKeysAPI:
    async def test_create_key(self, client):
        response = await client.post(
            "/admin/keys",
            json={"name": "n8n-key", "owner": "n8n team"},
            headers=admin_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["key"].startswith("ides_")
        assert data["name"] == "n8n-key"
        assert data["owner"] == "n8n team"

    async def test_list_keys(self, client):
        await client.post(
            "/admin/keys",
            json={"name": "list-test", "owner": "test"},
            headers=admin_headers(),
        )
        response = await client.get("/admin/keys", headers=admin_headers())
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert any(k["name"] == "list-test" for k in data)

    async def test_delete_key(self, client):
        create_resp = await client.post(
            "/admin/keys",
            json={"name": "to-delete", "owner": "test"},
            headers=admin_headers(),
        )
        key_id = create_resp.json()["id"]

        response = await client.delete(f"/admin/keys/{key_id}", headers=admin_headers())
        assert response.status_code == 200
        assert response.json()["deleted"] is True

        response = await client.delete(f"/admin/keys/{key_id}", headers=admin_headers())
        assert response.status_code == 404

    async def test_create_key_with_ip_restriction(self, client):
        response = await client.post(
            "/admin/keys",
            json={"name": "ip-key", "owner": "test", "allowed_ips": ["203.0.113.50"]},
            headers=admin_headers(),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "ip-key"


class TestJobAuth:
    async def test_extract_no_key(self, client):
        response = await client.post("/extract")
        assert response.status_code == 401

    async def test_extract_wrong_key(self, client):
        response = await client.post(
            "/extract",
            headers={"X-API-Key": "ides_wrongkey"},
        )
        assert response.status_code == 401


class TestExtractEndpoint:
    async def test_extract_json(self, client, sample_pdf_base64, api_key):
        raw_key = api_key[0]
        response = await client.post(
            "/extract",
            json={
                "file_base64": sample_pdf_base64,
                "filename": "test.pdf",
                "pages": "all",
            },
            headers={**api_headers(raw_key), "Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"

    async def test_extract_multipart(self, client, sample_pdf_bytes, api_key):
        raw_key = api_key[0]
        response = await client.post(
            "/extract",
            files={"file": ("test.pdf", sample_pdf_bytes, "application/pdf")},
            data={"pages": "all"},
            headers=api_headers(raw_key),
        )
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data

    async def test_extract_empty_file(self, client, api_key):
        raw_key = api_key[0]
        response = await client.post(
            "/extract",
            json={"file_base64": "", "filename": "test.pdf"},
            headers={**api_headers(raw_key), "Content-Type": "application/json"},
        )
        assert response.status_code == 400

    async def test_extract_invalid_pdf(self, client, api_key):
        import base64

        raw_key = api_key[0]
        response = await client.post(
            "/extract",
            json={
                "file_base64": base64.b64encode(b"not a pdf").decode(),
                "filename": "test.pdf",
            },
            headers={**api_headers(raw_key), "Content-Type": "application/json"},
        )
        assert response.status_code == 400


class TestJobStatusEndpoint:
    async def test_get_job_status(self, client, db, api_key):
        raw_key = api_key[0]
        await job_store.create_job(
            db, "status-test-1", "test.pdf", "jobs/status-test-1/"
        )

        response = await client.get(
            "/jobs/status-test-1",
            headers=api_headers(raw_key),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "status-test-1"
        assert data["status"] == "pending"

    async def test_get_nonexistent_job(self, client, api_key):
        raw_key = api_key[0]
        response = await client.get(
            "/jobs/nonexistent",
            headers=api_headers(raw_key),
        )
        assert response.status_code == 404

    async def test_get_job_result_pending(self, client, db, api_key):
        raw_key = api_key[0]
        await job_store.create_job(
            db, "result-pending", "test.pdf", "jobs/result-pending/"
        )

        response = await client.get(
            "/jobs/result-pending/result",
            headers=api_headers(raw_key),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["markdown"] == ""

    async def test_get_job_detail_pending(self, client, db, api_key):
        raw_key = api_key[0]
        await job_store.create_job(
            db, "detail-pending", "test.pdf", "jobs/detail-pending/"
        )

        response = await client.get(
            "/jobs/detail-pending/detail",
            headers=api_headers(raw_key),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
