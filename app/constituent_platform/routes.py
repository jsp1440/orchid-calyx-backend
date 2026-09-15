"""Journey 12 — Newsletter Subscribe/Preferences/Unsubscribe + Archive/Web-Version MVP.

Route layer only (R1 MVP). Stub repository calls return in-memory fixtures;
full DB integration is a REUSE_EXTEND follow-up after
feature/oc-constituent-communications-foundation merges.

Human-approval gate: any outbound delivery (e.g. welcome email after subscribe)
MUST transit CommunicationState.AWAITING_APPROVAL → APPROVED before the
email_gateway is invoked.  These stubs record that boundary with a comment and
return the communication state so callers can observe it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key

from .domain import (
    CommunicationState,
    MessagePurpose,
    PreferenceState,
    normalize_email,
)

router = APIRouter(
    prefix="/api/constituent",
    tags=["constituent-platform"],
    dependencies=[
        Depends(verify_owner_or_api_key),
        Depends(add_mission_control_cors_headers),
    ],
)

# ---------------------------------------------------------------------------
# Request / response Pydantic models
# ---------------------------------------------------------------------------


class SubscribeRequest(BaseModel):
    """Inbound subscription request from a constituent."""

    email: str = Field(..., description="Constituent email address (will be normalized).")
    display_name: str | None = Field(None, max_length=200)
    topics: list[str] = Field(
        default_factory=list,
        description="Topic slugs the constituent wants to receive (e.g. ['orchid-news', 'shows']).",
    )
    frequency: str = Field(
        "weekly",
        pattern=r"^(immediate|daily|weekly|monthly)$",
        description="Delivery cadence preference.",
    )
    format: str = Field(
        "html",
        pattern=r"^(html|plain)$",
        description="Preferred email format.",
    )


class UnsubscribeRequest(BaseModel):
    """Request to unsubscribe a constituent by email or token."""

    email: str = Field(..., description="Constituent email address.")
    token: str | None = Field(
        None,
        description="Signed one-click unsubscribe token (RFC 8058). "
        "When omitted, owner-level API key authentication is required.",
    )
    reason: str | None = Field(None, max_length=500)


class PreferencesResponse(BaseModel):
    """Current communication preferences for a constituent."""

    constituent_id: UUID
    normalized_email: str
    state: PreferenceState
    topics: list[str]
    frequency: str
    format: str
    updated_at: datetime


class PreferencesPatchRequest(BaseModel):
    """Partial update to communication preferences."""

    topics: list[str] | None = None
    frequency: str | None = Field(
        None, pattern=r"^(immediate|daily|weekly|monthly)$"
    )
    format: str | None = Field(None, pattern=r"^(html|plain)$")


class SubscribeResponse(BaseModel):
    """Result of a subscribe action."""

    constituent_id: UUID
    normalized_email: str
    state: PreferenceState
    # Human-approval gate: welcome email is NOT yet sent; it waits in this state.
    welcome_email_communication_state: CommunicationState
    message: str


class UnsubscribeResponse(BaseModel):
    """Result of an unsubscribe action."""

    normalized_email: str
    state: PreferenceState
    message: str


class NewsletterArchiveEntry(BaseModel):
    """A single newsletter edition in the archive listing."""

    newsletter_id: UUID
    title: str
    published_at: datetime
    topic_slugs: list[str]
    web_url: str


class NewsletterArchivePage(BaseModel):
    """Paginated newsletter archive response."""

    items: list[NewsletterArchiveEntry]
    total: int
    offset: int
    limit: int


class NewsletterWebVersion(BaseModel):
    """Web-renderable representation of a single newsletter edition."""

    newsletter_id: UUID
    title: str
    published_at: datetime
    topic_slugs: list[str]
    html_body: str
    plain_text_body: str
    # Purpose recorded so callers know delivery rules that applied at send time.
    purpose: MessagePurpose


# ---------------------------------------------------------------------------
# Stub repository helpers  (replaced with real DB calls post-foundation merge)
# ---------------------------------------------------------------------------

_STUB_CONSTITUENT_ID = UUID("00000000-0000-0000-0000-000000000001")
_STUB_NEWSLETTER_ID = UUID("00000000-0000-0000-0000-000000000002")
_STUB_PUBLISHED_AT = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)


def _stub_preferences(normalized: str) -> PreferencesResponse:
    return PreferencesResponse(
        constituent_id=_STUB_CONSTITUENT_ID,
        normalized_email=normalized,
        state=PreferenceState.SUBSCRIBED,
        topics=["orchid-news", "shows"],
        frequency="weekly",
        format="html",
        updated_at=_STUB_PUBLISHED_AT,
    )


def _stub_archive_entries() -> list[NewsletterArchiveEntry]:
    return [
        NewsletterArchiveEntry(
            newsletter_id=_STUB_NEWSLETTER_ID,
            title="Orchid Continuum Newsletter — September 2026",
            published_at=_STUB_PUBLISHED_AT,
            topic_slugs=["orchid-news", "shows"],
            web_url=f"/api/constituent/newsletter/archive/{_STUB_NEWSLETTER_ID}/web",
        )
    ]


def _stub_web_version(newsletter_id: UUID) -> NewsletterWebVersion:
    return NewsletterWebVersion(
        newsletter_id=newsletter_id,
        title="Orchid Continuum Newsletter — September 2026",
        published_at=_STUB_PUBLISHED_AT,
        topic_slugs=["orchid-news", "shows"],
        html_body="<p>Stub HTML body — full content from DB post-foundation merge.</p>",
        plain_text_body="Stub plain-text body — full content from DB post-foundation merge.",
        purpose=MessagePurpose.COMMUNITY,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/subscribe", response_model=SubscribeResponse)
def subscribe(payload: SubscribeRequest) -> SubscribeResponse:
    """Subscribe a constituent to newsletter communications.

    On success the constituent's preference is set to SUBSCRIBED.  A welcome
    email is queued but NOT dispatched: it enters CommunicationState.AWAITING_APPROVAL
    as required by the human-approval gate (approval_required() is True for
    MessagePurpose.COMMUNITY audience > 1).  The owner must approve before the
    email_gateway sends.
    """
    try:
        normalized = normalize_email(payload.email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # STUB: upsert constituent + preference record here (DB integration pending)
    # welcome_comm = create_draft_communication(purpose=MessagePurpose.COMMUNITY, ...)
    # validate_state_transition(DRAFT → AWAITING_APPROVAL, audience_frozen=True)

    # Human-approval gate: welcome email waits here until an owner approves.
    welcome_state = CommunicationState.AWAITING_APPROVAL

    return SubscribeResponse(
        constituent_id=_STUB_CONSTITUENT_ID,
        normalized_email=normalized,
        state=PreferenceState.SUBSCRIBED,
        welcome_email_communication_state=welcome_state,
        message=(
            "Subscribed successfully. Welcome email is awaiting human approval "
            "before dispatch (CommunicationState.AWAITING_APPROVAL)."
        ),
    )


@router.post("/unsubscribe", response_model=UnsubscribeResponse)
def unsubscribe(payload: UnsubscribeRequest) -> UnsubscribeResponse:
    """Unsubscribe a constituent and record a suppression entry.

    Sets PreferenceState.UNSUBSCRIBED and adds SuppressionKind.UNSUBSCRIBE.
    No outbound email is sent on unsubscribe (no approval gate needed here).
    """
    try:
        normalized = normalize_email(payload.email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # STUB: upsert suppression record + set preference to UNSUBSCRIBED (DB pending)

    return UnsubscribeResponse(
        normalized_email=normalized,
        state=PreferenceState.UNSUBSCRIBED,
        message="Unsubscribed successfully. No further marketing communications will be sent.",
    )


@router.get("/preferences", response_model=PreferencesResponse)
def get_preferences(
    email: Annotated[str, Query(description="Constituent email to look up.")],
) -> PreferencesResponse:
    """Return current communication preferences for a constituent.

    In the full implementation this reads the authenticated session's
    constituent record.  For R1 MVP the email query param is the lookup key.
    """
    try:
        normalized = normalize_email(email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # STUB: fetch from constituent_preferences table (DB pending)
    return _stub_preferences(normalized)


@router.patch("/preferences", response_model=PreferencesResponse)
def patch_preferences(
    email: Annotated[str, Query(description="Constituent email to update.")],
    payload: PreferencesPatchRequest,
) -> PreferencesResponse:
    """Update topic filters, delivery frequency, or format for a constituent.

    Does not change PreferenceState (use /subscribe or /unsubscribe for that).
    """
    try:
        normalized = normalize_email(email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    base = _stub_preferences(normalized)

    # STUB: apply partial update to DB record (DB pending)
    updated = PreferencesResponse(
        constituent_id=base.constituent_id,
        normalized_email=base.normalized_email,
        state=base.state,
        topics=payload.topics if payload.topics is not None else base.topics,
        frequency=payload.frequency if payload.frequency is not None else base.frequency,
        format=payload.format if payload.format is not None else base.format,
        updated_at=datetime.now(tz=timezone.utc),
    )
    return updated


@router.get("/newsletter/archive", response_model=NewsletterArchivePage)
def list_newsletter_archive(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> NewsletterArchivePage:
    """List newsletter archive editions, newest first, paginated.

    Only COMPLETED newsletters (CommunicationState.COMPLETED) appear in the
    public archive.  DRAFT / AWAITING_APPROVAL editions are excluded.
    """
    # STUB: query newsletter_editions WHERE state = COMPLETED ORDER BY published_at DESC
    all_entries = _stub_archive_entries()
    page = all_entries[offset : offset + limit]
    return NewsletterArchivePage(
        items=page,
        total=len(all_entries),
        offset=offset,
        limit=limit,
    )


@router.get(
    "/newsletter/archive/{newsletter_id}/web",
    response_model=NewsletterWebVersion,
)
def get_newsletter_web_version(
    newsletter_id: Annotated[UUID, Path(description="Newsletter edition UUID.")],
) -> NewsletterWebVersion:
    """Return the web-renderable HTML + plain-text body for a newsletter edition.

    Only published (CommunicationState.COMPLETED) editions are served.
    """
    # STUB: fetch from newsletter_editions by id WHERE state = COMPLETED
    stub_id = _STUB_NEWSLETTER_ID
    if newsletter_id != stub_id:
        raise HTTPException(status_code=404, detail="Newsletter edition not found.")
    return _stub_web_version(newsletter_id)
