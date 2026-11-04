"""Tenant self-service API-key management (admin scope). Keys never cross tenants."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from adapters.relational_store.control_store import ControlStore
from apps.api.auth import SCOPES, Principal, authorize, issue_key
from apps.api.control import get_control_store

admin_router = APIRouter()


class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    scopes: list[str] = Field(..., min_length=1, description=f"Subset of {list(SCOPES)}")


class ApiKeyInfo(BaseModel):
    key_id: str
    name: str
    key_prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class CreatedKey(ApiKeyInfo):
    api_key: str = Field(..., description="Shown once. Store it in a secret manager.")


def _info(r) -> dict:
    return {k: getattr(r, k) for k in ApiKeyInfo.model_fields}


@admin_router.post("/keys", response_model=CreatedKey, status_code=status.HTTP_201_CREATED)
async def create_key(
    req: CreateKeyRequest,
    principal: Annotated[Principal, Depends(authorize)],
    store: Annotated[ControlStore, Depends(get_control_store)],
):
    try:
        record, raw = await issue_key(store, principal.tenant_id, req.scopes, req.name)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    return {**_info(record), "api_key": raw}


@admin_router.get("/keys", response_model=list[ApiKeyInfo])
async def list_keys(
    principal: Annotated[Principal, Depends(authorize)],
    store: Annotated[ControlStore, Depends(get_control_store)],
):
    return [_info(r) for r in await store.list_api_keys(principal.tenant_id)]


@admin_router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: str,
    principal: Annotated[Principal, Depends(authorize)],
    store: Annotated[ControlStore, Depends(get_control_store)],
):
    if key_id == principal.key_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "cannot revoke the key making this request")
    if not await store.revoke_api_key(principal.tenant_id, key_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "key not found")


class AuditEntry(BaseModel):
    seq: int
    key_id: str
    principal: str
    method: str
    route: str
    status: int
    created_at: datetime


@admin_router.get("/audit", response_model=list[AuditEntry])
async def audit_trail(
    principal: Annotated[Principal, Depends(authorize)],
    store: Annotated[ControlStore, Depends(get_control_store)],
    limit: int = 100,
):
    """Most recent mutating API calls for the caller's tenant (who did what, when)."""
    rows = await store.list_audit(principal.tenant_id, limit=min(max(limit, 1), 1000))
    return [{k: getattr(r, k) for k in AuditEntry.model_fields} for r in rows]
