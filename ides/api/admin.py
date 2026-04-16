from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ides.models import APIKeyCreate, APIKeyInfo, APIKeyResponse
from ides.security import generate_api_key

router = APIRouter(prefix="/admin")


@router.post("/keys", response_model=APIKeyResponse)
async def create_key(body: APIKeyCreate, request: Request):
    db = request.app.state.db
    raw_key, key_hash, key_prefix = generate_api_key()

    import uuid
    from ides.storage.job_store import create_api_key

    key_id = uuid.uuid4().hex[:16]
    await create_api_key(
        db,
        key_id=key_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=body.name,
        owner=body.owner,
        allowed_ips=body.allowed_ips,
    )

    return APIKeyResponse(
        id=key_id,
        key=raw_key,
        key_prefix=key_prefix,
        name=body.name,
        owner=body.owner,
    )


@router.get("/keys", response_model=list[APIKeyInfo])
async def list_keys(request: Request):
    db = request.app.state.db
    from ides.storage.job_store import list_api_keys
    import json

    keys = await list_api_keys(db)
    result = []
    for k in keys:
        allowed_ips = None
        if k.get("allowed_ips"):
            allowed_ips = json.loads(k["allowed_ips"])
        result.append(
            APIKeyInfo(
                id=k["id"],
                key_prefix=k["key_prefix"],
                name=k["name"],
                owner=k["owner"],
                is_active=bool(k.get("is_active", 1)),
                allowed_ips=allowed_ips,
                last_used_at=k.get("last_used_at"),
                expires_at=k.get("expires_at"),
            )
        )
    return result


@router.delete("/keys/{key_id}")
async def delete_key(key_id: str, request: Request):
    db = request.app.state.db
    from ides.storage.job_store import deactivate_api_key

    deleted = await deactivate_api_key(db, key_id)
    if not deleted:
        raise HTTPException(404, "Key not found or already deactivated")
    return {"deleted": True}
