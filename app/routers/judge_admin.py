"""Owner routes for judge credentials, the judge and owner audits, tag
re-issue and blind display labels.

Guarded by ``verify_owner_or_api_key``: the owner's browser session or the
owner key, as on the other owner routes. A judge credential never opens
them: it is not the owner key and the owner-session decoder rejects it.
Every change made here is written to the append-only ``show_owner_audit``.
"""

import hashlib
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
    event_exhibitors,
    exhibitor_mention_reasons,
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
    ShowOwnerAudit,
)
from app.routers.show_day import is_legacy_qr_token, new_qr_token
from app.security import verify_owner_or_api_key
from app.show_lock import ensure_show_unlocked

DbSession = Annotated[Session, Depends(get_db)]
Owner = Annotated[dict, Depends(verify_owner_or_api_key)]

router = APIRouter(
    prefix="/api",
    tags=["Judge Credentials"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


class BlindDisplayNameUpdate(BaseModel):
    blind_display_name: str | None = Field(None, max_length=200)
    confirm_despite_warnings: bool = False


class JudgeCredentialCreate(BaseModel):
    expires_in_minutes: int = Field(
        DEFAULT_TTL_MINUTES, ge=MIN_TTL_MINUTES, le=MAX_TTL_MINUTES
    )
    event_ids: list[str] | None = None
    category_ids: list[str] | None = None
    label: str | None = Field(None, max_length=120)
    rotate: bool = True


def _owner_audit(
    db: Session,
    owner: dict,
    *,
    action: str,
    object_type: str,
    object_id: str,
    show_id: str | None = None,
    judging_event_id: str | None = None,
    warnings: list[str] | None = None,
    confirmed: bool = False,
    text: str | None = None,
    detail: str | None = None,
) -> None:
    """Add one owner-audit row to the session; the caller commits.

    Text that drew warnings is recorded only as its SHA-256 digest.
    """
    withhold = bool(warnings) and text is not None
    db.add(
        ShowOwnerAudit(
            actor=str(owner.get("actor") or "owner"),
            auth_type=str(owner.get("auth_type") or "unknown"),
            action=action,
            object_type=object_type,
            object_id=object_id,
            show_id=show_id,
            judging_event_id=judging_event_id,
            warnings_json=json.dumps(warnings) if warnings else None,
            confirmed_despite_warnings=confirmed,
            text_value=None if withhold else text,
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest()
            if text
            else None,
            text_withheld=withhold,
            detail=detail,
            created_at=utcnow(),
        )
    )


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
def issue_judge_credential(
    judge_id: str, data: JudgeCredentialCreate, db: DbSession, owner: Owner
):
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
        issued_by=str(owner.get("auth_type") or "owner"),
        created_at=now,
        expires_at=now + timedelta(minutes=data.expires_in_minutes),
    )
    db.add(credential)
    _owner_audit(
        db,
        owner,
        action="rotate_credential" if revoked else "issue_credential",
        object_type="judge_credential",
        object_id=credential_id,
        show_id=judge.show_id,
        detail=f"judge={judge.id} revoked_previous={revoked}",
    )
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
def revoke_judge_credential(credential_id: str, db: DbSession, owner: Owner):
    credential = db.get(JudgeCredential, credential_id)
    if credential is None:
        raise HTTPException(status_code=404, detail="Judge credential not found")
    if credential.revoked_at is None:
        credential.revoked_at = utcnow()
        _owner_audit(
            db,
            owner,
            action="revoke_credential",
            object_type="judge_credential",
            object_id=credential.id,
            show_id=credential.show_id,
            detail=f"judge={credential.judge_id}",
        )
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
    owner: Owner,
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
    _owner_audit(
        db,
        owner,
        action="reissue_qr_tokens",
        object_type="judging_event",
        object_id=event.id,
        show_id=event.show_id,
        judging_event_id=event.id,
        detail=f"reissued={reissued} include_random={include_random}",
    )
    db.commit()
    return {"judging_event_id": event_id, "plants": len(plants), "reissued": reissued}


def _set_blind_label(
    db: Session,
    owner: Owner,
    *,
    target,
    object_type: str,
    event: JudgingEvent | None,
    data: BlindDisplayNameUpdate,
) -> dict:
    """Shared by the plant, class and event label routes.

    Warns (409 with reasons) when the label may identify any exhibitor with a
    plant in the event, unless the owner confirms. Every accepted change and
    every refusal is written to ``show_owner_audit``.
    """
    ensure_show_unlocked(db, event.show_id if event else None)
    text = (data.blind_display_name or "").strip() or None
    warnings: list[str] = []
    for exhibitor in event_exhibitors(db, event) if event else []:
        warnings.extend(exhibitor_mention_reasons(text, exhibitor))
    warnings = list(dict.fromkeys(warnings))
    audit = {
        "object_type": object_type,
        "object_id": target.id,
        "show_id": event.show_id if event else None,
        "judging_event_id": event.id if event else None,
        "warnings": warnings,
        "text": text,
    }
    if warnings and not data.confirm_despite_warnings:
        _owner_audit(db, owner, action="blind_label_refused", **audit)
        db.commit()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "This display name may identify an exhibitor. "
                "Resend with confirm_despite_warnings to keep it.",
                "warnings": warnings,
            },
        )
    target.blind_display_name = text
    action = "blind_label_cleared" if text is None else "blind_label_set"
    _owner_audit(db, owner, action=action, confirmed=bool(warnings), **audit)
    db.commit()
    return {
        f"{object_type}_id": target.id,
        "blind_display_name": text,
        "warnings": warnings,
        "confirmed_despite_warnings": bool(warnings),
    }


@router.put("/judging/plants/{plant_id}/blind-display-name")
def set_plant_blind_display_name(
    plant_id: str, data: BlindDisplayNameUpdate, db: DbSession, owner: Owner
):
    """Set the only plant name a judge sees while the plant's event is blind.

    Blind events withhold every free-text name entered for a plant; this is
    the owner's explicit, reviewed replacement (for example the taxon alone).
    ``null`` clears it, so judges see no name.
    """
    plant = db.get(Plant, plant_id)
    if plant is None:
        raise HTTPException(status_code=404, detail="Plant not found")
    event = db.get(JudgingEvent, plant.judging_event_id)
    return _set_blind_label(
        db, owner, target=plant, object_type="plant", event=event, data=data
    )


@router.put("/judging/categories/{category_id}/blind-display-name")
def set_category_blind_display_name(
    category_id: str, data: BlindDisplayNameUpdate, db: DbSession, owner: Owner
):
    """Set the class name judges see while the event is blind (else the class
    name is shown unless it mentions an exhibitor, when it is withheld)."""
    category = db.get(PlantCategory, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    event = db.get(JudgingEvent, category.judging_event_id)
    return _set_blind_label(
        db, owner, target=category, object_type="category", event=event, data=data
    )


@router.put("/judging/events/{event_id}/blind-display-name")
def set_event_blind_display_name(
    event_id: str, data: BlindDisplayNameUpdate, db: DbSession, owner: Owner
):
    """Set the event name judges see while it is blind (same rule as classes)."""
    event = db.get(JudgingEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Judging event not found")
    return _set_blind_label(
        db, owner, target=event, object_type="judging_event", event=event, data=data
    )


@router.get("/judging/owner-audit")
def owner_audit(
    db: DbSession,
    show_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
):
    """The append-only owner action trail for judging access and blind labels."""
    query = select(ShowOwnerAudit)
    if show_id:
        query = query.where(ShowOwnerAudit.show_id == show_id)
    rows = (
        db.execute(
            query.order_by(ShowOwnerAudit.created_at.desc(), ShowOwnerAudit.id).limit(
                limit
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "actor": r.actor,
            "auth_type": r.auth_type,
            "action": r.action,
            "object_type": r.object_type,
            "object_id": r.object_id,
            "show_id": r.show_id,
            "judging_event_id": r.judging_event_id,
            "warnings": json.loads(r.warnings_json) if r.warnings_json else [],
            "confirmed_despite_warnings": r.confirmed_despite_warnings,
            "text_value": r.text_value,
            "text_sha256": r.text_sha256,
            "text_withheld": r.text_withheld,
            "detail": r.detail,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
