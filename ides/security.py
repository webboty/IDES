from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from ides.config import AppConfig
from ides.storage.job_store import (
    deactivate_api_key,
    get_api_key_by_hash,
    update_api_key_last_used,
)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    raw = f"ides_{secrets.token_hex(16)}"
    key_hash = hash_key(raw)
    prefix = raw[:9]
    return raw, key_hash, prefix


async def verify_api_key(api_key: str, client_ip: str, db: Any) -> dict | None:
    if not api_key:
        return None
    key_hash = hash_key(api_key)
    record = await get_api_key_by_hash(db, key_hash)
    if not record:
        return None
    allowed_ips = record.get("allowed_ips")
    if allowed_ips:
        allowed = json.loads(allowed_ips)
        if client_ip not in allowed:
            return None
    expires_at = record.get("expires_at")
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                return None
        except (ValueError, TypeError):
            pass
    return record


def create_auth_middleware(app: Any, config: AppConfig):
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next: Any):
        path = request.url.path

        if path.startswith("/admin"):
            admin_key = request.headers.get("X-Admin-Key")
            if admin_key != config.server.master_admin_key:
                return JSONResponse(
                    status_code=401, content={"error": "Invalid admin key"}
                )
            return await call_next(request)

        if path == "/extract" or path.startswith("/jobs"):
            api_key = request.headers.get("X-API-Key")
            client_ip = request.client.host if request.client else "unknown"
            db = getattr(request.app.state, "db", None)
            if db is None:
                return JSONResponse(
                    status_code=503, content={"error": "Service unavailable"}
                )
            key_record = await verify_api_key(api_key, client_ip, db)
            if not key_record:
                return JSONResponse(
                    status_code=401,
                    content={"error": "Invalid API key or IP not allowed"},
                )
            await update_api_key_last_used(db, key_record["id"])
            return await call_next(request)

        return await call_next(request)
