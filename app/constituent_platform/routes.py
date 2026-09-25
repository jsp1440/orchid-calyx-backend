"""Journey 12 / 13 — newsletter subscribe / unsubscribe / preferences / archive and contact intake.

Two routers share the ``/api/constituent`` prefix:

* ``router`` (public): what the public site's Newsletter and Contact pages call
  without credentials — subscribe, unsubscribe, the published archive, and
  contact intake. Every write is validated, bounded, and stored as untrusted
  plain text; nothing here sends email.
* ``owner_router`` (owner session / backend API key): the preference centre
  when no manage token is presented, publishing an issue to the archive, the
  contact inbox, and a subscription summary that carries counts, never
  addresses.

Preference reads and writes are the one place an address's state would be
disclosed, so they require either the owner boundary or the per-address manage
token issued at subscription (the token a future confirmation email carries).

Human-approval gate: the welcome communication is recorded in
``CommunicationState.AWAITING_APPROVAL`` and this module never transitions it.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Security
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.rate_limit import public_write_rate_limit
from app.routers.health import add_mission_control_cors_headers
from app.security import OWNER_SESSION_COOKIE, api_key_header, verify_owner_or_api_key

from .domain import (
    CommunicationState,
    MessagePurpose,
    PreferenceState,
    normalize_email,
)
from .service import (
    CONTACT_AGENT_EXPOSURE,
    CONTACT_REVIEW,
    ConstituentService,
    NotFound,
    get_store,
    issue_manage_token,
    verify_manage_token,
)

router = APIRouter(
    prefix="/api/constituent",
    tags=["constituent-platform"],
    dependencies=[Depends(add_mission_control_cors_headers)],
)

owner_router = APIRouter(
    prefix="/api/constituent",
    tags=["constituent-platform-owner"],
    dependencies=[Depends(verify_owner_or_api_key), Depends(add_mission_control_cors_headers)],
)

# Slugs as the public Newsletter page sends them (e.g. "field_research", "orchid-news").
TOPIC_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
Frequency = Literal["immediate", "daily", "weekly", "monthly", "quarterly"]
Format = Literal["html", "plain"]
ContactCategory = Literal["general", "bug", "suggestion"]

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _plain_text(value: str, limit: int) -> str:
    """Untrusted user text: control characters removed, whitespace kept, length bounded."""
    return _CONTROL_CHARS.sub("", value).strip()[:limit]


def _topics(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        slug = value.strip().lower()
        if not TOPIC_SLUG.match(slug):
            raise ValueError(f"topic slugs are lowercase letters, digits, hyphens and underscores; got {value!r}")
        cleaned.append(slug)
    return cleaned


def get_service() -> ConstituentService:
    return ConstituentService(get_store())


Service = Annotated[ConstituentService, Depends(get_service)]


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SubscribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., description="Constituent email address (will be normalized).")
    display_name: str | None = Field(None, max_length=200)
    topics: list[str] = Field(default_factory=list, max_length=20)
    frequency: Frequency = "weekly"
    format: Format = "html"

    @field_validator("topics")
    @classmethod
    def _valid_topics(cls, values: list[str]) -> list[str]:
        return _topics(values)

    @field_validator("display_name")
    @classmethod
    def _plain_name(cls, value: str | None) -> str | None:
        return _plain_text(value, 200) or None if value is not None else None


class UnsubscribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    token: str | None = Field(None, max_length=120, description="Optional manage token; not required to unsubscribe.")
    reason: str | None = Field(None, max_length=500)


class PreferencesPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topics: list[str] | None = Field(None, max_length=20)
    frequency: Frequency | None = None
    format: Format | None = None

    @field_validator("topics")
    @classmethod
    def _valid_topics(cls, values: list[str] | None) -> list[str] | None:
        return _topics(values) if values is not None else None


class PreferencesResponse(BaseModel):
    constituent_id: uuid.UUID
    normalized_email: str
    state: PreferenceState
    topics: list[str]
    frequency: str
    format: str
    updated_at: datetime


class SubscribeResponse(BaseModel):
    constituent_id: uuid.UUID
    normalized_email: str
    state: PreferenceState
    welcome_email_communication_state: CommunicationState
    manage_token: str | None = Field(
        None, description="Per-address preference-centre token; null when the server has no signing secret."
    )
    message: str


class UnsubscribeResponse(BaseModel):
    normalized_email: str
    state: PreferenceState
    message: str


class NewsletterIssueIn(BaseModel):
    """An issue the owner publishes to the web archive. Publishing here sends nothing."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    published_at: datetime
    topic_slugs: list[str] = Field(default_factory=list, max_length=20)
    html_body: str = Field(min_length=1, max_length=200_000)
    plain_text_body: str = Field(min_length=1, max_length=100_000)
    purpose: MessagePurpose = MessagePurpose.COMMUNITY

    @field_validator("topic_slugs")
    @classmethod
    def _valid_topics(cls, values: list[str]) -> list[str]:
        return _topics(values)


class NewsletterArchiveEntry(BaseModel):
    newsletter_id: uuid.UUID
    title: str
    published_at: datetime
    topic_slugs: list[str]
    web_url: str


class NewsletterArchivePage(BaseModel):
    items: list[NewsletterArchiveEntry]
    total: int
    offset: int
    limit: int


class NewsletterWebVersion(BaseModel):
    newsletter_id: uuid.UUID
    title: str
    published_at: datetime
    topic_slugs: list[str]
    html_body: str
    plain_text_body: str
    purpose: MessagePurpose


class ContactRequest(BaseModel):
    """The public contact form. Body is untrusted plain text and is never handed to an agent."""

    model_config = ConfigDict(extra="forbid")

    category: ContactCategory = "general"
    name: str | None = Field(None, max_length=200)
    email: str
    subject: str | None = Field(None, max_length=300)
    body: str = Field(min_length=10, max_length=4000)
    source: str | None = Field(None, max_length=120)

    @field_validator("body")
    @classmethod
    def _plain_body(cls, value: str) -> str:
        cleaned = _plain_text(value, 4000)
        if len(cleaned) < 10:
            raise ValueError("body must be at least 10 characters of plain text")
        return cleaned

    @field_validator("name", "subject", "source")
    @classmethod
    def _plain_fields(cls, value: str | None) -> str | None:
        return _plain_text(value, 300) or None if value is not None else None


class ContactReceipt(BaseModel):
    reference_id: str
    category: ContactCategory
    state: str
    review: str
    agent_exposure: str
    message: str


class ContactMessageOut(BaseModel):
    reference_id: str
    category: str
    name: str | None
    normalized_email: str
    subject: str | None
    body: str
    source: str | None
    received_at: datetime
    state: str
    review: str
    agent_exposure: str
    content_trust: str


class ContactInboxPage(BaseModel):
    items: list[ContactMessageOut]
    total: int
    offset: int
    limit: int


class SubscriptionSummary(BaseModel):
    total: int
    by_state: dict[str, int]
    welcome_communications_awaiting_approval: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalized(email: str) -> str:
    try:
        return normalize_email(email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _preferences(record: dict[str, Any]) -> PreferencesResponse:
    return PreferencesResponse(
        constituent_id=record["constituent_id"],
        normalized_email=record["normalized_email"],
        state=record["state"],
        topics=record["topics"],
        frequency=record["frequency"],
        format=record["format"],
        updated_at=record["updated_at"],
    )


async def owner_if_credentialed(
    request: Request, api_key: str = Security(api_key_header)
) -> dict[str, Any] | None:
    """The owner/API-key principal when credentials are presented; ``None`` when none are.

    Presented credentials are always verified (invalid ones fail with 401), so a
    caller cannot downgrade a bad owner credential into an anonymous request.
    """
    if not (api_key or request.headers.get("authorization") or request.cookies.get(OWNER_SESSION_COOKIE)):
        return None
    return await verify_owner_or_api_key(request, api_key)


def preference_access(
    email: Annotated[str, Query(description="Constituent email.")],
    owner: Annotated[dict[str, Any] | None, Depends(owner_if_credentialed)],
    token: Annotated[str | None, Query(max_length=120, description="Per-address manage token.")] = None,
) -> str:
    """The normalised email the caller may read or change: via manage token or the owner boundary."""
    normalized = _normalized(email)
    if token and verify_manage_token(normalized, token):
        return normalized
    if owner is None:
        raise HTTPException(status_code=401, detail="Owner session or API key is required")
    return normalized


def _issue_entry(record: dict[str, Any]) -> NewsletterArchiveEntry:
    return NewsletterArchiveEntry(
        newsletter_id=record["newsletter_id"],
        title=record["title"],
        published_at=record["published_at"],
        topic_slugs=record.get("topic_slugs", []),
        web_url=f"/api/constituent/newsletter/archive/{record['newsletter_id']}/web",
    )


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------


@router.post("/subscribe", response_model=SubscribeResponse, dependencies=[Depends(public_write_rate_limit("constituent"))])
def subscribe(payload: SubscribeRequest, service: Service) -> SubscribeResponse:
    """Subscribe (or re-subscribe) an address. The welcome message waits at the human-approval gate."""
    normalized = _normalized(payload.email)
    result = service.subscribe(
        normalized,
        display_name=payload.display_name,
        topics=payload.topics,
        frequency=payload.frequency,
        format=payload.format,
    )
    record = result["subscription"]
    return SubscribeResponse(
        constituent_id=record["constituent_id"],
        normalized_email=record["normalized_email"],
        state=record["state"],
        welcome_email_communication_state=result["communication"]["state"],
        manage_token=issue_manage_token(normalized),
        message=(
            "Subscribed. The welcome email is held for human approval before any dispatch "
            "(CommunicationState.AWAITING_APPROVAL)."
        ),
    )


@router.post("/unsubscribe", response_model=UnsubscribeResponse, dependencies=[Depends(public_write_rate_limit("constituent"))])
def unsubscribe(payload: UnsubscribeRequest, service: Service) -> UnsubscribeResponse:
    """Unsubscribe an address. Idempotent, and answers identically for known and unknown addresses."""
    normalized = _normalized(payload.email)
    record = service.unsubscribe(normalized, reason=payload.reason)
    return UnsubscribeResponse(
        normalized_email=record["normalized_email"],
        state=record["state"],
        message="Unsubscribed. No further community, fundraising or marketing email will be sent to this address.",
    )


@router.get("/newsletter/archive", response_model=NewsletterArchivePage)
def list_newsletter_archive(
    service: Service,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> NewsletterArchivePage:
    """Published (COMPLETED) issues only, newest first."""
    rows = service.list_issues()
    return NewsletterArchivePage(
        items=[_issue_entry(row) for row in rows[offset : offset + limit]],
        total=len(rows),
        offset=offset,
        limit=limit,
    )


@router.get("/newsletter/archive/{newsletter_id}/web", response_model=NewsletterWebVersion)
def get_newsletter_web_version(
    newsletter_id: Annotated[uuid.UUID, Path(description="Newsletter edition UUID.")],
    service: Service,
) -> NewsletterWebVersion:
    try:
        record = service.get_issue(str(newsletter_id))
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="Newsletter edition not found.") from exc
    return NewsletterWebVersion(
        newsletter_id=record["newsletter_id"],
        title=record["title"],
        published_at=record["published_at"],
        topic_slugs=record.get("topic_slugs", []),
        html_body=record["html_body"],
        plain_text_body=record["plain_text_body"],
        purpose=record.get("purpose", MessagePurpose.COMMUNITY.value),
    )


@router.post("/contact", response_model=ContactReceipt, dependencies=[Depends(public_write_rate_limit("constituent"))])
def receive_contact(payload: ContactRequest, service: Service) -> ContactReceipt:
    """Public contact intake. Stored for human review; never forwarded to an automated agent."""
    normalized = _normalized(payload.email)
    record = service.receive_contact(
        {
            "category": payload.category,
            "name": payload.name,
            "normalized_email": normalized,
            "subject": payload.subject,
            "body": payload.body,
            "source": payload.source,
        }
    )
    return ContactReceipt(
        reference_id=record["reference_id"],
        category=record["category"],
        state=record["state"],
        review=CONTACT_REVIEW,
        agent_exposure=CONTACT_AGENT_EXPOSURE,
        message="Received. A person will read this; it is not passed to automated agents.",
    )


# ---------------------------------------------------------------------------
# Preference centre: manage token or owner boundary
# ---------------------------------------------------------------------------


@router.get("/preferences", response_model=PreferencesResponse)
def get_preferences(
    normalized: Annotated[str, Depends(preference_access)],
    service: Service,
) -> PreferencesResponse:
    record = service.get_subscription(normalized)
    if record is None:
        raise HTTPException(status_code=404, detail="No subscription record for this address.")
    return _preferences(record)


@router.patch("/preferences", response_model=PreferencesResponse)
def patch_preferences(
    normalized: Annotated[str, Depends(preference_access)],
    payload: PreferencesPatchRequest,
    service: Service,
) -> PreferencesResponse:
    """Update topics, cadence or format. State changes go through /subscribe or /unsubscribe."""
    try:
        record = service.update_preferences(
            normalized, topics=payload.topics, frequency=payload.frequency, format=payload.format
        )
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="No subscription record for this address.") from exc
    return _preferences(record)


# ---------------------------------------------------------------------------
# Owner routes
# ---------------------------------------------------------------------------


@owner_router.post("/newsletter/archive", response_model=NewsletterArchiveEntry, status_code=201)
def publish_newsletter_issue(payload: NewsletterIssueIn, service: Service) -> NewsletterArchiveEntry:
    """Record a published issue in the web archive. This is the archive, not a send."""
    newsletter_id = str(uuid.uuid4())
    record = service.publish_issue(
        {
            "newsletter_id": newsletter_id,
            "title": _plain_text(payload.title, 300),
            "published_at": payload.published_at.astimezone(timezone.utc).isoformat()
            if payload.published_at.tzinfo
            else payload.published_at.replace(tzinfo=timezone.utc).isoformat(),
            "topic_slugs": payload.topic_slugs,
            "html_body": payload.html_body,
            "plain_text_body": payload.plain_text_body,
            "purpose": payload.purpose.value,
        }
    )
    return _issue_entry(record)


@owner_router.get("/contact/messages", response_model=ContactInboxPage)
def list_contact_messages(
    service: Service,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ContactInboxPage:
    rows, total = service.list_contact_messages(limit=limit, offset=offset)
    return ContactInboxPage(items=[ContactMessageOut(**row) for row in rows], total=total, offset=offset, limit=limit)


@owner_router.get("/subscriptions/summary", response_model=SubscriptionSummary)
def subscription_summary(service: Service) -> SubscriptionSummary:
    """Counts only; no addresses leave through this route."""
    return SubscriptionSummary(**service.subscription_summary())
