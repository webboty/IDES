from __future__ import annotations

from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    name TEXT NOT NULL,
    owner TEXT NOT NULL,
    allowed_ips TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP,
    expires_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_active ON api_keys(is_active);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending',
    original_filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    options TEXT,
    opencode_session_id TEXT,
    attempt INTEGER DEFAULT 1,
    max_attempts INTEGER DEFAULT 3,
    last_error TEXT,
    agent_recovery_plan TEXT,
    error_analysis TEXT,
    retry_history TEXT,
    result_summary TEXT,
    progress_current INTEGER DEFAULT 0,
    progress_total INTEGER DEFAULT 0,
    pages_skipped INTEGER DEFAULT 0,
    layers_stats TEXT,
    job_date TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
"""

DB_PATH: str = "data/ides.db"


async def _migrate(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(jobs)")
    cols = {row[1] for row in await cursor.fetchall()}
    if "job_date" not in cols:
        await db.execute("ALTER TABLE jobs ADD COLUMN job_date TEXT")
        await db.execute(
            "UPDATE jobs SET job_date = date(created_at) WHERE job_date IS NULL"
        )


async def init_database(db_path: str = DB_PATH) -> aiosqlite.Connection:
    db_dir = Path(db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.executescript(SCHEMA)
    await _migrate(db)
    await db.commit()
    return db


async def close_database(db: aiosqlite.Connection) -> None:
    await db.close()
