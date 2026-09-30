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
    equal to any other secret the app reads (``OTHER_SECRET_ENVS``), no judge
    credential can be issued or used. Failed sign-ins are rate limited per
    credential id and per client address.

Blind projection
    ``judge_plant_view`` is the single function that shapes a plant for a
    judge. For a blind event it drops every exhibitor field and every
    free-text field entered per plant (name, notes); only an owner-approved
    ``blind_display_name`` is shown. Plants and scorecards are named by
    opaque handles that are judge-scoped and re-keyed each time the event
    enters blind mode, and lists are ordered by handle, so registration order
    (which groups an exhibitor's plants) does not show.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import string
import unicodedata
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
from app.rate_limit import SlidingWindowLimiter
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
# Every secret-bearing variable the app reads (``grep -rhoE 'getenv\("[A-Z_]*
# (SECRET|KEY|TOKEN|PASSWORD|ACCESS_CODE)'`` over app/). A judge secret equal
# to any of them would tie judge access to another authority.
OTHER_SECRET_ENVS = (
    "CALYX_API_KEY",
    "CALYX_OWNER_SESSION_SECRET",
    "CALYX_OWNER_ACCESS_CODE",
    "ORCHID_JUDGE_ADMIN_KEY",
    "ADMIN_API_KEY",
    "CONSTITUENT_MANAGE_SECRET",
    "CALYX_GITHUB_RESEARCH_WEBHOOK_SECRET",
    "CALYX_GITHUB_RESEARCH_FEEDBACK_TOKEN",
    "CALYX_ENGINEERING_PROVIDER_API_KEY",
    "CALYX_ENGINEERING_PROVIDER_TOKEN",
    "CALYX_CHAT_API_KEY",
    "GITHUB_TOKEN",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "FIRECRAWL_API_KEY",
    "BHL_API_KEY",
    "ZENODO_ACCESS_TOKEN",
    "OCU_SUPABASE_ANON_KEY",
    "PGPASSWORD",
)

# Authentication failures are braked per credential id and per client address
# with the shared in-process SlidingWindowLimiter. Once either key is spent,
# further attempts are refused (429) before any credential is checked. The
# per-client allowance is generous because a show hall usually shares one
# address.
AUTH_FAILURE_LIMITER = SlidingWindowLimiter()


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, "").strip() or default))
    except ValueError:
        return default


def auth_failure_limits() -> tuple[int, int, int]:
    """(per-credential limit, per-client limit, window seconds)."""
    return (
        _int_env("JUDGE_AUTH_FAILURE_LIMIT_PER_CREDENTIAL", 10),
        _int_env("JUDGE_AUTH_FAILURE_LIMIT_PER_CLIENT", 50),
        max(1, _int_env("JUDGE_AUTH_FAILURE_WINDOW_SECONDS", 300)),
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
    for name in OTHER_SECRET_ENVS:
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


def handle_epoch(event: JudgingEvent) -> str:
    """Which naming period handles belong to.

    Open events share one period. Each switch into blind mode draws a new
    ``blind_handle_salt`` (``app/routers/judging.py``), so a handle a judge
    saw beside an exhibitor name while the event was open never reappears
    once it is blind.
    """
    if event.is_blind:
        return f"blind:{event.blind_handle_salt or '-'}"
    return "open"


def plant_handle(
    secret: bytes, judge_id: str, event: JudgingEvent, plant_id: str
) -> str:
    """Opaque plant name for one judge in one event and naming period.

    Judge-scoped: two judges' handles for the same plant differ, so lists
    cannot be pooled to link plants across judges. No shared semantics depend
    on a common handle; scores bind to scorecards server-side and results use
    raw ids on owner routes only.
    """
    mac = _mac(
        secret, "plant-handle", "v2", judge_id, event.id, handle_epoch(event), plant_id
    )
    return "p_" + mac[:24]


def scorecard_handle(
    secret: bytes, judge_id: str, event: JudgingEvent, scorecard_id: str
) -> str:
    mac = _mac(
        secret,
        "scorecard-handle",
        "v2",
        judge_id,
        event.id,
        handle_epoch(event),
        scorecard_id,
    )
    return "s_" + mac[:24]


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


def _auth_failure_keys(client: str, credential_id: str | None) -> list[tuple[str, int]]:
    per_credential, per_client, _window = auth_failure_limits()
    keys = [(f"judge-auth:client:{client}", per_client)]
    if credential_id:
        keys.append((f"judge-auth:credential:{credential_id}", per_credential))
    return keys


def authenticate_judge_token(
    db: Session, token: str, client: str = "unknown"
) -> JudgeContext:
    """Resolve a presented bearer token to a judge, or raise 401/429/503.

    Every failure counts against the client address and, when the token
    names one, the credential id. A spent allowance refuses further attempts
    before any lookup. A known credential presented with the wrong secret,
    revoked, expired or orphaned is audited under its judge; no presented
    secret material is ever recorded. An unknown id is not audited, so
    anonymous guessing cannot fill the table.
    """
    secret = require_judge_secret()
    window = auth_failure_limits()[2]
    credential_id = parse_credential_id(token)
    keys = _auth_failure_keys(client, credential_id)
    for key, limit in keys:
        limited, retry_after = AUTH_FAILURE_LIMITER.is_limited(
            key, limit=limit, window_seconds=window
        )
        if limited:
            raise HTTPException(
                status_code=429,
                detail="Too many failed judge sign-in attempts. Wait and try again.",
                headers={"Retry-After": str(retry_after)},
            )

    def refuse(detail: str, credential: JudgeCredential | None, outcome: str) -> None:
        for key, limit in keys:
            AUTH_FAILURE_LIMITER.check(key, limit=limit, window_seconds=window)
        if credential is not None:
            _write_audit(
                db,
                judge_id=credential.judge_id,
                credential_id=credential.id,
                action="authenticate",
                outcome=outcome,
                http_status=401,
                ref=AuditRef(),
            )
        raise HTTPException(status_code=401, detail=detail)

    credential = db.get(JudgeCredential, credential_id) if credential_id else None
    presented_hash = hash_judge_token(secret, token)
    matches = credentials_match(
        presented_hash, credential.token_hash if credential else _NO_MATCH_HASH
    )
    if credential is None:
        refuse("Invalid judge credential", None, "unknown_credential")
    if not matches:
        refuse("Invalid judge credential", credential, "credential_mismatch")

    judge = db.get(Judge, credential.judge_id)
    if credential.revoked_at is not None:
        refuse("Judge credential has been revoked", credential, "credential_revoked")
    if credential.expires_at <= utcnow():
        refuse("Judge credential has expired", credential, "credential_expired")
    if judge is None or judge.show_id != credential.show_id:
        refuse("Invalid judge credential", credential, "credential_invalid")

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


# Mail providers whose domain says nothing about who an exhibitor is.
_GENERIC_MAIL_LABELS = frozenset(
    [
        "gmail",
        "googlemail",
        "yahoo",
        "ymail",
        "hotmail",
        "outlook",
        "live",
        "msn",
        "icloud",
        "me",
        "mac",
        "aol",
        "proton",
        "protonmail",
        "pm",
        "mail",
        "email",
        "gmx",
        "zoho",
        "comcast",
        "verizon",
        "att",
        "btinternet",
    ]
)


def fold_text(text: str | None) -> str:
    """NFKD, strip combining marks, casefold, and turn separators into spaces."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(re.split(r"[\W_]+", stripped.casefold())).strip()


def exhibitor_mention_reasons(
    text: str | None, exhibitor: Exhibitor | None
) -> list[str]:
    """Why ``text`` may identify ``exhibitor``: a deliberately loose warning.

    Accent-insensitive; matches whole name words of any length, shared
    prefixes of 3+ letters (partial surnames, many nicknames), initials,
    email local part and non-generic domain labels, the id and phone digits.
    It is a warning for the owner, never a guarantee: blind events withhold
    free-text plant names whatever it says.
    """
    if not text or exhibitor is None:
        return []
    folded = fold_text(text)
    words = folded.split()
    reasons: list[str] = []
    if exhibitor.id and exhibitor.id.casefold() in text.casefold():
        reasons.append("contains the exhibitor id")
    name_words = fold_text(exhibitor.name).split()
    email_local, _, email_domain = (exhibitor.email or "").partition("@")
    local_words = fold_text(email_local).split()
    for candidate in name_words + local_words:
        if candidate in words:
            reasons.append("contains an exhibitor name word")
            break
        if len(candidate) >= 3 and any(
            len(w) >= 3 and (w[:3] == candidate[:3]) for w in words
        ):
            reasons.append("shares a prefix with an exhibitor name word")
            break
    if len(name_words) >= 2:
        initials = [w[0] for w in name_words]
        spaced = r"\b" + r"\s*".join(map(re.escape, initials)) + r"\b"
        if re.search(spaced, folded):
            reasons.append("contains the exhibitor's initials")
    if exhibitor.email and exhibitor.email.casefold() in text.casefold():
        reasons.append("contains the exhibitor email")
    labels = fold_text(email_domain).split()[:-1]
    if any(
        label in words
        for label in labels
        if len(label) >= 3 and label not in _GENERIC_MAIL_LABELS
    ):
        reasons.append("contains the exhibitor email domain")
    phone = re.sub(r"\D", "", exhibitor.phone or "")
    if len(phone) >= 4 and phone[-4:] in re.sub(r"\D", "", text):
        reasons.append("contains exhibitor phone digits")
    return list(dict.fromkeys(reasons))


def mentions_exhibitor(text: str | None, exhibitor: Exhibitor | None) -> bool:
    return bool(exhibitor_mention_reasons(text, exhibitor))


def _event_exhibitors(db: Session, event: JudgingEvent) -> list[Exhibitor]:
    ids = set(
        db.execute(
            select(Plant.exhibitor_id).where(Plant.judging_event_id == event.id)
        ).scalars()
    )
    return [e for e in (db.get(Exhibitor, i) for i in sorted(ids)) if e is not None]


def blind_safe_text(db: Session, event: JudgingEvent, text: str | None) -> str | None:
    """Schedule text (a class description) with any exhibitor mention withheld."""
    if not text or not event.is_blind:
        return text
    if any(mentions_exhibitor(text, e) for e in _event_exhibitors(db, event)):
        return None
    return text


def judge_plant_view(
    db: Session, ctx: JudgeContext, event: JudgingEvent, plant: Plant
) -> dict:
    """The only shape in which a plant reaches a judge.

    Never includes the plant id, exhibitor id, exhibitor contact, QR token or
    registration timestamps. In a blind event every free-text field entered
    per plant (its name and notes) is withheld: the judge sees the class, the
    opaque handle and, only if the owner set one, the owner-approved
    ``blind_display_name``. No heuristic decides what an exhibitor-derived name
    looks like. A non-blind event shows the entered name, the notes and the
    exhibitor's name, as the owner's tag sheet does.
    """
    category = db.get(PlantCategory, plant.category_id)
    view: dict = {
        "plant_handle": plant_handle(ctx.secret, ctx.judge_id, event, plant.id),
        "judging_event_id": event.id,
        "category_id": plant.category_id,
        "category_name": category.name if category else None,
        "blind": bool(event.is_blind),
    }
    if event.is_blind:
        approved = plant.blind_display_name or None
        view["plant_name"] = approved
        view["plant_name_withheld"] = approved is None
        view["plant_name_source"] = "owner_approved" if approved else "withheld"
    else:
        exhibitor = db.get(Exhibitor, plant.exhibitor_id)
        view["plant_name"] = plant.name
        view["plant_name_withheld"] = False
        view["plant_name_source"] = "entry"
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
        "scorecard_handle": scorecard_handle(
            ctx.secret, ctx.judge_id, event, scorecard.id
        ),
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

    def plant(self, ctx: JudgeContext, event: JudgingEvent, plant: Plant) -> None:
        self.judging_event_id = plant.judging_event_id
        self.category_id = plant.category_id
        self.plant_id = plant.id
        self.plant_handle = plant_handle(ctx.secret, ctx.judge_id, event, plant.id)


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


def write_judge_audit(
    db: Session,
    ctx: JudgeContext,
    *,
    action: str,
    outcome: str,
    http_status: int,
    ref: AuditRef,
    detail: str | None = None,
) -> None:
    _write_audit(
        db,
        judge_id=ctx.judge_id,
        credential_id=ctx.credential_id,
        action=action,
        outcome=outcome,
        http_status=http_status,
        ref=ref,
        detail=detail,
    )


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
