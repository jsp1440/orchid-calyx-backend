"""Society CRM payment ledger: dues, offline payments, donations, refunds, webhooks.

Provider-neutral model
----------------------
``PaymentLedgerService`` owns the ledger (``oc_constituent.payments`` and friends,
``migrations/20260928_society_crm_money.sql``). Payment *providers* only translate
their own wire format into a provider-neutral ``ProviderEvent``; the ledger never
sees a provider SDK object. One provider is implemented: ``StripeWebhookAdapter``,
which verifies and parses Stripe webhook deliveries. It makes no network calls.

What is never stored
--------------------
Card numbers, CVV, bank account/routing numbers, and provider secrets never enter a
CRM table or a log line. Only the provider's opaque object id (``pi_...``) is kept.
Free text (notes, reasons) is rejected when it contains a 13+ digit run (the shape of
a card number), both here and by a database CHECK. ``check_number`` is a paper
check serial (<= 12 characters), never a bank account number. The webhook secret
comes only from the environment (``OC_STRIPE_WEBHOOK_SECRET``) and raw webhook
payloads are not persisted -- only their SHA-256 and minimal parsed fields.

Trust of webhook metadata
-------------------------
When Orchid Continuum creates a Stripe Checkout Session it sets ``metadata`` (on the
session and on ``payment_intent_data``) with ``oc_organization_id``,
``oc_membership_id``, ``oc_constituent_id``, ``oc_purpose``, ``oc_renewal_key`` and
optionally ``oc_designation``. Those values are only read from a payload whose
``Stripe-Signature`` has been verified with the webhook secret; metadata from an
unverified payload is never parsed at all. Even verified metadata is re-checked
against the tenant: a membership or person id that does not exist in the named
organization fails the event (``WEBHOOK_UNKNOWN_MEMBERSHIP``), it is never re-routed.

Decisions encoded here (see docs/operations/OC-CRM-PAYMENTS-001.md)
-----------------------------------------------------------------
* Dues amount different from the level's dues is *recorded and flagged*
  (``dues_mismatch``), not blocked: treasurers take partial, discounted, and
  overpaid dues by check, and refusing them would push money off-ledger.
* A refund never silently shortens a membership. The renewal ledger is append-only
  and whether a refund ends a membership is a policy decision, so a refund of a
  dues payment that renewed a membership sets ``membership_review_required`` and
  writes a ``membership.review_required`` audit event for an administrator.
* Void is for offline data-entry mistakes only. A payment that already renewed a
  membership, issued a donation receipt, or has been refunded cannot be voided
  (``PAYMENT_RENEWAL_APPLIED_USE_REFUND`` etc.); use a refund so the history stays
  truthful.
* Card refunds are issued in the provider dashboard and arrive as a webhook; this
  service does not call the provider (``PROVIDER_REFUND_MUST_BE_ISSUED_AT_PROVIDER``).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

import psycopg
from psycopg.types.json import Jsonb

from .authorization import (
    SocietyAccessDenied,
    SocietyCapability,
    capabilities_for_roles,
    require_capability,
)
from .domain import normalize_auth_subject
from .postgres_repository import PostgresSocietyCRMRepository
from .society_service import CRMPrincipal, NotFound, SocietyCRMService
from .tenant_db import ConnectionFactory, tenant_transaction

logger = logging.getLogger(__name__)

__all__ = [
    "OCPaymentMetadata",
    "PaymentError",
    "PaymentLedgerService",
    "PaymentProvider",
    "ProviderEvent",
    "StripeWebhookAdapter",
    "WebhookSignatureError",
    "contains_card_like_number",
]

STRIPE_WEBHOOK_SECRET_ENV = "OC_STRIPE_WEBHOOK_SECRET"
STRIPE_SIGNATURE_TOLERANCE_SECONDS = 300
MAX_WEBHOOK_PAYLOAD_BYTES = 512 * 1024

PURPOSES = frozenset({"membership_dues", "donation", "event", "other"})
OFFLINE_METHODS = frozenset({"check", "cash", "other_offline"})
_REFUNDABLE = frozenset({"succeeded", "partially_refunded"})
_MAX_AMOUNT_CENTS = 100_000_000_000  # sanity ceiling, not a business limit
_MAX_PAGE = 500

_PAN_LIKE = re.compile(r"[0-9]{13,}")
_SEPARATORS = re.compile(r"[\s-]")
_CHECK_NUMBER = re.compile(r"^[A-Za-z0-9-]{1,12}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9:_.\-]{1,200}$")
_DESIGNATION = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_PROVIDER_ID = re.compile(r"^[A-Za-z0-9_]{1,255}$")
_FAILURE_CODE = re.compile(r"^[a-z0-9_]{1,60}$")

# Error codes a redelivery can plausibly fix without anyone changing data.
_RETRYABLE_WEBHOOK_ERRORS = frozenset({"WEBHOOK_UNKNOWN_PAYMENT"})

_WEBHOOK_ERROR_MESSAGES: dict[str, str] = {
    "WEBHOOK_UNKNOWN_MEMBERSHIP": (
        "The payment names a membership that does not exist in this society. Confirm the member record, "
        "then resend the event from the Stripe dashboard (Developers > Events > Resend)."
    ),
    "WEBHOOK_UNKNOWN_CONSTITUENT": (
        "The payment names a person who does not exist in this society. Confirm the person record, then "
        "resend the event from the Stripe dashboard."
    ),
    "WEBHOOK_CONSTITUENT_MISMATCH": (
        "The payment's person and membership do not belong together. Check the checkout link that was sent "
        "to the member; do not resend until the records are corrected."
    ),
    "WEBHOOK_METADATA_INVALID": (
        "The payment is missing Orchid Continuum metadata (purpose, membership or person). It was probably "
        "created outside Orchid Continuum; record it manually as an offline payment if it is genuine."
    ),
    "WEBHOOK_UNKNOWN_PAYMENT": (
        "A refund or failure arrived before the payment itself was recorded. It is retried automatically; "
        "if it persists, resend the original payment event from the Stripe dashboard first."
    ),
    "WEBHOOK_AMOUNT_MISSING": "The provider event carried no amount or currency. Contact support with the event id.",
    "WEBHOOK_PAYMENT_REF_MISSING": (
        "The provider event carried no payment intent id. Only one-time Checkout payments are supported."
    ),
    "WEBHOOK_PAYMENT_REF_CONFLICT": (
        "This provider payment id is already recorded elsewhere. Contact support with the event id; do not "
        "record it manually."
    ),
    "REFUND_EXCEEDS_REMAINING": (
        "The provider reports more refunded than the ledger's payment amount. Reconcile this payment."
    ),
}
_DEFAULT_WEBHOOK_MESSAGE = (
    "Processing failed. Review the error code, correct the records, and resend the event from the provider "
    "dashboard. A processed event is never applied twice."
)


class PaymentError(ValueError):
    """A payment request that is refused; ``code`` is stable and safe to show."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class WebhookSignatureError(ValueError):
    """Missing, malformed, expired, or non-matching provider signature. Nothing is written."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def contains_card_like_number(value: str | None) -> bool:
    """True when ``value`` holds a 13+ digit run once spaces/dashes are removed."""
    if not value:
        return False
    return bool(_PAN_LIKE.search(_SEPARATORS.sub("", value)))


# ---------------------------------------------------------------------------
# Provider-neutral events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OCPaymentMetadata:
    """Orchid Continuum routing metadata, read only from a signature-verified payload."""

    organization_id: int | None = None
    membership_id: int | None = None
    constituent_id: int | None = None
    purpose: str | None = None
    renewal_key: str | None = None
    designation: str | None = None
    invalid_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderEvent:
    provider: str
    provider_event_id: str
    provider_event_type: str
    # payment.succeeded | payment.pending | payment.failed | payment.refunded | unsupported
    kind: str
    payload_sha256: str
    provider_payment_ref: str | None = None
    amount_cents: int | None = None
    currency: str | None = None
    refunded_amount_cents: int | None = None
    provider_refund_ref: str | None = None
    failure_code: str | None = None
    occurred_at: datetime | None = None
    livemode: bool = False
    metadata: OCPaymentMetadata = field(default_factory=OCPaymentMetadata)


class PaymentProvider(Protocol):
    name: str

    def verify_and_parse(self, payload: bytes, signature_header: str | None, now: float) -> ProviderEvent:
        """Verify authenticity first; raise ``WebhookSignatureError`` before parsing anything."""


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdigit() and len(value) <= 18:
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _provider_id(value: Any) -> str | None:
    if isinstance(value, dict):  # expanded object
        value = value.get("id")
    if isinstance(value, str) and _PROVIDER_ID.fullmatch(value):
        return value
    return None


def _parse_oc_metadata(raw: Any) -> OCPaymentMetadata:
    if not isinstance(raw, dict):
        return OCPaymentMetadata()
    invalid: list[str] = []

    def number(key: str) -> int | None:
        if key not in raw or raw[key] in (None, ""):
            return None
        parsed = _positive_int(raw[key])
        if parsed is None:
            invalid.append(key)
        return parsed

    def text(key: str, pattern: re.Pattern[str]) -> str | None:
        value = raw.get(key)
        if value in (None, ""):
            return None
        if not isinstance(value, str) or not pattern.fullmatch(value):
            invalid.append(key)
            return None
        return value

    organization_id = number("oc_organization_id")
    membership_id = number("oc_membership_id")
    constituent_id = number("oc_constituent_id")
    purpose = raw.get("oc_purpose") or None
    if purpose is not None and purpose not in PURPOSES:
        invalid.append("oc_purpose")
        purpose = None
    return OCPaymentMetadata(
        organization_id=organization_id,
        membership_id=membership_id,
        constituent_id=constituent_id,
        purpose=purpose,
        renewal_key=text("oc_renewal_key", _IDEMPOTENCY_KEY),
        designation=text("oc_designation", _DESIGNATION),
        invalid_fields=tuple(invalid),
    )


class StripeWebhookAdapter:
    """Verifies ``Stripe-Signature`` and maps Stripe events to ``ProviderEvent``.

    Header format: ``t=<unix ts>,v1=<hex HMAC-SHA256(secret, f"{t}.{payload}")>[,v1=...]``.
    Several ``v1`` values are accepted (Stripe sends one per active secret during a
    secret roll). The timestamp must be within ``tolerance_seconds`` of ``now`` in
    either direction, and comparison is constant time. No network calls are made.
    """

    name = "stripe"

    def __init__(self, secret: str, *, tolerance_seconds: int = STRIPE_SIGNATURE_TOLERANCE_SECONDS) -> None:
        if not isinstance(secret, str) or not secret.strip():
            raise ValueError("STRIPE_WEBHOOK_SECRET_REQUIRED")
        self.__secret = secret.encode("utf-8")
        self._tolerance = int(tolerance_seconds)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> StripeWebhookAdapter:
        value = (environ if environ is not None else os.environ).get(STRIPE_WEBHOOK_SECRET_ENV, "")
        if not value.strip():
            raise ValueError("STRIPE_WEBHOOK_SECRET_NOT_CONFIGURED")
        return cls(value)

    def __repr__(self) -> str:  # never reveal the secret
        return f"StripeWebhookAdapter(tolerance_seconds={self._tolerance})"

    # -- signature ---------------------------------------------------------------------

    def verify(self, payload: bytes, signature_header: str | None, now: float) -> None:
        if not isinstance(payload, (bytes, bytearray)):
            raise WebhookSignatureError("WEBHOOK_PAYLOAD_MUST_BE_BYTES")
        if len(payload) > MAX_WEBHOOK_PAYLOAD_BYTES:
            raise WebhookSignatureError("WEBHOOK_PAYLOAD_TOO_LARGE")
        if not signature_header or not signature_header.strip():
            raise WebhookSignatureError("WEBHOOK_SIGNATURE_MISSING")
        timestamp: int | None = None
        candidates: list[str] = []
        for item in signature_header.split(","):
            key, sep, value = item.strip().partition("=")
            if not sep:
                continue
            if key == "t":
                if timestamp is not None or not value.isdigit() or len(value) > 12:
                    raise WebhookSignatureError("WEBHOOK_SIGNATURE_MALFORMED")
                timestamp = int(value)
            elif key == "v1" and value:
                candidates.append(value)
        if timestamp is None or not candidates:
            raise WebhookSignatureError("WEBHOOK_SIGNATURE_MALFORMED")
        if abs(float(now) - timestamp) > self._tolerance:
            raise WebhookSignatureError("WEBHOOK_SIGNATURE_EXPIRED")
        expected = hmac.new(self.__secret, str(timestamp).encode("ascii") + b"." + bytes(payload),
                            hashlib.sha256).hexdigest()
        matched = False
        for candidate in candidates:  # compare every candidate; no early exit
            matched |= hmac.compare_digest(expected, candidate.strip().lower())
        if not matched:
            raise WebhookSignatureError("WEBHOOK_SIGNATURE_MISMATCH")

    # -- parsing -----------------------------------------------------------------------

    def verify_and_parse(self, payload: bytes, signature_header: str | None, now: float) -> ProviderEvent:
        self.verify(payload, signature_header, now)
        try:
            document = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebhookSignatureError("WEBHOOK_PAYLOAD_NOT_JSON") from exc
        if not isinstance(document, dict):
            raise WebhookSignatureError("WEBHOOK_PAYLOAD_NOT_JSON")
        event_id = _provider_id(document.get("id"))
        event_type = document.get("type")
        if event_id is None or not isinstance(event_type, str) or not (1 <= len(event_type) <= 100):
            raise WebhookSignatureError("WEBHOOK_EVENT_ENVELOPE_INVALID")
        data = document.get("data") if isinstance(document.get("data"), dict) else {}
        obj = data.get("object") if isinstance(data.get("object"), dict) else {}
        created = _non_negative_int(document.get("created"))
        base = {
            "provider": self.name,
            "provider_event_id": event_id,
            "provider_event_type": event_type,
            "payload_sha256": hashlib.sha256(bytes(payload)).hexdigest(),
            "occurred_at": datetime.fromtimestamp(created, tz=timezone.utc) if created is not None else None,
            "livemode": bool(document.get("livemode", False)),
            "metadata": _parse_oc_metadata(obj.get("metadata")),
        }
        currency = obj.get("currency")
        currency = currency.upper() if isinstance(currency, str) and _CURRENCY.fullmatch(currency.upper()) else None

        if event_type == "checkout.session.completed":
            payment_status = obj.get("payment_status")
            kind = {"paid": "payment.succeeded", "unpaid": "payment.pending"}.get(payment_status, "unsupported")
            return ProviderEvent(
                kind=kind, provider_payment_ref=_provider_id(obj.get("payment_intent")),
                amount_cents=_positive_int(obj.get("amount_total")), currency=currency, **base,
            )
        if event_type == "payment_intent.succeeded":
            return ProviderEvent(
                kind="payment.succeeded", provider_payment_ref=_provider_id(obj.get("id")),
                amount_cents=_positive_int(obj.get("amount_received")) or _positive_int(obj.get("amount")),
                currency=currency, **base,
            )
        if event_type == "payment_intent.payment_failed":
            error = obj.get("last_payment_error") if isinstance(obj.get("last_payment_error"), dict) else {}
            code = error.get("code") if isinstance(error.get("code"), str) else None
            return ProviderEvent(
                kind="payment.failed", provider_payment_ref=_provider_id(obj.get("id")),
                amount_cents=_positive_int(obj.get("amount")), currency=currency,
                failure_code=code if code and _FAILURE_CODE.fullmatch(code) else None, **base,
            )
        if event_type == "charge.refunded":
            refunds = obj.get("refunds") if isinstance(obj.get("refunds"), dict) else {}
            refund_items = refunds.get("data") if isinstance(refunds.get("data"), list) else []
            latest = _provider_id(refund_items[0]) if refund_items else None
            return ProviderEvent(
                kind="payment.refunded", provider_payment_ref=_provider_id(obj.get("payment_intent")),
                amount_cents=_positive_int(obj.get("amount")), currency=currency,
                refunded_amount_cents=_non_negative_int(obj.get("amount_refunded")),
                provider_refund_ref=latest, **base,
            )
        return ProviderEvent(kind="unsupported", **base)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _amount(value: Any, code: str = "INVALID_AMOUNT") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > _MAX_AMOUNT_CENTS:
        raise PaymentError(code)
    return value


def _currency(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    if not _CURRENCY.fullmatch(normalized):
        raise PaymentError("INVALID_CURRENCY")
    return normalized


def _idempotency_key(value: Any) -> str:
    key = str(value or "").strip()
    if not _IDEMPOTENCY_KEY.fullmatch(key):
        raise PaymentError("IDEMPOTENCY_KEY_REQUIRED")
    return key


def _free_text(value: str | None, *, limit: int = 500, required: bool = False, code: str = "INVALID_TEXT") -> str | None:
    if value is None:
        if required:
            raise PaymentError(code)
        return None
    cleaned = " ".join(str(value).split())
    if len(cleaned) > limit:
        raise PaymentError(f"{code}_TOO_LONG")
    if required and not cleaned:
        raise PaymentError(code)
    if contains_card_like_number(cleaned):
        raise PaymentError("CARD_LIKE_NUMBER_REJECTED")
    return cleaned or None


def _check_number(value: str | None, method: str) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    if method != "check":
        raise PaymentError("CHECK_NUMBER_ONLY_FOR_CHECKS")
    cleaned = str(value).strip()
    if contains_card_like_number(cleaned):
        raise PaymentError("CARD_LIKE_NUMBER_REJECTED")
    if not _CHECK_NUMBER.fullmatch(cleaned):
        raise PaymentError("INVALID_CHECK_NUMBER")
    return cleaned


def _received_at(value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise PaymentError("RECEIVED_AT_TIMEZONE_REQUIRED")
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _format_money(amount_cents: int, currency: str) -> str:
    return f"{currency} {amount_cents // 100:,}.{amount_cents % 100:02d}"


_METHOD_LABELS = {
    "check": "Check",
    "cash": "Cash",
    "other_offline": "Other (offline)",
    "card_provider": "Card (online)",
    "bank_transfer_provider": "Bank transfer (online)",
}


# ---------------------------------------------------------------------------
# Ledger service
# ---------------------------------------------------------------------------


class PaymentLedgerService:
    """Authorized, tenant-scoped payment ledger. See module docstring for policy."""

    def __init__(
        self,
        repository: PostgresSocietyCRMRepository,
        crm: SocietyCRMService,
        *,
        connect: ConnectionFactory | None = None,
    ) -> None:
        self._repo = repository
        self._crm = crm
        # Same connection factory as the CRM repository by default, so a payment and the
        # renewal it triggers share one connection (and one transaction).
        self._connect: ConnectionFactory = connect or repository._connect  # noqa: SLF001

    # -- plumbing ------------------------------------------------------------------------

    @contextmanager
    def _unit(self, organization_id: int) -> Iterator[tuple[psycopg.Connection, psycopg.Cursor]]:
        conn = self._connect()
        try:
            with tenant_transaction(organization_id, connect=self._connect, connection=conn) as cur:
                yield conn, cur
        finally:
            conn.close()

    def _caps(self, organization_id: int, principal: CRMPrincipal) -> frozenset[SocietyCapability]:
        return capabilities_for_roles(self._crm.roles(organization_id, principal))

    def _require(self, organization_id: int, principal: CRMPrincipal, capability: SocietyCapability) -> None:
        require_capability(self._crm.roles(organization_id, principal), capability)

    @staticmethod
    def _audit(cur, *, organization_id: int, actor_subject: str, action: str, entity_type: str, entity_id: str,
               before_state: dict[str, Any] | None = None, after_state: dict[str, Any] | None = None,
               metadata: dict[str, Any] | None = None) -> None:
        cur.execute(
            """
            INSERT INTO oc_constituent.crm_audit_events
                (organization_id, actor_subject, action, entity_type, entity_id,
                 before_state, after_state, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (organization_id, actor_subject, action, entity_type, entity_id,
             Jsonb(_jsonable(before_state)) if before_state is not None else None,
             Jsonb(_jsonable(after_state)) if after_state is not None else None,
             Jsonb(_jsonable(metadata or {}))),
        )

    @staticmethod
    def _event(cur, *, organization_id: int, payment_id: int, from_status: str | None, to_status: str,
               reason: str, actor_subject: str, amount_cents: int | None = None,
               provider_event_id: str | None = None) -> None:
        cur.execute(
            """
            INSERT INTO oc_constituent.payment_events
                (organization_id, payment_id, from_status, to_status, reason, amount_cents,
                 actor_subject, provider_event_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (organization_id, payment_id, from_status, to_status, reason, amount_cents, actor_subject,
             provider_event_id),
        )

    @staticmethod
    def _payment_by_key(cur, organization_id: int, key: str) -> dict[str, Any] | None:
        cur.execute(
            "SELECT * FROM oc_constituent.payments WHERE organization_id = %s AND idempotency_key = %s FOR UPDATE",
            (organization_id, key),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _lock_payment(cur, organization_id: int, payment_id: int) -> dict[str, Any] | None:
        cur.execute(
            "SELECT * FROM oc_constituent.payments WHERE organization_id = %s AND id = %s FOR UPDATE",
            (organization_id, payment_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _membership(cur, organization_id: int, membership_id: int) -> dict[str, Any] | None:
        cur.execute(
            """
            SELECT m.id, m.constituent_id, m.level_code, m.status, l.dues_amount_cents, l.currency
            FROM oc_constituent.memberships m
            JOIN oc_constituent.membership_levels l
              ON l.organization_id = m.organization_id AND l.code = m.level_code
            WHERE m.organization_id = %s AND m.id = %s
            """,
            (organization_id, membership_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _constituent_exists(cur, organization_id: int, constituent_id: int) -> bool:
        cur.execute(
            "SELECT 1 FROM oc_constituent.constituents WHERE owner_organization_id = %s AND id = %s",
            (organization_id, constituent_id),
        )
        return cur.fetchone() is not None

    @staticmethod
    def _insert_payment(cur, **values: Any) -> dict[str, Any] | None:
        columns = list(values)
        cur.execute(
            f"INSERT INTO oc_constituent.payments ({', '.join(columns)}) "
            f"VALUES ({', '.join(['%s'] * len(columns))}) ON CONFLICT DO NOTHING RETURNING *",
            [values[c] for c in columns],
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def _renew_for_payment(self, conn, cur, *, organization_id: int, payment: dict[str, Any], source_kind: str,
                           actor: str, as_of: datetime) -> dict[str, Any]:
        result = self._repo.renew_membership(
            organization_id=organization_id, membership_id=int(payment["membership_id"]),
            renewal_key=f"payment:{payment['id']}", source_kind=source_kind, actor_subject=actor,
            source_ref=str(payment["id"]), as_of=as_of, connection=conn,
        )
        cur.execute(
            "UPDATE oc_constituent.payments SET renewal_id = %s, updated_at = NOW() "
            "WHERE organization_id = %s AND id = %s RETURNING *",
            (result["renewal"]["id"], organization_id, payment["id"]),
        )
        payment.update(dict(cur.fetchone()))
        return result

    @staticmethod
    def _dues_check(membership: dict[str, Any] | None, amount_cents: int, currency: str) -> dict[str, Any]:
        if membership is None:
            return {"dues_mismatch": False, "expected_dues_cents": None}
        expected = int(membership["dues_amount_cents"])
        mismatch = expected != amount_cents or str(membership["currency"]).strip() != currency
        return {"dues_mismatch": mismatch, "expected_dues_cents": expected,
                "expected_currency": str(membership["currency"]).strip()}

    def _allocate_receipt_number(self, cur, organization_id: int) -> int:
        # The counter row is locked by this transaction until COMMIT, so concurrent
        # donations in one organization serialize and numbers are gap-free on commit
        # (a rolled-back donation also rolls back its increment).
        cur.execute(
            """
            INSERT INTO oc_constituent.donation_receipt_counters (organization_id, last_receipt_number)
            VALUES (%s, 1)
            ON CONFLICT (organization_id) DO UPDATE
               SET last_receipt_number = oc_constituent.donation_receipt_counters.last_receipt_number + 1,
                   updated_at = NOW()
            RETURNING last_receipt_number
            """,
            (organization_id,),
        )
        return int(cur.fetchone()["last_receipt_number"])

    def _insert_donation(self, cur, *, organization_id: int, payment: dict[str, Any], designation: str,
                         tax_deductible_cents: int, is_anonymous_to_public: bool, actor: str) -> dict[str, Any]:
        receipt_number = self._allocate_receipt_number(cur, organization_id)
        cur.execute(
            """
            INSERT INTO oc_constituent.donations
                (organization_id, constituent_id, payment_id, amount_cents, currency, designation,
                 is_anonymous_to_public, tax_deductible_cents, receipt_number, receipt_issued_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING *
            """,
            (organization_id, payment["constituent_id"], payment["id"], payment["amount_cents"],
             payment["currency"], designation, is_anonymous_to_public, tax_deductible_cents, receipt_number),
        )
        donation = dict(cur.fetchone())
        self._audit(cur, organization_id=organization_id, actor_subject=actor, action="donation.recorded",
                    entity_type="donation", entity_id=str(donation["id"]), after_state=donation,
                    metadata={"payment_id": payment["id"], "receipt_number": receipt_number})
        return donation

    # -- offline payments ----------------------------------------------------------------

    def record_offline_payment(
        self,
        principal: CRMPrincipal,
        organization_id: int,
        *,
        constituent_id: int,
        amount_cents: int,
        currency: str,
        method: str,
        received_at: datetime,
        idempotency_key: str,
        membership_id: int | None = None,
        check_number: str | None = None,
        purpose: str = "membership_dues",
        renew: bool = True,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Record a check/cash payment; dues renew the membership in the same transaction.

        A repeated ``idempotency_key`` returns the original payment and never renews
        twice. A different payment reusing the key is refused (IDEMPOTENCY_KEY_CONFLICT).
        """
        self._require(organization_id, principal, SocietyCapability.PAYMENT_WRITE)
        if method not in OFFLINE_METHODS:
            raise PaymentError("INVALID_OFFLINE_METHOD")
        if purpose not in PURPOSES:
            raise PaymentError("INVALID_PAYMENT_PURPOSE")
        if purpose == "donation":
            raise PaymentError("USE_RECORD_DONATION")
        amount = _amount(amount_cents)
        cur_code = _currency(currency)
        key = _idempotency_key(idempotency_key)
        check = _check_number(check_number, method)
        note = _free_text(notes, code="INVALID_NOTES")
        received = _received_at(received_at)
        will_renew = purpose == "membership_dues" and renew
        if will_renew and membership_id is None:
            raise PaymentError("PAYMENT_MEMBERSHIP_REQUIRED_FOR_RENEWAL")
        actor = principal.subject

        with self._unit(organization_id) as (conn, cur):
            existing = self._payment_by_key(cur, organization_id, key)
            if existing is None:
                if not self._constituent_exists(cur, organization_id, constituent_id):
                    raise NotFound("CONSTITUENT_NOT_FOUND")
                membership = None
                if membership_id is not None:
                    membership = self._membership(cur, organization_id, membership_id)
                    if membership is None:
                        raise NotFound("MEMBERSHIP_NOT_FOUND")
                    if int(membership["constituent_id"]) != constituent_id:
                        raise PaymentError("PAYMENT_MEMBERSHIP_CONSTITUENT_MISMATCH")
                payment = self._insert_payment(
                    cur, organization_id=organization_id, constituent_id=constituent_id,
                    membership_id=membership_id, purpose=purpose, amount_cents=amount, currency=cur_code,
                    method=method, check_number=check, status="succeeded", received_at=received,
                    recorded_by_subject=actor, idempotency_key=key, notes=note,
                )
                if payment is None:  # a concurrent request with the same key committed first
                    existing = self._payment_by_key(cur, organization_id, key)
                    if existing is None:
                        raise PaymentError("PAYMENT_CONFLICT")
            if existing is not None:
                if (existing["constituent_id"], existing["membership_id"], existing["amount_cents"],
                        existing["currency"].strip(), existing["method"], existing["purpose"]) != (
                        constituent_id, membership_id, amount, cur_code, method, purpose):
                    raise PaymentError("IDEMPOTENCY_KEY_CONFLICT")
                membership = self._membership(cur, organization_id, membership_id) if membership_id else None
                return {"created": False, "payment": existing, "renewal_applied": False,
                        **(self._dues_check(membership, amount, cur_code) if purpose == "membership_dues" else
                           {"dues_mismatch": False, "expected_dues_cents": None})}

            self._event(cur, organization_id=organization_id, payment_id=payment["id"], from_status=None,
                        to_status="succeeded", reason=f"offline_{method}_recorded", actor_subject=actor,
                        amount_cents=amount)
            dues = self._dues_check(membership, amount, cur_code) if purpose == "membership_dues" else {
                "dues_mismatch": False, "expected_dues_cents": None}
            renewal = None
            if will_renew:
                renewal = self._renew_for_payment(conn, cur, organization_id=organization_id, payment=payment,
                                                  source_kind="offline_payment", actor=actor, as_of=received)
            self._audit(cur, organization_id=organization_id, actor_subject=actor, action="payment.recorded",
                        entity_type="payment", entity_id=str(payment["id"]), after_state=payment,
                        metadata={"method": method, "purpose": purpose, "renewal_applied": renewal is not None,
                                  **dues})
            return {"created": True, "payment": payment, "renewal_applied": bool(renewal and renewal["applied"]),
                    "renewal": renewal["renewal"] if renewal else None,
                    "membership": renewal["membership"] if renewal else None, **dues}

    # -- donations -----------------------------------------------------------------------

    def record_donation(
        self,
        principal: CRMPrincipal,
        organization_id: int,
        *,
        constituent_id: int,
        amount_cents: int,
        currency: str,
        method: str,
        designation: str,
        idempotency_key: str,
        received_at: datetime,
        tax_deductible_cents: int | None = None,
        check_number: str | None = None,
        is_anonymous_to_public: bool = False,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Payment (purpose donation) + donation + sequential receipt number, atomically.

        ``tax_deductible_cents`` defaults to the full amount (no goods or services
        provided); pass a lower value when the donor received something in return.
        """
        self._require(organization_id, principal, SocietyCapability.DONATION_WRITE)
        if method not in OFFLINE_METHODS:
            raise PaymentError("INVALID_OFFLINE_METHOD")
        amount = _amount(amount_cents)
        cur_code = _currency(currency)
        key = _idempotency_key(idempotency_key)
        check = _check_number(check_number, method)
        note = _free_text(notes, code="INVALID_NOTES")
        received = _received_at(received_at)
        fund = str(designation or "").strip().lower()
        if not _DESIGNATION.fullmatch(fund):
            raise PaymentError("INVALID_DESIGNATION")
        deductible = amount if tax_deductible_cents is None else tax_deductible_cents
        if isinstance(deductible, bool) or not isinstance(deductible, int) or not 0 <= deductible <= amount:
            raise PaymentError("INVALID_TAX_DEDUCTIBLE_AMOUNT")
        actor = principal.subject

        with self._unit(organization_id) as (_conn, cur):
            existing = self._payment_by_key(cur, organization_id, key)
            if existing is None:
                if not self._constituent_exists(cur, organization_id, constituent_id):
                    raise NotFound("CONSTITUENT_NOT_FOUND")
                payment = self._insert_payment(
                    cur, organization_id=organization_id, constituent_id=constituent_id, purpose="donation",
                    amount_cents=amount, currency=cur_code, method=method, check_number=check,
                    status="succeeded", received_at=received, recorded_by_subject=actor,
                    idempotency_key=key, notes=note,
                )
                if payment is None:
                    existing = self._payment_by_key(cur, organization_id, key)
                    if existing is None:
                        raise PaymentError("PAYMENT_CONFLICT")
            if existing is not None:
                if (existing["purpose"], existing["constituent_id"], existing["amount_cents"]) != (
                        "donation", constituent_id, amount):
                    raise PaymentError("IDEMPOTENCY_KEY_CONFLICT")
                cur.execute("SELECT * FROM oc_constituent.donations WHERE organization_id = %s AND payment_id = %s",
                            (organization_id, existing["id"]))
                donation = cur.fetchone()
                return {"created": False, "payment": existing, "donation": dict(donation) if donation else None}
            self._event(cur, organization_id=organization_id, payment_id=payment["id"], from_status=None,
                        to_status="succeeded", reason=f"offline_{method}_donation_recorded", actor_subject=actor,
                        amount_cents=amount)
            self._audit(cur, organization_id=organization_id, actor_subject=actor, action="payment.recorded",
                        entity_type="payment", entity_id=str(payment["id"]), after_state=payment,
                        metadata={"method": method, "purpose": "donation"})
            donation = self._insert_donation(cur, organization_id=organization_id, payment=payment,
                                             designation=fund, tax_deductible_cents=deductible,
                                             is_anonymous_to_public=bool(is_anonymous_to_public), actor=actor)
            return {"created": True, "payment": payment, "donation": donation}

    # -- receipts ------------------------------------------------------------------------

    def get_receipt(self, principal: CRMPrincipal, organization_id: int, payment_id: int) -> dict[str, Any]:
        """Structured receipt data (no PDF). Omits check numbers and provider ids."""
        caps = self._caps(organization_id, principal)
        if SocietyCapability.PAYMENT_READ not in caps and SocietyCapability.DONATION_READ not in caps:
            raise SocietyAccessDenied(SocietyCapability.PAYMENT_READ)
        with self._unit(organization_id) as (_conn, cur):
            cur.execute(
                """
                SELECT p.*, c.display_name AS payer_name, o.display_name AS organization_name,
                       d.receipt_number, d.receipt_issued_at, d.designation, d.tax_deductible_cents,
                       d.id AS donation_id
                FROM oc_constituent.payments p
                JOIN oc_constituent.organizations o ON o.id = p.organization_id
                JOIN oc_constituent.constituents c
                  ON c.id = p.constituent_id AND c.owner_organization_id = p.organization_id
                LEFT JOIN oc_constituent.donations d
                  ON d.organization_id = p.organization_id AND d.payment_id = p.id
                WHERE p.organization_id = %s AND p.id = %s
                """,
                (organization_id, payment_id),
            )
            row = cur.fetchone()
        if row is None:
            raise NotFound("PAYMENT_NOT_FOUND")
        is_donation = row["purpose"] == "donation"
        needed = SocietyCapability.DONATION_READ if is_donation else SocietyCapability.PAYMENT_READ
        if needed not in caps:
            raise SocietyAccessDenied(needed)
        currency = row["currency"].strip()
        receipt: dict[str, Any] = {
            "organization_name": row["organization_name"],
            "payment_id": row["id"],
            "payer_name": row["payer_name"],
            "purpose": row["purpose"],
            "received_date": row["received_at"].date().isoformat(),
            "amount_cents": row["amount_cents"],
            "currency": currency,
            "amount_display": _format_money(row["amount_cents"], currency),
            "method": _METHOD_LABELS[row["method"]],
            "status": row["status"],
            "refunded_amount_cents": row["refunded_amount_cents"],
        }
        if is_donation and row["donation_id"] is not None:
            deductible = int(row["tax_deductible_cents"])
            goods = int(row["amount_cents"]) - deductible
            if goods == 0:
                statement = "No goods or services were provided in exchange for this contribution."
            else:
                statement = (
                    f"Goods or services with an estimated value of {_format_money(goods, currency)} were provided "
                    f"in exchange for this contribution. The deductible amount is {_format_money(deductible, currency)}."
                )
            receipt.update({
                "receipt_number": f"{int(row['receipt_number']):06d}",
                "receipt_issued_date": row["receipt_issued_at"].date().isoformat(),
                "designation": row["designation"],
                "tax_deductible_cents": deductible,
                "deductibility_statement": statement,
                "notice": ("Receipt wording and the organization's tax-exempt status must be confirmed by the "
                           "organization before receipts are sent to donors."),
            })
        else:
            receipt["receipt_number"] = f"P-{int(row['id']):06d}"
        return receipt

    # -- refunds and voids ---------------------------------------------------------------

    def _apply_refund(self, cur, *, organization_id: int, payment: dict[str, Any], amount_cents: int, reason: str,
                      idempotency_key: str, actor: str, provider_refund_ref: str | None = None,
                      provider_event_id: str | None = None) -> dict[str, Any]:
        if payment["status"] not in _REFUNDABLE:
            raise PaymentError(f"REFUND_NOT_ALLOWED_FROM_STATUS:{payment['status']}")
        remaining = int(payment["amount_cents"]) - int(payment["refunded_amount_cents"])
        if amount_cents > remaining:
            raise PaymentError("REFUND_EXCEEDS_REMAINING")
        total = int(payment["refunded_amount_cents"]) + amount_cents
        new_status = "refunded" if total == int(payment["amount_cents"]) else "partially_refunded"
        cur.execute(
            """
            INSERT INTO oc_constituent.refunds
                (organization_id, payment_id, amount_cents, reason, provider_refund_ref, status,
                 idempotency_key, recorded_by_subject)
            VALUES (%s, %s, %s, %s, %s, 'succeeded', %s, %s)
            RETURNING *
            """,
            (organization_id, payment["id"], amount_cents, reason, provider_refund_ref, idempotency_key, actor),
        )
        refund = dict(cur.fetchone())
        review = payment["renewal_id"] is not None
        cur.execute(
            """
            UPDATE oc_constituent.payments
            SET refunded_amount_cents = %s, status = %s,
                membership_review_required = membership_review_required OR %s, updated_at = NOW()
            WHERE organization_id = %s AND id = %s
            RETURNING *
            """,
            (total, new_status, review, organization_id, payment["id"]),
        )
        after = dict(cur.fetchone())
        self._event(cur, organization_id=organization_id, payment_id=payment["id"], from_status=payment["status"],
                    to_status=new_status, reason=f"refund:{reason}"[:500], actor_subject=actor,
                    amount_cents=amount_cents, provider_event_id=provider_event_id)
        self._audit(cur, organization_id=organization_id, actor_subject=actor, action="payment.refunded",
                    entity_type="payment", entity_id=str(payment["id"]), before_state=payment, after_state=after,
                    metadata={"refund_id": refund["id"], "amount_cents": amount_cents,
                              "membership_review_required": review})
        if review:
            # The renewal ledger is append-only and the refund policy is an owner decision:
            # flag for an administrator instead of silently shortening the membership.
            self._audit(cur, organization_id=organization_id, actor_subject=actor,
                        action="membership.review_required", entity_type="membership",
                        entity_id=str(payment["membership_id"]),
                        metadata={"payment_id": payment["id"], "refund_id": refund["id"],
                                  "renewal_id": payment["renewal_id"], "cause": "payment_refunded",
                                  "fully_refunded": new_status == "refunded"})
        return {"refund": refund, "payment": after, "membership_review_required": review}

    def refund(
        self,
        principal: CRMPrincipal,
        organization_id: int,
        payment_id: int,
        *,
        amount_cents: int,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Record a refund of an offline payment (money already returned by check/cash)."""
        self._require(organization_id, principal, SocietyCapability.PAYMENT_WRITE)
        amount = _amount(amount_cents, "INVALID_REFUND_AMOUNT")
        why = _free_text(reason, required=True, code="REFUND_REASON_REQUIRED")
        key = _idempotency_key(idempotency_key)
        with self._unit(organization_id) as (_conn, cur):
            cur.execute("SELECT * FROM oc_constituent.refunds WHERE organization_id = %s AND idempotency_key = %s",
                        (organization_id, key))
            prior = cur.fetchone()
            if prior is not None:
                if prior["payment_id"] != payment_id or prior["amount_cents"] != amount:
                    raise PaymentError("IDEMPOTENCY_KEY_CONFLICT")
                return {"created": False, "refund": dict(prior),
                        "payment": self._lock_payment(cur, organization_id, payment_id)}
            payment = self._lock_payment(cur, organization_id, payment_id)
            if payment is None:
                raise NotFound("PAYMENT_NOT_FOUND")
            if payment["provider"] is not None:
                raise PaymentError("PROVIDER_REFUND_MUST_BE_ISSUED_AT_PROVIDER")
            result = self._apply_refund(cur, organization_id=organization_id, payment=payment, amount_cents=amount,
                                        reason=why, idempotency_key=key, actor=principal.subject)
            return {"created": True, **result}

    def void(self, principal: CRMPrincipal, organization_id: int, payment_id: int, reason: str) -> dict[str, Any]:
        """Void an offline entry mistake that has had no downstream effect."""
        self._require(organization_id, principal, SocietyCapability.PAYMENT_WRITE)
        why = _free_text(reason, required=True, code="VOID_REASON_REQUIRED")
        with self._unit(organization_id) as (_conn, cur):
            payment = self._lock_payment(cur, organization_id, payment_id)
            if payment is None:
                raise NotFound("PAYMENT_NOT_FOUND")
            if payment["status"] == "voided":
                return {"changed": False, "payment": payment}
            if payment["provider"] is not None:
                raise PaymentError("PROVIDER_PAYMENT_CANNOT_BE_VOIDED")
            if payment["status"] != "succeeded" or payment["refunded_amount_cents"]:
                raise PaymentError(f"PAYMENT_VOID_NOT_ALLOWED_FROM_STATUS:{payment['status']}")
            if payment["renewal_id"] is not None:
                raise PaymentError("PAYMENT_RENEWAL_APPLIED_USE_REFUND")
            cur.execute("SELECT 1 FROM oc_constituent.donations WHERE organization_id = %s AND payment_id = %s",
                        (organization_id, payment_id))
            if cur.fetchone() is not None:
                raise PaymentError("PAYMENT_DONATION_RECEIPT_ISSUED_USE_REFUND")
            cur.execute(
                """
                UPDATE oc_constituent.payments
                SET status = 'voided', voided_at = NOW(), void_reason = %s, updated_at = NOW()
                WHERE organization_id = %s AND id = %s RETURNING *
                """,
                (why, organization_id, payment_id),
            )
            after = dict(cur.fetchone())
            self._event(cur, organization_id=organization_id, payment_id=payment_id, from_status="succeeded",
                        to_status="voided", reason=f"void:{why}"[:500], actor_subject=principal.subject)
            self._audit(cur, organization_id=organization_id, actor_subject=principal.subject,
                        action="payment.voided", entity_type="payment", entity_id=str(payment_id),
                        before_state=payment, after_state=after)
            return {"changed": True, "payment": after}

    # -- provider webhooks ---------------------------------------------------------------

    def handle_webhook(
        self,
        provider_adapter: PaymentProvider,
        payload: bytes,
        signature_header: str | None,
        now: float,
    ) -> dict[str, Any]:
        """Verify, deduplicate and apply one provider webhook delivery.

        * Signature failure raises ``WebhookSignatureError`` before any database access.
        * ``(provider, provider_event_id)`` is unique: a redelivery of a processed or
          ignored event returns ``{"status": "duplicate"}`` with zero side effects.
        * A ``failed`` event is reprocessed on redelivery (``attempts`` increments), so a
          transient failure can succeed later; money effects are keyed by the provider
          payment id and ``payment:<id>`` renewal key, so nothing is applied twice.
        """
        event = provider_adapter.verify_and_parse(payload, signature_header, now)  # raises first
        base = {"provider": event.provider, "provider_event_id": event.provider_event_id,
                "event_type": event.provider_event_type}
        if event.kind == "unsupported":
            return {**base, "status": "ignored", "reason": "UNSUPPORTED_EVENT_TYPE"}
        org_id = event.metadata.organization_id
        if org_id is None:
            logger.warning("payment webhook unroutable: provider=%s event=%s type=%s code=%s", event.provider,
                           event.provider_event_id, event.provider_event_type, "WEBHOOK_ORGANIZATION_METADATA_MISSING")
            return {**base, "status": "unroutable", "error_code": "WEBHOOK_ORGANIZATION_METADATA_MISSING",
                    "retryable": False}
        actor = normalize_auth_subject(f"system:{event.provider}-webhook")
        now_dt = datetime.fromtimestamp(float(now), tz=timezone.utc)

        conn = self._connect()
        try:
            with tenant_transaction(org_id, connect=self._connect, connection=conn) as cur:
                cur.execute("SELECT id FROM oc_constituent.organizations WHERE id = %s", (org_id,))
                if cur.fetchone() is None:
                    logger.warning("payment webhook unroutable: provider=%s event=%s code=%s", event.provider,
                                   event.provider_event_id, "WEBHOOK_UNKNOWN_ORGANIZATION")
                    return {**base, "status": "unroutable", "error_code": "WEBHOOK_UNKNOWN_ORGANIZATION",
                            "retryable": False}
                cur.execute(
                    """
                    INSERT INTO oc_constituent.provider_webhook_events
                        (organization_id, provider, provider_event_id, event_type, payload_sha256,
                         signature_verified, provider_payment_ref, amount_cents, currency)
                    VALUES (%s, %s, %s, %s, %s, TRUE, %s, %s, %s)
                    ON CONFLICT (provider, provider_event_id) DO NOTHING
                    RETURNING *
                    """,
                    (org_id, event.provider, event.provider_event_id, event.provider_event_type,
                     event.payload_sha256, event.provider_payment_ref, event.amount_cents, event.currency),
                )
                row = cur.fetchone()
                if row is None:
                    cur.execute(
                        "SELECT * FROM oc_constituent.provider_webhook_events "
                        "WHERE provider = %s AND provider_event_id = %s FOR UPDATE",
                        (event.provider, event.provider_event_id),
                    )
                    row = cur.fetchone()
                    if row is not None and row["payload_sha256"] != event.payload_sha256:
                        # Same event id, different signed body: never applied, never overwrites.
                        logger.warning("payment webhook payload changed: provider=%s event=%s", event.provider,
                                       event.provider_event_id)
                        return {**base, "status": "duplicate", "organization_id": org_id,
                                "note": "WEBHOOK_EVENT_PAYLOAD_CHANGED"}
                    if row is None or row["processing_status"] in ("processed", "ignored"):
                        return {**base, "status": "duplicate", "organization_id": org_id}
                webhook = dict(row)

                status, error_code, outcome = "processed", None, {}
                try:
                    with conn.transaction():  # savepoint: a failure leaves no partial money rows
                        outcome = self._apply_provider_event(conn, cur, org_id, event, actor, now_dt)
                        status = outcome.pop("status", "processed")
                except (PaymentError, NotFound, ValueError, LookupError) as exc:
                    status, error_code = "failed", (getattr(exc, "code", None) or str(exc) or type(exc).__name__)
                except psycopg.Error as exc:
                    status, error_code = "failed", f"WEBHOOK_DATABASE_REJECTED:{exc.sqlstate or 'unknown'}"
                error_code = error_code[:100] if error_code else None

                cur.execute(
                    """
                    UPDATE oc_constituent.provider_webhook_events
                    SET processing_status = %s, error_code = %s, attempts = attempts + 1,
                        last_attempt_at = NOW(), payment_id = COALESCE(%s, payment_id),
                        processed_at = CASE WHEN %s IN ('processed', 'ignored') THEN NOW() ELSE NULL END
                    WHERE organization_id = %s AND id = %s
                    RETURNING *
                    """,
                    (status, error_code, outcome.get("payment_id"), status, org_id, webhook["id"]),
                )
                webhook = dict(cur.fetchone())
                self._audit(cur, organization_id=org_id, actor_subject=actor, action=f"payment.webhook_{status}",
                            entity_type="provider_webhook_event", entity_id=str(webhook["id"]),
                            after_state={k: webhook[k] for k in ("provider", "provider_event_id", "event_type",
                                                                   "processing_status", "error_code", "attempts",
                                                                   "payment_id")},
                            metadata={k: v for k, v in outcome.items() if k != "payment_id"})
                if status == "failed":
                    logger.warning("payment webhook failed: provider=%s event=%s org=%s code=%s attempts=%s",
                                   event.provider, event.provider_event_id, org_id, error_code, webhook["attempts"])
                return {**base, "status": status, "organization_id": org_id, "webhook_event_id": webhook["id"],
                        "error_code": error_code, "attempts": webhook["attempts"],
                        "retryable": status == "failed" and error_code in _RETRYABLE_WEBHOOK_ERRORS,
                        **outcome}
        finally:
            conn.close()

    def _resolve_payer(self, cur, org_id: int, meta: OCPaymentMetadata) -> tuple[int, dict[str, Any] | None]:
        if meta.invalid_fields:
            raise PaymentError("WEBHOOK_METADATA_INVALID")
        purpose = meta.purpose
        if purpose is None:
            raise PaymentError("WEBHOOK_METADATA_INVALID")
        membership = None
        if meta.membership_id is not None:
            membership = self._membership(cur, org_id, meta.membership_id)
            if membership is None:
                raise PaymentError("WEBHOOK_UNKNOWN_MEMBERSHIP")
        elif purpose == "membership_dues":
            raise PaymentError("WEBHOOK_METADATA_INVALID")
        if meta.constituent_id is not None:
            if not self._constituent_exists(cur, org_id, meta.constituent_id):
                raise PaymentError("WEBHOOK_UNKNOWN_CONSTITUENT")
            if membership is not None and int(membership["constituent_id"]) != meta.constituent_id:
                raise PaymentError("WEBHOOK_CONSTITUENT_MISMATCH")
            return meta.constituent_id, membership
        if membership is None:
            raise PaymentError("WEBHOOK_METADATA_INVALID")
        return int(membership["constituent_id"]), membership

    def _provider_payment(self, cur, org_id: int, event: ProviderEvent) -> dict[str, Any] | None:
        cur.execute(
            "SELECT * FROM oc_constituent.payments "
            "WHERE organization_id = %s AND provider = %s AND provider_payment_ref = %s FOR UPDATE",
            (org_id, event.provider, event.provider_payment_ref),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def _apply_provider_event(self, conn, cur, org_id: int, event: ProviderEvent, actor: str,
                              now_dt: datetime) -> dict[str, Any]:
        if event.provider_payment_ref is None:
            raise PaymentError("WEBHOOK_PAYMENT_REF_MISSING")
        payment = self._provider_payment(cur, org_id, event)

        if event.kind == "payment.refunded":
            if payment is None:
                raise PaymentError("WEBHOOK_UNKNOWN_PAYMENT")
            if event.refunded_amount_cents is None:
                raise PaymentError("WEBHOOK_AMOUNT_MISSING")
            delta = event.refunded_amount_cents - int(payment["refunded_amount_cents"])
            if delta <= 0:
                return {"status": "processed", "payment_id": payment["id"], "outcome": "refund_already_recorded"}
            ref = event.provider_refund_ref
            if ref is not None:
                cur.execute("SELECT 1 FROM oc_constituent.refunds WHERE provider_refund_ref = %s", (ref,))
                if cur.fetchone() is not None:
                    ref = None  # cumulative total moved but the latest ref is already recorded
            result = self._apply_refund(cur, organization_id=org_id, payment=payment, amount_cents=delta,
                                        reason="provider_refund", idempotency_key=f"{event.provider}:{event.provider_event_id}",
                                        actor=actor, provider_refund_ref=ref, provider_event_id=event.provider_event_id)
            return {"status": "processed", "payment_id": payment["id"], "outcome": "refund_recorded",
                    "refund_id": result["refund"]["id"],
                    "membership_review_required": result["membership_review_required"]}

        target = {"payment.succeeded": "succeeded", "payment.pending": "pending",
                  "payment.failed": "failed"}[event.kind]
        if payment is not None:
            current = payment["status"]
            allowed = {("pending", "succeeded"), ("pending", "failed"), ("failed", "succeeded"),
                       ("failed", "pending")}
            if current == target or (current, target) not in allowed:
                # Never downgrade a settled payment on an out-of-order failed/pending event.
                return {"status": "processed", "payment_id": payment["id"], "outcome": f"already_{current}"}
            cur.execute(
                "UPDATE oc_constituent.payments SET status = %s, updated_at = NOW() "
                "WHERE organization_id = %s AND id = %s RETURNING *",
                (target, org_id, payment["id"]),
            )
            after = dict(cur.fetchone())
            self._event(cur, organization_id=org_id, payment_id=payment["id"], from_status=current, to_status=target,
                        reason=f"provider:{event.provider_event_type}"
                        + (f":{event.failure_code}" if event.failure_code else ""),
                        actor_subject=actor, amount_cents=event.amount_cents,
                        provider_event_id=event.provider_event_id)
            self._audit(cur, organization_id=org_id, actor_subject=actor, action="payment.status_changed",
                        entity_type="payment", entity_id=str(payment["id"]), before_state=payment, after_state=after)
            payment = after
            created = False
        else:
            constituent_id, membership = self._resolve_payer(cur, org_id, event.metadata)
            if event.amount_cents is None or event.currency is None:
                raise PaymentError("WEBHOOK_AMOUNT_MISSING")
            payment = self._insert_payment(
                cur, organization_id=org_id, constituent_id=constituent_id,
                membership_id=membership["id"] if membership else None, purpose=event.metadata.purpose,
                amount_cents=event.amount_cents, currency=event.currency, method="card_provider",
                provider=event.provider, provider_payment_ref=event.provider_payment_ref, status=target,
                received_at=event.occurred_at or now_dt, recorded_by_subject=actor,
                idempotency_key=f"{event.provider}:{event.provider_payment_ref}",
            )
            if payment is None:
                raise PaymentError("WEBHOOK_PAYMENT_REF_CONFLICT")
            self._event(cur, organization_id=org_id, payment_id=payment["id"], from_status=None, to_status=target,
                        reason=f"provider:{event.provider_event_type}"
                        + (f":{event.failure_code}" if event.failure_code else ""),
                        actor_subject=actor, amount_cents=event.amount_cents,
                        provider_event_id=event.provider_event_id)
            self._audit(cur, organization_id=org_id, actor_subject=actor, action="payment.recorded",
                        entity_type="payment", entity_id=str(payment["id"]), after_state=payment,
                        metadata={"method": "card_provider", "purpose": payment["purpose"],
                                  "provider_event_id": event.provider_event_id})
            created = True

        outcome: dict[str, Any] = {"status": "processed", "payment_id": payment["id"],
                                   "outcome": f"payment_{target}", "payment_created": created,
                                   "renewal_applied": False}
        if target != "succeeded":
            return outcome
        if payment["purpose"] == "membership_dues" and payment["membership_id"] is not None \
                and payment["renewal_id"] is None:
            membership = self._membership(cur, org_id, int(payment["membership_id"]))
            result = self._renew_for_payment(conn, cur, organization_id=org_id, payment=payment,
                                             source_kind="online_payment", actor=actor,
                                             as_of=event.occurred_at or now_dt)
            outcome.update({"renewal_applied": result["applied"], "renewal_id": result["renewal"]["id"],
                            **self._dues_check(membership, int(payment["amount_cents"]),
                                               payment["currency"].strip())})
        if payment["purpose"] == "donation":
            cur.execute("SELECT id FROM oc_constituent.donations WHERE organization_id = %s AND payment_id = %s",
                        (org_id, payment["id"]))
            if cur.fetchone() is None:
                donation = self._insert_donation(
                    cur, organization_id=org_id, payment=payment,
                    designation=event.metadata.designation or "general",
                    tax_deductible_cents=int(payment["amount_cents"]), is_anonymous_to_public=False, actor=actor,
                )
                outcome["donation_id"] = donation["id"]
        return outcome

    def failed_webhooks(self, principal: CRMPrincipal, organization_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
        """Administrator diagnostics: failed provider deliveries with actionable messages."""
        self._require(organization_id, principal, SocietyCapability.DIAGNOSTICS_READ)
        with self._unit(organization_id) as (_conn, cur):
            cur.execute(
                """
                SELECT id, provider, provider_event_id, event_type, provider_payment_ref, amount_cents, currency,
                       error_code, attempts, received_at, last_attempt_at
                FROM oc_constituent.provider_webhook_events
                WHERE organization_id = %s AND processing_status = 'failed'
                ORDER BY received_at DESC, id DESC LIMIT %s
                """,
                (organization_id, max(1, min(int(limit), _MAX_PAGE))),
            )
            rows = [dict(r) for r in cur.fetchall()]
        for row in rows:
            base_code = row["error_code"].split(":", 1)[0]
            row["message"] = _WEBHOOK_ERROR_MESSAGES.get(base_code, _DEFAULT_WEBHOOK_MESSAGE)
            row["retryable"] = base_code in _RETRYABLE_WEBHOOK_ERRORS
        return rows

    # -- reads ---------------------------------------------------------------------------

    def list_payments(
        self,
        principal: CRMPrincipal,
        organization_id: int,
        *,
        status: str | None = None,
        purpose: str | None = None,
        method: str | None = None,
        constituent_id: int | None = None,
        membership_id: int | None = None,
        membership_review_required: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        caps = self._caps(organization_id, principal)
        if SocietyCapability.PAYMENT_READ not in caps:
            raise SocietyAccessDenied(SocietyCapability.PAYMENT_READ)
        clauses, params = ["organization_id = %s"], [organization_id]
        if SocietyCapability.DONATION_READ not in caps:
            clauses.append("purpose <> 'donation'")
        for column, value in (("status", status), ("purpose", purpose), ("method", method),
                              ("constituent_id", constituent_id),
                              ("membership_id", membership_id),
                              ("membership_review_required", membership_review_required)):
            if value is not None:
                clauses.append(f"{column} = %s")
                params.append(value)
        where = " WHERE " + " AND ".join(clauses)
        with self._unit(organization_id) as (_conn, cur):
            cur.execute("SELECT count(*) AS n FROM oc_constituent.payments" + where, params)
            total = int(cur.fetchone()["n"])
            cur.execute(
                "SELECT * FROM oc_constituent.payments" + where + " ORDER BY received_at DESC, id DESC LIMIT %s OFFSET %s",
                [*params, max(1, min(int(limit), _MAX_PAGE)), max(0, int(offset))],
            )
            return [dict(r) for r in cur.fetchall()], total

    def get_payment(self, principal: CRMPrincipal, organization_id: int, payment_id: int) -> dict[str, Any]:
        """Payment with its full status history, refunds and donation (traceability)."""
        caps = self._caps(organization_id, principal)
        if SocietyCapability.PAYMENT_READ not in caps:
            raise SocietyAccessDenied(SocietyCapability.PAYMENT_READ)
        with self._unit(organization_id) as (_conn, cur):
            cur.execute("SELECT * FROM oc_constituent.payments WHERE organization_id = %s AND id = %s",
                        (organization_id, payment_id))
            payment = cur.fetchone()
            if payment is None or (payment["purpose"] == "donation" and SocietyCapability.DONATION_READ not in caps):
                raise NotFound("PAYMENT_NOT_FOUND")
            result = {"payment": dict(payment)}
            for key, table in (("events", "payment_events"), ("refunds", "refunds"), ("donations", "donations")):
                cur.execute(f"SELECT * FROM oc_constituent.{table} WHERE organization_id = %s AND payment_id = %s "
                            "ORDER BY id", (organization_id, payment_id))
                result[key] = [dict(r) for r in cur.fetchall()]
            return result

    def list_donations(self, principal: CRMPrincipal, organization_id: int, *, limit: int = 100,
                       offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        self._require(organization_id, principal, SocietyCapability.DONATION_READ)
        with self._unit(organization_id) as (_conn, cur):
            cur.execute("SELECT count(*) AS n FROM oc_constituent.donations WHERE organization_id = %s",
                        (organization_id,))
            total = int(cur.fetchone()["n"])
            cur.execute(
                """
                SELECT d.*, p.status AS payment_status, p.refunded_amount_cents, p.method,
                       c.display_name AS donor_name
                FROM oc_constituent.donations d
                JOIN oc_constituent.payments p ON p.organization_id = d.organization_id AND p.id = d.payment_id
                JOIN oc_constituent.constituents c
                  ON c.owner_organization_id = d.organization_id AND c.id = d.constituent_id
                WHERE d.organization_id = %s
                ORDER BY d.receipt_number DESC LIMIT %s OFFSET %s
                """,
                (organization_id, max(1, min(int(limit), _MAX_PAGE)), max(0, int(offset))),
            )
            return [dict(r) for r in cur.fetchall()], total

    # -- reconciliation ------------------------------------------------------------------

    def reconcile_payments(
        self,
        principal: CRMPrincipal,
        organization_id: int,
        provider_rows: Sequence[Mapping[str, Any]],
        *,
        provider: str = "stripe",
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict[str, Any]:
        """Compare a provider charge/payout export with the ledger. Read-only (audited).

        Each provider row: ``provider_payment_ref``, ``amount_cents``, ``status`` (one of
        the ledger statuses) and optionally ``currency``. ``since``/``until`` bound the
        ledger side by ``received_at`` so an export window compares like with like.
        """
        self._require(organization_id, principal, SocietyCapability.PAYMENT_READ)
        statuses = {"pending", "succeeded", "failed", "refunded", "partially_refunded"}
        provided: dict[str, dict[str, Any]] = {}
        duplicates: list[str] = []
        for raw in provider_rows:
            ref = _provider_id(raw.get("provider_payment_ref"))
            status = raw.get("status")
            amount = raw.get("amount_cents")
            if ref is None or status not in statuses or isinstance(amount, bool) or not isinstance(amount, int):
                raise PaymentError("PROVIDER_ROW_INVALID")
            if ref in provided:
                duplicates.append(ref)
                continue
            provided[ref] = {"provider_payment_ref": ref, "amount_cents": amount, "status": status,
                             "currency": (str(raw["currency"]).upper() if raw.get("currency") else None)}
        clauses, params = ["organization_id = %s", "provider = %s"], [organization_id, provider]
        if since is not None:
            clauses.append("received_at >= %s")
            params.append(since)
        if until is not None:
            clauses.append("received_at < %s")
            params.append(until)
        with self._unit(organization_id) as (_conn, cur):
            cur.execute("SELECT id, provider_payment_ref, amount_cents, currency, status FROM oc_constituent.payments "
                        "WHERE " + " AND ".join(clauses), params)
            ledger = {r["provider_payment_ref"]: dict(r) for r in cur.fetchall()}
            if since is not None or until is not None:
                # Provider rows outside the window may still be in the ledger.
                outside = [ref for ref in provided if ref not in ledger]
                if outside:
                    cur.execute("SELECT id, provider_payment_ref, amount_cents, currency, status "
                                "FROM oc_constituent.payments WHERE organization_id = %s AND provider = %s "
                                "AND provider_payment_ref = ANY(%s)", (organization_id, provider, outside))
                    for r in cur.fetchall():
                        ledger[r["provider_payment_ref"]] = dict(r)
            report: dict[str, Any] = {"missing_in_oc": [], "missing_in_provider": [], "amount_mismatch": [],
                                      "status_mismatch": [], "duplicate_in_provider": sorted(set(duplicates)),
                                      "matched": 0}
            for ref, row in sorted(provided.items()):
                mine = ledger.get(ref)
                if mine is None:
                    report["missing_in_oc"].append(row)
                    continue
                ok = True
                if mine["amount_cents"] != row["amount_cents"] or (
                        row["currency"] and row["currency"] != mine["currency"].strip()):
                    report["amount_mismatch"].append({"provider_payment_ref": ref, "payment_id": mine["id"],
                                                      "ledger_amount_cents": mine["amount_cents"],
                                                      "provider_amount_cents": row["amount_cents"]})
                    ok = False
                if mine["status"] != row["status"]:
                    report["status_mismatch"].append({"provider_payment_ref": ref, "payment_id": mine["id"],
                                                      "ledger_status": mine["status"],
                                                      "provider_status": row["status"]})
                    ok = False
                report["matched"] += int(ok)
            for ref, mine in sorted(ledger.items()):
                if ref not in provided:
                    report["missing_in_provider"].append({"provider_payment_ref": ref, "payment_id": mine["id"],
                                                          "amount_cents": mine["amount_cents"],
                                                          "status": mine["status"]})
            counts = {k: (len(v) if isinstance(v, list) else v) for k, v in report.items()}
            self._audit(cur, organization_id=organization_id, actor_subject=principal.subject,
                        action="payment.reconciliation_run", entity_type="organization",
                        entity_id=str(organization_id),
                        metadata={"provider": provider, "provider_rows": len(provider_rows), **counts})
            report["counts"] = counts
            return report


def _register_diagnostics() -> None:
    from .crm_diagnostics import register_organization_check

    @register_organization_check
    def payment_webhook_check(repo: PostgresSocietyCRMRepository, organization_id: int) -> list[dict[str, Any]]:
        with tenant_transaction(organization_id, connect=repo._connect) as cur:  # noqa: SLF001
            cur.execute(
                "SELECT count(*) AS n FROM oc_constituent.provider_webhook_events "
                "WHERE organization_id = %s AND processing_status = 'failed'",
                (organization_id,),
            )
            failed = int(cur.fetchone()["n"])
            cur.execute(
                "SELECT count(*) AS n FROM oc_constituent.payments "
                "WHERE organization_id = %s AND membership_review_required",
                (organization_id,),
            )
            review = int(cur.fetchone()["n"])
        results = [
            {"check": "payment_webhooks", "status": "warning",
             "message": f"{failed} online payment notification(s) could not be applied.",
             "action": "Open Payments > Failed notifications; each entry explains the fix. Stripe retries automatically for temporary problems.",
             "count": failed}
            if failed else
            {"check": "payment_webhooks", "status": "ok", "message": "All online payment notifications were applied.",
             "action": ""}
        ]
        if review:
            results.append({"check": "refund_membership_review", "status": "warning",
                            "message": f"{review} refunded dues payment(s) need a membership decision.",
                            "action": "Review each refunded member and decide whether to keep, shorten or cancel the membership.",
                            "count": review})
        return results


_register_diagnostics()
