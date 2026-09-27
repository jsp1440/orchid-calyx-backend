"""Society CRM money: payment ledger, donations, refunds, and Stripe webhooks on PostgreSQL.

Every test creates its own synthetic organizations and provider ids (uuid-based), so
the suite is re-runnable against a persistent database. Webhook payloads are
synthetic and signed with a test secret; nothing talks to Stripe.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.constituent_platform.authorization import SocietyAccessDenied, SocietyRole
from app.constituent_platform.payment_routes import build_payment_webhook_router
from app.constituent_platform.payments import (
    PaymentError,
    PaymentLedgerService,
    StripeWebhookAdapter,
    WebhookSignatureError,
    contains_card_like_number,
)
from app.constituent_platform.postgres_repository import PostgresSocietyCRMRepository
from app.constituent_platform.society_service import CRMPrincipal, NotFound, SocietyCRMService
from app.constituent_platform.tenant_db import tenant_transaction

pytestmark = pytest.mark.requires_postgres("DATABASE_URL", psql=False)

MIGRATIONS = (
    "migrations/20260823_oc_constituent_communications_foundation.sql",
    "migrations/20260926_society_crm_p0_core.sql",
    "migrations/20260927_society_crm_p1_tenant_isolation.sql",
    "migrations/20260928_society_crm_money.sql",
)
MONEY_TABLES = ("payments", "payment_events", "refunds", "donations", "donation_receipt_counters",
                "provider_webhook_events")
T0 = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
NOW = T0.timestamp()
SECRET = "whsec_test_" + "a1b2c3d4" * 4
OPERATOR = CRMPrincipal("owner:platform-operator", platform_operator=True)


def _apply_migrations(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        for path in MIGRATIONS:
            conn.execute(Path(path).read_text(encoding="utf-8"))
        for path in MIGRATIONS[1:]:  # idempotent re-apply, including the money migration
            conn.execute(Path(path).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dsn() -> str:
    value = os.environ["DATABASE_URL"]
    _apply_migrations(value)
    return value


@pytest.fixture()
def repo(dsn: str) -> PostgresSocietyCRMRepository:
    return PostgresSocietyCRMRepository(dsn)


@pytest.fixture()
def crm(repo: PostgresSocietyCRMRepository) -> SocietyCRMService:
    return SocietyCRMService(repo)


@pytest.fixture()
def ledger(repo: PostgresSocietyCRMRepository, crm: SocietyCRMService) -> PaymentLedgerService:
    return PaymentLedgerService(repo, crm)


@pytest.fixture()
def stripe() -> StripeWebhookAdapter:
    return StripeWebhookAdapter(SECRET)


# ---------------------------------------------------------------------------
# Helpers (local to this module)
# ---------------------------------------------------------------------------


def _subject() -> str:
    return f"supabase:{uuid.uuid4()}"


def _society(crm: SocietyCRMService, label: str = "Orchid Society") -> tuple[int, CRMPrincipal]:
    org = crm.create_organization(OPERATOR, slug=f"m-{uuid.uuid4().hex[:12]}", display_name=label)
    admin = CRMPrincipal(_subject())
    crm.bootstrap_admin(OPERATOR, org["id"], display_name="Pat Admin", auth_subject=admin.subject)
    crm.create_level(admin, org["id"], code="individual", display_name="Individual",
                     dues_amount_cents=3000, term_months=12)
    return org["id"], admin


def _staff(crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, org_id: int, admin: CRMPrincipal,
           role: SocietyRole | None, name: str = "Staff Person") -> CRMPrincipal:
    subject = _subject()
    person = repo.create_person(organization_id=org_id, display_name=name, actor_subject=admin.subject)
    crm.bind_identity(admin, org_id, constituent_id=person["id"], auth_subject=subject)
    if role is not None:
        crm.grant_role(admin, org_id, constituent_id=person["id"], role=role)
    return CRMPrincipal(subject)


def _pending_member(crm: SocietyCRMService, org_id: int, admin: CRMPrincipal, name: str = "Mia Member") -> dict:
    return crm.create_member(admin, org_id, display_name=name, level_code="individual",
                             email=f"{uuid.uuid4().hex[:10]}@example.org")


def _sign(payload: bytes, *, secret: str = SECRET, t: int | None = None) -> str:
    ts = int(NOW) if t is None else t
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def _evt() -> str:
    return f"evt_{uuid.uuid4().hex}"


def _pi() -> str:
    return f"pi_{uuid.uuid4().hex}"


def _meta(org_id: int | None, membership_id: int | None = None, purpose: str = "membership_dues",
          **extra: str) -> dict:
    meta = {"oc_purpose": purpose, **extra}
    if org_id is not None:
        meta["oc_organization_id"] = str(org_id)
    if membership_id is not None:
        meta["oc_membership_id"] = str(membership_id)
    return meta


def _payload(event_type: str, obj: dict, *, event_id: str | None = None) -> bytes:
    return json.dumps({
        "id": event_id or _evt(), "object": "event", "type": event_type, "created": int(NOW),
        "livemode": False, "data": {"object": obj},
    }).encode()


def _pi_succeeded(pi: str, amount: int, meta: dict, event_id: str | None = None) -> bytes:
    return _payload("payment_intent.succeeded", {
        "id": pi, "object": "payment_intent", "amount": amount, "amount_received": amount,
        "currency": "usd", "status": "succeeded", "metadata": meta}, event_id=event_id)


def _pi_failed(pi: str, amount: int, meta: dict, event_id: str | None = None) -> bytes:
    return _payload("payment_intent.payment_failed", {
        "id": pi, "object": "payment_intent", "amount": amount, "currency": "usd",
        "status": "requires_payment_method", "last_payment_error": {"code": "card_declined"},
        "metadata": meta}, event_id=event_id)


def _checkout_completed(pi: str, amount: int, meta: dict) -> bytes:
    return _payload("checkout.session.completed", {
        "id": f"cs_{uuid.uuid4().hex}", "object": "checkout.session", "payment_intent": pi,
        "amount_total": amount, "currency": "usd", "payment_status": "paid", "metadata": meta})


def _charge_refunded(pi: str, amount: int, refunded: int, meta: dict, event_id: str | None = None) -> bytes:
    return _payload("charge.refunded", {
        "id": f"ch_{uuid.uuid4().hex}", "object": "charge", "payment_intent": pi, "amount": amount,
        "amount_refunded": refunded, "currency": "usd", "metadata": meta,
        "refunds": {"data": [{"id": f"re_{uuid.uuid4().hex}"}]}}, event_id=event_id)


def _deliver(ledger: PaymentLedgerService, stripe: StripeWebhookAdapter, payload: bytes) -> dict:
    return ledger.handle_webhook(stripe, payload, _sign(payload), NOW)


def _owner_rows(dsn: str, sql: str, params: tuple = ()) -> list[dict]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _count(dsn: str, table: str, org_id: int) -> int:
    return _owner_rows(dsn, f"SELECT count(*) AS n FROM oc_constituent.{table} WHERE organization_id = %s",
                       (org_id,))[0]["n"]


def _money_counts(dsn: str, org_id: int) -> dict[str, int]:
    return {table: _count(dsn, table, org_id) for table in MONEY_TABLES}


def _audit_actions(dsn: str, org_id: int) -> list[str]:
    return [r["action"] for r in _owner_rows(
        dsn, "SELECT action FROM oc_constituent.crm_audit_events WHERE organization_id = %s ORDER BY id", (org_id,))]


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def test_stripe_signature_verification_rejects_every_bad_form(stripe: StripeWebhookAdapter) -> None:
    payload = _pi_succeeded(_pi(), 3000, _meta(1, 1))
    event = stripe.verify_and_parse(payload, _sign(payload), NOW)
    assert event.kind == "payment.succeeded" and event.metadata.organization_id == 1

    cases = {
        "WEBHOOK_SIGNATURE_MISSING": [None, "", "   "],
        "WEBHOOK_SIGNATURE_MALFORMED": ["garbage", "t=abc,v1=00", f"t={int(NOW)}", "v1=00"],
        "WEBHOOK_SIGNATURE_MISMATCH": [_sign(payload, secret="whsec_wrong"), _sign(payload + b" ")],
        "WEBHOOK_SIGNATURE_EXPIRED": [_sign(payload, t=int(NOW) - 301), _sign(payload, t=int(NOW) + 301)],
    }
    for code, headers in cases.items():
        for header in headers:
            with pytest.raises(WebhookSignatureError) as err:
                stripe.verify_and_parse(payload, header, NOW)
            assert err.value.code == code, header
    # Tampered payload with the original header.
    with pytest.raises(WebhookSignatureError):
        stripe.verify_and_parse(payload.replace(b"3000", b"1"), _sign(payload), NOW)
    # Within tolerance is accepted; multiple v1 values (secret roll) accept any match.
    stripe.verify_and_parse(payload, _sign(payload, t=int(NOW) - 299), NOW)
    good = _sign(payload).split("v1=")[1]
    stripe.verify_and_parse(payload, f"t={int(NOW)},v1={'0' * 64},v1={good}", NOW)
    # The secret never appears in repr and is required.
    assert SECRET not in repr(stripe)
    with pytest.raises(ValueError):
        StripeWebhookAdapter("")
    with pytest.raises(ValueError):
        StripeWebhookAdapter.from_env({})
    assert repr(StripeWebhookAdapter.from_env({"OC_STRIPE_WEBHOOK_SECRET": SECRET})).count(SECRET) == 0


def test_bad_signature_expired_or_wrong_secret_writes_nothing(
    crm: SocietyCRMService, ledger: PaymentLedgerService, stripe: StripeWebhookAdapter, dsn: str
) -> None:
    org, admin = _society(crm)
    member = _pending_member(crm, org, admin)
    payload = _pi_succeeded(_pi(), 3000, _meta(org, member["membership_id"]))
    before = _money_counts(dsn, org)
    audit_before = _audit_actions(dsn, org)
    for header in (_sign(payload, secret="whsec_wrong"), _sign(payload, t=int(NOW) - 3600), "t=1,v1=zz", None):
        with pytest.raises(WebhookSignatureError):
            ledger.handle_webhook(stripe, payload, header, NOW)
    assert _money_counts(dsn, org) == before
    assert _audit_actions(dsn, org) == audit_before
    assert crm.get_member(admin, org, member["membership_id"])["status"] == "pending"


# ---------------------------------------------------------------------------
# Webhook idempotency, failure, retry
# ---------------------------------------------------------------------------


def test_duplicate_webhook_creates_one_payment_and_one_renewal(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, ledger: PaymentLedgerService,
    stripe: StripeWebhookAdapter, dsn: str,
) -> None:
    org, admin = _society(crm)
    member = _pending_member(crm, org, admin)
    pi = _pi()
    meta = _meta(org, member["membership_id"], oc_constituent_id=str(member["constituent_id"]))
    payload = _pi_succeeded(pi, 3000, meta)

    first = _deliver(ledger, stripe, payload)
    assert first["status"] == "processed" and first["renewal_applied"] is True
    assert first["dues_mismatch"] is False
    # Same event redelivered: no side effects at all.
    counts = _money_counts(dsn, org)
    audit = _audit_actions(dsn, org)
    second = _deliver(ledger, stripe, payload)
    assert second["status"] == "duplicate"
    assert _money_counts(dsn, org) == counts and _audit_actions(dsn, org) == audit
    # A different event for the same payment intent (Checkout completion) is absorbed.
    third = _deliver(ledger, stripe, _checkout_completed(pi, 3000, meta))
    assert third["status"] == "processed" and third["outcome"] == "already_succeeded"
    assert third["payment_id"] == first["payment_id"]

    payments = _owner_rows(dsn, "SELECT * FROM oc_constituent.payments WHERE organization_id = %s", (org,))
    assert len(payments) == 1
    assert payments[0]["method"] == "card_provider" and payments[0]["provider_payment_ref"] == pi
    assert payments[0]["idempotency_key"] == f"stripe:{pi}"
    renewals = repo.list_renewals(organization_id=org, membership_id=member["membership_id"])
    assert len(renewals) == 1
    assert renewals[0]["renewal_key"] == f"payment:{first['payment_id']}"
    assert renewals[0]["source_kind"] == "online_payment"
    after = crm.get_member(admin, org, member["membership_id"])
    assert after["status"] == "active"
    assert after["expires_at"] == datetime(2027, 1, 15, 12, 0, tzinfo=timezone.utc)  # exactly one term
    events = _owner_rows(dsn, "SELECT processing_status, attempts FROM oc_constituent.provider_webhook_events "
                              "WHERE organization_id = %s ORDER BY id", (org,))
    assert events == [{"processing_status": "processed", "attempts": 1}] * 2


def test_failed_payment_does_not_activate_membership_and_retry_succeeds_once(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, ledger: PaymentLedgerService,
    stripe: StripeWebhookAdapter, dsn: str,
) -> None:
    org, admin = _society(crm)
    member = _pending_member(crm, org, admin)
    pi = _pi()
    meta = _meta(org, member["membership_id"])

    failed = _deliver(ledger, stripe, _pi_failed(pi, 3000, meta))
    assert failed["status"] == "processed" and failed["outcome"] == "payment_failed"
    assert failed["renewal_applied"] is False
    assert crm.get_member(admin, org, member["membership_id"])["status"] == "pending"
    assert repo.list_renewals(organization_id=org, membership_id=member["membership_id"]) == []
    payment = ledger.get_payment(admin, org, failed["payment_id"])
    assert payment["payment"]["status"] == "failed"
    assert payment["events"][0]["reason"] == "provider:payment_intent.payment_failed:card_declined"

    # The member retries on the same payment intent and it succeeds.
    ok = _deliver(ledger, stripe, _pi_succeeded(pi, 3000, meta))
    assert ok["payment_id"] == failed["payment_id"] and ok["renewal_applied"] is True
    # A late, out-of-order failure never downgrades the settled payment.
    late = _deliver(ledger, stripe, _pi_failed(pi, 3000, meta))
    assert late["outcome"] == "already_succeeded"
    trail = ledger.get_payment(admin, org, ok["payment_id"])
    assert [(e["from_status"], e["to_status"]) for e in trail["events"]] == [(None, "failed"), ("failed", "succeeded")]
    assert trail["payment"]["status"] == "succeeded"
    assert len(repo.list_renewals(organization_id=org, membership_id=member["membership_id"])) == 1
    assert crm.get_member(admin, org, member["membership_id"])["status"] == "active"


def test_webhook_refund_states_and_retry_of_failed_event(
    crm: SocietyCRMService, ledger: PaymentLedgerService, stripe: StripeWebhookAdapter, dsn: str
) -> None:
    org, admin = _society(crm)
    member = _pending_member(crm, org, admin)
    pi = _pi()
    meta = _meta(org, member["membership_id"])

    # Refund arrives before its payment: recorded as a retryable failure, nothing applied.
    refund_evt = _evt()
    early_payload = _charge_refunded(pi, 3000, 1000, meta, event_id=refund_evt)
    early = _deliver(ledger, stripe, early_payload)
    assert early["status"] == "failed" and early["error_code"] == "WEBHOOK_UNKNOWN_PAYMENT"
    assert early["retryable"] is True and _count(dsn, "payments", org) == 0
    diag = ledger.failed_webhooks(admin, org)
    assert [d["provider_event_id"] for d in diag] == [refund_evt]
    assert diag[0]["retryable"] and "retried automatically" in diag[0]["message"]

    paid = _deliver(ledger, stripe, _pi_succeeded(pi, 3000, meta))
    # Redelivery of the previously failed event now succeeds (attempts incremented).
    retried = _deliver(ledger, stripe, early_payload)  # a redelivery is byte-identical
    assert retried["status"] == "processed" and retried["attempts"] == 2
    assert retried["membership_review_required"] is True
    # Once processed, the same event is a pure duplicate.
    assert _deliver(ledger, stripe, early_payload)["status"] == "duplicate"
    # A different body under an already-used event id is never applied.
    changed = _deliver(ledger, stripe, _charge_refunded(pi, 3000, 3000, meta, event_id=refund_evt))
    assert changed["status"] == "duplicate" and changed["note"] == "WEBHOOK_EVENT_PAYLOAD_CHANGED"
    # A later event with a cumulative total completes the refund exactly once.
    done = _deliver(ledger, stripe, _charge_refunded(pi, 3000, 3000, meta))
    assert done["outcome"] == "refund_recorded"
    again = _deliver(ledger, stripe, _charge_refunded(pi, 3000, 3000, meta))
    assert again["outcome"] == "refund_already_recorded"

    trail = ledger.get_payment(admin, org, paid["payment_id"])
    assert trail["payment"]["status"] == "refunded" and trail["payment"]["refunded_amount_cents"] == 3000
    assert [r["amount_cents"] for r in trail["refunds"]] == [1000, 2000]
    assert [(e["from_status"], e["to_status"]) for e in trail["events"]] == [
        (None, "succeeded"), ("succeeded", "partially_refunded"), ("partially_refunded", "refunded")]
    assert ledger.failed_webhooks(admin, org) == []
    # The refund did not shorten the membership: it is flagged for an administrator.
    assert crm.get_member(admin, org, member["membership_id"])["status"] == "active"
    assert trail["payment"]["membership_review_required"] is True
    actions = _audit_actions(dsn, org)
    assert actions.count("payment.refunded") == 2 and "membership.review_required" in actions
    assert "payment.webhook_failed" in actions and "payment.webhook_processed" in actions

    # Card refunds are issued at the provider, never by the admin API.
    with pytest.raises(PaymentError) as err:
        ledger.refund(admin, org, paid["payment_id"], amount_cents=1, reason="x", idempotency_key=f"r-{uuid.uuid4()}")
    assert err.value.code == "PROVIDER_REFUND_MUST_BE_ISSUED_AT_PROVIDER"


def test_unroutable_and_unsupported_webhooks_write_nothing(
    crm: SocietyCRMService, ledger: PaymentLedgerService, stripe: StripeWebhookAdapter, dsn: str
) -> None:
    org, admin = _society(crm)
    member = _pending_member(crm, org, admin)
    before = _money_counts(dsn, org)
    no_org = _deliver(ledger, stripe, _pi_succeeded(_pi(), 3000, _meta(None, member["membership_id"])))
    assert no_org["status"] == "unroutable" and no_org["error_code"] == "WEBHOOK_ORGANIZATION_METADATA_MISSING"
    bad_org = _deliver(ledger, stripe, _pi_succeeded(_pi(), 3000, _meta(2_000_000_000, member["membership_id"])))
    assert bad_org["status"] == "unroutable" and bad_org["error_code"] == "WEBHOOK_UNKNOWN_ORGANIZATION"
    other = _deliver(ledger, stripe, _payload("customer.created", {"id": "cus_x", "metadata": _meta(org)}))
    assert other["status"] == "ignored"
    assert _money_counts(dsn, org) == before
    assert crm.get_member(admin, org, member["membership_id"])["status"] == "pending"


def test_webhook_naming_another_tenants_membership_is_refused_and_recorded_failed(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, ledger: PaymentLedgerService,
    stripe: StripeWebhookAdapter, dsn: str,
) -> None:
    org_a, admin_a = _society(crm, "Society A")
    org_b, admin_b = _society(crm, "Society B")
    member_b = _pending_member(crm, org_b, admin_b)
    member_a = _pending_member(crm, org_a, admin_a)
    evt = _evt()
    payload = _pi_succeeded(_pi(), 3000, _meta(org_a, member_b["membership_id"]), event_id=evt)

    result = _deliver(ledger, stripe, payload)
    assert result["status"] == "failed" and result["error_code"] == "WEBHOOK_UNKNOWN_MEMBERSHIP"
    assert result["retryable"] is False
    assert _count(dsn, "payments", org_a) == 0 and _count(dsn, "payments", org_b) == 0
    assert crm.get_member(admin_b, org_b, member_b["membership_id"])["status"] == "pending"
    assert repo.list_renewals(organization_id=org_b, membership_id=member_b["membership_id"]) == []
    rows = _owner_rows(dsn, "SELECT organization_id, processing_status, error_code FROM "
                            "oc_constituent.provider_webhook_events WHERE provider_event_id = %s", (evt,))
    assert rows == [{"organization_id": org_a, "processing_status": "failed",
                     "error_code": "WEBHOOK_UNKNOWN_MEMBERSHIP"}]
    diag = ledger.failed_webhooks(admin_a, org_a)
    assert diag[0]["provider_event_id"] == evt and "does not exist in this society" in diag[0]["message"]
    assert ledger.failed_webhooks(admin_b, org_b) == []
    # Redelivery reprocesses (still failing) and counts the attempt.
    assert _deliver(ledger, stripe, payload)["attempts"] == 2

    # Person/membership mismatch inside one tenant is also refused.
    mismatch = _deliver(ledger, stripe, _pi_succeeded(_pi(), 3000, _meta(
        org_a, member_a["membership_id"], oc_constituent_id=str(member_b["constituent_id"]))))
    assert mismatch["error_code"] == "WEBHOOK_UNKNOWN_CONSTITUENT"

    # And the database itself refuses a cross-tenant payment row (composite FK).
    with psycopg.connect(dsn) as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(
                "INSERT INTO oc_constituent.payments (organization_id, constituent_id, membership_id, purpose, "
                "amount_cents, currency, method, status, received_at, recorded_by_subject, idempotency_key) "
                "VALUES (%s, %s, %s, 'membership_dues', 100, 'USD', 'cash', 'succeeded', NOW(), 'x:y', %s)",
                (org_a, member_a["constituent_id"], member_b["membership_id"], f"k-{uuid.uuid4()}"),
            )

    # Diagnostics are admin-only.
    treasurer = _staff(crm, repo, org_a, admin_a, SocietyRole.TREASURER)
    with pytest.raises(SocietyAccessDenied):
        ledger.failed_webhooks(treasurer, org_a)


# ---------------------------------------------------------------------------
# Offline payments and authorization
# ---------------------------------------------------------------------------


def test_check_payment_recorded_by_treasurer_renews_exactly_once(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, ledger: PaymentLedgerService, dsn: str
) -> None:
    org, admin = _society(crm)
    treasurer = _staff(crm, repo, org, admin, SocietyRole.TREASURER, "Terry Treasurer")
    member = _pending_member(crm, org, admin)
    key = f"check-{uuid.uuid4()}"
    kwargs = dict(constituent_id=member["constituent_id"], membership_id=member["membership_id"],
                  amount_cents=3000, currency="usd", method="check", check_number="1042",
                  received_at=T0, idempotency_key=key)

    first = ledger.record_offline_payment(treasurer, org, **kwargs)
    assert first["created"] and first["renewal_applied"] and first["dues_mismatch"] is False
    assert first["payment"]["status"] == "succeeded" and first["payment"]["check_number"] == "1042"
    renewal = first["renewal"]
    assert renewal["source_kind"] == "offline_payment" and renewal["source_ref"] == str(first["payment"]["id"])
    assert renewal["renewal_key"] == f"payment:{first['payment']['id']}"
    assert first["membership"]["expires_at"] == datetime(2027, 1, 15, 12, 0, tzinfo=timezone.utc)

    replay = ledger.record_offline_payment(treasurer, org, **kwargs)
    assert replay["created"] is False and replay["payment"]["id"] == first["payment"]["id"]
    assert len(repo.list_renewals(organization_id=org, membership_id=member["membership_id"])) == 1
    with pytest.raises(PaymentError) as err:
        ledger.record_offline_payment(treasurer, org, **{**kwargs, "amount_cents": 2999})
    assert err.value.code == "IDEMPOTENCY_KEY_CONFLICT"

    # Underpaid dues are recorded and flagged, not blocked; the term extends from expiry.
    partial = ledger.record_offline_payment(treasurer, org, **{**kwargs, "idempotency_key": f"cash-{uuid.uuid4()}",
                                                               "method": "cash", "check_number": None,
                                                               "amount_cents": 2500})
    assert partial["dues_mismatch"] is True and partial["expected_dues_cents"] == 3000
    assert partial["membership"]["expires_at"] == datetime(2028, 1, 15, 12, 0, tzinfo=timezone.utc)

    audit = _owner_rows(dsn, "SELECT actor_subject, metadata FROM oc_constituent.crm_audit_events "
                             "WHERE organization_id = %s AND action = 'payment.recorded' ORDER BY id", (org,))
    assert len(audit) == 2 and {a["actor_subject"] for a in audit} == {treasurer.subject}
    assert [a["metadata"]["dues_mismatch"] for a in audit] == [False, True]

    receipt = ledger.get_receipt(treasurer, org, first["payment"]["id"])
    assert receipt["method"] == "Check" and receipt["amount_display"] == "USD 30.00"
    assert "1042" not in json.dumps(receipt, default=str)  # no check number on receipts


def test_people_without_payment_write_cannot_record_payments(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, ledger: PaymentLedgerService, dsn: str
) -> None:
    org, admin = _society(crm)
    member = _pending_member(crm, org, admin)
    plain = CRMPrincipal(_subject())
    crm.bind_identity(admin, org, constituent_id=member["constituent_id"], auth_subject=plain.subject)
    editor = _staff(crm, repo, org, admin, SocietyRole.MEMBERSHIP_EDITOR)
    viewer = _staff(crm, repo, org, admin, SocietyRole.VIEWER)
    stranger = CRMPrincipal(_subject())
    before = _money_counts(dsn, org)

    for who in (plain, editor, viewer, stranger):
        with pytest.raises(SocietyAccessDenied):
            ledger.record_offline_payment(who, org, constituent_id=member["constituent_id"],
                                          membership_id=member["membership_id"], amount_cents=3000, currency="USD",
                                          method="cash", received_at=T0, idempotency_key=f"k-{uuid.uuid4()}")
        with pytest.raises(SocietyAccessDenied):
            ledger.record_donation(who, org, constituent_id=member["constituent_id"], amount_cents=100,
                                   currency="USD", method="cash", designation="general",
                                   idempotency_key=f"k-{uuid.uuid4()}", received_at=T0)
        with pytest.raises(SocietyAccessDenied):
            ledger.list_payments(who, org)
        with pytest.raises(SocietyAccessDenied):
            ledger.list_donations(who, org)
    assert _money_counts(dsn, org) == before
    assert crm.get_member(admin, org, member["membership_id"])["status"] == "pending"


def test_offline_refund_is_traceable_bounded_and_flags_membership_review(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, ledger: PaymentLedgerService, dsn: str
) -> None:
    org, admin = _society(crm)
    treasurer = _staff(crm, repo, org, admin, SocietyRole.TREASURER)
    member = _pending_member(crm, org, admin)
    paid = ledger.record_offline_payment(treasurer, org, constituent_id=member["constituent_id"],
                                         membership_id=member["membership_id"], amount_cents=3000, currency="USD",
                                         method="check", check_number="77", received_at=T0,
                                         idempotency_key=f"k-{uuid.uuid4()}")
    payment_id = paid["payment"]["id"]
    expires = crm.get_member(admin, org, member["membership_id"])["expires_at"]

    key1 = f"r-{uuid.uuid4()}"
    part = ledger.refund(treasurer, org, payment_id, amount_cents=1000, reason="duplicate family dues",
                         idempotency_key=key1)
    assert part["payment"]["status"] == "partially_refunded" and part["membership_review_required"] is True
    assert ledger.refund(treasurer, org, payment_id, amount_cents=1000, reason="duplicate family dues",
                         idempotency_key=key1)["created"] is False
    with pytest.raises(PaymentError) as err:
        ledger.refund(treasurer, org, payment_id, amount_cents=2001, reason="too much", idempotency_key=f"r-{uuid.uuid4()}")
    assert err.value.code == "REFUND_EXCEEDS_REMAINING"
    full = ledger.refund(treasurer, org, payment_id, amount_cents=2000, reason="member moved away",
                         idempotency_key=f"r-{uuid.uuid4()}")
    assert full["payment"]["status"] == "refunded"
    with pytest.raises(PaymentError) as err:
        ledger.refund(treasurer, org, payment_id, amount_cents=1, reason="again", idempotency_key=f"r-{uuid.uuid4()}")
    assert err.value.code == "REFUND_NOT_ALLOWED_FROM_STATUS:refunded"

    trail = ledger.get_payment(treasurer, org, payment_id)
    assert [(e["from_status"], e["to_status"], e["amount_cents"]) for e in trail["events"]] == [
        (None, "succeeded", 3000), ("succeeded", "partially_refunded", 1000), ("partially_refunded", "refunded", 2000)]
    assert [r["amount_cents"] for r in trail["refunds"]] == [1000, 2000]
    assert {e["actor_subject"] for e in trail["events"]} == {treasurer.subject}
    # Membership untouched; administrator review flagged instead.
    after = crm.get_member(admin, org, member["membership_id"])
    assert after["status"] == "active" and after["expires_at"] == expires
    assert len(repo.list_renewals(organization_id=org, membership_id=member["membership_id"])) == 1
    flagged, total = ledger.list_payments(treasurer, org, membership_review_required=True)
    assert total == 1 and flagged[0]["id"] == payment_id
    review = _owner_rows(dsn, "SELECT entity_id, metadata FROM oc_constituent.crm_audit_events "
                              "WHERE organization_id = %s AND action = 'membership.review_required' ORDER BY id", (org,))
    assert len(review) == 2 and review[0]["entity_id"] == str(member["membership_id"])
    assert review[1]["metadata"]["fully_refunded"] is True

    # The ledger history is append-only even for the table owner.
    with psycopg.connect(dsn) as conn:
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("UPDATE oc_constituent.payment_events SET reason = 'x' WHERE payment_id = %s", (payment_id,))
    with psycopg.connect(dsn) as conn:
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("DELETE FROM oc_constituent.refunds WHERE payment_id = %s", (payment_id,))
    # Over-refund is also structurally impossible.
    with psycopg.connect(dsn) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE oc_constituent.payments SET refunded_amount_cents = 3001 WHERE id = %s", (payment_id,))


def test_void_only_for_entries_without_downstream_effects(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, ledger: PaymentLedgerService
) -> None:
    org, admin = _society(crm)
    treasurer = _staff(crm, repo, org, admin, SocietyRole.TREASURER)
    member = _pending_member(crm, org, admin)
    common = dict(constituent_id=member["constituent_id"], amount_cents=1500, currency="USD", method="cash",
                  received_at=T0)
    event_fee = ledger.record_offline_payment(treasurer, org, purpose="event", idempotency_key=f"k-{uuid.uuid4()}",
                                              **common)
    voided = ledger.void(treasurer, org, event_fee["payment"]["id"], "entered twice")
    assert voided["payment"]["status"] == "voided"
    assert ledger.void(treasurer, org, event_fee["payment"]["id"], "entered twice")["changed"] is False

    dues = ledger.record_offline_payment(treasurer, org, membership_id=member["membership_id"],
                                         idempotency_key=f"k-{uuid.uuid4()}", **common)
    with pytest.raises(PaymentError) as err:
        ledger.void(treasurer, org, dues["payment"]["id"], "mistake")
    assert err.value.code == "PAYMENT_RENEWAL_APPLIED_USE_REFUND"
    gift = ledger.record_donation(treasurer, org, designation="general", idempotency_key=f"k-{uuid.uuid4()}", **common)
    with pytest.raises(PaymentError) as err:
        ledger.void(treasurer, org, gift["payment"]["id"], "mistake")
    assert err.value.code == "PAYMENT_DONATION_RECEIPT_ISSUED_USE_REFUND"
    with pytest.raises(PaymentError):
        ledger.record_offline_payment(treasurer, org, purpose="donation", idempotency_key=f"k-{uuid.uuid4()}",
                                      **common)


def test_card_like_numbers_are_rejected_everywhere(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, ledger: PaymentLedgerService, dsn: str
) -> None:
    org, admin = _society(crm)
    member = _pending_member(crm, org, admin)
    assert contains_card_like_number("card 4111 1111 1111 1111") and contains_card_like_number("4111-1111-1111-1")
    assert not contains_card_like_number("check 1042, phone 805-555-0100")
    base = dict(constituent_id=member["constituent_id"], membership_id=member["membership_id"], amount_cents=3000,
                currency="USD", received_at=T0)
    bad = [
        dict(method="check", check_number="4111111111111111"),
        dict(method="check", check_number="12345678901234"),
        dict(method="cash", notes="paid with card 4111 1111 1111 1111"),
        dict(method="cash", check_number="1001"),  # check number on a cash payment
        dict(method="check", check_number="12/34 bad!"),
    ]
    before = _money_counts(dsn, org)
    for extra in bad:
        with pytest.raises(PaymentError):
            ledger.record_offline_payment(admin, org, idempotency_key=f"k-{uuid.uuid4()}", **base, **extra)
    assert _money_counts(dsn, org) == before
    paid = ledger.record_offline_payment(admin, org, method="cash", idempotency_key=f"k-{uuid.uuid4()}", **base)
    with pytest.raises(PaymentError) as err:
        ledger.refund(admin, org, paid["payment"]["id"], amount_cents=100, reason="to card 4111111111111111",
                      idempotency_key=f"r-{uuid.uuid4()}")
    assert err.value.code == "CARD_LIKE_NUMBER_REJECTED"
    # Database-level defence for any path that bypasses the service.
    with psycopg.connect(dsn) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE oc_constituent.payments SET notes = 'pan 4111-1111-1111-1111' WHERE id = %s",
                         (paid["payment"]["id"],))


def test_money_tables_have_no_sensitive_columns_and_least_privilege_grants(dsn: str) -> None:
    columns = _owner_rows(dsn, "SELECT table_name, column_name FROM information_schema.columns "
                               "WHERE table_schema = 'oc_constituent' AND table_name = ANY(%s)", (list(MONEY_TABLES),))
    assert {c["table_name"] for c in columns} == set(MONEY_TABLES)
    forbidden = re.compile(r"card|cvv|cvc|(^|_)pan(_|$)|account_number|routing|iban|secret|expiry|exp_month|raw_payload|password")
    assert [c for c in columns if forbidden.search(c["column_name"])] == []
    grants = _owner_rows(dsn, "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                              "WHERE grantee = 'oc_crm_runtime' AND table_schema = 'oc_constituent' "
                              "AND table_name = ANY(%s)", (list(MONEY_TABLES),))
    privileges: dict[str, set[str]] = {}
    for g in grants:
        privileges.setdefault(g["table_name"], set()).add(g["privilege_type"])
    for table in ("payment_events", "refunds", "donations"):
        assert privileges[table] == {"SELECT", "INSERT"}, table
    for table in ("payments", "donation_receipt_counters", "provider_webhook_events"):
        assert privileges[table] == {"SELECT", "INSERT", "UPDATE"}, table
    policies = _owner_rows(dsn, "SELECT tablename FROM pg_policies WHERE schemaname = 'oc_constituent' "
                                "AND policyname = 'oc_crm_tenant_isolation' AND tablename = ANY(%s)",
                           (list(MONEY_TABLES),))
    assert {p["tablename"] for p in policies} == set(MONEY_TABLES)


# ---------------------------------------------------------------------------
# Donations and receipts
# ---------------------------------------------------------------------------


def test_donation_receipt_numbers_are_sequential_per_org_and_independent(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, ledger: PaymentLedgerService,
    stripe: StripeWebhookAdapter, dsn: str,
) -> None:
    org_a, admin_a = _society(crm, "Society A")
    org_b, admin_b = _society(crm, "Society B")
    treasurer_a = _staff(crm, repo, org_a, admin_a, SocietyRole.TREASURER)
    donor_a = _pending_member(crm, org_a, admin_a, "Dana Donor")
    donor_b = _pending_member(crm, org_b, admin_b, "Dana Donor")

    def give(principal, org, donor, key=None, **extra):
        return ledger.record_donation(principal, org, constituent_id=donor["constituent_id"], amount_cents=5000,
                                      currency="USD", method="check", check_number="300", designation="library-fund",
                                      idempotency_key=key or f"d-{uuid.uuid4()}", received_at=T0, **extra)

    key = f"d-{uuid.uuid4()}"
    numbers_a = [give(treasurer_a, org_a, donor_a, key)["donation"]["receipt_number"]]
    assert give(treasurer_a, org_a, donor_a, key)["donation"]["receipt_number"] == numbers_a[0]  # idempotent
    numbers_a += [give(treasurer_a, org_a, donor_a)["donation"]["receipt_number"] for _ in range(2)]
    numbers_b = [give(admin_b, org_b, donor_b)["donation"]["receipt_number"] for _ in range(2)]
    assert numbers_a == [1, 2, 3] and numbers_b == [1, 2]

    # An online donation takes the next number in its own organization.
    web = _deliver(ledger, stripe, _pi_succeeded(_pi(), 2500, _meta(
        org_a, None, purpose="donation", oc_constituent_id=str(donor_a["constituent_id"]),
        oc_designation="general")))
    assert web["status"] == "processed" and web["donation_id"]
    donations, total = ledger.list_donations(treasurer_a, org_a)
    assert total == 4 and [d["receipt_number"] for d in donations] == [4, 3, 2, 1]

    goods = give(treasurer_a, org_a, donor_a, tax_deductible_cents=3500)
    receipt = ledger.get_receipt(treasurer_a, org_a, goods["payment"]["id"])
    assert receipt["receipt_number"] == "000005" and receipt["organization_name"] == "Society A"
    assert receipt["designation"] == "library-fund" and receipt["tax_deductible_cents"] == 3500
    assert "USD 15.00" in receipt["deductibility_statement"] and "USD 35.00" in receipt["deductibility_statement"]
    full = ledger.get_receipt(treasurer_a, org_a, ledger.list_donations(treasurer_a, org_a)[0][-1]["payment_id"])
    assert full["deductibility_statement"].startswith("No goods or services")
    with pytest.raises(PaymentError):
        give(treasurer_a, org_a, donor_a, tax_deductible_cents=5001)
    actions = _audit_actions(dsn, org_a)
    assert actions.count("donation.recorded") == 5


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


def test_society_a_cannot_see_or_touch_society_b_money(
    crm: SocietyCRMService, repo: PostgresSocietyCRMRepository, ledger: PaymentLedgerService,
    stripe: StripeWebhookAdapter, dsn: str,
) -> None:
    org_a, admin_a = _society(crm, "Five Cities Orchid Society")
    org_b, admin_b = _society(crm, "Five Cities Orchid Society")
    treasurer_a = _staff(crm, repo, org_a, admin_a, SocietyRole.TREASURER)
    m_a = _pending_member(crm, org_a, admin_a, "Same Person")
    m_b = _pending_member(crm, org_b, admin_b, "Same Person")
    pay_a = ledger.record_offline_payment(treasurer_a, org_a, constituent_id=m_a["constituent_id"],
                                          membership_id=m_a["membership_id"], amount_cents=3000, currency="USD",
                                          method="cash", received_at=T0, idempotency_key="shared-key-1")
    pay_b = ledger.record_offline_payment(admin_b, org_b, constituent_id=m_b["constituent_id"],
                                          membership_id=m_b["membership_id"], amount_cents=3000, currency="USD",
                                          method="cash", received_at=T0, idempotency_key="shared-key-1")
    assert pay_a["created"] and pay_b["created"]  # idempotency keys are per organization
    gift_b = ledger.record_donation(admin_b, org_b, constituent_id=m_b["constituent_id"], amount_cents=100,
                                    currency="USD", method="cash", designation="general",
                                    idempotency_key=f"d-{uuid.uuid4()}", received_at=T0)
    _deliver(ledger, stripe, _pi_succeeded(_pi(), 3000, _meta(org_b, m_b["membership_id"])))
    b_payment = pay_b["payment"]["id"]

    rows, total = ledger.list_payments(treasurer_a, org_a)
    assert total == 1 and [r["id"] for r in rows] == [pay_a["payment"]["id"]]
    assert ledger.list_payments(treasurer_a, org_a, method="cash")[1] == 1
    assert ledger.list_payments(treasurer_a, org_a, method="check")[1] == 0
    assert ledger.list_donations(treasurer_a, org_a) == ([], 0)
    for call in (
        lambda: ledger.list_payments(treasurer_a, org_b),
        lambda: ledger.list_donations(treasurer_a, org_b),
        lambda: ledger.get_receipt(treasurer_a, org_b, b_payment),
        lambda: ledger.refund(treasurer_a, org_b, b_payment, amount_cents=1, reason="x", idempotency_key="r-1"),
        lambda: ledger.record_offline_payment(treasurer_a, org_b, constituent_id=m_b["constituent_id"],
                                              amount_cents=1, currency="USD", method="cash", received_at=T0,
                                              idempotency_key="x-1", purpose="other"),
        lambda: ledger.failed_webhooks(admin_a, org_b),
    ):
        with pytest.raises(SocietyAccessDenied):
            call()
    # Through A's own tenant, B's ids simply do not exist.
    for call in (
        lambda: ledger.get_receipt(treasurer_a, org_a, b_payment),
        lambda: ledger.get_payment(treasurer_a, org_a, b_payment),
        lambda: ledger.get_receipt(treasurer_a, org_a, gift_b["payment"]["id"]),
        lambda: ledger.refund(treasurer_a, org_a, b_payment, amount_cents=1, reason="x", idempotency_key="r-2"),
        lambda: ledger.void(treasurer_a, org_a, b_payment, "x"),
        lambda: ledger.record_offline_payment(treasurer_a, org_a, constituent_id=m_b["constituent_id"],
                                              amount_cents=1, currency="USD", method="cash", received_at=T0,
                                              idempotency_key="x-2", purpose="other"),
    ):
        with pytest.raises(NotFound):
            call()
    with pytest.raises(NotFound):
        ledger.record_offline_payment(treasurer_a, org_a, constituent_id=m_a["constituent_id"],
                                      membership_id=m_b["membership_id"], amount_cents=1, currency="USD",
                                      method="cash", received_at=T0, idempotency_key="x-3")
    assert ledger.get_payment(admin_b, org_b, b_payment)["payment"]["status"] == "succeeded"

    # RLS: under tenant A, unfiltered selects see only A rows.
    connect = lambda: psycopg.connect(dsn, row_factory=dict_row)  # noqa: E731
    with tenant_transaction(org_a, connect=connect) as cur:
        for table in MONEY_TABLES:
            cur.execute(f"SELECT DISTINCT organization_id FROM oc_constituent.{table}")  # no WHERE
            assert {r["organization_id"] for r in cur.fetchall()} <= {org_a}, table
        cur.execute("SELECT count(*) AS n FROM oc_constituent.payments")
        assert cur.fetchone()["n"] == 1
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with tenant_transaction(org_a, connect=connect) as cur:
            cur.execute(
                "INSERT INTO oc_constituent.payments (organization_id, constituent_id, purpose, amount_cents, "
                "currency, method, status, received_at, recorded_by_subject, idempotency_key) "
                "VALUES (%s, %s, 'other', 1, 'USD', 'cash', 'succeeded', NOW(), 'x:y', 'smuggled')",
                (org_b, m_b["constituent_id"]),
            )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with tenant_transaction(org_a, connect=connect) as cur:
            cur.execute("DELETE FROM oc_constituent.payments WHERE id = %s", (pay_a["payment"]["id"],))


# ---------------------------------------------------------------------------
# Reconciliation and HTTP route
# ---------------------------------------------------------------------------


def test_reconciliation_reports_every_discrepancy_class(
    crm: SocietyCRMService, ledger: PaymentLedgerService, stripe: StripeWebhookAdapter, dsn: str
) -> None:
    org, admin = _society(crm)
    members = [_pending_member(crm, org, admin, f"Member {i}") for i in range(3)]
    pis = [_pi() for _ in range(3)]
    for member, pi in zip(members, pis):
        _deliver(ledger, stripe, _pi_succeeded(pi, 3000, _meta(org, member["membership_id"])))
    ledger.record_offline_payment(admin, org, constituent_id=members[0]["constituent_id"], amount_cents=10,
                                  currency="USD", method="cash", received_at=T0, purpose="other",
                                  idempotency_key=f"k-{uuid.uuid4()}")  # offline rows are not provider rows
    missing = _pi()
    report = ledger.reconcile_payments(admin, org, [
        {"provider_payment_ref": pis[0], "amount_cents": 3000, "currency": "usd", "status": "succeeded"},
        {"provider_payment_ref": pis[1], "amount_cents": 2900, "status": "refunded"},
        {"provider_payment_ref": missing, "amount_cents": 500, "status": "succeeded"},
        {"provider_payment_ref": missing, "amount_cents": 500, "status": "succeeded"},
    ])
    assert report["matched"] == 1
    assert [r["provider_payment_ref"] for r in report["missing_in_oc"]] == [missing]
    assert [r["provider_payment_ref"] for r in report["missing_in_provider"]] == [pis[2]]
    assert report["amount_mismatch"][0]["provider_amount_cents"] == 2900
    assert report["status_mismatch"][0] == {"provider_payment_ref": pis[1], "payment_id": ANY_INT,
                                            "ledger_status": "succeeded", "provider_status": "refunded"}
    assert report["duplicate_in_provider"] == [missing]
    audit = _owner_rows(dsn, "SELECT metadata FROM oc_constituent.crm_audit_events WHERE organization_id = %s "
                             "AND action = 'payment.reconciliation_run'", (org,))
    assert audit[0]["metadata"]["missing_in_oc"] == 1
    with pytest.raises(PaymentError):
        ledger.reconcile_payments(admin, org, [{"provider_payment_ref": pis[0], "amount_cents": "x", "status": "?"}])


class _AnyInt:
    def __eq__(self, other: object) -> bool:
        return isinstance(other, int)


ANY_INT = _AnyInt()


def test_webhook_route_status_codes(
    crm: SocietyCRMService, ledger: PaymentLedgerService, dsn: str
) -> None:
    org, admin = _society(crm)
    member = _pending_member(crm, org, admin)
    app = FastAPI()
    app.include_router(build_payment_webhook_router(
        service_factory=lambda: ledger, adapter_factory=lambda: StripeWebhookAdapter(SECRET), clock=lambda: NOW))
    client = TestClient(app)
    payload = _pi_succeeded(_pi(), 3000, _meta(org, member["membership_id"]))
    url = "/api/society/webhooks/stripe"

    bad = client.post(url, content=payload, headers={"Stripe-Signature": _sign(payload, secret="whsec_nope")})
    assert bad.status_code == 400 and bad.json()["detail"] == "WEBHOOK_SIGNATURE_MISMATCH"
    assert client.post(url, content=payload).status_code == 400
    assert _count(dsn, "provider_webhook_events", org) == 0
    ok = client.post(url, content=payload, headers={"Stripe-Signature": _sign(payload)})
    assert ok.status_code == 200 and ok.json()["status"] == "processed"
    dup = client.post(url, content=payload, headers={"Stripe-Signature": _sign(payload)})
    assert dup.status_code == 200 and dup.json()["status"] == "duplicate"
    early = _charge_refunded(_pi(), 3000, 100, _meta(org, member["membership_id"]))
    retry = client.post(url, content=early, headers={"Stripe-Signature": _sign(early)})
    assert retry.status_code == 503 and retry.json()["error_code"] == "WEBHOOK_UNKNOWN_PAYMENT"
    assert SECRET not in ok.text + dup.text + retry.text

    def unconfigured():
        return StripeWebhookAdapter.from_env({})

    app2 = FastAPI()
    app2.include_router(build_payment_webhook_router(service_factory=lambda: ledger, adapter_factory=unconfigured))
    assert TestClient(app2).post(url, content=payload, headers={"Stripe-Signature": _sign(payload)}).status_code == 503
