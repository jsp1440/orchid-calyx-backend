"""Journey 12 / 13 — durable constituent records over the Research Station store.

Subscriptions, held welcome communications, published newsletter issues and
contact messages live in ``oc_admin.research_station_records`` when a database
is configured and in process memory otherwise, exactly as the field
observation and hypothesis modules do. No new tables, no migration.

Privacy posture: records are keyed by a hash of the normalised email, the
table is owner-only, and nothing here ever tells an anonymous caller whether a
given address is subscribed. Unsubscribe is idempotent and answers the same
way for known and unknown addresses.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from app.security import get_owner_session_secret
from runtime.research_station_store import (
    MemoryProjectRecordStore,
    ProjectRecordStore,
    build_record_store,
)

from .domain import (
    CommunicationState,
    MessagePurpose,
    PreferenceState,
    SuppressionKind,
    approval_required,
    normalize_email,
)

OWNER_KEY = "constituent-platform"
KIND_SUBSCRIPTION = "constituent_subscription"
PROJECT_SUBSCRIPTIONS = "subscriptions"
KIND_COMMUNICATION = "constituent_communication"
PROJECT_WELCOME = "welcome"
KIND_ISSUE = "newsletter_issue"
PROJECT_ARCHIVE = "archive"
KIND_CONTACT = "contact_message"
PROJECT_INBOX = "inbox"

CONSTITUENT_NAMESPACE = uuid.UUID("6f1c2a2e-2f4e-4b8e-9c2b-7a3d5e1f0c11")
CONTACT_REVIEW = "human_review_required"
CONTACT_AGENT_EXPOSURE = "never_forwarded_to_agents"


class NotFound(LookupError):
    pass


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def constituent_id_for(normalized_email: str) -> str:
    return str(uuid.uuid5(CONSTITUENT_NAMESPACE, f"orchid-continuum:constituent:{normalized_email}"))


def subscription_record_id(normalized_email: str) -> str:
    return hashlib.sha256(normalized_email.encode("utf-8")).hexdigest()[:32]


def manage_secret() -> str | None:
    return os.getenv("CONSTITUENT_MANAGE_SECRET") or get_owner_session_secret()


def issue_manage_token(normalized_email: str) -> str | None:
    """A per-address preference-centre token, or ``None`` when no secret is configured."""
    secret = manage_secret()
    if not secret:
        return None
    return hmac.new(secret.encode("utf-8"), f"manage:{normalized_email}".encode(), hashlib.sha256).hexdigest()[:40]


def verify_manage_token(normalized_email: str, token: str | None) -> bool:
    expected = issue_manage_token(normalized_email)
    if not expected or not token:
        return False
    return hmac.compare_digest(expected, token.strip())


_store: ProjectRecordStore | None = None


def configure_store(store: ProjectRecordStore | None) -> None:
    global _store
    _store = store


def get_store() -> ProjectRecordStore:
    global _store
    if _store is None:
        _store = build_record_store()
    return _store


def memory_store() -> MemoryProjectRecordStore:
    return MemoryProjectRecordStore()


class ConstituentService:
    def __init__(self, store: ProjectRecordStore) -> None:
        self._store = store

    # -- subscriptions --------------------------------------------------------------------

    def get_subscription(self, normalized_email: str) -> dict[str, Any] | None:
        return self._store.get(
            owner_key=OWNER_KEY,
            project_id=PROJECT_SUBSCRIPTIONS,
            kind=KIND_SUBSCRIPTION,
            record_id=subscription_record_id(normalized_email),
        )

    def _put_subscription(self, record: dict[str, Any]) -> None:
        self._store.put(
            owner_key=OWNER_KEY,
            project_id=PROJECT_SUBSCRIPTIONS,
            kind=KIND_SUBSCRIPTION,
            record_id=subscription_record_id(record["normalized_email"]),
            record=record,
        )

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
        now = _now()
        record = self.get_subscription(normalized) or {
            "constituent_id": constituent_id_for(normalized),
            "normalized_email": normalized,
            "display_name": None,
            "state": PreferenceState.UNSUBSCRIBED.value,
            "topics": [],
            "frequency": frequency,
            "format": format,
            "suppressions": [],
            "subscribed_at": None,
            "unsubscribed_at": None,
            "created_at": now,
            "updated_at": now,
            "history": [],
        }
        record["display_name"] = display_name or record.get("display_name")
        record["state"] = PreferenceState.SUBSCRIBED.value
        record["topics"] = sorted(set(topics))
        record["frequency"] = frequency
        record["format"] = format
        # Re-subscribing lifts the constituent's own unsubscribe; delivery-critical
        # suppressions (bounce, complaint, invalid, admin block) are never lifted here.
        record["suppressions"] = [
            item for item in record.get("suppressions", []) if item != SuppressionKind.UNSUBSCRIBE.value
        ]
        record["subscribed_at"] = now
        record["updated_at"] = now
        record["history"] = [*record.get("history", [])[-19:], {"event": "subscribed", "at": now}]
        self._put_subscription(record)

        # The welcome message is a communication held at the human-approval gate;
        # nothing is sent by this module.
        communication = {
            "communication_id": f"welcome-{record['constituent_id']}",
            "purpose": MessagePurpose.COMMUNITY.value,
            "state": CommunicationState.AWAITING_APPROVAL.value,
            "approval_required": approval_required(MessagePurpose.COMMUNITY, 1),
            "audience_size": 1,
            "constituent_id": record["constituent_id"],
            "requested_at": now,
            "dispatch": "blocked_pending_human_approval",
        }
        self._store.put(
            owner_key=OWNER_KEY,
            project_id=PROJECT_WELCOME,
            kind=KIND_COMMUNICATION,
            record_id=record["constituent_id"],
            record=communication,
        )
        return {"subscription": record, "communication": communication}

    def unsubscribe(self, email: str, *, reason: str | None) -> dict[str, Any]:
        normalized = normalize_email(email)
        now = _now()
        record = self.get_subscription(normalized) or {
            "constituent_id": constituent_id_for(normalized),
            "normalized_email": normalized,
            "display_name": None,
            "state": PreferenceState.UNSUBSCRIBED.value,
            "topics": [],
            "frequency": "weekly",
            "format": "html",
            "suppressions": [],
            "subscribed_at": None,
            "unsubscribed_at": None,
            "created_at": now,
            "updated_at": now,
            "history": [],
        }
        record["state"] = PreferenceState.UNSUBSCRIBED.value
        if SuppressionKind.UNSUBSCRIBE.value not in record["suppressions"]:
            record["suppressions"] = [*record["suppressions"], SuppressionKind.UNSUBSCRIBE.value]
        record["unsubscribed_at"] = now
        record["updated_at"] = now
        record["history"] = [
            *record.get("history", [])[-19:],
            {"event": "unsubscribed", "at": now, "reason": (reason or "")[:500] or None},
        ]
        self._put_subscription(record)
        return record

    def update_preferences(
        self,
        normalized_email: str,
        *,
        topics: list[str] | None,
        frequency: str | None,
        format: str | None,
    ) -> dict[str, Any]:
        record = self.get_subscription(normalized_email)
        if record is None:
            raise NotFound(normalized_email)
        if topics is not None:
            record["topics"] = sorted(set(topics))
        if frequency is not None:
            record["frequency"] = frequency
        if format is not None:
            record["format"] = format
        record["updated_at"] = _now()
        self._put_subscription(record)
        return record

    def subscription_summary(self) -> dict[str, Any]:
        rows = self._store.list(owner_key=OWNER_KEY, project_id=PROJECT_SUBSCRIPTIONS, kind=KIND_SUBSCRIPTION)
        by_state: dict[str, int] = {}
        for row in rows:
            by_state[row["state"]] = by_state.get(row["state"], 0) + 1
        held = self._store.list(owner_key=OWNER_KEY, project_id=PROJECT_WELCOME, kind=KIND_COMMUNICATION)
        return {
            "total": len(rows),
            "by_state": by_state,
            "welcome_communications_awaiting_approval": sum(
                1 for item in held if item.get("state") == CommunicationState.AWAITING_APPROVAL.value
            ),
        }

    # -- newsletter archive ---------------------------------------------------------------

    def publish_issue(self, issue: dict[str, Any]) -> dict[str, Any]:
        record = {**issue, "state": CommunicationState.COMPLETED.value, "recorded_at": _now()}
        self._store.put(
            owner_key=OWNER_KEY,
            project_id=PROJECT_ARCHIVE,
            kind=KIND_ISSUE,
            record_id=str(record["newsletter_id"]),
            record=record,
        )
        return record

    def list_issues(self) -> list[dict[str, Any]]:
        rows = self._store.list(owner_key=OWNER_KEY, project_id=PROJECT_ARCHIVE, kind=KIND_ISSUE)
        rows = [row for row in rows if row.get("state") == CommunicationState.COMPLETED.value]
        rows.sort(key=lambda row: str(row.get("published_at", "")), reverse=True)
        return rows

    def get_issue(self, newsletter_id: str) -> dict[str, Any]:
        row = self._store.get(owner_key=OWNER_KEY, project_id=PROJECT_ARCHIVE, kind=KIND_ISSUE, record_id=newsletter_id)
        if row is None or row.get("state") != CommunicationState.COMPLETED.value:
            raise NotFound(newsletter_id)
        return row

    # -- contact inbox ----------------------------------------------------------------------

    def receive_contact(self, message: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        seed = f"{message['normalized_email']}\n{message['body']}\n{message.get('subject') or ''}"
        record = {
            **message,
            "reference_id": f"cm-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:24]}",
            "received_at": now,
            "state": "received",
            "review": CONTACT_REVIEW,
            "agent_exposure": CONTACT_AGENT_EXPOSURE,
            "content_trust": "untrusted_plain_text",
        }
        existing = self._store.get(
            owner_key=OWNER_KEY, project_id=PROJECT_INBOX, kind=KIND_CONTACT, record_id=record["reference_id"]
        )
        if existing is not None:
            return existing
        self._store.put(
            owner_key=OWNER_KEY, project_id=PROJECT_INBOX, kind=KIND_CONTACT, record_id=record["reference_id"], record=record
        )
        return record

    def list_contact_messages(self, *, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
        rows = self._store.list(owner_key=OWNER_KEY, project_id=PROJECT_INBOX, kind=KIND_CONTACT)
        rows.sort(key=lambda row: str(row.get("received_at", "")), reverse=True)
        return rows[offset : offset + limit], len(rows)
