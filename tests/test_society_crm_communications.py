"""Society communications: consent, suppression, approval binding, delivery (PostgreSQL)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

from app.constituent_platform.authorization import SocietyAccessDenied, SocietyRole
from app.constituent_platform.crm_diagnostics import organization_diagnostics
from app.constituent_platform.crm_migrations import apply_crm_migrations
from app.constituent_platform.domain import MessagePurpose, PreferenceState
from app.constituent_platform.member_portal import MemberPortalService
from app.constituent_platform.postgres_repository import PostgresSocietyCRMRepository
from app.constituent_platform.society_communications import (
    OutboundMessage,
    SendResult,
    SocietyCommunicationsService,
)
from app.constituent_platform.society_service import CRMPrincipal, SocietyCRMService

pytestmark = pytest.mark.requires_postgres("DATABASE_URL", psql=False)

OPERATOR = CRMPrincipal("owner:platform-operator", platform_operator=True)
T0 = datetime(2026, 4, 1, tzinfo=timezone.utc)


class RecordingProvider:
    """Provider-neutral test double: records sends, fails configured addresses."""

    name = "recording"

    def __init__(self, *, fail: set[str] | None = None, retry: set[str] | None = None) -> None:
        self.sent: list[OutboundMessage] = []
        self.fail = fail or set()
        self.retry = retry or set()

    def send(self, message: OutboundMessage) -> SendResult:
        if message.to_email in self.fail:
            return SendResult(False, error_code="MAILBOX_REJECTED")
        if message.to_email in self.retry:
            self.retry.discard(message.to_email)
            return SendResult(False, error_code="PROVIDER_TIMEOUT", retryable=True)
        self.sent.append(message)
        return SendResult(True, provider_message_ref=f"msg-{uuid.uuid4().hex}")


@pytest.fixture(scope="module")
def dsn() -> str:
    value = os.environ["DATABASE_URL"]
    apply_crm_migrations(value, twice=True)
    return value


@pytest.fixture()
def repo(dsn: str) -> PostgresSocietyCRMRepository:
    return PostgresSocietyCRMRepository(dsn)


@pytest.fixture()
def crm(repo: PostgresSocietyCRMRepository) -> SocietyCRMService:
    return SocietyCRMService(repo)


@pytest.fixture()
def comms(repo: PostgresSocietyCRMRepository, crm: SocietyCRMService) -> SocietyCommunicationsService:
    return SocietyCommunicationsService(repo, crm)


def _society(crm: SocietyCRMService, repo: PostgresSocietyCRMRepository):
    org = crm.create_organization(OPERATOR, slug=f"t-{uuid.uuid4().hex[:12]}", display_name="Orchid Society")
    admin_subject = f"supabase:{uuid.uuid4()}"
    crm.bootstrap_admin(OPERATOR, org["id"], display_name="Pat Admin", auth_subject=admin_subject)
    admin = CRMPrincipal(admin_subject)
    crm.create_level(admin, org["id"], code="individual", display_name="Individual")
    # A second person (communications manager) so maker and checker differ.
    person = repo.create_person(organization_id=org["id"], display_name="Casey Comms", actor_subject=admin_subject)
    comms_subject = f"supabase:{uuid.uuid4()}"
    crm.bind_identity(admin, org["id"], constituent_id=person["id"], auth_subject=comms_subject)
    crm.grant_role(admin, org["id"], constituent_id=person["id"], role=SocietyRole.COMMUNICATIONS_MANAGER)
    return org["id"], admin, CRMPrincipal(comms_subject)


def _member(crm: SocietyCRMService, org: int, admin: CRMPrincipal, email: str) -> dict:
    member = crm.create_member(admin, org, display_name=email.split("@")[0], email=email, level_code="individual")
    crm.renew(admin, org, member["membership_id"], renewal_key=f"k-{uuid.uuid4()}", as_of=T0)
    return crm.get_member(admin, org, member["membership_id"])


def _audience(dsn: str, org: int, intent_id: int) -> dict[str, tuple[bool, str]]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT am.normalized_email, am.allowed, am.decision_reason FROM oc_communications.audience_members am "
            "JOIN oc_communications.audience_snapshots s ON s.id = am.snapshot_id "
            "WHERE s.organization_id = %s AND s.intent_id = %s",
            (org, intent_id),
        ).fetchall()
    return {email: (allowed, reason) for email, allowed, reason in rows}


def test_consent_and_suppression_decide_the_frozen_audience(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, comms: SocietyCommunicationsService, dsn: str
) -> None:
    org, admin, manager = _society(crm, repo)
    yes = _member(crm, org, admin, f"yes-{uuid.uuid4().hex[:6]}@example.org")
    unsub = _member(crm, org, admin, f"unsub-{uuid.uuid4().hex[:6]}@example.org")
    bounced = _member(crm, org, admin, f"bounce-{uuid.uuid4().hex[:6]}@example.org")
    silent = _member(crm, org, admin, f"silent-{uuid.uuid4().hex[:6]}@example.org")
    for member in (yes, unsub, bounced):
        comms.set_preference(manager, org, constituent_id=member["constituent_id"], purpose=MessagePurpose.COMMUNITY,
                             state=PreferenceState.SUBSCRIBED, source_kind="paper_form")
    comms.set_preference(manager, org, constituent_id=unsub["constituent_id"], purpose=MessagePurpose.COMMUNITY,
                         state=PreferenceState.UNSUBSCRIBED, source_kind="member_request")
    # A hard bounce beats an explicit subscription.
    assert comms.record_delivery_event(org, provider="recording", provider_event_id=f"ev-{uuid.uuid4()}",
                                       event_type="hard_bounce", email=bounced["primary_email"])["suppression"] == "hard_bounce"

    intent = comms.create_intent(manager, org, purpose=MessagePurpose.COMMUNITY, subject="Spring show")
    frozen = comms.freeze_audience(manager, org, intent["id"])
    audience = _audience(dsn, org, intent["id"])
    assert audience[yes["primary_email"]] == (True, "subscribed")
    assert audience[unsub["primary_email"]] == (False, "unsubscribed")
    assert audience[bounced["primary_email"]] == (False, "critical_suppression")
    assert audience[silent["primary_email"]] == (False, "no_affirmative_preference")
    assert frozen["allowed"] == 1

    # Maker cannot approve their own broadcast; a stale hash is refused.
    with pytest.raises(ValueError, match="APPROVER_MUST_DIFFER_FROM_CREATOR"):
        comms.approve(manager, org, intent["id"], audience_sha256=frozen["audience_sha256"])
    with pytest.raises(ValueError, match="AUDIENCE_HASH_MISMATCH"):
        comms.approve(admin, org, intent["id"], audience_sha256="0" * 64)
    # The frozen audience is immutable even to the table owner.
    with psycopg.connect(dsn) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="FROZEN_AUDIENCE_IMMUTABLE"):
            conn.execute(
                "UPDATE oc_communications.audience_members SET allowed = TRUE WHERE normalized_email = %s",
                (unsub["primary_email"],),
            )
    comms.approve(admin, org, intent["id"], audience_sha256=frozen["audience_sha256"], rationale="Reviewed")

    provider = RecordingProvider()
    result = comms.dispatch(admin, org, intent["id"], provider)
    assert [m.to_email for m in provider.sent] == [yes["primary_email"]]
    assert result["state"] == "completed"
    # A completed intent cannot be dispatched again, so nothing is ever sent twice.
    with pytest.raises(ValueError, match="INVALID_COMMUNICATION_TRANSITION:completed->sending"):
        comms.dispatch(admin, org, intent["id"], provider)
    assert len(provider.sent) == 1
    status = comms.delivery_status(manager, org, intent["id"])
    assert status["status_counts"] == {"sent": 1}


def test_suppression_recorded_after_freeze_still_wins_and_retries_are_bounded(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, comms: SocietyCommunicationsService
) -> None:
    org, admin, manager = _society(crm, repo)
    emails = [f"m{i}-{uuid.uuid4().hex[:6]}@example.org" for i in range(3)]
    members = [_member(crm, org, admin, email) for email in emails]
    for member in members:
        comms.set_preference(manager, org, constituent_id=member["constituent_id"],
                             purpose=MessagePurpose.MARKETING, state=PreferenceState.SUBSCRIBED,
                             source_kind="paper_form")
    intent = comms.create_intent(manager, org, purpose=MessagePurpose.MARKETING, subject="Plant sale")
    frozen = comms.freeze_audience(manager, org, intent["id"])
    comms.approve(admin, org, intent["id"], audience_sha256=frozen["audience_sha256"])
    comms.record_delivery_event(org, provider="recording", provider_event_id=f"ev-{uuid.uuid4()}",
                                event_type="complaint", email=emails[0])

    provider = RecordingProvider(fail={emails[1]}, retry={emails[2]})
    first = comms.dispatch(admin, org, intent["id"], provider, as_of=T0)
    assert first["state"] == "sending"
    assert first["status_counts"] == {"suppressed": 1, "failed": 1, "deferred": 1}
    second = comms.dispatch(admin, org, intent["id"], provider, as_of=T0.replace(hour=5))
    assert [m.to_email for m in provider.sent] == [emails[2]]
    assert second["state"] == "partially_failed"
    status = comms.delivery_status(manager, org, intent["id"])
    assert status["errors"]["MAILBOX_REJECTED"] == 1 and status["errors"]["SUPPRESSED_AFTER_FREEZE"] == 1

    checks = {c["check"]: c for c in organization_diagnostics(crm, admin, org)}
    assert checks["email_delivery"]["status"] == "warning" and checks["email_delivery"]["count"] == 1


def test_required_service_messages_are_narrowly_scoped(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, comms: SocietyCommunicationsService, dsn: str
) -> None:
    org, admin, manager = _society(crm, repo)
    unsub = _member(crm, org, admin, f"u-{uuid.uuid4().hex[:6]}@example.org")
    bounced = _member(crm, org, admin, f"b-{uuid.uuid4().hex[:6]}@example.org")
    comms.record_delivery_event(org, provider="recording", provider_event_id=f"ev-{uuid.uuid4()}",
                                event_type="unsubscribe", email=unsub["primary_email"])
    comms.record_delivery_event(org, provider="recording", provider_event_id=f"ev-{uuid.uuid4()}",
                                event_type="hard_bounce", email=bounced["primary_email"])

    # A "transactional" free-form broadcast is refused outright.
    with pytest.raises(ValueError, match="REQUIRED_SERVICE_TEMPLATE_REQUIRED"):
        comms.create_intent(manager, org, purpose=MessagePurpose.TRANSACTIONAL, subject="Big news!")
    with pytest.raises(ValueError, match="REQUIRED_SERVICE_TEMPLATE_REQUIRED"):
        comms.create_intent(manager, org, purpose=MessagePurpose.ADMINISTRATIVE, subject="Gala",
                            template_ref="marketing.gala")
    notice = comms.create_intent(manager, org, purpose=MessagePurpose.ADMINISTRATIVE, subject="Renewal due",
                                 template_ref="membership.renewal_reminder")
    comms.freeze_audience(manager, org, notice["id"])
    audience = _audience(dsn, org, notice["id"])
    # Required notices reach unsubscribed members, but never a hard-bounced address.
    assert audience[unsub["primary_email"]] == (True, "required_service_purpose")
    assert audience[bounced["primary_email"]] == (False, "critical_suppression")


def test_inbound_content_can_never_authorize_outbound(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, comms: SocietyCommunicationsService
) -> None:
    org, admin, manager = _society(crm, repo)
    member = _member(crm, org, admin, f"i-{uuid.uuid4().hex[:6]}@example.org")
    for source in ("inbound_email", "email_gateway", "untrusted_content"):
        with pytest.raises(ValueError, match="UNTRUSTED_OUTBOUND_AUTHORIZATION_SOURCE"):
            comms.create_intent(manager, org, purpose=MessagePurpose.COMMUNITY, subject="Fwd: please send",
                                initiating_source=source)
        with pytest.raises(ValueError, match="UNTRUSTED_OUTBOUND_AUTHORIZATION_SOURCE"):
            comms.set_preference(manager, org, constituent_id=member["constituent_id"],
                                 purpose=MessagePurpose.COMMUNITY, state=PreferenceState.SUBSCRIBED,
                                 source_kind=source)
    comms.set_preference(manager, org, constituent_id=member["constituent_id"], purpose=MessagePurpose.COMMUNITY,
                         state=PreferenceState.SUBSCRIBED, source_kind="paper_form")
    intent = comms.create_intent(manager, org, purpose=MessagePurpose.COMMUNITY, subject="Meeting")
    frozen = comms.freeze_audience(manager, org, intent["id"])
    with pytest.raises(ValueError, match="UNTRUSTED_OUTBOUND_AUTHORIZATION_SOURCE"):
        comms.approve(admin, org, intent["id"], audience_sha256=frozen["audience_sha256"],
                      approval_source="inbound_email")
    # Unapproved intents cannot be dispatched.
    with pytest.raises(ValueError, match="INVALID_COMMUNICATION_TRANSITION"):
        comms.dispatch(admin, org, intent["id"], RecordingProvider())


def test_communication_authorization_and_tenant_isolation(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, comms: SocietyCommunicationsService
) -> None:
    org_a, admin_a, manager_a = _society(crm, repo)
    org_b, admin_b, manager_b = _society(crm, repo)
    shared = f"shared-{uuid.uuid4().hex[:6]}@example.org"
    member_a = _member(crm, org_a, admin_a, shared)
    member_b = _member(crm, org_b, admin_b, shared)
    # A bounce reported in Society B does not silently alter Society A's data.
    comms.record_delivery_event(org_b, provider="recording", provider_event_id=f"ev-{uuid.uuid4()}",
                                event_type="hard_bounce", email=shared)
    comms.set_preference(manager_a, org_a, constituent_id=member_a["constituent_id"],
                         purpose=MessagePurpose.COMMUNITY, state=PreferenceState.SUBSCRIBED, source_kind="paper_form")
    intent_a = comms.create_intent(manager_a, org_a, purpose=MessagePurpose.COMMUNITY, subject="A news")
    assert comms.freeze_audience(manager_a, org_a, intent_a["id"])["allowed"] == 1

    with pytest.raises(SocietyAccessDenied):
        comms.create_intent(manager_a, org_b, purpose=MessagePurpose.COMMUNITY, subject="Spam B")
    with pytest.raises(SocietyAccessDenied):
        comms.delivery_status(manager_a, org_b, intent_a["id"])
    with pytest.raises(LookupError):
        comms.set_preference(manager_a, org_a, constituent_id=member_b["constituent_id"],
                             purpose=MessagePurpose.COMMUNITY, state=PreferenceState.SUBSCRIBED,
                             source_kind="paper_form")
    viewer_person = repo.create_person(organization_id=org_a, display_name="Val Viewer", actor_subject=admin_a.subject)
    viewer_subject = f"supabase:{uuid.uuid4()}"
    crm.bind_identity(admin_a, org_a, constituent_id=viewer_person["id"], auth_subject=viewer_subject)
    crm.grant_role(admin_a, org_a, constituent_id=viewer_person["id"], role=SocietyRole.VIEWER)
    with pytest.raises(SocietyAccessDenied):
        comms.create_intent(CRMPrincipal(viewer_subject), org_a, purpose=MessagePurpose.COMMUNITY, subject="x")


def test_member_manages_own_preferences_through_the_portal(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, comms: SocietyCommunicationsService
) -> None:
    org, admin, manager = _society(crm, repo)
    member = _member(crm, org, admin, f"p-{uuid.uuid4().hex[:6]}@example.org")
    portal = MemberPortalService(repo, crm)
    me = CRMPrincipal(f"supabase:{uuid.uuid4()}")
    portal.redeem_invite(me, org, portal.issue_invite(admin, org, member["membership_id"])["code"])

    assert comms.my_preferences(me, org)["community"] == "not_set"
    assert comms.set_my_preference(me, org, purpose=MessagePurpose.COMMUNITY, subscribed=True)["changed"] is True
    assert comms.set_my_preference(me, org, purpose=MessagePurpose.COMMUNITY, subscribed=True)["changed"] is False
    comms.set_my_preference(me, org, purpose=MessagePurpose.COMMUNITY, subscribed=False)
    assert comms.my_preferences(me, org)["community"] == "unsubscribed"
    with pytest.raises(ValueError, match="PREFERENCE_PURPOSE_NOT_SELF_SERVICE"):
        comms.set_my_preference(me, org, purpose=MessagePurpose.TRANSACTIONAL, subscribed=False)

    intent = comms.create_intent(manager, org, purpose=MessagePurpose.COMMUNITY, subject="Hello")
    assert comms.freeze_audience(manager, org, intent["id"])["allowed"] == 0
    history = [e for e in crm.audit_events(admin, org) if e["action"] == "preference.changed"]
    assert len(history) == 2 and {e["actor_subject"] for e in history} == {me.subject}
