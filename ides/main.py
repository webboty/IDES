from __future__ import annotations

import argparse
import asyncio
import signal
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI

from ides.api.admin import router as admin_router
from ides.api.jobs import router as jobs_router
from ides.config import AppConfig, load_config
from ides.llm.client import LLMClient
from ides.pipeline.orchestrator import run_with_retry
from ides.security import create_auth_middleware
from ides.storage.database import close_database, init_database
from ides.storage.file_store import FileStore
from ides.storage.job_store import get_pending_jobs, get_job, update_job

import aiosqlite


_db: aiosqlite.Connection | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db
    config: AppConfig = app.state.config
    db_path = str(config.storage.base_path) + "/ides.db"
    _db = await init_database(db_path)
    app.state.db = _db
    app.state.file_store = FileStore(config.storage.base_path)
    app.state.llm_client = LLMClient(
        {name: p.model_dump() for name, p in config.providers.items()}
    )

    llm_results = await app.state.llm_client.check_all()
    for r in llm_results:
        status = r["status"]
        name = r["provider"]
        if status == "ok":
            print(f"  LLM provider '{name}': OK")
        else:
            print(
                f"  LLM provider '{name}': {status} (extraction will use text_layer + OCR only)"
            )

    worker_task = asyncio.create_task(
        _worker_loop(_db, config, app.state.file_store, app.state.llm_client)
    )

    yield

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    await close_database(_db)
    _db = None


async def _worker_loop(
    db: aiosqlite.Connection,
    config: AppConfig,
    file_store: FileStore,
    llm_client: LLMClient,
):
    semaphore = asyncio.Semaphore(config.queue.max_concurrent_jobs)

    while True:
        try:
            pending = await get_pending_jobs(db, limit=config.queue.max_concurrent_jobs)
            if pending:
                tasks = []
                for job in pending:
                    await update_job(db, job["id"], status="processing")
                    tasks.append(
                        _run_job_with_semaphore(
                            semaphore, job, config, file_store, llm_client, db
                        )
                    )
                await asyncio.gather(*tasks, return_exceptions=True)
            else:
                await asyncio.sleep(config.queue.worker_poll_interval)
        except asyncio.CancelledError:
            break
        except Exception as e:
            await asyncio.sleep(config.queue.worker_poll_interval)


async def _run_job_with_semaphore(
    semaphore: asyncio.Semaphore,
    job: dict,
    config: AppConfig,
    file_store: FileStore,
    llm_client: LLMClient,
    db: aiosqlite.Connection,
):
    async with semaphore:
        try:
            await asyncio.wait_for(
                run_with_retry(job, config, file_store, llm_client, db),
                timeout=config.queue.job_timeout,
            )
        except asyncio.TimeoutError:
            await update_job(job["id"], status="failed", last_error="Job timed out")
        except Exception as e:
            await update_job(job["id"], status="failed", last_error=str(e))


def create_app(config: AppConfig | None = None) -> FastAPI:
    if config is None:
        config = load_config()

    app = FastAPI(title="IDES", version="0.1.0")
    app.state.config = config

    create_auth_middleware(app, config)

    app.include_router(jobs_router)
    app.include_router(admin_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/health/llm")
    async def health_llm():
        llm: LLMClient | None = getattr(app.state, "llm_client", None)
        if not llm:
            return {"providers": [], "note": "LLM client not initialized"}
        results = await llm.check_all()
        return {"providers": results}

    app.router.lifespan_context = lifespan

    return app


app = create_app()


def cli():
    parser = argparse.ArgumentParser(
        description="IDES - Intelligent Document Extraction System"
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--host", default=None, help="Override host")
    parser.add_argument("--port", type=int, default=None, help="Override port")
    args = parser.parse_args()

    config = load_config(args.config)
    host = args.host or config.server.host
    port = args.port or config.server.port

    app = create_app(config)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    cli()
