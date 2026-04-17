"""IDES management CLI — run 'ides help' or 'ides --help' to get started."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ── colour helpers (only when stdout is a real terminal) ─────────────────────

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text

def bold(t: str) -> str:   return _c("1",  t)
def green(t: str) -> str:  return _c("32", t)
def yellow(t: str) -> str: return _c("33", t)
def red(t: str) -> str:    return _c("31", t)
def cyan(t: str) -> str:   return _c("36", t)
def dim(t: str) -> str:    return _c("2",  t)


def _status_colour(status: str) -> str:
    return {
        "completed":  green,
        "processing": cyan,
        "pending":    yellow,
        "retrying":   yellow,
        "recovering": yellow,
        "failed":     red,
        "cancelled":  dim,
    }.get(status, lambda x: x)(status)


# ── config / db helpers ───────────────────────────────────────────────────────

def _load_config(path: str):
    from ides.config import load_config
    return load_config(path)


async def _open_db(config):
    from ides.storage.database import init_database
    db_path = str(Path(config.storage.base_path) / "ides.db")
    return await init_database(db_path)


# ── serve ─────────────────────────────────────────────────────────────────────

def cmd_serve(args):
    import uvicorn
    from ides.main import create_app
    config = _load_config(args.config)
    host = args.host or config.server.host
    port = args.port or config.server.port
    uvicorn.run(create_app(config), host=host, port=port, workers=1)


# ── keys ──────────────────────────────────────────────────────────────────────

async def cmd_keys_create(args):
    import uuid
    from ides.security import generate_api_key
    from ides.storage.job_store import create_api_key

    config = _load_config(args.config)
    db = await _open_db(config)
    try:
        raw_key, key_hash, key_prefix = generate_api_key()
        key_id = uuid.uuid4().hex[:16]
        allowed_ips = [ip.strip() for ip in args.ips.split(",")] if args.ips else None
        await create_api_key(db, key_id=key_id, key_hash=key_hash, key_prefix=key_prefix,
                             name=args.name, owner=args.owner, allowed_ips=allowed_ips)
        print(bold("API key created"))
        print(f"  ID     : {key_id}")
        print(f"  Name   : {args.name}")
        print(f"  Owner  : {args.owner}")
        print(f"  Prefix : {key_prefix}")
        if allowed_ips:
            print(f"  IPs    : {', '.join(allowed_ips)}")
        print()
        print(f"  {bold('Key')} : {green(raw_key)}")
        print()
        print(yellow("  Save this key — it will not be shown again."))
    finally:
        await db.close()


async def cmd_keys_list(args):
    from ides.storage.job_store import list_api_keys

    config = _load_config(args.config)
    db = await _open_db(config)
    try:
        keys = await list_api_keys(db)
        if not keys:
            print(dim("No active API keys."))
            return
        print(bold(f"{'ID':<18} {'PREFIX':<12} {'NAME':<22} {'OWNER':<22} LAST USED"))
        print("─" * 95)
        for k in keys:
            last = k.get("last_used_at") or ""
            last = last[:19].replace("T", " ") if last else dim("never")
            print(f"{k['id']:<18} {k['key_prefix']:<12} {k['name']:<22} {k['owner']:<22} {last}")
    finally:
        await db.close()


async def cmd_keys_revoke(args):
    from ides.storage.job_store import deactivate_api_key

    config = _load_config(args.config)
    db = await _open_db(config)
    try:
        ok = await deactivate_api_key(db, args.id)
        if ok:
            print(green(f"Key {args.id} revoked."))
        else:
            print(red(f"Key {args.id} not found or already revoked."))
            sys.exit(1)
    finally:
        await db.close()


# ── jobs ──────────────────────────────────────────────────────────────────────

async def cmd_jobs_list(args):
    config = _load_config(args.config)
    db = await _open_db(config)
    try:
        conditions, params = [], []
        if args.date:
            conditions.append("job_date = ?")
            params.append(args.date)
        if args.status:
            conditions.append("status = ?")
            params.append(args.status)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(args.limit)

        cursor = await db.execute(
            f"SELECT id, job_date, original_filename, status, pages_skipped "
            f"FROM jobs {where} ORDER BY created_at DESC LIMIT ?",
            params,
        )
        rows = await cursor.fetchall()
        if not rows:
            print(dim("No jobs found."))
            return

        print(bold(f"{'JOB ID':<26} {'DATE':<12} {'STATUS':<22} {'SKIP':>5}  FILENAME"))
        print("─" * 100)
        for r in rows:
            fname = (r["original_filename"] or "")[:42]
            print(f"{r['id']:<26} {(r['job_date'] or ''):<12} "
                  f"{_status_colour(r['status']):<30} {(r['pages_skipped'] or 0):>5}  {fname}")
    finally:
        await db.close()


async def cmd_jobs_stats(args):
    config = _load_config(args.config)
    db = await _open_db(config)
    try:
        cursor = await db.execute(
            """SELECT job_date,
                      COUNT(*) as total,
                      SUM(CASE WHEN status='completed'  THEN 1 ELSE 0 END) as ok,
                      SUM(CASE WHEN status='failed'     THEN 1 ELSE 0 END) as failed,
                      SUM(CASE WHEN status='cancelled'  THEN 1 ELSE 0 END) as cancelled,
                      SUM(CASE WHEN status IN ('pending','processing','retrying','recovering')
                               THEN 1 ELSE 0 END) as active
               FROM jobs
               WHERE job_date >= date('now', ?)
               GROUP BY job_date ORDER BY job_date DESC""",
            [f"-{args.days} days"],
        )
        rows = await cursor.fetchall()
        if not rows:
            print(dim(f"No jobs in the last {args.days} days."))
            return
        print(bold(f"{'DATE':<14} {'TOTAL':>7} {'OK':>7} {'FAILED':>8} {'CANCELLED':>10} {'ACTIVE':>7}"))
        print("─" * 56)
        for r in rows:
            ok_s    = green(f"{r['ok']:>7}")    if r["ok"]        else f"{'0':>7}"
            fail_s  = red(f"{r['failed']:>8}")  if r["failed"]    else f"{'0':>8}"
            print(f"{r['job_date']:<14} {r['total']:>7} {ok_s} {fail_s} "
                  f"{(r['cancelled'] or 0):>10} {(r['active'] or 0):>7}")
    finally:
        await db.close()


async def cmd_jobs_cancel(args):
    config = _load_config(args.config)
    db = await _open_db(config)
    try:
        cursor = await db.execute(
            "SELECT id, status, original_filename FROM jobs WHERE id = ?", [args.job_id]
        )
        job = await cursor.fetchone()
        if not job:
            print(red(f"Job {args.job_id} not found."))
            sys.exit(1)
        if job["status"] not in ("pending", "retrying"):
            print(yellow(f"Cannot cancel — job status is '{job['status']}'. "
                         f"Only pending/retrying jobs can be cancelled."))
            sys.exit(1)
        await db.execute(
            "UPDATE jobs SET status='cancelled', updated_at=? WHERE id=?",
            [datetime.now(timezone.utc).isoformat(), args.job_id],
        )
        await db.commit()
        print(green(f"Job {args.job_id} ({job['original_filename']}) cancelled."))
    finally:
        await db.close()


async def cmd_jobs_purge(args):
    config = _load_config(args.config)
    db = await _open_db(config)
    try:
        cursor = await db.execute(
            "SELECT id, status, original_filename, storage_path FROM jobs WHERE id = ?",
            [args.job_id],
        )
        job = await cursor.fetchone()
        if not job:
            print(red(f"Job {args.job_id} not found."))
            sys.exit(1)

        if not args.force:
            job_dir = Path(config.storage.base_path) / job["storage_path"]
            print(f"About to permanently delete:")
            print(f"  Job ID : {job['id']}")
            print(f"  File   : {job['original_filename']}")
            print(f"  Status : {job['status']}")
            print(f"  Path   : {job_dir}")
            answer = input(bold("  Confirm? [y/N] ")).strip().lower()
            if answer != "y":
                print("Aborted.")
                return

        job_dir = Path(config.storage.base_path) / job["storage_path"]
        if job_dir.exists():
            shutil.rmtree(job_dir)
            print(dim(f"  Files deleted: {job_dir}"))
        else:
            print(dim(f"  No files on disk (already gone)."))

        await db.execute("DELETE FROM jobs WHERE id = ?", [args.job_id])
        await db.commit()
        print(green(f"Job {args.job_id} purged."))
    finally:
        await db.close()


async def cmd_jobs_cleanup(args):
    config = _load_config(args.config)
    db = await _open_db(config)
    try:
        cursor = await db.execute(
            "SELECT id, storage_path FROM jobs "
            "WHERE job_date <= date('now', ?) AND status IN ('completed','failed','cancelled')",
            [f"-{args.older_than} days"],
        )
        jobs = await cursor.fetchall()
        if not jobs:
            print(dim(f"No completed/failed/cancelled jobs older than {args.older_than} days."))
            return
        removed, missing = 0, 0
        for job in jobs:
            job_dir = Path(config.storage.base_path) / job["storage_path"]
            if job_dir.exists():
                shutil.rmtree(job_dir)
                removed += 1
            else:
                missing += 1
        print(green(f"Deleted files for {removed} job(s) older than {args.older_than} days."))
        if missing:
            print(dim(f"  {missing} job(s) had no files (already clean)."))
        print(dim("  DB records kept for audit trail."))
    finally:
        await db.close()


# ── status ────────────────────────────────────────────────────────────────────

async def cmd_status(args):
    config = _load_config(args.config)

    # Server reachability
    try:
        import httpx
        r = httpx.get(f"http://127.0.0.1:{config.server.port}/health", timeout=3)
        server_line = green("running") if r.status_code == 200 else red(f"unhealthy (HTTP {r.status_code})")
    except Exception:
        server_line = red("stopped / unreachable")

    print(bold("Server"))
    print(f"  Status  : {server_line}")
    print(f"  Address : http://127.0.0.1:{config.server.port}")
    print()

    db = await _open_db(config)
    try:
        cursor = await db.execute("SELECT status, COUNT(*) as n FROM jobs GROUP BY status")
        counts = {r["status"]: r["n"] for r in await cursor.fetchall()}

        processing_n = counts.get("processing", 0)
        pending_n    = counts.get("pending", 0)

        if processing_n:
            worker_line = cyan(f"processing ({processing_n} active job{'s' if processing_n > 1 else ''})")
        elif pending_n:
            worker_line = yellow(f"idle — {pending_n} job{'s' if pending_n > 1 else ''} waiting in queue")
        else:
            worker_line = green("idle")

        print(bold("Worker"))
        print(f"  Status  : {worker_line}")

        if processing_n:
            cursor2 = await db.execute(
                "SELECT id, original_filename, progress_current, progress_total FROM jobs WHERE status='processing'"
            )
            for j in await cursor2.fetchall():
                cur = j["progress_current"] or 0
                tot = j["progress_total"] or "?"
                print(f"  ↳ {dim(j['id'])}  {j['original_filename']}  page {cur}/{tot}")
        print()

        print(bold("Queue"))
        for s in ("pending", "processing", "retrying", "recovering", "completed", "failed", "cancelled"):
            n = counts.get(s, 0)
            if n or s in ("pending", "completed", "failed"):
                label = _status_colour(s)
                print(f"  {s:<14} {n:>6}")
        print()

        print(bold("Storage"))
        data_path = Path(config.storage.base_path)
        if data_path.exists():
            usage = shutil.disk_usage(data_path)
            used  = usage.used  / 1024**3
            total = usage.total / 1024**3
            free  = usage.free  / 1024**3
            pct   = usage.used / usage.total * 100
            bar_filled = int(pct / 5)
            bar = f"[{'█' * bar_filled}{'░' * (20 - bar_filled)}]"
            print(f"  Path    : {data_path}")
            print(f"  Disk    : {bar} {pct:.0f}%  ({used:.1f} GB used, {free:.1f} GB free of {total:.1f} GB)")
    finally:
        await db.close()


# ── llm ───────────────────────────────────────────────────────────────────────

async def cmd_llm(args):
    config = _load_config(args.config)

    print(bold("Providers"))
    for name, p in config.providers.items():
        if p.api_key and len(p.api_key) > 8:
            masked = p.api_key[:8] + "..."
        else:
            masked = dim("(not set)")
        print(f"  {cyan(name):<20} {p.base_url}")
        print(f"  {'':20} key: {masked}   timeout: {p.timeout}s")
    print()

    print(bold("Models"))
    roles = [
        ("vision",        config.models.vision,        "page image → markdown"),
        ("merge",         config.models.merge,         "fusion agent (multi-source → final)"),
        ("filter",        config.models.filter,        "boilerplate page detection"),
        ("image_describe",config.models.image_describe,"embedded image descriptions"),
    ]
    for role, m, desc in roles:
        print(f"  {cyan(role):<20} {m.provider} / {m.name}   (max_tokens: {m.max_tokens})")
        print(f"  {'':20} {dim(desc)}")
    print()

    if args.test:
        print(bold("Live connectivity"))
        try:
            import httpx
            r = httpx.get(f"http://127.0.0.1:{config.server.port}/health/llm", timeout=15)
            if r.status_code == 200:
                for p in r.json().get("providers", []):
                    s = green("ok") if p["status"] == "ok" else red(p["status"])
                    err = f"  {dim(p.get('error',''))}" if p.get("error") else ""
                    print(f"  {p['provider']:<20} {s}{err}")
            else:
                print(yellow("  Server not running — start it first, then re-run: ides llm --test"))
        except Exception:
            print(yellow("  Server not running — start it first, then re-run: ides llm --test"))


# ── restart / stop ────────────────────────────────────────────────────────────

def _systemctl(action: str, args):
    if shutil.which("systemctl") is None:
        print(yellow("systemctl not found — not running on a systemd system."))
        print(dim("  To stop manually: kill $(lsof -ti:<port>)"))
        return
    result = subprocess.run(["systemctl", action, "ides"], capture_output=True, text=True)
    if result.returncode == 0:
        print(green(f"ides service {action}ed."))
    else:
        err = result.stderr.strip()
        if any(x in err for x in ("not found", "not loaded", "not-found")):
            print(yellow("Systemd service 'ides' is not installed."))
            print(dim("  See DEPLOY.md §6 to set it up."))
        else:
            print(red(f"systemctl {action} ides: {err or 'unknown error'}"))


def cmd_restart(args): _systemctl("restart", args)
def cmd_stop(args):    _systemctl("stop", args)


# ── parser ────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ides",
        description=bold("IDES — Intelligent Document Extraction System"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
commands:
  serve               Start the API server
  keys create         Create a new API key  (shown once — save it!)
  keys list           List all active API keys
  keys revoke <id>    Revoke an API key
  jobs list           List jobs — filter by --date and/or --status
  jobs stats          Daily job statistics for the last N days
  jobs cancel <id>    Cancel a pending/retrying job (keeps DB record)
  jobs purge <id>     Delete a job completely — files and DB row
  jobs cleanup        Delete job files older than N days (keeps DB records)
  status              Server state, worker activity, queue depth, disk usage
  llm                 Show LLM provider and model config; --test checks live
  restart             Restart the IDES systemd service
  stop                Stop the IDES systemd service

run 'ides <command> --help' for per-command options
""",
    )

    parser.add_argument(
        "--config", default="config.yaml", metavar="PATH",
        help="path to config file (default: config.yaml)",
    )

    sub = parser.add_subparsers(title="commands", metavar="<command>")

    # serve
    p = sub.add_parser("serve", help="start the API server")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.set_defaults(func=cmd_serve)

    # keys
    p_keys = sub.add_parser("keys", help="API key management")
    ks = p_keys.add_subparsers(title="actions", metavar="<action>")

    p = ks.add_parser("create", help="create a new API key")
    p.add_argument("--name",  required=True, help="key label, e.g. 'n8n-prod'")
    p.add_argument("--owner", required=True, help="owner name")
    p.add_argument("--ips",   metavar="IP,IP", help="restrict to IPs (comma-separated, optional)")
    p.set_defaults(func=lambda a: asyncio.run(cmd_keys_create(a)))

    p = ks.add_parser("list", help="list active API keys")
    p.set_defaults(func=lambda a: asyncio.run(cmd_keys_list(a)))

    p = ks.add_parser("revoke", help="revoke an API key")
    p.add_argument("id", help="key ID to revoke")
    p.set_defaults(func=lambda a: asyncio.run(cmd_keys_revoke(a)))

    # jobs
    p_jobs = sub.add_parser("jobs", help="job management")
    js = p_jobs.add_subparsers(title="actions", metavar="<action>")

    p = js.add_parser("list", help="list jobs")
    p.add_argument("--date",   metavar="YYYY-MM-DD", help="filter by date")
    p.add_argument("--status", help="filter by status")
    p.add_argument("--limit",  type=int, default=50, help="max rows (default 50)")
    p.set_defaults(func=lambda a: asyncio.run(cmd_jobs_list(a)))

    p = js.add_parser("stats", help="daily job statistics")
    p.add_argument("--days", type=int, default=30, help="days to look back (default 30)")
    p.set_defaults(func=lambda a: asyncio.run(cmd_jobs_stats(a)))

    p = js.add_parser("cancel", help="cancel a pending/retrying job")
    p.add_argument("job_id")
    p.set_defaults(func=lambda a: asyncio.run(cmd_jobs_cancel(a)))

    p = js.add_parser("purge", help="delete job files and DB row")
    p.add_argument("job_id")
    p.add_argument("--force", action="store_true", help="skip confirmation prompt")
    p.set_defaults(func=lambda a: asyncio.run(cmd_jobs_purge(a)))

    p = js.add_parser("cleanup", help="delete old job files (keeps DB records)")
    p.add_argument("--older-than", type=int, default=90, dest="older_than",
                   metavar="DAYS", help="days threshold (default 90)")
    p.set_defaults(func=lambda a: asyncio.run(cmd_jobs_cleanup(a)))

    # status
    p = sub.add_parser("status", help="server/worker status, queue, disk usage")
    p.set_defaults(func=lambda a: asyncio.run(cmd_status(a)))

    # llm
    p = sub.add_parser("llm", help="show LLM configuration")
    p.add_argument("--test", action="store_true", help="test live provider connectivity")
    p.set_defaults(func=lambda a: asyncio.run(cmd_llm(a)))

    # restart / stop
    p = sub.add_parser("restart", help="restart the IDES systemd service")
    p.set_defaults(func=cmd_restart)

    p = sub.add_parser("stop", help="stop the IDES systemd service")
    p.set_defaults(func=cmd_stop)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)
    args.func(args)


if __name__ == "__main__":
    main()
