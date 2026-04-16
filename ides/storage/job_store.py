from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: aiosqlite.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


async def create_job(
    db: aiosqlite.Connection,
    job_id: str,
    filename: str,
    storage_path: str,
    options: dict | None = None,
    max_attempts: int = 3,
) -> dict:
    now = _now_iso()
    await db.execute(
        """INSERT INTO jobs (id, status, original_filename, storage_path, options, max_attempts, created_at, updated_at)
           VALUES (?, 'pending', ?, ?, ?, ?, ?, ?)""",
        [
            job_id,
            filename,
            storage_path,
            json.dumps(options) if options else None,
            max_attempts,
            now,
            now,
        ],
    )
    await db.commit()
    return {
        "id": job_id,
        "status": "pending",
        "original_filename": filename,
        "storage_path": storage_path,
    }


async def get_job(db: aiosqlite.Connection, job_id: str) -> dict | None:
    cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", [job_id])
    row = await cursor.fetchone()
    return _row_to_dict(row)


async def update_job(db: aiosqlite.Connection, job_id: str, **kwargs: Any) -> None:
    if not kwargs:
        return
    kwargs["updated_at"] = _now_iso()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [job_id]
    await db.execute(f"UPDATE jobs SET {sets} WHERE id = ?", values)
    await db.commit()


async def get_pending_jobs(db: aiosqlite.Connection, limit: int = 10) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
        [limit],
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


async def append_retry_history(
    db: aiosqlite.Connection, job_id: str, entry: dict
) -> None:
    job = await get_job(db, job_id)
    if not job:
        return
    history = json.loads(job.get("retry_history") or "[]")
    history.append(entry)
    await update_job(db, job_id, retry_history=json.dumps(history))


async def store_result_summary(
    db: aiosqlite.Connection, job_id: str, summary: dict
) -> None:
    await update_job(db, job_id, result_summary=json.dumps(summary))


# --- API Key operations ---


async def create_api_key(
    db: aiosqlite.Connection,
    key_id: str,
    key_hash: str,
    key_prefix: str,
    name: str,
    owner: str,
    allowed_ips: list[str] | None = None,
) -> dict:
    now = _now_iso()
    await db.execute(
        """INSERT INTO api_keys (id, key_hash, key_prefix, name, owner, allowed_ips, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            key_id,
            key_hash,
            key_prefix,
            name,
            owner,
            json.dumps(allowed_ips) if allowed_ips else None,
            now,
        ],
    )
    await db.commit()
    return {"id": key_id, "key_prefix": key_prefix, "name": name, "owner": owner}


async def get_api_key_by_hash(db: aiosqlite.Connection, key_hash: str) -> dict | None:
    cursor = await db.execute(
        "SELECT * FROM api_keys WHERE key_hash = ? AND is_active = 1",
        [key_hash],
    )
    row = await cursor.fetchone()
    return _row_to_dict(row)


async def update_api_key_last_used(db: aiosqlite.Connection, key_id: str) -> None:
    now = _now_iso()
    await db.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", [now, key_id])
    await db.commit()


async def list_api_keys(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM api_keys WHERE is_active = 1 ORDER BY created_at DESC"
    )
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


async def deactivate_api_key(db: aiosqlite.Connection, key_id: str) -> bool:
    cursor = await db.execute(
        "UPDATE api_keys SET is_active = 0 WHERE id = ? AND is_active = 1", [key_id]
    )
    await db.commit()
    return cursor.rowcount > 0
