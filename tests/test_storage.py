from __future__ import annotations

import json

import pytest
import pytest_asyncio

from ides.security import generate_api_key, hash_key, verify_api_key
from ides.storage import job_store


pytestmark = pytest.mark.asyncio


class TestAPIKeys:
    async def test_create_and_get_key(self, db):
        raw, key_hash, prefix = generate_api_key()
        assert raw.startswith("ides_")
        assert len(raw) > 10
        assert prefix == raw[:9]

        result = await job_store.create_api_key(
            db, "key-1", key_hash, prefix, "test-key", "test-owner"
        )
        assert result["name"] == "test-key"
        assert result["owner"] == "test-owner"

    async def test_get_key_by_hash(self, db):
        raw, key_hash, prefix = generate_api_key()
        await job_store.create_api_key(
            db, "key-2", key_hash, prefix, "lookup-test", "owner"
        )

        found = await job_store.get_api_key_by_hash(db, key_hash)
        assert found is not None
        assert found["name"] == "lookup-test"

        not_found = await job_store.get_api_key_by_hash(db, "badhash")
        assert not_found is None

    async def test_list_keys(self, db):
        keys = await job_store.list_api_keys(db)
        assert isinstance(keys, list)

    async def test_deactivate_key(self, db):
        raw, key_hash, prefix = generate_api_key()
        await job_store.create_api_key(
            db, "key-del", key_hash, prefix, "to-delete", "owner"
        )

        deleted = await job_store.deactivate_api_key(db, "key-del")
        assert deleted is True

        found = await job_store.get_api_key_by_hash(db, key_hash)
        assert found is None

        deleted_again = await job_store.deactivate_api_key(db, "key-del")
        assert deleted_again is False

    async def test_update_last_used(self, db):
        raw, key_hash, prefix = generate_api_key()
        await job_store.create_api_key(
            db, "key-lu", key_hash, prefix, "last-used", "owner"
        )
        await job_store.update_api_key_last_used(db, "key-lu")

        found = await job_store.get_api_key_by_hash(db, key_hash)
        assert found["last_used_at"] is not None

    async def test_verify_api_key(self, db):
        raw, key_hash, prefix = generate_api_key()
        await job_store.create_api_key(db, "key-v", key_hash, prefix, "verify", "owner")

        result = await verify_api_key(raw, "127.0.0.1", db)
        assert result is not None
        assert result["name"] == "verify"

        result = await verify_api_key("ides_badkey", "127.0.0.1", db)
        assert result is None

    async def test_verify_api_key_with_ip_restriction(self, db):
        raw, key_hash, prefix = generate_api_key()
        await job_store.create_api_key(
            db,
            "key-ip",
            key_hash,
            prefix,
            "ip-test",
            "owner",
            allowed_ips=["10.0.0.1"],
        )

        result = await verify_api_key(raw, "10.0.0.1", db)
        assert result is not None

        result = await verify_api_key(raw, "192.168.1.1", db)
        assert result is None


class TestJobs:
    async def test_create_job(self, db):
        job = await job_store.create_job(
            db,
            "job-1",
            "test.pdf",
            "jobs/job-1/",
            options={"pages": "all"},
            max_attempts=3,
        )
        assert job["id"] == "job-1"
        assert job["status"] == "pending"

    async def test_get_job(self, db):
        await job_store.create_job(db, "job-2", "test.pdf", "jobs/job-2/")
        job = await job_store.get_job(db, "job-2")
        assert job is not None
        assert job["id"] == "job-2"

        not_found = await job_store.get_job(db, "nonexistent")
        assert not_found is None

    async def test_update_job(self, db):
        await job_store.create_job(db, "job-3", "test.pdf", "jobs/job-3/")
        await job_store.update_job(db, "job-3", status="processing", progress_current=2)

        job = await job_store.get_job(db, "job-3")
        assert job["status"] == "processing"
        assert job["progress_current"] == 2

    async def test_get_pending_jobs(self, db):
        await job_store.create_job(db, "pending-1", "test.pdf", "jobs/pending-1/")
        await job_store.create_job(db, "pending-2", "test.pdf", "jobs/pending-2/")

        pending = await job_store.get_pending_jobs(db)
        assert len(pending) >= 2

    async def test_get_pending_excludes_non_pending(self, db):
        await job_store.create_job(db, "pending-done", "test.pdf", "jobs/pending-done/")
        await job_store.update_job(db, "pending-done", status="completed")

        pending = await job_store.get_pending_jobs(db)
        ids = [p["id"] for p in pending]
        assert "pending-done" not in ids

    async def test_append_retry_history(self, db):
        await job_store.create_job(db, "retry-1", "test.pdf", "jobs/retry-1/")
        entry = {
            "attempt": 1,
            "error": "test error",
            "timestamp": "2024-01-01T00:00:00",
        }
        await job_store.append_retry_history(db, "retry-1", entry)

        job = await job_store.get_job(db, "retry-1")
        history = json.loads(job["retry_history"])
        assert len(history) == 1
        assert history[0]["error"] == "test error"

    async def test_store_result_summary(self, db):
        await job_store.create_job(db, "result-1", "test.pdf", "jobs/result-1/")
        summary = {"pages_processed": 5, "pages_skipped": 1}
        await job_store.store_result_summary(db, "result-1", summary)

        job = await job_store.get_job(db, "result-1")
        loaded = json.loads(job["result_summary"])
        assert loaded["pages_processed"] == 5
