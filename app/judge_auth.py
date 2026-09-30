"""Per-judge credentials, the server-side blind projection and the judge audit.

Owner decision (Gate 8): every judge has an individual credential, a judge
device never holds the shared owner key (``CALYX_API_KEY``), and blind judging
is enforced here rather than in a client.

Credentials
    ``ocj_<credential id>_<43 random url-safe chars>``, minted by the owner and
    shown once. Only ``HMAC-SHA256(CALYX_JUDGE_TOKEN_SECRET, token)`` is
    stored, and it is compared in constant time. A credential names one judge
    and one show, may narrow to events and categories, expires, and can be
    revoked or rotated. It is presented as ``Authorization: Bearer <token>``
    to the judge routes only. It contains no ``.``, so the owner-session
    decoder rejects it, and it can never equal ``CALYX_API_KEY``: neither owner
    dependency accepts it.

Fail closed
    With ``CALYX_JUDGE_TOKEN_SECRET`` unset, shorter than 32 characters, or
    equal to an owner credential, no judge credential can be issued or used.

Blind projection
    ``judge_plant_view`` is the single function that shapes a plant for a
    judge. For a blind event it drops every exhibitor field, the plant notes,
    and a plant name that mentions the exhibitor, and it names the plant by an
    opaque per-event handle instead of its id. Judge-facing scorecards are
    likewise named by an opaque handle, and lists are ordered by handle, so
    registration order (which groups an exhibitor's plants) does not show.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import string
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Exhibitor,
    Judge,
    JudgeActionAudit,
    JudgeAssignment,
    JudgeCredential,
    JudgingEvent,
    Plant,
    PlantCategory,
    Score,
    Scorecard,
)
from app.security import credentials_match

JUDGE_TOKEN_PREFIX = "ocj_"
JUDGE_SECRET_ENV = "CALYX_JUDGE_TOKEN_SECRET"
MIN_SECRET_LENGTH = 32
DEFAULT_TTL_MINUTES = 24 * 60
MIN_TTL_MINUTES = 5
MAX_TTL_MINUTES = 14 * 24 * 60

_CREDENTIAL_ID_LENGTH = 32
_HEX = frozenset(string.hexdigits.lower())
# Compared against when no credential matches, so an unknown id costs the
# same constant-time comparison as a wrong secret.
_NO_MATCH_HASH = "0" * 64
_OWNER_SECRET_ENVS = (
    "CALYX_API_KEY",
    "CALYX_OWNER_SESSION_SECRET",
    "CALYX_OWNER_ACCESS_CODE",
)


def utcnow() -> datetime:
    """Naive UTC, matching the existing timezone-naive columns."""
    return datetime.now(UTC).replace(tzinfo=None)


# ── Secret ────────────────────────────────────────────────────────


def judge_token_secret() -> bytes | None:
    """The server secret, or None when judge access must stay closed."""
    raw = (os.getenv(JUDGE_SECRET_ENV) or "").strip()
    if len(raw) < MIN_SECRET_LENGTH:
        return None
    for name in _OWNER_SECRET_ENVS:
        other = (os.getenv(name) or "").strip()
        # A judge secret equal to an owner credential would tie the two
        # authorities together; refuse to run judge access on it.
        if other and credentials_match(raw, other):
            return None
    return raw.encode("utf-8")


def require_judge_secret() -> bytes:
    secret = judge_token_secret()
    if secret is None:
        raise HTTPException(
            status_code=503, detail="Judge authentication is not configured"
        )
    return secret


def _mac(secret: bytes, *parts: str) -> str:
    message = "|".join(parts).encode("utf-8", "surrogatepass")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def hash_judge_token(secret: bytes, token: str) -> str:
    return _mac(secret, "judge-credential", "v1", token)


def plant_handle(secret: bytes, event_id: str, plant_id: str) -> str:
    """Opaque per-event plant name; nothing outside the server can invert it."""
    return "p_" + _mac(secret, "plant-handle", "v1", event_id, plant_id)[:24]


def scorecard_handle(secret: bytes, scorecard_id: str) -> str:
    return "s_" + _mac(secret, "scorecard-handle", "v1", scorecard_id)[:24]


# ── Credentials ───────────────────────────────────────────────────


def mint_judge_token() -> tuple[str, str]:
    """Return ``(credential_id, token)``; the token is never stored."""
    credential_id = secrets.token_hex(_CREDENTIAL_ID_LENGTH // 2)
    return (
        credential_id,
        f"{JUDGE_TOKEN_PREFIX}{credential_id}_{secrets.token_urlsafe(32)}",
    )


def parse_credential_id(token: str) -> str | None:
    if not token.startswith(JUDGE_TOKEN_PREFIX):
        return None
    body = token[len(JUDGE_TOKEN_PREFIX) :]
    credential_id, sep, rest = (
        body[:_CREDENTIAL_ID_LENGTH],
        body[_CREDENTIAL_ID_LENGTH : _CREDENTIAL_ID_LENGTH + 1],
        body[_CREDENTIAL_ID_LENGTH + 1 :],
    )
    if sep != "_" or len(rest) < 32 or not set(credential_id) <= _HEX:
        return None
    return credential_id


def _json_ids(raw: str | None) -> frozenset[str] | None:
    if raw is None:
        return None
    return frozenset(json.loads(raw))


@dataclass
class JudgeContext:
    """Who the verified credential says the caller is; never read from a header."""

    judge_id: str
    judge_name: str
    show_id: str
    credential_id: str
    expires_at: datetime
    secret: bytes = field(repr=False)
    event_ids: frozenset[str] | None = None
    category_ids: frozenset[str] | None = None


def credential_scope(credential: JudgeCredential) -> dict[str, list[str] | None]:
    events = _json_ids(credential.event_ids_json)
    categories = _json_ids(credential.category_ids_json)
    return {
        "event_ids": sorted(events) if events is not None else None,
        "category_ids": sorted(categories) if categories is not None else None,
    }


def authenticate_judge_token(db: Session, token: str) -> JudgeContext:
    """Resolve a presented bearer token to a judge, or raise 401/503."""
    secret = require_judge_secret()
    credential_id = parse_credential_id(token)
    credential = db.get(JudgeCredential, credential_id) if credential_id else None
    presented_hash = hash_judge_token(secret, token)
    matches = credentials_match(
        presented_hash, credential.token_hash if credential else _NO_MATCH_HASH
    )
    if credential is None or not matches:
        raise HTTPException(status_code=401, detail="Invalid judge credential")

    now = utcnow()
    failure = None
    if credential.revoked_at is not None:
        failure = ("credential_revoked", "Judge credential has been revoked")
    elif credential.expires_at <= now:
        failure = ("credential_expired", "Judge credential has expired")
    judge = db.get(Judge, credential.judge_id)
    if failure is None and (judge is None or judge.show_id != credential.show_id):
        failure = ("credential_invalid", "Invalid judge credential")
    if failure is not None:
        _write_audit(
            db,
            judge_id=credential.judge_id,
            credential_id=credential.id,
            action="authenticate",
            outcome=failure[0],
            http_status=401,
            ref=AuditRef(),
        )
        raise HTTPException(status_code=401, detail=failure[1])

    return JudgeContext(
        judge_id=judge.id,
        judge_name=judge.name,
        show_id=credential.show_id,
        credential_id=credential.id,
        expires_at=credential.expires_at,
        secret=secret,
        event_ids=_json_ids(credential.event_ids_json),
        category_ids=_json_ids(credential.category_ids_json),
    )


def bearer_judge_token(authorization: str | None) -> str | None:
    scheme, _, token = (authorization or "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token.startswith(JUDGE_TOKEN_PREFIX):
        return None
    return token


# ── Scope ─────────────────────────────────────────────────────────


def judge_scope(db: Session, ctx: JudgeContext) -> dict[str, set[str]]:
    """Event id -> category ids this judge may see, from assignments and credential.

    A category is in scope only when an active assignment covers it (an
    assignment without a category covers the whole event) and the credential,
    if it narrows, names it; the event must belong to the credential's show.
    """
    assignments = (
        db.execute(
            select(JudgeAssignment).where(
                JudgeAssignment.judge_id == ctx.judge_id,
                JudgeAssignment.active.is_(True),
            )
        )
        .scalars()
        .all()
    )
    covered: dict[str, set[str] | None] = {}
    for assignment in assignments:
        event_id = assignment.judging_event_id
        if ctx.event_ids is not None and event_id not in ctx.event_ids:
            continue
        if assignment.category_id is None:
            covered[event_id] = None
        elif covered.get(event_id, set()) is not None:
            covered.setdefault(event_id, set()).add(assignment.category_id)

    scope: dict[str, set[str]] = {}
    for event_id, categories in covered.items():
        event = db.get(JudgingEvent, event_id)
        if event is None or event.show_id != ctx.show_id:
            continue
        event_categories = set(
            db.execute(
                select(PlantCategory.id).where(
                    PlantCategory.judging_event_id == event_id
                )
            ).scalars()
        )
        allowed = (
            event_categories if categories is None else categories & event_categories
        )
        if ctx.category_ids is not None:
            allowed &= ctx.category_ids
        if allowed:
            scope[event_id] = allowed
    return scope


def plant_in_scope(scope: dict[str, set[str]], plant: Plant) -> bool:
    return plant.category_id in scope.get(plant.judging_event_id, set())


# ── Blind projection ──────────────────────────────────────────────


def _exhibitor_markers(exhibitor: Exhibitor | None) -> tuple[list[str], str | None]:
    """Lower-cased strings whose presence in text identifies the exhibitor."""
    if exhibitor is None:
        return [], None
    markers = [exhibitor.id.casefold()]
    for value in (exhibitor.name, exhibitor.email):
        if value:
            markers.append(value.casefold())
    words = re.split(
        r"[^\w]+",
        f"{exhibitor.name or ''} {(exhibitor.email or '').split('@')[0]}".casefold(),
    )
    markers.extend(word for word in words if len(word) >= 3)
    phone_digits = re.sub(r"\D", "", exhibitor.phone or "")
    return [m for m in markers if m], (
        phone_digits[-7:] if len(phone_digits) >= 4 else None
    )


def mentions_exhibitor(text: str | None, exhibitor: Exhibitor | None) -> bool:
    """Conservative: any exhibitor name word (3+ chars), email, id or phone tail."""
    if not text:
        return False
    markers, phone_tail = _exhibitor_markers(exhibitor)
    folded = text.casefold()
    if any(marker in folded for marker in markers):
        return True
    return bool(phone_tail) and phone_tail in re.sub(r"\D", "", text)


def judge_plant_view(
    db: Session, ctx: JudgeContext, event: JudgingEvent, plant: Plant
) -> dict:
    """The only shape in which a plant reaches a judge.

    Never includes the plant id, exhibitor id, exhibitor contact, QR token or
    registration timestamps. A blind event also withholds the exhibitor name,
    the free-text notes, and a plant name that mentions the exhibitor. A
    non-blind event shows the exhibitor's name, as the owner's tag sheet does.
    """
    category = db.get(PlantCategory, plant.category_id)
    exhibitor = db.get(Exhibitor, plant.exhibitor_id)
    view: dict = {
        "plant_handle": plant_handle(ctx.secret, event.id, plant.id),
        "judging_event_id": event.id,
        "category_id": plant.category_id,
        "category_name": category.name if category else None,
        "blind": bool(event.is_blind),
    }
    if event.is_blind:
        withheld = mentions_exhibitor(plant.name, exhibitor)
        view["plant_name"] = None if withheld else plant.name
        view["plant_name_withheld"] = withheld
    else:
        view["plant_name"] = plant.name
        view["plant_name_withheld"] = False
        view["notes"] = plant.notes
        view["exhibitor_name"] = exhibitor.name if exhibitor else None
    return view


def judge_event_view(event: JudgingEvent) -> dict:
    return {
        "id": event.id,
        "name": event.name,
        "judging_type": event.judging_type,
        "is_blind": bool(event.is_blind),
        "status": event.status,
    }


def judge_scorecard_view(
    db: Session,
    ctx: JudgeContext,
    scorecard: Scorecard,
    event: JudgingEvent,
    plant: Plant,
    *,
    include_scores: bool = False,
) -> dict:
    view = {
        "scorecard_handle": scorecard_handle(ctx.secret, scorecard.id),
        "judging_event_id": event.id,
        "status": scorecard.status,
        "total": scorecard.total,
        "version": scorecard.version,
        "submitted_at": scorecard.submitted_at.isoformat()
        if scorecard.submitted_at
        else None,
        "plant": judge_plant_view(db, ctx, event, plant),
    }
    if include_scores:
        scores = (
            db.execute(
                select(Score).where(
                    Score.plant_id == plant.id, Score.judge_id == ctx.judge_id
                )
            )
            .scalars()
            .all()
        )
        view["scores"] = [
            {
                "criterion_id": s.criterion_id,
                "value": s.value,
                "choice": s.choice,
                "value_rank": s.value_rank,
            }
            for s in sorted(scores, key=lambda s: s.criterion_id)
        ]
    return view


# ── Audit ─────────────────────────────────────────────────────────


@dataclass
class AuditRef:
    """Object ids a judge action touched, filled in as the route resolves them."""

    judging_event_id: str | None = None
    category_id: str | None = None
    scorecard_id: str | None = None
    plant_id: str | None = None
    plant_handle: str | None = None

    def plant(self, ctx: JudgeContext, plant: Plant) -> None:
        self.judging_event_id = plant.judging_event_id
        self.category_id = plant.category_id
        self.plant_id = plant.id
        self.plant_handle = plant_handle(ctx.secret, plant.judging_event_id, plant.id)


_OUTCOMES = {
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "invalid",
}


def _write_audit(
    db: Session,
    *,
    judge_id: str,
    credential_id: str | None,
    action: str,
    outcome: str,
    http_status: int,
    ref: AuditRef,
    detail: str | None = None,
) -> None:
    db.add(
        JudgeActionAudit(
            judge_id=judge_id,
            credential_id=credential_id,
            action=action,
            judging_event_id=ref.judging_event_id,
            category_id=ref.category_id,
            scorecard_id=ref.scorecard_id,
            plant_id=ref.plant_id,
            plant_handle=ref.plant_handle,
            outcome=outcome,
            http_status=http_status,
            detail=detail[:200] if detail else None,
            created_at=utcnow(),
        )
    )
    db.commit()


@contextmanager
def judge_action(
    db: Session, ctx: JudgeContext, action: str, **ids: str | None
) -> Iterator[AuditRef]:
    """Record one judge action, successful or refused, in the append-only audit."""
    ref = AuditRef(**ids)
    try:
        yield ref
    except HTTPException as exc:
        db.rollback()
        detail = exc.detail if isinstance(exc.detail, str) else None
        outcome = (
            "locked"
            if detail and "locked" in detail.lower()
            else _OUTCOMES.get(exc.status_code, "error")
        )
        _write_audit(
            db,
            judge_id=ctx.judge_id,
            credential_id=ctx.credential_id,
            action=action,
            outcome=outcome,
            http_status=exc.status_code,
            ref=ref,
            detail=detail,
        )
        raise
    _write_audit(
        db,
        judge_id=ctx.judge_id,
        credential_id=ctx.credential_id,
        action=action,
        outcome="ok",
        http_status=200,
        ref=ref,
    )
