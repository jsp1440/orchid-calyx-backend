"""Journey 12 / 13 over the canonical ``oc_constituent`` / ``oc_communications`` schemas (#1652).

``CanonicalConstituentService`` has exactly the public methods and return shapes
of :class:`app.constituent_platform.service.ConstituentService`, so the routes
behave identically whichever store is selected.

Exactly one store is authoritative at a time
--------------------------------------------
``OC_CONSTITUENT_PERSISTENCE`` selects it:

* ``research_station`` (default): the legacy ``ConstituentService`` over the
  generic Research Station record store (behaviour unchanged);
* ``canonical``: this module.

There is no fallback. When ``canonical`` is selected and ``DATABASE_URL`` is
missing, the schema is not migrated, or the platform organization cannot be
resolved, the API fails closed with HTTP 503 and names the migration to apply.
Silently writing to the other store would split the source of truth.

Cutover: apply ``migrations/20260927b_constituent_newsletter_canonical.sql``, run
``scripts/oc_constituent_migrate_research_station.py`` (dry run, then
``--apply``), re-run it and verify every record is ``unchanged`` with zero
``conflict`` / ``invalid``, then set ``OC_CONSTITUENT_PERSISTENCE=canonical``.

Where the records live (all owned by the Orchid Continuum platform organization,
slug ``orchid-continuum``, kind ``orchid_continuum``):

* subscriber: a tenant-owned ``oc_constituent.constituents`` row, its primary
  ``oc_constituent.email_addresses`` row, and one
  ``oc_communications.newsletter_subscription_settings`` row (topics, cadence,
  format, display name, and the stable public id);
* subscription state: the latest append-only ``communication_preferences`` row
  (channel ``email``, purpose ``community``, topic ``*``); every change appends a
  row that ``supersedes_id`` the previous one;
* unsubscribe: also an active ``suppressions`` row of kind ``unsubscribe``,
  lifted (``lifted_at``) on re-subscribe. Critical suppressions (hard bounce,
  complaint, invalid, admin block) are never lifted here;
* welcome email: an ``oc_communications.intents`` row (initiating module
  ``constituent_platform.welcome``, one per constituent) with a frozen
  single-member audience snapshot hashed by ``domain.audience_snapshot_sha256``,
  held in ``awaiting_approval``. Nothing is sent by this module;
* archive: ``oc_communications.newsletter_issues``;
* contact inbox: ``oc_communications.inbound_contact_messages`` (untrusted plain
  text, idempotent on ``reference_id``, never an authorization source).

Public constituent id: responses keep the deterministic uuid5 from
``service.constituent_id_for(normalized_email)``. It is stored in
``newsletter_subscription_settings.public_constituent_id`` (unique per
organization) and is also the lookup key, so existing clients and manage links
are unaffected. The internal BIGINT constituent id never leaves this module.

Every tenant-owned read/write runs in ``tenant_transaction`` (runtime role +
transaction-local tenant); only the organization slug lookup/creation and the
schema readiness probe use ``platform_transaction``.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from .domain import (
    AudienceMember,
    CommunicationState,
    MessagePurpose,
    PreferenceState,
    SuppressionKind,
    approval_required,
    audience_snapshot_sha256,
    normalize_email,
    recipient_delivery_decision,
    validate_state_transition,
)
from .service import (
    CONTACT_AGENT_EXPOSURE,
    CONTACT_REVIEW,
    NotFound,
    constituent_id_for,
    contact_reference_id,
)
from .tenant_db import ConnectionFactory, dsn_connection_factory, platform_transaction, tenant_transaction

PERSISTENCE_ENV = "OC_CONSTITUENT_PERSISTENCE"
PERSISTENCE_RESEARCH_STATION = "research_station"
PERSISTENCE_CANONICAL = "canonical"

PLATFORM_ORG_SLUG = "orchid-continuum"
PLATFORM_ORG_KIND = "orchid_continuum"
PLATFORM_ORG_DISPLAY_NAME = "Orchid Continuum"

REQUIRED_MIGRATIONS = (
    "migrations/20260823_oc_constituent_communications_foundation.sql",
    "migrations/20260926_society_crm_p0_core.sql",
    "migrations/20260927_society_crm_p1_tenant_isolation.sql",
    "migrations/20260927b_constituent_newsletter_canonical.sql",
)

CHANNEL = "email"
PURPOSE = MessagePurpose.COMMUNITY.value
TOPIC_ALL = "*"
WELCOME_MODULE = "constituent_platform.welcome"
WELCOME_PRINCIPAL = "system:constituent_platform"
WELCOME_SUBJECT = "Welcome to the Orchid Continuum newsletter"
WELCOME_TEMPLATE = "constituent_platform.welcome.v1"
WELCOME_AUTH_CLASS = "owner_approval"
DEFAULT_DISPLAY_NAME = "Newsletter subscriber"
SOURCE_PUBLIC_FORM = "public_newsletter_form"
HISTORY_LIMIT = 20

_DRIVER_PREFIX = re.compile(r"^postgres(ql)?\+\w+://")


class CanonicalStoreUnavailable(RuntimeError):
    """The canonical store was selected but cannot serve; the API answers 503."""


def _migration_hint() -> str:
    return "apply, in order: " + ", ".join(REQUIRED_MIGRATIONS)


def persistence_selection(env: dict[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    value = str(source.get(PERSISTENCE_ENV, "") or "").strip().lower()
    if not value:
        return PERSISTENCE_RESEARCH_STATION
    if value in {PERSISTENCE_RESEARCH_STATION, PERSISTENCE_CANONICAL}:
        return value
    raise CanonicalStoreUnavailable(
        f"{PERSISTENCE_ENV}={value!r} is not recognised; use "
        f"{PERSISTENCE_RESEARCH_STATION!r} or {PERSISTENCE_CANONICAL!r}"
    )


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def email_sha256(normalized_email: str) -> str:
    return hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()


def _lock_key(organization_id: int, key: str) -> int:
    digest = hashlib.sha256(f"oc_constituent:{organization_id}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def issue_content_sha256(html_body: str, plain_text_body: str) -> str:
    return hashlib.sha256(f"{html_body}\n\x1e\n{plain_text_body}".encode()).hexdigest()


def contact_content_sha256(message: dict[str, Any]) -> str:
    fields = [str(message.get(key) or "") for key in ("category", "name", "normalized_email", "subject", "body", "source")]
    return hashlib.sha256("\n\x1e\n".join(fields).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Cursor-level helpers (shared with the Research Station migration tool). Every
# helper filters by organization_id explicitly, beneath RLS.
# ---------------------------------------------------------------------------


def lock_subscriber(cur: psycopg.Cursor, organization_id: int, public_id: str) -> None:
    """Serialize concurrent writes for one address so a subscriber is created once."""
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (_lock_key(organization_id, public_id),))


def find_subscriber(cur: psycopg.Cursor, organization_id: int, public_id: str) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT s.constituent_id, s.public_constituent_id, s.display_name, s.topics, s.frequency,
               s.format, s.subscribed_at, s.unsubscribed_at, s.created_at, s.updated_at,
               e.normalized_email
        FROM oc_communications.newsletter_subscription_settings s
        JOIN oc_constituent.email_addresses e
          ON e.organization_id = s.organization_id
         AND e.constituent_id = s.constituent_id
         AND e.is_primary
        WHERE s.organization_id = %s AND s.public_constituent_id = %s
        """,
        (organization_id, public_id),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def latest_preference(cur: psycopg.Cursor, organization_id: int, constituent_id: int) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT id, state, created_at FROM oc_constituent.communication_preferences
        WHERE organization_id = %s AND constituent_id = %s
          AND channel = %s AND purpose = %s AND topic = %s
        ORDER BY id DESC LIMIT 1
        """,
        (organization_id, constituent_id, CHANNEL, PURPOSE, TOPIC_ALL),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def preference_history(cur: psycopg.Cursor, organization_id: int, constituent_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT state, created_at FROM (
            SELECT id, state, created_at FROM oc_constituent.communication_preferences
            WHERE organization_id = %s AND constituent_id = %s
              AND channel = %s AND purpose = %s AND topic = %s
            ORDER BY id DESC LIMIT %s
        ) recent ORDER BY id ASC
        """,
        (organization_id, constituent_id, CHANNEL, PURPOSE, TOPIC_ALL, HISTORY_LIMIT),
    )
    return [{"event": row["state"], "at": _iso(row["created_at"])} for row in cur.fetchall()]


def active_suppressions(
    cur: psycopg.Cursor, organization_id: int, constituent_id: int, normalized_email: str
) -> list[str]:
    cur.execute(
        """
        SELECT kind FROM oc_constituent.suppressions
        WHERE organization_id = %s AND lifted_at IS NULL
          AND (constituent_id = %s OR normalized_email = %s)
        ORDER BY created_at ASC, id ASC
        """,
        (organization_id, constituent_id, normalized_email),
    )
    kinds: list[str] = []
    for row in cur.fetchall():
        if row["kind"] not in kinds:
            kinds.append(row["kind"])
    return kinds


def create_subscriber(
    cur: psycopg.Cursor,
    organization_id: int,
    *,
    normalized_email: str,
    public_id: str,
    display_name: str | None,
    topics: list[str],
    frequency: str,
    format: str,
    subscribed_at: Any = None,
    unsubscribed_at: Any = None,
    created_at: Any = None,
) -> int:
    cur.execute(
        """
        INSERT INTO oc_constituent.constituents (kind, display_name, owner_organization_id)
        VALUES ('person', %s, %s) RETURNING id
        """,
        (display_name or DEFAULT_DISPLAY_NAME, organization_id),
    )
    constituent_id = int(cur.fetchone()["id"])
    cur.execute(
        """
        INSERT INTO oc_constituent.email_addresses (constituent_id, organization_id, normalized_email, is_primary)
        VALUES (%s, %s, %s, TRUE)
        """,
        (constituent_id, organization_id, normalized_email),
    )
    cur.execute(
        """
        INSERT INTO oc_communications.newsletter_subscription_settings
            (organization_id, constituent_id, public_constituent_id, display_name, topics, frequency,
             format, subscribed_at, unsubscribed_at, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s::text[], %s, %s, %s, %s, COALESCE(%s::timestamptz, NOW()), NOW())
        """,
        (
            organization_id,
            constituent_id,
            public_id,
            display_name,
            sorted(set(topics)),
            frequency,
            format,
            subscribed_at,
            unsubscribed_at,
            created_at,
        ),
    )
    return constituent_id


def record_preference(
    cur: psycopg.Cursor,
    organization_id: int,
    constituent_id: int,
    *,
    state: str,
    supersedes_id: int | None,
    source_kind: str,
    evidence_ref: str | None = None,
    created_at: Any = None,
) -> int:
    cur.execute(
        """
        INSERT INTO oc_constituent.communication_preferences
            (organization_id, constituent_id, channel, purpose, topic, state, source_kind,
             evidence_ref, supersedes_id, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s::timestamptz, NOW()))
        RETURNING id
        """,
        (
            organization_id,
            constituent_id,
            CHANNEL,
            PURPOSE,
            TOPIC_ALL,
            state,
            source_kind,
            evidence_ref,
            supersedes_id,
            created_at,
        ),
    )
    return int(cur.fetchone()["id"])


def add_suppression(
    cur: psycopg.Cursor,
    organization_id: int,
    constituent_id: int,
    *,
    normalized_email: str,
    kind: str,
    reason: str | None,
    source_kind: str,
) -> None:
    cur.execute(
        """
        INSERT INTO oc_constituent.suppressions
            (organization_id, constituent_id, normalized_email, kind, reason, source_kind)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (organization_id, constituent_id, normalized_email, kind, reason, source_kind),
    )


def lift_own_unsubscribe(cur: psycopg.Cursor, organization_id: int, constituent_id: int, normalized_email: str) -> None:
    """Lift only the constituent's own unsubscribe; critical suppressions are untouched."""
    cur.execute(
        """
        UPDATE oc_constituent.suppressions SET lifted_at = NOW()
        WHERE organization_id = %s AND lifted_at IS NULL AND kind = %s
          AND (constituent_id = %s OR normalized_email = %s)
        """,
        (organization_id, SuppressionKind.UNSUBSCRIBE.value, constituent_id, normalized_email),
    )


def find_welcome_intent(cur: psycopg.Cursor, organization_id: int, constituent_id: int) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT i.id, i.state, i.created_at, s.audience_sha256, s.frozen_at
        FROM oc_communications.intents i
        LEFT JOIN oc_communications.audience_snapshots s
          ON s.intent_id = i.id AND s.organization_id = i.organization_id
        WHERE i.organization_id = %s AND i.initiating_module = %s
          AND i.audience_definition ->> 'constituent_id' = %s
        """,
        (organization_id, WELCOME_MODULE, str(constituent_id)),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def create_welcome_intent(
    cur: psycopg.Cursor,
    organization_id: int,
    *,
    constituent_id: int,
    public_id: str,
    normalized_email: str,
    requested_at: Any = None,
) -> dict[str, Any]:
    """Draft -> single-member snapshot -> freeze with hash -> awaiting_approval."""
    from psycopg.types.json import Jsonb

    cur.execute(
        """
        INSERT INTO oc_communications.intents
            (organization_id, purpose, initiating_module, initiating_principal, subject, template_ref,
             audience_definition, required_auth_class, state, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s::timestamptz, NOW()), NOW())
        RETURNING id
        """,
        (
            organization_id,
            PURPOSE,
            WELCOME_MODULE,
            WELCOME_PRINCIPAL,
            WELCOME_SUBJECT,
            WELCOME_TEMPLATE,
            Jsonb({"kind": "welcome", "constituent_id": str(constituent_id), "public_constituent_id": public_id}),
            WELCOME_AUTH_CLASS,
            CommunicationState.DRAFT.value,
            requested_at,
        ),
    )
    intent_id = int(cur.fetchone()["id"])
    cur.execute(
        "INSERT INTO oc_communications.audience_snapshots (organization_id, intent_id) VALUES (%s, %s) RETURNING id",
        (organization_id, intent_id),
    )
    snapshot_id = int(cur.fetchone()["id"])

    latest = latest_preference(cur, organization_id, constituent_id)
    preference = PreferenceState(latest["state"]) if latest else None
    suppressions = {SuppressionKind(kind) for kind in active_suppressions(cur, organization_id, constituent_id, normalized_email)}
    allowed, reason = recipient_delivery_decision(
        purpose=MessagePurpose.COMMUNITY, preference=preference, suppressions=suppressions
    )
    member = AudienceMember(
        constituent_id=constituent_id, normalized_email=normalized_email, allowed=allowed, decision_reason=reason
    )
    cur.execute(
        """
        INSERT INTO oc_communications.audience_members
            (organization_id, snapshot_id, constituent_id, normalized_email, allowed, decision_reason)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (organization_id, snapshot_id, constituent_id, normalized_email, allowed, reason),
    )
    digest = audience_snapshot_sha256([member])
    cur.execute(
        """
        UPDATE oc_communications.audience_snapshots SET audience_sha256 = %s, frozen_at = NOW()
        WHERE organization_id = %s AND id = %s
        """,
        (digest, organization_id, snapshot_id),
    )
    validate_state_transition(CommunicationState.DRAFT, CommunicationState.AWAITING_APPROVAL, audience_frozen=True)
    cur.execute(
        """
        UPDATE oc_communications.intents SET state = %s, updated_at = NOW()
        WHERE organization_id = %s AND id = %s AND state = %s
        """,
        (CommunicationState.AWAITING_APPROVAL.value, organization_id, intent_id, CommunicationState.DRAFT.value),
    )
    found = find_welcome_intent(cur, organization_id, constituent_id)
    assert found is not None
    return found


def communication_record(intent: dict[str, Any], public_id: str) -> dict[str, Any]:
    """The same shape ``ConstituentService.subscribe`` returns for the welcome message."""
    return {
        "communication_id": f"welcome-{public_id}",
        "purpose": PURPOSE,
        "state": intent["state"],
        "approval_required": approval_required(MessagePurpose.COMMUNITY, 1),
        "audience_size": 1,
        "constituent_id": public_id,
        "requested_at": _iso(intent["created_at"]),
        "dispatch": "blocked_pending_human_approval",
    }


def subscription_record(cur: psycopg.Cursor, organization_id: int, subscriber: dict[str, Any]) -> dict[str, Any]:
    """The same shape ``ConstituentService.get_subscription`` returns."""
    constituent_id = int(subscriber["constituent_id"])
    latest = latest_preference(cur, organization_id, constituent_id)
    return {
        "constituent_id": str(subscriber["public_constituent_id"]),
        "normalized_email": subscriber["normalized_email"],
        "display_name": subscriber["display_name"],
        "state": latest["state"] if latest else PreferenceState.UNSUBSCRIBED.value,
        "topics": sorted(subscriber["topics"] or []),
        "frequency": subscriber["frequency"],
        "format": subscriber["format"],
        "suppressions": active_suppressions(cur, organization_id, constituent_id, subscriber["normalized_email"]),
        "subscribed_at": _iso(subscriber["subscribed_at"]),
        "unsubscribed_at": _iso(subscriber["unsubscribed_at"]),
        "created_at": _iso(subscriber["created_at"]),
        "updated_at": _iso(subscriber["updated_at"]),
        "history": preference_history(cur, organization_id, constituent_id),
    }


def find_issue(cur: psycopg.Cursor, organization_id: int, newsletter_id: str) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT newsletter_id, title, published_at, topic_slugs, html_body, plain_text_body, purpose,
               state, recorded_at, content_sha256
        FROM oc_communications.newsletter_issues
        WHERE organization_id = %s AND newsletter_id = %s
        """,
        (organization_id, newsletter_id),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def insert_issue(cur: psycopg.Cursor, organization_id: int, issue: dict[str, Any], *, state: str, recorded_at: Any = None) -> None:
    cur.execute(
        """
        INSERT INTO oc_communications.newsletter_issues
            (organization_id, newsletter_id, title, published_at, topic_slugs, html_body, plain_text_body,
             purpose, state, content_sha256, recorded_at)
        VALUES (%s, %s, %s, %s, %s::text[], %s, %s, %s, %s, %s, COALESCE(%s::timestamptz, NOW()))
        ON CONFLICT (organization_id, newsletter_id) DO NOTHING
        """,
        (
            organization_id,
            str(issue["newsletter_id"]),
            issue["title"],
            issue["published_at"],
            list(issue.get("topic_slugs") or []),
            issue["html_body"],
            issue["plain_text_body"],
            issue.get("purpose") or PURPOSE,
            state,
            issue_content_sha256(issue["html_body"], issue["plain_text_body"]),
            recorded_at,
        ),
    )


def issue_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "newsletter_id": str(row["newsletter_id"]),
        "title": row["title"],
        "published_at": _iso(row["published_at"]),
        "topic_slugs": list(row["topic_slugs"] or []),
        "html_body": row["html_body"],
        "plain_text_body": row["plain_text_body"],
        "purpose": row["purpose"],
        "state": row["state"],
        "recorded_at": _iso(row["recorded_at"]),
    }


_CONTACT_COLUMNS = (
    "reference_id, category, name, normalized_email, subject, body, source, received_at, state, "
    "review, agent_exposure, content_trust, content_sha256"
)


def find_contact(cur: psycopg.Cursor, organization_id: int, reference_id: str) -> dict[str, Any] | None:
    cur.execute(
        f"SELECT {_CONTACT_COLUMNS} FROM oc_communications.inbound_contact_messages "
        "WHERE organization_id = %s AND reference_id = %s",
        (organization_id, reference_id),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def insert_contact(cur: psycopg.Cursor, organization_id: int, message: dict[str, Any], *, received_at: Any = None) -> None:
    cur.execute(
        """
        INSERT INTO oc_communications.inbound_contact_messages
            (organization_id, reference_id, category, name, normalized_email, subject, body, source,
             state, content_sha256, received_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s::timestamptz, NOW()))
        ON CONFLICT (organization_id, reference_id) DO NOTHING
        """,
        (
            organization_id,
            message["reference_id"],
            message["category"],
            message.get("name"),
            message["normalized_email"],
            message.get("subject"),
            message["body"],
            message.get("source"),
            message.get("state") or "received",
            contact_content_sha256(message),
            received_at,
        ),
    )


def contact_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": row["category"],
        "name": row["name"],
        "normalized_email": row["normalized_email"],
        "subject": row["subject"],
        "body": row["body"],
        "source": row["source"],
        "reference_id": row["reference_id"],
        "received_at": _iso(row["received_at"]),
        "state": row["state"],
        "review": row["review"],
        "agent_exposure": row["agent_exposure"],
        "content_trust": row["content_trust"],
    }


# ---------------------------------------------------------------------------
# Readiness and organization resolution (platform-level, not tenant-owned).
# ---------------------------------------------------------------------------


def missing_schema_objects(cur: psycopg.Cursor) -> list[str]:
    cur.execute(
        """
        SELECT
            to_regprocedure('oc_constituent.current_tenant_id()') IS NOT NULL AS tenant_fn,
            EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'oc_crm_runtime') AS runtime_role,
            to_regclass('oc_constituent.organizations') IS NOT NULL AS organizations,
            to_regclass('oc_communications.newsletter_subscription_settings') IS NOT NULL AS settings,
            to_regclass('oc_communications.newsletter_issues') IS NOT NULL AS issues,
            to_regclass('oc_communications.inbound_contact_messages') IS NOT NULL AS contact,
            to_regclass('oc_communications.uq_oc_communications_welcome_intent_per_constituent') IS NOT NULL AS welcome,
            EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'oc_communications' AND table_name = 'audience_members'
                  AND column_name = 'organization_id'
            ) AS audience_tenant
        """
    )
    row = cur.fetchone()
    return [name for name, present in row.items() if not present]


def resolve_platform_organization(
    cur: psycopg.Cursor, *, slug: str, display_name: str = PLATFORM_ORG_DISPLAY_NAME, create: bool = True
) -> int | None:
    if create:
        cur.execute(
            """
            INSERT INTO oc_constituent.organizations (slug, display_name, kind)
            VALUES (%s, %s, %s) ON CONFLICT (slug) DO NOTHING
            """,
            (slug, display_name, PLATFORM_ORG_KIND),
        )
    cur.execute("SELECT id, kind, status FROM oc_constituent.organizations WHERE slug = %s", (slug,))
    row = cur.fetchone()
    if row is None:
        return None
    if row["kind"] != PLATFORM_ORG_KIND:
        raise CanonicalStoreUnavailable(
            f"organization {slug!r} exists with kind {row['kind']!r}; the newsletter requires kind {PLATFORM_ORG_KIND!r}"
        )
    if row["status"] != "active":
        raise CanonicalStoreUnavailable(f"organization {slug!r} is {row['status']!r}, not active")
    return int(row["id"])


class CanonicalConstituentService:
    """``ConstituentService`` over the canonical CRM schemas; see the module docstring."""

    def __init__(
        self,
        *,
        connect: ConnectionFactory,
        organization_slug: str = PLATFORM_ORG_SLUG,
        organization_display_name: str = PLATFORM_ORG_DISPLAY_NAME,
    ) -> None:
        self._connect = connect
        self._slug = organization_slug.strip().lower()
        self._display_name = organization_display_name
        self._organization_id: int | None = None

    @property
    def organization_slug(self) -> str:
        return self._slug

    def ensure_ready(self) -> int:
        """Probe the schema and resolve (idempotently create) the platform organization."""
        if self._organization_id is not None:
            return self._organization_id
        try:
            with platform_transaction(connect=self._connect) as cur:
                missing = missing_schema_objects(cur)
                if missing:
                    raise CanonicalStoreUnavailable(
                        "canonical constituent schema is not migrated (missing: "
                        + ", ".join(missing)
                        + "); "
                        + _migration_hint()
                    )
                organization_id = resolve_platform_organization(
                    cur, slug=self._slug, display_name=self._display_name, create=True
                )
        except psycopg.Error as exc:
            raise CanonicalStoreUnavailable(
                f"canonical constituent store is unreachable ({type(exc).__name__}); check DATABASE_URL and "
                + _migration_hint()
            ) from exc
        if organization_id is None:
            raise CanonicalStoreUnavailable(f"platform organization {self._slug!r} could not be resolved")
        self._organization_id = organization_id
        return organization_id

    def _tx(self):
        return tenant_transaction(self.ensure_ready(), connect=self._connect)

    # -- subscriptions --------------------------------------------------------------------

    def get_subscription(self, normalized_email: str) -> dict[str, Any] | None:
        public_id = constituent_id_for(normalized_email)
        with self._tx() as cur:
            subscriber = find_subscriber(cur, self._organization_id, public_id)
            if subscriber is None:
                return None
            return subscription_record(cur, self._organization_id, subscriber)

    def subscribe(
        self,
        email: str,
        *,
        display_name: str | None,
        topics: list[str],
        frequency: str,
        format: str,
    ) -> dict[str, Any]:
        normalized = normalize_email(email)
        public_id = constituent_id_for(normalized)
        with self._tx() as cur:
            org = self._organization_id
            lock_subscriber(cur, org, public_id)
            subscriber = find_subscriber(cur, org, public_id)
            if subscriber is None:
                constituent_id = create_subscriber(
                    cur,
                    org,
                    normalized_email=normalized,
                    public_id=public_id,
                    display_name=display_name,
                    topics=topics,
                    frequency=frequency,
                    format=format,
                )
            else:
                constituent_id = int(subscriber["constituent_id"])
            cur.execute(
                """
                UPDATE oc_communications.newsletter_subscription_settings
                SET display_name = COALESCE(%s, display_name), topics = %s::text[], frequency = %s,
                    format = %s, subscribed_at = NOW(), updated_at = NOW()
                WHERE organization_id = %s AND constituent_id = %s
                """,
                (display_name, sorted(set(topics)), frequency, format, org, constituent_id),
            )
            latest = latest_preference(cur, org, constituent_id)
            if latest is None or latest["state"] != PreferenceState.SUBSCRIBED.value:
                record_preference(
                    cur,
                    org,
                    constituent_id,
                    state=PreferenceState.SUBSCRIBED.value,
                    supersedes_id=latest["id"] if latest else None,
                    source_kind=SOURCE_PUBLIC_FORM,
                )
            # Re-subscribing lifts the constituent's own unsubscribe; delivery-critical
            # suppressions (bounce, complaint, invalid, admin block) are never lifted here.
            lift_own_unsubscribe(cur, org, constituent_id, normalized)
            intent = find_welcome_intent(cur, org, constituent_id) or create_welcome_intent(
                cur, org, constituent_id=constituent_id, public_id=public_id, normalized_email=normalized
            )
            record = subscription_record(cur, org, find_subscriber(cur, org, public_id))
        return {"subscription": record, "communication": communication_record(intent, public_id)}

    def unsubscribe(self, email: str, *, reason: str | None) -> dict[str, Any]:
        normalized = normalize_email(email)
        public_id = constituent_id_for(normalized)
        with self._tx() as cur:
            org = self._organization_id
            lock_subscriber(cur, org, public_id)
            subscriber = find_subscriber(cur, org, public_id)
            if subscriber is None:
                # Unknown addresses get the same answer and a durable suppression.
                constituent_id = create_subscriber(
                    cur,
                    org,
                    normalized_email=normalized,
                    public_id=public_id,
                    display_name=None,
                    topics=[],
                    frequency="weekly",
                    format="html",
                )
            else:
                constituent_id = int(subscriber["constituent_id"])
            latest = latest_preference(cur, org, constituent_id)
            if latest is None or latest["state"] != PreferenceState.UNSUBSCRIBED.value:
                record_preference(
                    cur,
                    org,
                    constituent_id,
                    state=PreferenceState.UNSUBSCRIBED.value,
                    supersedes_id=latest["id"] if latest else None,
                    source_kind=SOURCE_PUBLIC_FORM,
                )
                cur.execute(
                    """
                    UPDATE oc_communications.newsletter_subscription_settings
                    SET unsubscribed_at = NOW(), updated_at = NOW()
                    WHERE organization_id = %s AND constituent_id = %s
                    """,
                    (org, constituent_id),
                )
            if SuppressionKind.UNSUBSCRIBE.value not in active_suppressions(cur, org, constituent_id, normalized):
                add_suppression(
                    cur,
                    org,
                    constituent_id,
                    normalized_email=normalized,
                    kind=SuppressionKind.UNSUBSCRIBE.value,
                    reason=(reason or "")[:500] or None,
                    source_kind=SOURCE_PUBLIC_FORM,
                )
            return subscription_record(cur, org, find_subscriber(cur, org, public_id))

    def update_preferences(
        self,
        normalized_email: str,
        *,
        topics: list[str] | None,
        frequency: str | None,
        format: str | None,
    ) -> dict[str, Any]:
        public_id = constituent_id_for(normalized_email)
        with self._tx() as cur:
            org = self._organization_id
            lock_subscriber(cur, org, public_id)
            subscriber = find_subscriber(cur, org, public_id)
            if subscriber is None:
                raise NotFound(normalized_email)
            cur.execute(
                """
                UPDATE oc_communications.newsletter_subscription_settings
                SET topics = COALESCE(%s::text[], topics), frequency = COALESCE(%s, frequency),
                    format = COALESCE(%s, format), updated_at = NOW()
                WHERE organization_id = %s AND constituent_id = %s
                """,
                (
                    sorted(set(topics)) if topics is not None else None,
                    frequency,
                    format,
                    org,
                    int(subscriber["constituent_id"]),
                ),
            )
            return subscription_record(cur, org, find_subscriber(cur, org, public_id))

    def delivery_decision(self, normalized_email: str, purpose: MessagePurpose) -> tuple[bool, str]:
        """What ``recipient_delivery_decision`` says for this address today (no address disclosed)."""
        public_id = constituent_id_for(normalized_email)
        with self._tx() as cur:
            subscriber = find_subscriber(cur, self._organization_id, public_id)
            if subscriber is None:
                return recipient_delivery_decision(purpose=purpose, preference=None, suppressions=frozenset())
            constituent_id = int(subscriber["constituent_id"])
            latest = latest_preference(cur, self._organization_id, constituent_id)
            kinds = active_suppressions(cur, self._organization_id, constituent_id, normalized_email)
        return recipient_delivery_decision(
            purpose=purpose,
            preference=PreferenceState(latest["state"]) if latest else None,
            suppressions={SuppressionKind(kind) for kind in kinds},
        )

    def subscription_summary(self) -> dict[str, Any]:
        with self._tx() as cur:
            org = self._organization_id
            cur.execute(
                "SELECT count(*) AS n FROM oc_communications.newsletter_subscription_settings WHERE organization_id = %s",
                (org,),
            )
            total = int(cur.fetchone()["n"])
            cur.execute(
                """
                SELECT COALESCE(p.state, 'unsubscribed') AS state, count(*) AS n
                FROM oc_communications.newsletter_subscription_settings s
                LEFT JOIN LATERAL (
                    SELECT state FROM oc_constituent.communication_preferences cp
                    WHERE cp.organization_id = s.organization_id AND cp.constituent_id = s.constituent_id
                      AND cp.channel = %s AND cp.purpose = %s AND cp.topic = %s
                    ORDER BY cp.id DESC LIMIT 1
                ) p ON TRUE
                WHERE s.organization_id = %s
                GROUP BY 1 ORDER BY 1
                """,
                (CHANNEL, PURPOSE, TOPIC_ALL, org),
            )
            by_state = {row["state"]: int(row["n"]) for row in cur.fetchall()}
            cur.execute(
                """
                SELECT count(*) AS n FROM oc_communications.intents
                WHERE organization_id = %s AND initiating_module = %s AND state = %s
                """,
                (org, WELCOME_MODULE, CommunicationState.AWAITING_APPROVAL.value),
            )
            held = int(cur.fetchone()["n"])
        return {"total": total, "by_state": by_state, "welcome_communications_awaiting_approval": held}

    # -- newsletter archive ---------------------------------------------------------------

    def publish_issue(self, issue: dict[str, Any]) -> dict[str, Any]:
        with self._tx() as cur:
            insert_issue(cur, self._organization_id, issue, state=CommunicationState.COMPLETED.value)
            row = find_issue(cur, self._organization_id, str(issue["newsletter_id"]))
        return issue_record(row)

    def list_issues(self) -> list[dict[str, Any]]:
        with self._tx() as cur:
            cur.execute(
                """
                SELECT newsletter_id, title, published_at, topic_slugs, html_body, plain_text_body, purpose,
                       state, recorded_at
                FROM oc_communications.newsletter_issues
                WHERE organization_id = %s AND state = %s
                ORDER BY published_at DESC, id DESC
                """,
                (self._organization_id, CommunicationState.COMPLETED.value),
            )
            return [issue_record(row) for row in cur.fetchall()]

    def get_issue(self, newsletter_id: str) -> dict[str, Any]:
        try:
            parsed = str(uuid.UUID(str(newsletter_id)))
        except ValueError as exc:
            raise NotFound(newsletter_id) from exc
        with self._tx() as cur:
            row = find_issue(cur, self._organization_id, parsed)
        if row is None or row["state"] != CommunicationState.COMPLETED.value:
            raise NotFound(newsletter_id)
        return issue_record(row)

    # -- contact inbox ----------------------------------------------------------------------

    def receive_contact(self, message: dict[str, Any]) -> dict[str, Any]:
        record = {
            **message,
            "reference_id": contact_reference_id(message),
            "state": "received",
            "review": CONTACT_REVIEW,
            "agent_exposure": CONTACT_AGENT_EXPOSURE,
            "content_trust": "untrusted_plain_text",
        }
        with self._tx() as cur:
            insert_contact(cur, self._organization_id, record)
            row = find_contact(cur, self._organization_id, record["reference_id"])
        return contact_record(row)

    def list_contact_messages(self, *, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        with self._tx() as cur:
            org = self._organization_id
            cur.execute(
                "SELECT count(*) AS n FROM oc_communications.inbound_contact_messages WHERE organization_id = %s",
                (org,),
            )
            total = int(cur.fetchone()["n"])
            cur.execute(
                f"SELECT {_CONTACT_COLUMNS} FROM oc_communications.inbound_contact_messages "
                "WHERE organization_id = %s ORDER BY received_at DESC, id DESC LIMIT %s OFFSET %s",
                (org, limit, offset),
            )
            rows = [contact_record(row) for row in cur.fetchall()]
        return rows, total


# ---------------------------------------------------------------------------
# Process-level selection
# ---------------------------------------------------------------------------

_configured: CanonicalConstituentService | None = None
_by_dsn: dict[str, CanonicalConstituentService] = {}


def configure_canonical_service(service: CanonicalConstituentService | None) -> None:
    """Pin the canonical service (tests, or an app factory); ``None`` restores env resolution."""
    global _configured
    _configured = service
    _by_dsn.clear()


def normalized_dsn(dsn: str) -> str:
    return _DRIVER_PREFIX.sub("postgresql://", dsn.strip())


def get_canonical_service() -> CanonicalConstituentService:
    """The canonical service for this process, ready to serve, or ``CanonicalStoreUnavailable``."""
    if _configured is not None:
        _configured.ensure_ready()
        return _configured
    raw = str(os.environ.get("DATABASE_URL", "") or "").strip()
    if not raw:
        raise CanonicalStoreUnavailable(
            f"{PERSISTENCE_ENV}=canonical requires DATABASE_URL; refusing to fall back to the Research "
            "Station store. " + _migration_hint()
        )
    dsn = normalized_dsn(raw)
    service = _by_dsn.get(dsn) or CanonicalConstituentService(connect=dsn_connection_factory(dsn))
    service.ensure_ready()
    _by_dsn[dsn] = service
    return service
