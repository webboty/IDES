"""CLI unit tests — pure logic + DB-backed command tests using a real temp SQLite."""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from ides.storage.database import init_database, close_database, SCHEMA


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_cli_dir():
    d = tempfile.mkdtemp(prefix="ides_cli_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def cli_config_path(tmp_cli_dir):
    """Write a minimal config.yaml into tmp_cli_dir and return its path."""
    path = os.path.join(tmp_cli_dir, "config.yaml")
    Path(path).write_text(
        f"""\
server:
  master_admin_key: "test-admin-key"
  port: 19998
storage:
  base_path: "{tmp_cli_dir}"
providers:
  openai:
    base_url: "https://api.openai.com/v1"
    api_key: "test-key"
    timeout: 10
models:
  vision:
    provider: openai
    name: test-model
    max_tokens: 100
  merge:
    provider: openai
    name: test-model
    max_tokens: 100
  filter:
    provider: openai
    name: test-model
    max_tokens: 100
  image_describe:
    provider: openai
    name: test-model
    max_tokens: 100
extraction:
  max_pages: 50
  max_file_size_mb: 50
retry:
  max_attempts: 1
  backoff_base: 1
queue:
  max_concurrent_jobs: 2
  job_timeout: 60
  worker_poll_interval: 1
"""
    )
    return path


@pytest_asyncio.fixture
async def cli_db(tmp_cli_dir):
    """Initialise the ides.db that CLI commands will also use."""
    db_path = os.path.join(tmp_cli_dir, "ides.db")
    conn = await init_database(db_path)
    yield conn
    await close_database(conn)


def _ns(**kwargs) -> argparse.Namespace:
    """Build a fake argparse Namespace."""
    return argparse.Namespace(**kwargs)


async def _direct_query(tmp_cli_dir: str, sql: str, params=None):
    """Run a one-shot SELECT against ides.db and return rows as dicts."""
    db_path = os.path.join(tmp_cli_dir, "ides.db")
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(sql, params or [])
        return [dict(r) for r in await cursor.fetchall()]


async def _insert_job(
    tmp_cli_dir: str,
    job_id: str,
    status: str = "pending",
    storage_path: str | None = None,
    job_date: str = "2026-04-17",
    filename: str = "test.pdf",
) -> None:
    """Insert a bare-minimum job row directly into the DB."""
    sp = storage_path or f"jobs/2026/04/17/{job_id}/"
    now = datetime.now(timezone.utc).isoformat()
    db_path = os.path.join(tmp_cli_dir, "ides.db")
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(SCHEMA)
        await conn.execute(
            """INSERT OR IGNORE INTO jobs
               (id, status, original_filename, storage_path, max_attempts, job_date, created_at, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
            [job_id, status, filename, sp, job_date, now, now],
        )
        await conn.commit()


# ── pure-logic tests ──────────────────────────────────────────────────────────

class TestColours:
    def test_non_tty_returns_plain_text(self, monkeypatch):
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        # Re-import so the monkeypatch takes effect
        import importlib
        import ides.cli as cli_mod
        importlib.reload(cli_mod)
        assert cli_mod._c("1", "hello") == "hello"
        assert cli_mod.bold("text") == "text"
        assert cli_mod.green("ok") == "ok"
        assert cli_mod.red("err") == "err"
        # Restore
        importlib.reload(cli_mod)

    def test_status_colour_covers_all_statuses(self):
        from ides.cli import _status_colour
        for status in ("completed", "processing", "pending", "retrying",
                       "recovering", "failed", "cancelled"):
            result = _status_colour(status)
            assert isinstance(result, str)
            assert status in result

    def test_status_colour_unknown_passthrough(self):
        from ides.cli import _status_colour
        assert _status_colour("unknown_state") == "unknown_state"


# ── argument-parser tests ─────────────────────────────────────────────────────

class TestParser:
    def _parse(self, *argv):
        from ides.cli import build_parser
        return build_parser().parse_args(list(argv))

    def test_keys_create_required_args(self):
        args = self._parse("keys", "create", "--name", "n8n", "--owner", "ops")
        assert args.name == "n8n"
        assert args.owner == "ops"
        assert args.ips is None

    def test_keys_create_with_ips(self):
        args = self._parse("keys", "create", "--name", "n8n", "--owner", "ops",
                           "--ips", "1.2.3.4,5.6.7.8")
        assert args.ips == "1.2.3.4,5.6.7.8"

    def test_jobs_list_defaults(self):
        args = self._parse("jobs", "list")
        assert args.date is None
        assert args.status is None
        assert args.limit == 50

    def test_jobs_list_filters(self):
        args = self._parse("jobs", "list", "--date", "2026-04-17",
                           "--status", "failed", "--limit", "10")
        assert args.date == "2026-04-17"
        assert args.status == "failed"
        assert args.limit == 10

    def test_jobs_stats_default_days(self):
        args = self._parse("jobs", "stats")
        assert args.days == 30

    def test_jobs_cleanup_default_older_than(self):
        args = self._parse("jobs", "cleanup")
        assert args.older_than == 90

    def test_jobs_purge_force_flag(self):
        args = self._parse("jobs", "purge", "abc123", "--force")
        assert args.force is True
        assert args.job_id == "abc123"

    def test_llm_test_flag(self):
        args = self._parse("llm", "--test")
        assert args.test is True

    def test_global_config_override(self):
        args = self._parse("--config", "/custom/config.yaml", "keys", "list")
        assert args.config == "/custom/config.yaml"

    def test_no_subcommand_has_no_func(self):
        from ides.cli import build_parser
        args = build_parser().parse_args([])
        assert not hasattr(args, "func")


# ── keys commands ─────────────────────────────────────────────────────────────

class TestKeysCommands:
    @pytest.mark.asyncio
    async def test_create_prints_key(self, cli_config_path, cli_db, capsys):
        from ides.cli import cmd_keys_create
        await cmd_keys_create(_ns(config=cli_config_path, name="n8n-prod",
                                  owner="ops", ips=None))
        out = capsys.readouterr().out
        assert "ides_" in out
        assert "n8n-prod" in out
        assert "ops" in out
        assert "Save this key" in out

    @pytest.mark.asyncio
    async def test_create_with_ip_restriction(self, cli_config_path, cli_db, capsys):
        from ides.cli import cmd_keys_create
        await cmd_keys_create(_ns(config=cli_config_path, name="restricted",
                                  owner="ops", ips="10.0.0.1,10.0.0.2"))
        out = capsys.readouterr().out
        assert "10.0.0.1" in out
        assert "10.0.0.2" in out

    @pytest.mark.asyncio
    async def test_create_stores_in_db(self, cli_config_path, tmp_cli_dir, cli_db, capsys):
        from ides.cli import cmd_keys_create
        await cmd_keys_create(_ns(config=cli_config_path, name="db-check",
                                  owner="tester", ips=None))
        capsys.readouterr()
        rows = await _direct_query(tmp_cli_dir,
                                   "SELECT * FROM api_keys WHERE name = ?", ["db-check"])
        assert len(rows) == 1
        assert rows[0]["owner"] == "tester"
        assert rows[0]["is_active"] == 1

    @pytest.mark.asyncio
    async def test_list_shows_all_keys(self, cli_config_path, cli_db, capsys):
        from ides.cli import cmd_keys_create, cmd_keys_list
        await cmd_keys_create(_ns(config=cli_config_path, name="key-alpha",
                                  owner="alice", ips=None))
        await cmd_keys_create(_ns(config=cli_config_path, name="key-beta",
                                  owner="bob", ips=None))
        capsys.readouterr()

        await cmd_keys_list(_ns(config=cli_config_path))
        out = capsys.readouterr().out
        assert "key-alpha" in out
        assert "alice" in out
        assert "key-beta" in out
        assert "bob" in out

    @pytest.mark.asyncio
    async def test_list_empty(self, cli_config_path, cli_db, capsys):
        from ides.cli import cmd_keys_list
        await cmd_keys_list(_ns(config=cli_config_path))
        out = capsys.readouterr().out
        assert "No active" in out

    @pytest.mark.asyncio
    async def test_revoke_existing_key(self, cli_config_path, tmp_cli_dir,
                                       cli_db, capsys):
        from ides.cli import cmd_keys_create, cmd_keys_revoke
        await cmd_keys_create(_ns(config=cli_config_path, name="to-revoke",
                                  owner="ops", ips=None))
        capsys.readouterr()

        rows = await _direct_query(tmp_cli_dir,
                                   "SELECT id FROM api_keys WHERE name = ?", ["to-revoke"])
        key_id = rows[0]["id"]

        await cmd_keys_revoke(_ns(config=cli_config_path, id=key_id))
        out = capsys.readouterr().out
        assert "revoked" in out.lower()

        rows = await _direct_query(tmp_cli_dir,
                                   "SELECT is_active FROM api_keys WHERE id = ?", [key_id])
        assert rows[0]["is_active"] == 0

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_exits(self, cli_config_path, cli_db):
        from ides.cli import cmd_keys_revoke
        with pytest.raises(SystemExit) as exc:
            await cmd_keys_revoke(_ns(config=cli_config_path, id="does-not-exist"))
        assert exc.value.code == 1


# ── jobs commands ─────────────────────────────────────────────────────────────

class TestJobsCommands:
    @pytest.mark.asyncio
    async def test_list_empty(self, cli_config_path, cli_db, capsys):
        from ides.cli import cmd_jobs_list
        await cmd_jobs_list(_ns(config=cli_config_path, date=None,
                                status=None, limit=50))
        out = capsys.readouterr().out
        assert "No jobs" in out

    @pytest.mark.asyncio
    async def test_list_shows_jobs(self, cli_config_path, tmp_cli_dir, cli_db, capsys):
        from ides.cli import cmd_jobs_list
        jid = uuid.uuid4().hex[:24]
        await _insert_job(tmp_cli_dir, jid, status="completed",
                          filename="invoice.pdf")

        await cmd_jobs_list(_ns(config=cli_config_path, date=None,
                                status=None, limit=50))
        out = capsys.readouterr().out
        assert jid in out
        assert "invoice.pdf" in out

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, cli_config_path, tmp_cli_dir,
                                         cli_db, capsys):
        from ides.cli import cmd_jobs_list
        j_ok   = uuid.uuid4().hex[:24]
        j_fail = uuid.uuid4().hex[:24]
        await _insert_job(tmp_cli_dir, j_ok,   status="completed")
        await _insert_job(tmp_cli_dir, j_fail, status="failed")

        await cmd_jobs_list(_ns(config=cli_config_path, date=None,
                                status="failed", limit=50))
        out = capsys.readouterr().out
        assert j_fail in out
        assert j_ok not in out

    @pytest.mark.asyncio
    async def test_list_filter_by_date(self, cli_config_path, tmp_cli_dir,
                                        cli_db, capsys):
        from ides.cli import cmd_jobs_list
        j_today = uuid.uuid4().hex[:24]
        j_old   = uuid.uuid4().hex[:24]
        await _insert_job(tmp_cli_dir, j_today, job_date="2026-04-17")
        await _insert_job(tmp_cli_dir, j_old,   job_date="2026-03-01")

        await cmd_jobs_list(_ns(config=cli_config_path, date="2026-04-17",
                                status=None, limit=50))
        out = capsys.readouterr().out
        assert j_today in out
        assert j_old not in out

    @pytest.mark.asyncio
    async def test_stats_shows_counts(self, cli_config_path, tmp_cli_dir,
                                       cli_db, capsys):
        from ides.cli import cmd_jobs_stats
        for _ in range(3):
            await _insert_job(tmp_cli_dir, uuid.uuid4().hex[:24],
                               status="completed", job_date="2026-04-17")
        await _insert_job(tmp_cli_dir, uuid.uuid4().hex[:24],
                           status="failed", job_date="2026-04-17")

        await cmd_jobs_stats(_ns(config=cli_config_path, days=30))
        out = capsys.readouterr().out
        assert "2026-04-17" in out
        # 4 total, 3 ok, 1 failed
        assert "4" in out

    @pytest.mark.asyncio
    async def test_cancel_pending_job(self, cli_config_path, tmp_cli_dir,
                                       cli_db, capsys):
        from ides.cli import cmd_jobs_cancel
        jid = uuid.uuid4().hex[:24]
        await _insert_job(tmp_cli_dir, jid, status="pending")

        await cmd_jobs_cancel(_ns(config=cli_config_path, job_id=jid))
        out = capsys.readouterr().out
        assert "cancelled" in out.lower()

        rows = await _direct_query(tmp_cli_dir,
                                   "SELECT status FROM jobs WHERE id = ?", [jid])
        assert rows[0]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_retrying_job(self, cli_config_path, tmp_cli_dir,
                                        cli_db, capsys):
        from ides.cli import cmd_jobs_cancel
        jid = uuid.uuid4().hex[:24]
        await _insert_job(tmp_cli_dir, jid, status="retrying")

        await cmd_jobs_cancel(_ns(config=cli_config_path, job_id=jid))
        rows = await _direct_query(tmp_cli_dir,
                                   "SELECT status FROM jobs WHERE id = ?", [jid])
        assert rows[0]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_completed_job_rejects(self, cli_config_path,
                                                 tmp_cli_dir, cli_db):
        from ides.cli import cmd_jobs_cancel
        jid = uuid.uuid4().hex[:24]
        await _insert_job(tmp_cli_dir, jid, status="completed")

        with pytest.raises(SystemExit) as exc:
            await cmd_jobs_cancel(_ns(config=cli_config_path, job_id=jid))
        assert exc.value.code == 1

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_exits(self, cli_config_path, cli_db):
        from ides.cli import cmd_jobs_cancel
        with pytest.raises(SystemExit) as exc:
            await cmd_jobs_cancel(_ns(config=cli_config_path,
                                      job_id="does-not-exist"))
        assert exc.value.code == 1

    @pytest.mark.asyncio
    async def test_purge_deletes_files_and_row(self, cli_config_path,
                                                tmp_cli_dir, cli_db, capsys):
        from ides.cli import cmd_jobs_purge
        jid = uuid.uuid4().hex[:24]
        sp = f"jobs/2026/04/17/{jid}/"
        job_dir = Path(tmp_cli_dir) / sp
        job_dir.mkdir(parents=True)
        (job_dir / "original.pdf").write_bytes(b"%PDF-fake")

        await _insert_job(tmp_cli_dir, jid, storage_path=sp)
        await cmd_jobs_purge(_ns(config=cli_config_path, job_id=jid, force=True))

        capsys.readouterr()
        assert not job_dir.exists()
        rows = await _direct_query(tmp_cli_dir,
                                   "SELECT id FROM jobs WHERE id = ?", [jid])
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_purge_nonexistent_exits(self, cli_config_path, cli_db):
        from ides.cli import cmd_jobs_purge
        with pytest.raises(SystemExit) as exc:
            await cmd_jobs_purge(_ns(config=cli_config_path,
                                     job_id="ghost-id", force=True))
        assert exc.value.code == 1

    @pytest.mark.asyncio
    async def test_purge_missing_files_still_removes_row(self, cli_config_path,
                                                          tmp_cli_dir, cli_db,
                                                          capsys):
        from ides.cli import cmd_jobs_purge
        jid = uuid.uuid4().hex[:24]
        await _insert_job(tmp_cli_dir, jid,
                           storage_path=f"jobs/2020/01/01/{jid}/")
        await cmd_jobs_purge(_ns(config=cli_config_path, job_id=jid, force=True))
        capsys.readouterr()
        rows = await _direct_query(tmp_cli_dir,
                                   "SELECT id FROM jobs WHERE id = ?", [jid])
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_cleanup_removes_old_files_keeps_db(self, cli_config_path,
                                                        tmp_cli_dir, cli_db,
                                                        capsys):
        from ides.cli import cmd_jobs_cleanup
        jid = uuid.uuid4().hex[:24]
        sp = f"jobs/2020/01/01/{jid}/"
        job_dir = Path(tmp_cli_dir) / sp
        job_dir.mkdir(parents=True)
        (job_dir / "result.json").write_text("{}")

        await _insert_job(tmp_cli_dir, jid, status="completed",
                           storage_path=sp, job_date="2020-01-01")

        await cmd_jobs_cleanup(_ns(config=cli_config_path, older_than=30))
        capsys.readouterr()

        assert not job_dir.exists()
        rows = await _direct_query(tmp_cli_dir,
                                   "SELECT id FROM jobs WHERE id = ?", [jid])
        assert len(rows) == 1  # DB record kept

    @pytest.mark.asyncio
    async def test_cleanup_skips_recent_jobs(self, cli_config_path,
                                              tmp_cli_dir, cli_db, capsys):
        from ides.cli import cmd_jobs_cleanup
        jid = uuid.uuid4().hex[:24]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sp = f"jobs/{today.replace('-', '/')}/{jid}/"
        job_dir = Path(tmp_cli_dir) / sp
        job_dir.mkdir(parents=True)

        await _insert_job(tmp_cli_dir, jid, status="completed",
                           storage_path=sp, job_date=today)

        await cmd_jobs_cleanup(_ns(config=cli_config_path, older_than=90))
        capsys.readouterr()

        assert job_dir.exists()  # recent job not touched
