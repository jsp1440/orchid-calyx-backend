"""Owner routes for judge credentials, the judge audit and tag re-issue.

Guarded by the existing owner key (``verify_api_key``), exactly like the rest
of the judging admin surface; a judge credential never opens them.
"""

import json
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.judge_auth import (
    DEFAULT_TTL_MINUTES,
    MAX_TTL_MINUTES,
    MIN_TTL_MINUTES,
    credential_scope,
    hash_judge_token,
    mint_judge_token,
    require_judge_secret,
    utcnow,
)
from app.models import (
    Judge,
    JudgeActionAudit,
    JudgeCredential,
    JudgingEvent,
    Plant,
    PlantCategory,
)
from app.routers.show_day import is_legacy_qr_token, new_qr_token
from app.security import verify_api_key
from app.show_lock import ensure_show_unlocked

DbSession = Annotated[Session, Depends(get_db)]

router = APIRouter(
    prefix="/api", tags=["Judge Credentials"], dependencies=[Depends(verify_api_key)]
)


class JudgeCredentialCreate(BaseModel):
    expires_in_minutes: int = Field(
        DEFAULT_TTL_MINUTES, ge=MIN_TTL_MINUTES, le=MAX_TTL_MINUTES
    )
    event_ids: list[str] | None = None
    category_ids: list[str] | None = None
    label: str | None = Field(None, max_length=120)
    rotate: bool = True


def _credential_out(credential: JudgeCredential) -> dict:
    now = utcnow()
    if credential.revoked_at is not None:
        state = "revoked"
    elif credential.expires_at <= now:
        state = "expired"
    else:
        state = "active"
    return {
        "credential_id": credential.id,
        "judge_id": credential.judge_id,
        "show_id": credential.show_id,
        "label": credential.label,
        "state": state,
        "created_at": credential.created_at.isoformat()
        if credential.created_at
        else None,
        "expires_at": credential.expires_at.isoformat(),
        "revoked_at": credential.revoked_at.isoformat()
        if credential.revoked_at
        else None,
        "scope": credential_scope(credential),
    }


def _get_judge(db: Session, judge_id: str) -> Judge:
    judge = db.get(Judge, judge_id)
    if judge is None:
        raise HTTPException(status_code=404, detail="Judge not found")
    return judge


def _validate_scope(db: Session, judge: Judge, data: JudgeCredentialCreate) -> None:
    event_ids = set(data.event_ids or [])
    for event_id in event_ids:
        event = db.get(JudgingEvent, event_id)
        if event is None or event.show_id != judge.show_id:
            raise HTTPException(
                status_code=422,
                detail=f"Judging event {event_id} is not in this judge's show",
            )
    for category_id in set(data.category_ids or []):
        category = db.get(PlantCategory, category_id)
        event = db.get(JudgingEvent, category.judging_event_id) if category else None
        if event is None or event.show_id != judge.show_id:
            raise HTTPException(
                status_code=422,
                detail=f"Category {category_id} is not in this judge's show",
            )
        if data.event_ids is not None and category.judging_event_id not in event_ids:
            raise HTTPException(
                status_code=422,
                detail=f"Category {category_id} is outside the credential's events",
            )


def _revoke_active(db: Session, judge_id: str) -> int:
    now = utcnow()
    active = (
        db.execute(
            select(JudgeCredential).where(
                JudgeCredential.judge_id == judge_id,
                JudgeCredential.revoked_at.is_(None),
                JudgeCredential.expires_at > now,
            )
        )
        .scalars()
        .all()
    )
    for credential in active:
        credential.revoked_at = now
    return len(active)


@router.post("/judges/{judge_id}/credentials")
def issue_judge_credential(judge_id: str, data: JudgeCredentialCreate, db: DbSession):
    """Issue (and by default rotate to) a credential; the token is returned once only."""
    secret = require_judge_secret()
    judge = _get_judge(db, judge_id)
    _validate_scope(db, judge, data)
    revoked = _revoke_active(db, judge_id) if data.rotate else 0
    credential_id, token = mint_judge_token()
    now = utcnow()
    credential = JudgeCredential(
        id=credential_id,
        judge_id=judge.id,
        show_id=judge.show_id,
        token_hash=hash_judge_token(secret, token),
        event_ids_json=json.dumps(sorted(set(data.event_ids)))
        if data.event_ids is not None
        else None,
        category_ids_json=json.dumps(sorted(set(data.category_ids)))
        if data.category_ids is not None
        else None,
        label=data.label,
        issued_by="owner_api_key",
        created_at=now,
        expires_at=now + timedelta(minutes=data.expires_in_minutes),
    )
    db.add(credential)
    db.commit()
    db.refresh(credential)
    return {
        **_credential_out(credential),
        "token": token,
        "token_type": "Bearer",
        "token_notice": "Shown once. Only a keyed hash is stored; issue a new credential if it is lost.",
        "revoked_previous": revoked,
    }


@router.get("/judges/{judge_id}/credentials")
def list_judge_credentials(judge_id: str, db: DbSession):
    _get_judge(db, judge_id)
    credentials = (
        db.execute(
            select(JudgeCredential)
            .where(JudgeCredential.judge_id == judge_id)
            .order_by(JudgeCredential.created_at, JudgeCredential.id)
        )
        .scalars()
        .all()
    )
    return [_credential_out(c) for c in credentials]


@router.post("/judge-credentials/{credential_id}/revoke")
def revoke_judge_credential(credential_id: str, db: DbSession):
    credential = db.get(JudgeCredential, credential_id)
    if credential is None:
        raise HTTPException(status_code=404, detail="Judge credential not found")
    if credential.revoked_at is None:
        credential.revoked_at = utcnow()
        db.commit()
        db.refresh(credential)
    return _credential_out(credential)


@router.get("/judging/judge-audit")
def judge_audit(
    db: DbSession,
    judging_event_id: Annotated[str | None, Query()] = None,
    judge_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
):
    """The append-only judge action trail (owner only); it holds no exhibitor data."""
    query = select(JudgeActionAudit)
    if judging_event_id:
        query = query.where(JudgeActionAudit.judging_event_id == judging_event_id)
    if judge_id:
        query = query.where(JudgeActionAudit.judge_id == judge_id)
    rows = (
        db.execute(
            query.order_by(
                JudgeActionAudit.created_at.desc(), JudgeActionAudit.id
            ).limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "judge_id": r.judge_id,
            "credential_id": r.credential_id,
            "action": r.action,
            "judging_event_id": r.judging_event_id,
            "category_id": r.category_id,
            "scorecard_id": r.scorecard_id,
            "plant_id": r.plant_id,
            "plant_handle": r.plant_handle,
            "outcome": r.outcome,
            "http_status": r.http_status,
            "detail": r.detail,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/judging/events/{event_id}/reissue-qr-tokens")
def reissue_qr_tokens(
    event_id: str,
    db: DbSession,
    include_random: Annotated[bool, Query()] = False,
):
    """Replace id-derived tag tokens with random ones; reprint the tag sheet after.

    By default only legacy (id-derived) tokens are replaced; ``include_random``
    replaces every token, for example after a tag sheet was lost.
    """
    event = db.get(JudgingEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Judging event not found")
    ensure_show_unlocked(db, event.show_id)
    plants = (
        db.execute(select(Plant).where(Plant.judging_event_id == event_id))
        .scalars()
        .all()
    )
    reissued = 0
    for plant in plants:
        if include_random or not plant.qr_code or is_legacy_qr_token(plant):
            plant.qr_code = new_qr_token()
            reissued += 1
    db.commit()
    return {"judging_event_id": event_id, "plants": len(plants), "reissued": reissued}
