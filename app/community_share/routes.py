"""Community share routes for Journey 11: audience-scoped sharing of observations and research artifacts.

Audience visibility rules:
  PUBLIC       — always visible to any caller
  MEMBERS_ONLY — requires X-Member: true header (MVP membership signal)
  PRIVATE      — only visible to the sharer (X-Requester-Id header matches sharer_auth_subject)

MVP uses an in-memory dict store. Full persistence via constituent_platform identity is a follow-up.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException

from .models import (
    AudienceScope,
    ShareListResponse,
    ShareLookupResponse,
    ShareRecord,
    ShareRequest,
)

router = APIRouter(
    prefix="/api/community",
    tags=["community-share"],
)

# In-memory store: share_token -> ShareRecord
_store: dict[str, ShareRecord] = {}


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _is_expired(record: ShareRecord) -> bool:
    if record.expires_at is None:
        return False
    return _now() >= record.expires_at


@router.post("/shares", status_code=201, response_model=ShareRecord)
def create_share(payload: ShareRequest) -> ShareRecord:
    """Create a new share record with a generated opaque share token."""
    record = ShareRecord(
        id=str(uuid.uuid4()),
        artifact_id=payload.artifact_id,
        artifact_kind=payload.artifact_kind,
        audience=payload.audience,
        sharer_auth_subject=payload.sharer_auth_subject,
        share_token=str(uuid.uuid4()),
        created_at=_now(),
        expires_at=payload.expires_at,
        is_active=True,
    )
    _store[record.share_token] = record
    return record


@router.get("/shares/{share_token}", response_model=ShareLookupResponse)
def get_share(
    share_token: str,
    x_member: str | None = Header(default=None, alias="X-Member"),
    x_requester_id: str | None = Header(default=None, alias="X-Requester-Id"),
) -> ShareLookupResponse:
    """Retrieve a share record by token, respecting audience-scoped visibility."""
    record = _store.get(share_token)

    if record is None or not record.is_active or _is_expired(record):
        raise HTTPException(status_code=404, detail="Share not found or expired")

    audience = record.audience

    if audience == AudienceScope.PUBLIC:
        pass  # always visible

    elif audience == AudienceScope.MEMBERS_ONLY:
        member_signal = (x_member or "").strip().lower()
        if member_signal != "true":
            raise HTTPException(
                status_code=403,
                detail="MEMBERS_ONLY content requires membership. Set X-Member: true.",
            )

    elif audience == AudienceScope.PRIVATE and (
        not x_requester_id or x_requester_id.strip() != record.sharer_auth_subject
    ):
        raise HTTPException(
            status_code=403,
            detail="PRIVATE content is only visible to the original sharer.",
        )

    artifact_preview = {
        "artifact_id": record.artifact_id,
        "artifact_kind": record.artifact_kind.value,
        "stub": True,
    }
    return ShareLookupResponse(share_record=record, artifact_preview=artifact_preview)


@router.get("/shares", response_model=ShareListResponse)
def list_shares(
    x_requester_id: str | None = Header(default=None, alias="X-Requester-Id"),
) -> ShareListResponse:
    """List all active share records belonging to the requester."""
    if not x_requester_id:
        raise HTTPException(
            status_code=400,
            detail="X-Requester-Id header is required to list shares.",
        )
    requester = x_requester_id.strip()
    items = [
        record
        for record in _store.values()
        if record.sharer_auth_subject == requester and record.is_active
    ]
    return ShareListResponse(items=items, total=len(items))


@router.delete("/shares/{share_token}", response_model=ShareRecord)
def delete_share(
    share_token: str,
    x_requester_id: str | None = Header(default=None, alias="X-Requester-Id"),
) -> ShareRecord:
    """Deactivate a share (set is_active=False). Owner only."""
    record = _store.get(share_token)
    if record is None:
        raise HTTPException(status_code=404, detail="Share not found")

    if not x_requester_id or x_requester_id.strip() != record.sharer_auth_subject:
        raise HTTPException(
            status_code=403,
            detail="Only the original sharer may deactivate this share.",
        )

    updated = record.model_copy(update={"is_active": False})
    _store[share_token] = updated
    return updated
