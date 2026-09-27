"""Society communications: consent-aware audiences, approval by exact audience, delivery.

Flow (every step tenant-scoped, audited, and default deny):

1. ``create_intent`` (communication.write) -- purpose, subject, template, audience
   filter. The initiating source is checked: inbound email or other untrusted
   content can never originate or authorize an outbound message.
2. ``freeze_audience`` -- resolves recipients from the society roster, applies
   ``recipient_delivery_decision`` (critical suppressions first, then unsubscribe,
   then purpose-specific preference) per recipient, hashes the exact decision set,
   freezes it, and moves the intent to ``awaiting_approval``.
3. ``approve`` -- a *different* person with communication.write approves the exact
   audience hash (maker/checker). A stale hash is refused.
4. ``dispatch`` -- creates delivery attempts only for allowed recipients and hands
   them to a provider-neutral ``OutboundProvider``. No provider credentials exist in
   this repository; production sending needs an owner-approved provider adapter.
5. ``record_delivery_event`` -- idempotent provider feedback. Hard bounces and
   complaints become suppressions that override every later preference.

Required-service purposes (transactional, support, administrative) bypass marketing
unsubscribe by design, so they are narrowly scoped: only fixed membership notice
templates, never a free-form broadcast.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from psycopg.types.json import Jsonb

from .authorization import SocietyCapability
from .crm_diagnostics import register_organization_check
from .domain import (
    REQUIRED_SERVICE_PURPOSES,
    AudienceMember,
    CommunicationState,
    MembershipStatus,
    MessagePurpose,
    PreferenceState,
    SuppressionKind,
    assert_authorization_source,
    audience_snapshot_sha256,
    normalize_email,
    recipient_delivery_decision,
    validate_state_transition,
)
from .postgres_repository import PostgresSocietyCRMRepository
from .society_service import CRMPrincipal, NotFound, SocietyCRMService

REQUIRED_SERVICE_TEMPLATES = frozenset(
    {
        "membership.renewal_reminder",
        "membership.lapsed_notice",
        "membership.payment_receipt",
        "membership.welcome_confirmation",
    }
)
SELF_SERVICE_PURPOSES = frozenset(
    {
        MessagePurpose.MEMBERSHIP_RELATIONSHIP,
        MessagePurpose.COMMUNITY,
        MessagePurpose.FUNDRAISING,
        MessagePurpose.MARKETING,
    }
)
MAX_DELIVERY_ATTEMPTS = 5
RETRY_BACKOFF = timedelta(minutes=15)


@dataclass(frozen=True)
class OutboundMessage:
    organization_id: int
    intent_id: int
    delivery_attempt_id: int
    to_email: str
    subject: str
    template_ref: str | None
    content_sha256: str | None


@dataclass(frozen=True)
class SendResult:
    accepted: bool
    provider_message_ref: str | None = None
    error_code: str | None = None
    retryable: bool = False


class OutboundProvider(Protocol):
    name: str

    def send(self, message: OutboundMessage) -> SendResult: ...


class SocietyCommunicationsService:
    def __init__(self, repository: PostgresSocietyCRMRepository, crm: SocietyCRMService | None = None) -> None:
        self._repo = repository
        self._crm = crm or SocietyCRMService(repository)

    # -- preferences -------------------------------------------------------------------

    def set_preference(
        self,
        principal: CRMPrincipal,
        organization_id: int,
        *,
        constituent_id: int,
        purpose: MessagePurpose,
        state: PreferenceState,
        source_kind: str,
        evidence_ref: str | None = None,
    ) -> dict[str, Any]:
        """Administrator records a preference (e.g. a paper form). Append-only ledger."""
        self._crm._require(organization_id, principal, SocietyCapability.COMMUNICATION_WRITE)
        return self._append_preference(organization_id, constituent_id, purpose, state, source_kind,
                                       evidence_ref, principal.subject)

    def set_my_preference(
        self, principal: CRMPrincipal, organization_id: int, *, purpose: MessagePurpose, subscribed: bool
    ) -> dict[str, Any]:
        """A linked member changes their own consent for one purpose in this society."""
        if purpose not in SELF_SERVICE_PURPOSES:
            raise ValueError("PREFERENCE_PURPOSE_NOT_SELF_SERVICE")
        constituent_id = self._repo.bound_constituent_id(organization_id=organization_id,
                                                         auth_subject=principal.subject)
        if constituent_id is None:
            raise NotFound("PORTAL_NOT_LINKED")
        state = PreferenceState.SUBSCRIBED if subscribed else PreferenceState.UNSUBSCRIBED
        return self._append_preference(organization_id, constituent_id, purpose, state, "member_portal",
                                       None, principal.subject)

    def my_preferences(self, principal: CRMPrincipal, organization_id: int) -> dict[str, str]:
        constituent_id = self._repo.bound_constituent_id(organization_id=organization_id,
                                                         auth_subject=principal.subject)
        if constituent_id is None:
            raise NotFound("PORTAL_NOT_LINKED")
        with self._repo._tenant(organization_id) as cur:
            latest = self._latest_preferences(cur, organization_id, [constituent_id])
        return {
            purpose.value: (latest.get((constituent_id, purpose.value)) or "not_set")
            for purpose in sorted(SELF_SERVICE_PURPOSES, key=lambda p: p.value)
        }

    def _append_preference(
        self, organization_id: int, constituent_id: int, purpose: MessagePurpose, state: PreferenceState,
        source_kind: str, evidence_ref: str | None, actor: str,
    ) -> dict[str, Any]:
        assert_authorization_source(source_kind)
        with self._repo._tenant(organization_id) as cur:
            self._repo._require_constituent(cur, organization_id, constituent_id)
            cur.execute(
                """
                SELECT id, state FROM oc_constituent.communication_preferences
                WHERE organization_id = %s AND constituent_id = %s AND channel = 'email'
                  AND purpose = %s AND topic = '*'
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (organization_id, constituent_id, purpose.value),
            )
            previous = cur.fetchone()
            if previous is not None and previous["state"] == state.value:
                return {"id": previous["id"], "state": state.value, "changed": False}
            cur.execute(
                """
                INSERT INTO oc_constituent.communication_preferences
                    (organization_id, constituent_id, channel, purpose, topic, state, source_kind,
                     evidence_ref, supersedes_id)
                VALUES (%s, %s, 'email', %s, '*', %s, %s, %s, %s)
                RETURNING id, state
                """,
                (organization_id, constituent_id, purpose.value, state.value, source_kind,
                 evidence_ref, previous["id"] if previous else None),
            )
            row = dict(cur.fetchone())
            if state is PreferenceState.UNSUBSCRIBED and purpose in (MessagePurpose.MARKETING,):
                pass  # purpose-specific opt-out; no global suppression
            self._repo._audit(cur, organization_id=organization_id, actor_subject=actor,
                              action="preference.changed", entity_type="constituent",
                              entity_id=str(constituent_id), before_state=dict(previous) if previous else None,
                              after_state=row, metadata={"purpose": purpose.value, "source_kind": source_kind})
            return {**row, "changed": True}

    # -- intents and audiences ---------------------------------------------------------

    def create_intent(
        self,
        principal: CRMPrincipal,
        organization_id: int,
        *,
        purpose: MessagePurpose,
        subject: str,
        template_ref: str | None = None,
        content_sha256: str | None = None,
        statuses: list[MembershipStatus] | None = None,
        level_codes: list[str] | None = None,
        initiating_source: str = "society_admin_console",
    ) -> dict[str, Any]:
        self._crm._require(organization_id, principal, SocietyCapability.COMMUNICATION_WRITE)
        assert_authorization_source(initiating_source)
        if purpose in REQUIRED_SERVICE_PURPOSES and template_ref not in REQUIRED_SERVICE_TEMPLATES:
            raise ValueError("REQUIRED_SERVICE_TEMPLATE_REQUIRED")
        clean_subject = " ".join((subject or "").split())[:300]
        if not clean_subject:
            raise ValueError("COMMUNICATION_SUBJECT_REQUIRED")
        audience = {
            "statuses": sorted({(s.value if isinstance(s, MembershipStatus) else MembershipStatus(s).value)
                                for s in (statuses or [MembershipStatus.ACTIVE, MembershipStatus.GRACE])}),
            "level_codes": sorted({code.strip().lower() for code in (level_codes or [])}),
        }
        with self._repo._tenant(organization_id) as cur:
            cur.execute(
                """
                INSERT INTO oc_communications.intents
                    (organization_id, purpose, initiating_module, initiating_principal, subject, template_ref,
                     content_sha256, audience_definition, required_auth_class, state)
                VALUES (%s, %s, 'society_crm', %s, %s, %s, %s, %s, 'society_communication_write', 'draft')
                RETURNING *
                """,
                (organization_id, purpose.value, principal.subject, clean_subject, template_ref, content_sha256,
                 Jsonb(audience)),
            )
            intent = dict(cur.fetchone())
            self._repo._audit(cur, organization_id=organization_id, actor_subject=principal.subject,
                              action="communication.created", entity_type="communication",
                              entity_id=str(intent["id"]), before_state=None, after_state=intent)
            return intent

    def freeze_audience(self, principal: CRMPrincipal, organization_id: int, intent_id: int) -> dict[str, Any]:
        self._crm._require(organization_id, principal, SocietyCapability.COMMUNICATION_WRITE)
        with self._repo._tenant(organization_id) as cur:
            intent = self._lock_intent(cur, organization_id, intent_id)
            state = CommunicationState(intent["state"])
            validate_state_transition(state, CommunicationState.AWAITING_APPROVAL, audience_frozen=True)
            purpose = MessagePurpose(intent["purpose"])
            audience = intent["audience_definition"] or {}
            cur.execute(
                """
                SELECT m.constituent_id, e.normalized_email
                FROM oc_constituent.memberships m
                JOIN oc_constituent.email_addresses e
                  ON e.organization_id = m.organization_id AND e.constituent_id = m.constituent_id AND e.is_primary
                WHERE m.organization_id = %s AND m.status = ANY(%s)
                  AND (cardinality(%s::text[]) = 0 OR m.level_code = ANY(%s::text[]))
                ORDER BY m.constituent_id
                """,
                (organization_id, audience.get("statuses") or ["active", "grace"],
                 audience.get("level_codes") or [], audience.get("level_codes") or []),
            )
            recipients = [(int(r["constituent_id"]), r["normalized_email"]) for r in cur.fetchall()]
            if not recipients:
                raise ValueError("AUDIENCE_REQUIRED")
            ids = [cid for cid, _ in recipients]
            preferences = self._latest_preferences(cur, organization_id, ids, purpose=purpose)
            suppressions = self._active_suppressions(cur, organization_id, recipients)
            members: list[AudienceMember] = []
            for constituent_id, email in recipients:
                preference_state = preferences.get((constituent_id, purpose.value))
                allowed, reason = recipient_delivery_decision(
                    purpose=purpose,
                    preference=PreferenceState(preference_state) if preference_state else None,
                    suppressions=suppressions.get((constituent_id, email), frozenset()),
                )
                members.append(AudienceMember(constituent_id, email, allowed, reason))
            digest = audience_snapshot_sha256(members)
            cur.execute(
                "INSERT INTO oc_communications.audience_snapshots (intent_id, organization_id) VALUES (%s, %s) "
                "RETURNING id",
                (intent_id, organization_id),
            )
            snapshot_id = int(cur.fetchone()["id"])
            for member in members:
                cur.execute(
                    """
                    INSERT INTO oc_communications.audience_members
                        (snapshot_id, organization_id, constituent_id, normalized_email, allowed, decision_reason)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (snapshot_id, organization_id, member.constituent_id, member.normalized_email, member.allowed,
                     member.decision_reason),
                )
            cur.execute(
                "UPDATE oc_communications.audience_snapshots SET audience_sha256 = %s, frozen_at = NOW() "
                "WHERE organization_id = %s AND id = %s",
                (digest, organization_id, snapshot_id),
            )
            cur.execute(
                "UPDATE oc_communications.intents SET state = 'awaiting_approval', updated_at = NOW() "
                "WHERE organization_id = %s AND id = %s",
                (organization_id, intent_id),
            )
            summary = {
                "intent_id": intent_id,
                "audience_sha256": digest,
                "recipients": len(members),
                "allowed": sum(1 for m in members if m.allowed),
                "excluded_by_reason": _count_reasons(m.decision_reason for m in members if not m.allowed),
            }
            self._repo._audit(cur, organization_id=organization_id, actor_subject=principal.subject,
                              action="communication.audience_frozen", entity_type="communication",
                              entity_id=str(intent_id), before_state=None, after_state=None, metadata=summary)
            return summary

    def approve(
        self, principal: CRMPrincipal, organization_id: int, intent_id: int, *, audience_sha256: str,
        rationale: str | None = None, approval_source: str = "society_admin_console",
    ) -> dict[str, Any]:
        self._crm._require(organization_id, principal, SocietyCapability.COMMUNICATION_WRITE)
        assert_authorization_source(approval_source)
        with self._repo._tenant(organization_id) as cur:
            intent = self._lock_intent(cur, organization_id, intent_id)
            snapshot = self._snapshot(cur, organization_id, intent_id)
            if snapshot is None or snapshot["frozen_at"] is None:
                raise ValueError("FROZEN_AUDIENCE_REQUIRED")
            if snapshot["audience_sha256"] != audience_sha256:
                raise ValueError("AUDIENCE_HASH_MISMATCH")
            if intent["initiating_principal"] == principal.subject:
                raise ValueError("APPROVER_MUST_DIFFER_FROM_CREATOR")
            validate_state_transition(CommunicationState(intent["state"]), CommunicationState.APPROVED,
                                      audience_frozen=True, approval_recorded=True)
            cur.execute(
                """
                INSERT INTO oc_communications.approval_events
                    (intent_id, organization_id, action, principal, auth_class, audience_sha256, rationale)
                VALUES (%s, %s, 'approved', %s, 'society_communication_write', %s, %s)
                RETURNING id
                """,
                (intent_id, organization_id, principal.subject, audience_sha256, (rationale or "")[:500] or None),
            )
            approval_id = int(cur.fetchone()["id"])
            cur.execute(
                "UPDATE oc_communications.intents SET state = 'approved', updated_at = NOW() "
                "WHERE organization_id = %s AND id = %s",
                (organization_id, intent_id),
            )
            self._repo._audit(cur, organization_id=organization_id, actor_subject=principal.subject,
                              action="communication.approved", entity_type="communication",
                              entity_id=str(intent_id), before_state=None, after_state=None,
                              metadata={"approval_event_id": approval_id, "audience_sha256": audience_sha256})
            return {"intent_id": intent_id, "state": "approved", "approval_event_id": approval_id}

    # -- dispatch and delivery -----------------------------------------------------------

    def dispatch(
        self, principal: CRMPrincipal, organization_id: int, intent_id: int, provider: OutboundProvider,
        *, as_of: datetime | None = None,
    ) -> dict[str, Any]:
        self._crm._require(organization_id, principal, SocietyCapability.COMMUNICATION_WRITE)
        now = as_of or datetime.now(timezone.utc)
        with self._repo._tenant(organization_id) as cur:
            intent = self._lock_intent(cur, organization_id, intent_id)
            current = CommunicationState(intent["state"])
            if current is CommunicationState.APPROVED:
                validate_state_transition(current, CommunicationState.SENDING, audience_frozen=True)
                cur.execute(
                    "UPDATE oc_communications.intents SET state = 'sending', updated_at = NOW() "
                    "WHERE organization_id = %s AND id = %s",
                    (organization_id, intent_id),
                )
            elif current not in (CommunicationState.SENDING, CommunicationState.PARTIALLY_FAILED):
                raise ValueError(f"INVALID_COMMUNICATION_TRANSITION:{current.value}->sending")
            snapshot = self._snapshot(cur, organization_id, intent_id)
            cur.execute(
                """
                INSERT INTO oc_communications.delivery_attempts
                    (organization_id, intent_id, audience_member_id, normalized_email, provider)
                SELECT %s, %s, am.id, am.normalized_email, %s
                FROM oc_communications.audience_members am
                WHERE am.organization_id = %s AND am.snapshot_id = %s AND am.allowed
                ON CONFLICT (organization_id, intent_id, audience_member_id) DO NOTHING
                """,
                (organization_id, intent_id, provider.name, organization_id, snapshot["id"]),
            )
            cur.execute(
                """
                SELECT * FROM oc_communications.delivery_attempts
                WHERE organization_id = %s AND intent_id = %s
                  AND (status = 'queued' OR (status IN ('failed', 'deferred') AND attempts < %s
                       AND (next_attempt_at IS NULL OR next_attempt_at <= %s)))
                ORDER BY id FOR UPDATE
                """,
                (organization_id, intent_id, MAX_DELIVERY_ATTEMPTS, now),
            )
            pending = [dict(row) for row in cur.fetchall()]
            # Consent can change between freeze and send (or before a retry): re-run the
            # full decision per recipient with current preferences and suppressions.
            purpose = MessagePurpose(intent["purpose"])
            owners: dict[int, int] = {}
            if pending:
                cur.execute(
                    "SELECT id, constituent_id FROM oc_communications.audience_members "
                    "WHERE organization_id = %s AND id = ANY(%s)",
                    (organization_id, [a["audience_member_id"] for a in pending]),
                )
                owners = {int(r["id"]): int(r["constituent_id"]) for r in cur.fetchall()}
            recipients = [(owners[a["audience_member_id"]], a["normalized_email"]) for a in pending]
            current_preferences = self._latest_preferences(
                cur, organization_id, [cid for cid, _ in recipients], purpose=purpose
            ) if recipients else {}
            current_suppressions = self._active_suppressions(cur, organization_id, recipients) if recipients else {}
            for attempt in pending:
                recipient = (owners[attempt["audience_member_id"]], attempt["normalized_email"])
                preference_state = current_preferences.get((recipient[0], purpose.value))
                still_allowed, _reason = recipient_delivery_decision(
                    purpose=purpose,
                    preference=PreferenceState(preference_state) if preference_state else None,
                    suppressions=current_suppressions.get(recipient, frozenset()),
                )
                if not still_allowed:
                    self._update_attempt(cur, organization_id, attempt["id"], "suppressed", attempt["attempts"],
                                         None, "SUPPRESSED_AFTER_FREEZE", None)
                    continue
                result = provider.send(OutboundMessage(
                    organization_id=organization_id, intent_id=intent_id, delivery_attempt_id=attempt["id"],
                    to_email=attempt["normalized_email"], subject=intent["subject"],
                    template_ref=intent["template_ref"], content_sha256=intent["content_sha256"],
                ))
                attempts = attempt["attempts"] + 1
                if result.accepted:
                    self._update_attempt(cur, organization_id, attempt["id"], "sent", attempts,
                                         result.provider_message_ref, None, None)
                else:
                    retry_at = now + RETRY_BACKOFF * attempts if result.retryable else None
                    self._update_attempt(cur, organization_id, attempt["id"],
                                         "deferred" if result.retryable else "failed", attempts, None,
                                         result.error_code or "PROVIDER_REJECTED", retry_at)
            status = self._status_counts(cur, organization_id, intent_id)
            outstanding = status.get("queued", 0) + status.get("deferred", 0)
            final = None
            if outstanding == 0:
                final = CommunicationState.PARTIALLY_FAILED if status.get("failed", 0) else CommunicationState.COMPLETED
                cur.execute(
                    "UPDATE oc_communications.intents SET state = %s, updated_at = NOW() "
                    "WHERE organization_id = %s AND id = %s",
                    (final.value, organization_id, intent_id),
                )
            self._repo._audit(cur, organization_id=organization_id, actor_subject=principal.subject,
                              action="communication.dispatched", entity_type="communication",
                              entity_id=str(intent_id), before_state=None, after_state=None,
                              metadata={"provider": provider.name, "status_counts": status,
                                        "state": final.value if final else "sending"})
            return {"intent_id": intent_id, "state": final.value if final else "sending", "status_counts": status}

    def record_delivery_event(
        self, organization_id: int, *, provider: str, provider_event_id: str, event_type: str, email: str,
        provider_message_ref: str | None = None,
    ) -> dict[str, Any]:
        """Provider feedback (authenticated by the provider adapter before this call). Idempotent."""
        normalized = normalize_email(email)
        actor = f"system:{provider}-delivery-webhook"
        with self._repo._tenant(organization_id) as cur:
            attempt = None
            if provider_message_ref:
                cur.execute(
                    "SELECT * FROM oc_communications.delivery_attempts WHERE organization_id = %s "
                    "AND provider = %s AND provider_message_ref = %s FOR UPDATE",
                    (organization_id, provider, provider_message_ref),
                )
                attempt = cur.fetchone()
            cur.execute(
                """
                INSERT INTO oc_communications.delivery_events
                    (organization_id, provider, provider_event_id, delivery_attempt_id, event_type, normalized_email)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (provider, provider_event_id) DO NOTHING
                RETURNING id
                """,
                (organization_id, provider, provider_event_id, attempt["id"] if attempt else None, event_type,
                 normalized),
            )
            if cur.fetchone() is None:
                return {"status": "duplicate"}
            suppression = {
                "hard_bounce": SuppressionKind.HARD_BOUNCE,
                "complaint": SuppressionKind.COMPLAINT,
                "unsubscribe": SuppressionKind.UNSUBSCRIBE,
            }.get(event_type)
            if suppression is not None:
                cur.execute(
                    """
                    SELECT e.constituent_id FROM oc_constituent.email_addresses e
                    WHERE e.organization_id = %s AND e.normalized_email = %s ORDER BY e.constituent_id LIMIT 1
                    """,
                    (organization_id, normalized),
                )
                owner = cur.fetchone()
                cur.execute(
                    """
                    INSERT INTO oc_constituent.suppressions
                        (organization_id, constituent_id, normalized_email, kind, reason, source_kind)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (organization_id, owner["constituent_id"] if owner else None, normalized, suppression.value,
                     f"{provider}:{event_type}", f"{provider}_delivery_event"),
                )
            if attempt is not None:
                new_status = {"delivered": "delivered", "soft_bounce": "deferred", "hard_bounce": "bounced",
                              "complaint": "complained"}.get(event_type, attempt["status"])
                self._update_attempt(cur, organization_id, attempt["id"], new_status, attempt["attempts"],
                                     attempt["provider_message_ref"],
                                     "SOFT_BOUNCE" if event_type == "soft_bounce" else attempt["last_error_code"],
                                     None)
            self._repo._audit(cur, organization_id=organization_id, actor_subject=actor,
                              action="communication.delivery_event", entity_type="delivery",
                              entity_id=provider_event_id, before_state=None, after_state=None,
                              metadata={"event_type": event_type, "suppression": suppression.value if suppression else None})
            return {"status": "recorded", "suppression": suppression.value if suppression else None}

    def delivery_status(self, principal: CRMPrincipal, organization_id: int, intent_id: int) -> dict[str, Any]:
        self._crm._require(organization_id, principal, SocietyCapability.COMMUNICATION_READ)
        with self._repo._tenant(organization_id) as cur:
            intent = self._lock_intent(cur, organization_id, intent_id, lock=False)
            counts = self._status_counts(cur, organization_id, intent_id)
            cur.execute(
                """
                SELECT last_error_code, count(*) AS n FROM oc_communications.delivery_attempts
                WHERE organization_id = %s AND intent_id = %s AND last_error_code IS NOT NULL
                GROUP BY last_error_code ORDER BY 2 DESC
                """,
                (organization_id, intent_id),
            )
            errors = {row["last_error_code"]: int(row["n"]) for row in cur.fetchall()}
            return {"intent_id": intent_id, "state": intent["state"], "purpose": intent["purpose"],
                    "status_counts": counts, "errors": errors}

    # -- internals -----------------------------------------------------------------------

    @staticmethod
    def _lock_intent(cur, organization_id: int, intent_id: int, *, lock: bool = True) -> dict[str, Any]:
        cur.execute(
            "SELECT * FROM oc_communications.intents WHERE organization_id = %s AND id = %s"
            + (" FOR UPDATE" if lock else ""),
            (organization_id, intent_id),
        )
        row = cur.fetchone()
        if row is None:
            raise NotFound("COMMUNICATION_NOT_FOUND")
        return dict(row)

    @staticmethod
    def _snapshot(cur, organization_id: int, intent_id: int) -> dict[str, Any] | None:
        cur.execute(
            "SELECT * FROM oc_communications.audience_snapshots WHERE organization_id = %s AND intent_id = %s",
            (organization_id, intent_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _latest_preferences(cur, organization_id: int, constituent_ids: list[int],
                            purpose: MessagePurpose | None = None) -> dict[tuple[int, str], str]:
        cur.execute(
            """
            SELECT DISTINCT ON (constituent_id, purpose) constituent_id, purpose, state
            FROM oc_constituent.communication_preferences
            WHERE organization_id = %s AND constituent_id = ANY(%s) AND channel = 'email' AND topic = '*'
              AND (%s::text IS NULL OR purpose = %s::text)
            ORDER BY constituent_id, purpose, created_at DESC, id DESC
            """,
            (organization_id, constituent_ids, purpose.value if purpose else None,
             purpose.value if purpose else None),
        )
        return {(int(r["constituent_id"]), r["purpose"]): r["state"] for r in cur.fetchall()}

    @staticmethod
    def _active_suppressions(cur, organization_id: int, recipients: list[tuple[int, str]]):
        ids = [cid for cid, _ in recipients]
        emails = [email for _, email in recipients]
        cur.execute(
            """
            SELECT constituent_id, normalized_email, kind FROM oc_constituent.suppressions
            WHERE organization_id = %s AND lifted_at IS NULL
              AND (constituent_id = ANY(%s) OR normalized_email = ANY(%s))
            """,
            (organization_id, ids, emails),
        )
        rows = cur.fetchall()
        result: dict[tuple[int, str], frozenset[SuppressionKind]] = {}
        for cid, email in recipients:
            kinds = {SuppressionKind(r["kind"]) for r in rows
                     if r["constituent_id"] == cid or r["normalized_email"] == email}
            result[(cid, email)] = frozenset(kinds)
        return result

    @staticmethod
    def _status_counts(cur, organization_id: int, intent_id: int) -> dict[str, int]:
        cur.execute(
            "SELECT status, count(*) AS n FROM oc_communications.delivery_attempts "
            "WHERE organization_id = %s AND intent_id = %s GROUP BY status",
            (organization_id, intent_id),
        )
        return {row["status"]: int(row["n"]) for row in cur.fetchall()}

    @staticmethod
    def _update_attempt(cur, organization_id: int, attempt_id: int, status: str, attempts: int,
                        provider_ref: str | None, error_code: str | None, next_attempt_at: datetime | None) -> None:
        cur.execute(
            """
            UPDATE oc_communications.delivery_attempts
            SET status = %s, attempts = %s, provider_message_ref = COALESCE(%s, provider_message_ref),
                last_error_code = %s, next_attempt_at = %s, updated_at = NOW()
            WHERE organization_id = %s AND id = %s
            """,
            (status, attempts, provider_ref, error_code, next_attempt_at, organization_id, attempt_id),
        )


def _count_reasons(reasons) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reason in reasons:
        counts[reason] = counts.get(reason, 0) + 1
    return counts


@register_organization_check
def communication_delivery_check(repo: PostgresSocietyCRMRepository, organization_id: int) -> list[dict[str, Any]]:
    with repo._tenant(organization_id) as cur:
        cur.execute(
            """
            SELECT count(*) FILTER (WHERE status = 'failed') AS failed,
                   count(*) FILTER (WHERE status IN ('bounced', 'complained')) AS bounced
            FROM oc_communications.delivery_attempts WHERE organization_id = %s
            """,
            (organization_id,),
        )
        row = cur.fetchone()
        cur.execute(
            "SELECT count(*) AS n FROM oc_communications.intents WHERE organization_id = %s "
            "AND state IN ('sending', 'partially_failed') AND updated_at < NOW() - interval '6 hours'",
            (organization_id,),
        )
        stuck = int(cur.fetchone()["n"])
    results = []
    failed = int(row["failed"])
    results.append(
        {"check": "email_delivery", "status": "warning",
         "message": f"{failed} email(s) could not be delivered after retries.",
         "action": "Open the message's delivery report; correct the addresses or contact the members another way.",
         "count": failed}
        if failed else
        {"check": "email_delivery", "status": "ok", "message": "No failed email deliveries.", "action": ""}
    )
    if stuck:
        results.append({"check": "email_sending_stuck", "status": "warning",
                        "message": f"{stuck} message(s) have been sending for more than 6 hours.",
                        "action": "Retry sending from the message page; if it keeps stalling, check the email provider status.",
                        "count": stuck})
    return results
