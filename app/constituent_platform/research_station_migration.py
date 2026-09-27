"""Research Station -> canonical constituent store migration and discrepancy report (#1652).

Reads every constituent-platform record from the Research Station record store
(``OWNER_KEY='constituent-platform'``: subscriptions, welcome communications,
newsletter archive, contact inbox) and reconciles it against the canonical
``oc_constituent`` / ``oc_communications`` tables owned by the Orchid Continuum
platform organization.

Per record the outcome is exactly one of:

* ``created``   -- absent on the canonical side; written on ``apply`` (in a dry
  run: would be written);
* ``unchanged`` -- the canonical side already holds the same value;
* ``conflict``  -- the canonical side holds a DIFFERENT value. Never overwritten;
  the differing field names are reported for a human to resolve;
* ``invalid``   -- the legacy record cannot be migrated (bad email, unknown
  state, orphan welcome...). Reported, never silently dropped;
* ``failed``    -- an ``apply`` write raised; that record's transaction rolled
  back and the run continued.

Dry run is the default and performs no writes: every canonical read runs in a
``READ ONLY`` tenant transaction and the platform organization is looked up,
never created. Re-running ``apply`` is idempotent: a second run reports every
record ``unchanged``. The report carries hashed emails and record ids, never raw
addresses, so it can be attached to an issue.

``cutover_ready`` is true only when every record is ``unchanged`` (nothing left
to create, zero conflict/invalid/failed): the precondition for setting
``OC_CONSTITUENT_PERSISTENCE=canonical``.

Known simplifications (documented, not hidden): a migrated subscriber gets one
preference-ledger row for its current state (the legacy 20-event ``history`` is
not replayed), and legacy suppressions are written with
``source_kind='research_station_migration'`` and no reason text.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from runtime.research_station_store import ProjectRecordStore

from . import canonical_store as cs
from .domain import CommunicationState, MessagePurpose, PreferenceState, SuppressionKind, normalize_email
from .service import (
    KIND_COMMUNICATION,
    KIND_CONTACT,
    KIND_ISSUE,
    KIND_SUBSCRIPTION,
    OWNER_KEY,
    PROJECT_ARCHIVE,
    PROJECT_INBOX,
    PROJECT_SUBSCRIPTIONS,
    PROJECT_WELCOME,
    constituent_id_for,
    subscription_record_id,
)
from .tenant_db import ConnectionFactory, platform_transaction, tenant_transaction

SOURCE_KIND = "research_station_migration"
SOURCE_SYSTEM = "research_station"
OUTCOMES = ("created", "unchanged", "conflict", "invalid", "failed")
FREQUENCIES = frozenset({"immediate", "daily", "weekly", "monthly", "quarterly"})
FORMATS = frozenset({"html", "plain"})

SOURCES = (
    ("subscription", PROJECT_SUBSCRIPTIONS, KIND_SUBSCRIPTION),
    ("welcome_communication", PROJECT_WELCOME, KIND_COMMUNICATION),
    ("newsletter_issue", PROJECT_ARCHIVE, KIND_ISSUE),
    ("contact_message", PROJECT_INBOX, KIND_CONTACT),
)


class InvalidRecord(ValueError):
    pass


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def payload_sha256(record: dict[str, Any]) -> str:
    return _sha(json.dumps(record, sort_keys=True, separators=(",", ":"), default=str))


def _timestamp(value: Any, field: str, *, required: bool = False) -> datetime | None:
    if value in (None, ""):
        if required:
            raise InvalidRecord(f"missing_{field}")
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidRecord(f"invalid_{field}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _email(value: Any) -> str:
    try:
        return normalize_email(str(value or ""))
    except ValueError as exc:
        raise InvalidRecord("invalid_email") from exc


def _str_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InvalidRecord(f"invalid_{field}")
    return value


def _raw_email_hash(record: dict[str, Any]) -> str:
    return _sha(str(record.get("normalized_email") or "").strip().lower())


# ---------------------------------------------------------------------------
# Validation of legacy records into canonical-ready values
# ---------------------------------------------------------------------------


def _subscription(record: dict[str, Any]) -> dict[str, Any]:
    email = _email(record.get("normalized_email"))
    public_id = constituent_id_for(email)
    if str(record.get("constituent_id") or "") != public_id:
        raise InvalidRecord("public_id_mismatch")
    state = record.get("state")
    if state not in {item.value for item in PreferenceState}:
        raise InvalidRecord("invalid_state")
    suppressions = _str_list(record.get("suppressions"), "suppressions")
    if any(kind not in {item.value for item in SuppressionKind} for kind in suppressions):
        raise InvalidRecord("invalid_suppression_kind")
    frequency = record.get("frequency") or "weekly"
    fmt = record.get("format") or "html"
    if frequency not in FREQUENCIES:
        raise InvalidRecord("invalid_frequency")
    if fmt not in FORMATS:
        raise InvalidRecord("invalid_format")
    display_name = record.get("display_name")
    if display_name is not None and not isinstance(display_name, str):
        raise InvalidRecord("invalid_display_name")
    return {
        "normalized_email": email,
        "public_id": public_id,
        "state": state,
        "topics": sorted(set(_str_list(record.get("topics"), "topics"))),
        "frequency": frequency,
        "format": fmt,
        "suppressions": sorted(set(suppressions)),
        "display_name": display_name,
        "subscribed_at": _timestamp(record.get("subscribed_at"), "subscribed_at"),
        "unsubscribed_at": _timestamp(record.get("unsubscribed_at"), "unsubscribed_at"),
        "created_at": _timestamp(record.get("created_at"), "created_at"),
        "updated_at": _timestamp(record.get("updated_at"), "updated_at"),
    }


def _welcome(record: dict[str, Any]) -> dict[str, Any]:
    try:
        public_id = str(uuid.UUID(str(record.get("constituent_id") or "")))
    except ValueError as exc:
        raise InvalidRecord("invalid_constituent_id") from exc
    state = record.get("state")
    if state not in {item.value for item in CommunicationState}:
        raise InvalidRecord("invalid_state")
    return {
        "public_id": public_id,
        "state": state,
        "requested_at": _timestamp(record.get("requested_at"), "requested_at"),
    }


def _issue(record: dict[str, Any]) -> dict[str, Any]:
    try:
        newsletter_id = str(uuid.UUID(str(record.get("newsletter_id") or "")))
    except ValueError as exc:
        raise InvalidRecord("invalid_newsletter_id") from exc
    title = record.get("title")
    if not isinstance(title, str) or not 1 <= len(title) <= 300:
        raise InvalidRecord("invalid_title")
    for field in ("html_body", "plain_text_body"):
        if not isinstance(record.get(field), str) or not record[field]:
            raise InvalidRecord(f"invalid_{field}")
    purpose = record.get("purpose") or MessagePurpose.COMMUNITY.value
    if purpose not in {item.value for item in MessagePurpose}:
        raise InvalidRecord("invalid_purpose")
    state = record.get("state") or CommunicationState.COMPLETED.value
    if state not in {item.value for item in CommunicationState}:
        raise InvalidRecord("invalid_state")
    return {
        "newsletter_id": newsletter_id,
        "title": title,
        "published_at": _timestamp(record.get("published_at"), "published_at", required=True),
        "topic_slugs": list(_str_list(record.get("topic_slugs"), "topic_slugs")),
        "html_body": record["html_body"],
        "plain_text_body": record["plain_text_body"],
        "purpose": purpose,
        "state": state,
        "content_sha256": cs.issue_content_sha256(record["html_body"], record["plain_text_body"]),
        "recorded_at": _timestamp(record.get("recorded_at"), "recorded_at"),
    }


def _contact(record: dict[str, Any]) -> dict[str, Any]:
    reference_id = record.get("reference_id")
    if not isinstance(reference_id, str) or not 1 <= len(reference_id) <= 80:
        raise InvalidRecord("invalid_reference_id")
    email = _email(record.get("normalized_email"))
    body = record.get("body")
    if not isinstance(body, str) or not body:
        raise InvalidRecord("invalid_body")
    category = record.get("category")
    if not isinstance(category, str) or not category:
        raise InvalidRecord("invalid_category")
    for field in ("name", "subject", "source"):
        if record.get(field) is not None and not isinstance(record.get(field), str):
            raise InvalidRecord(f"invalid_{field}")
    message = {
        "reference_id": reference_id,
        "category": category,
        "name": record.get("name"),
        "normalized_email": email,
        "subject": record.get("subject"),
        "body": body,
        "source": record.get("source"),
        "state": record.get("state") or "received",
    }
    message["content_sha256"] = cs.contact_content_sha256(message)
    message["received_at"] = _timestamp(record.get("received_at"), "received_at")
    return message


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def _differences(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    return sorted(field for field, value in expected.items() if actual.get(field) != value)


class _Reconciler:
    def __init__(self, *, connect: ConnectionFactory, organization_id: int | None, apply: bool) -> None:
        self.connect = connect
        self.organization_id = organization_id
        self.apply = apply
        self.planned_subscribers: set[str] = set()

    def _tx(self):
        return tenant_transaction(self.organization_id, connect=self.connect)

    def _read_only(self, cur) -> None:
        if not self.apply:
            cur.execute("SET TRANSACTION READ ONLY")

    def subscription(self, value: dict[str, Any], legacy: dict[str, Any], record_id: str) -> dict[str, Any]:
        expected = {
            "state": value["state"],
            "topics": value["topics"],
            "frequency": value["frequency"],
            "format": value["format"],
            "suppressions": value["suppressions"],
        }
        if self.organization_id is None:
            self.planned_subscribers.add(value["public_id"])
            return {"outcome": "created"}
        org = self.organization_id
        with self._tx() as cur:
            self._read_only(cur)
            if self.apply:
                cs.lock_subscriber(cur, org, value["public_id"])
            existing = cs.find_subscriber(cur, org, value["public_id"])
            if existing is not None:
                current = cs.subscription_record(cur, org, existing)
                actual = {**current, "suppressions": sorted(set(current["suppressions"]))}
                fields = _differences(expected, actual)
                return {"outcome": "conflict", "fields": fields} if fields else {"outcome": "unchanged"}
            if not self.apply:
                self.planned_subscribers.add(value["public_id"])
                return {"outcome": "created"}
            constituent_id = cs.create_subscriber(
                cur,
                org,
                normalized_email=value["normalized_email"],
                public_id=value["public_id"],
                display_name=value["display_name"],
                topics=value["topics"],
                frequency=value["frequency"],
                format=value["format"],
                subscribed_at=value["subscribed_at"],
                unsubscribed_at=value["unsubscribed_at"],
                created_at=value["created_at"],
            )
            cs.record_preference(
                cur,
                org,
                constituent_id,
                state=value["state"],
                supersedes_id=None,
                source_kind=SOURCE_KIND,
                evidence_ref=f"{SOURCE_SYSTEM}:{OWNER_KEY}/{PROJECT_SUBSCRIPTIONS}/{record_id}",
                created_at=value["updated_at"],
            )
            for kind in value["suppressions"]:
                cs.add_suppression(
                    cur,
                    org,
                    constituent_id,
                    normalized_email=value["normalized_email"],
                    kind=kind,
                    reason=None,
                    source_kind=SOURCE_KIND,
                )
            cur.execute(
                """
                INSERT INTO oc_constituent.external_record_links
                    (organization_id, constituent_id, source_system, source_record_type, source_record_id,
                     source_payload_sha256)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (organization_id, source_system, source_record_type, source_record_id) DO NOTHING
                """,
                (org, constituent_id, SOURCE_SYSTEM, KIND_SUBSCRIPTION, record_id, payload_sha256(legacy)),
            )
        return {"outcome": "created"}

    def welcome(self, value: dict[str, Any]) -> dict[str, Any]:
        planned = value["public_id"] in self.planned_subscribers
        if self.organization_id is None:
            return {"outcome": "created"} if planned else {"outcome": "invalid", "reason": "orphan_welcome_communication"}
        org = self.organization_id
        with self._tx() as cur:
            self._read_only(cur)
            subscriber = cs.find_subscriber(cur, org, value["public_id"])
            if subscriber is None:
                if planned and not self.apply:
                    return {"outcome": "created"}
                return {"outcome": "invalid", "reason": "orphan_welcome_communication"}
            constituent_id = int(subscriber["constituent_id"])
            intent = cs.find_welcome_intent(cur, org, constituent_id)
            if intent is not None:
                if intent["state"] != value["state"]:
                    return {"outcome": "conflict", "fields": ["state"]}
                return {"outcome": "unchanged"}
            if value["state"] != CommunicationState.AWAITING_APPROVAL.value:
                return {"outcome": "invalid", "reason": "unsupported_legacy_state"}
            if self.apply:
                cs.lock_subscriber(cur, org, value["public_id"])
                cs.create_welcome_intent(
                    cur,
                    org,
                    constituent_id=constituent_id,
                    public_id=value["public_id"],
                    normalized_email=subscriber["normalized_email"],
                    requested_at=value["requested_at"],
                )
        return {"outcome": "created"}

    def issue(self, value: dict[str, Any]) -> dict[str, Any]:
        if self.organization_id is None:
            return {"outcome": "created"}
        org = self.organization_id
        with self._tx() as cur:
            self._read_only(cur)
            existing = cs.find_issue(cur, org, value["newsletter_id"])
            if existing is not None:
                expected = {key: value[key] for key in ("title", "published_at", "topic_slugs", "purpose", "state", "content_sha256")}
                actual = {**existing, "topic_slugs": list(existing["topic_slugs"] or [])}
                fields = _differences(expected, actual)
                return {"outcome": "conflict", "fields": fields} if fields else {"outcome": "unchanged"}
            if self.apply:
                cs.insert_issue(cur, org, value, state=value["state"], recorded_at=value["recorded_at"])
        return {"outcome": "created"}

    def contact(self, value: dict[str, Any]) -> dict[str, Any]:
        if self.organization_id is None:
            return {"outcome": "created"}
        org = self.organization_id
        with self._tx() as cur:
            self._read_only(cur)
            existing = cs.find_contact(cur, org, value["reference_id"])
            if existing is not None:
                if existing["content_sha256"] != value["content_sha256"]:
                    return {"outcome": "conflict", "fields": ["content_sha256"]}
                return {"outcome": "unchanged"}
            if self.apply:
                cs.insert_contact(cur, org, value, received_at=value["received_at"])
        return {"outcome": "created"}


def _entries(kind: str, records: Iterable[dict[str, Any]], reconciler: _Reconciler) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for legacy in records:
        entry: dict[str, Any] = {"kind": kind}
        try:
            if kind == "subscription":
                entry["email_sha256"] = _raw_email_hash(legacy)
                entry["record_id"] = subscription_record_id(str(legacy.get("normalized_email") or "").strip().lower())
                value = _subscription(legacy)
                entry["record_id"] = subscription_record_id(value["normalized_email"])
                entry.update(reconciler.subscription(value, legacy, entry["record_id"]))
            elif kind == "welcome_communication":
                entry["record_id"] = str(legacy.get("constituent_id") or f"payload:{payload_sha256(legacy)[:32]}")
                entry.update(reconciler.welcome(_welcome(legacy)))
            elif kind == "newsletter_issue":
                entry["record_id"] = str(legacy.get("newsletter_id") or f"payload:{payload_sha256(legacy)[:32]}")
                entry.update(reconciler.issue(_issue(legacy)))
            else:
                entry["record_id"] = str(legacy.get("reference_id") or f"payload:{payload_sha256(legacy)[:32]}")
                entry["email_sha256"] = _raw_email_hash(legacy)
                entry.update(reconciler.contact(_contact(legacy)))
        except InvalidRecord as exc:
            entry.update({"outcome": "invalid", "reason": str(exc)})
        except Exception as exc:  # noqa: BLE001 - one bad write must not abort the run; it is reported
            if not reconciler.apply:
                raise
            entry.update({"outcome": "failed", "reason": type(exc).__name__})
        entries.append(entry)
    return entries


def migrate(
    source: ProjectRecordStore,
    *,
    connect: ConnectionFactory,
    organization_slug: str = cs.PLATFORM_ORG_SLUG,
    apply: bool = False,
) -> dict[str, Any]:
    """Reconcile the Research Station records into the canonical store; dry run unless ``apply``."""
    slug = organization_slug.strip().lower()
    with platform_transaction(connect=connect) as cur:
        if not apply:
            cur.execute("SET TRANSACTION READ ONLY")
        missing = cs.missing_schema_objects(cur)
        if missing:
            raise cs.CanonicalStoreUnavailable(
                "canonical constituent schema is not migrated (missing: " + ", ".join(missing) + "); "
                + cs._migration_hint()
            )
        organization_id = cs.resolve_platform_organization(cur, slug=slug, create=apply)

    reconciler = _Reconciler(connect=connect, organization_id=organization_id, apply=apply)
    records: list[dict[str, Any]] = []
    for kind, project_id, record_kind in SOURCES:
        rows = source.list(owner_key=OWNER_KEY, project_id=project_id, kind=record_kind)
        records.extend(_entries(kind, rows, reconciler))

    counts = {outcome: 0 for outcome in OUTCOMES}
    for entry in records:
        counts[entry["outcome"]] += 1
    return {
        "mode": "apply" if apply else "dry_run",
        "writes_performed": bool(apply and counts["created"]),
        "organization_slug": slug,
        "organization_id": organization_id,
        "source": {"owner_key": OWNER_KEY, "projects": [project for _, project, _ in SOURCES]},
        "counts": counts,
        "cutover_ready": sum(counts.values()) == counts["unchanged"],
        "records": records,
    }
