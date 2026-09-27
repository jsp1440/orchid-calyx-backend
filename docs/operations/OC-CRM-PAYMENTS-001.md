# OC-CRM-PAYMENTS-001 — Society CRM payments, donations, and Stripe webhooks

Issue: #1656. Code: `app/constituent_platform/payments.py`,
`app/constituent_platform/payment_routes.py`. Schema:
`migrations/20260928_society_crm_money.sql`. Tests: `tests/test_society_crm_money.py`.

## 1. Model (provider-neutral)

| Table (`oc_constituent`) | Purpose | Runtime grants |
| --- | --- | --- |
| `payments` | One row per money movement: dues, donation, event, other. Offline (`check`, `cash`, `other_offline`) or provider (`card_provider`, `bank_transfer_provider`). Status: `pending`, `succeeded`, `failed`, `partially_refunded`, `refunded`, `voided`. | SELECT, INSERT, UPDATE |
| `payment_events` | Append-only status history (`from_status` → `to_status`, reason, actor, provider event id). | SELECT, INSERT |
| `refunds` | Append-only refunds; `payments.refunded_amount_cents` is bounded by a CHECK so over-refund is impossible. | SELECT, INSERT |
| `donations` | One per donation payment; per-organization sequential `receipt_number`. | SELECT, INSERT |
| `donation_receipt_counters` | Per-organization receipt allocator (row locked by the allocating transaction; gap-free on commit). | SELECT, INSERT, UPDATE |
| `provider_webhook_events` | Verified webhook deliveries: `UNIQUE (provider, provider_event_id)`, payload SHA-256, minimal parsed fields, `processing_status`, `error_code`, `attempts`. | SELECT, INSERT, UPDATE |

Every table has `organization_id`, composite tenant foreign keys to
`constituents (owner_organization_id, id)` / `memberships (organization_id, id)` /
`payments (organization_id, id)`, and the `oc_crm_tenant_isolation` RLS policy for
`oc_crm_runtime`. No DELETE grant exists anywhere.

Providers implement `PaymentProvider.verify_and_parse(payload, signature_header, now)`
and return a `ProviderEvent` (`payment.succeeded`, `payment.pending`, `payment.failed`,
`payment.refunded`, or `unsupported`). The ledger never handles provider SDK objects.
One provider exists: `StripeWebhookAdapter`, which makes **no network calls**.

### What is never stored

Card numbers, CVV, bank account/routing numbers, raw webhook payloads, and provider
secrets. Only the provider's opaque id (`pi_...`, `re_...`) is kept. Free text (notes,
reasons) containing a 13+ digit run (ignoring spaces/dashes) is refused by the service
(`CARD_LIKE_NUMBER_REJECTED`) and by a database CHECK. `check_number` is a paper check
serial of at most 12 characters. A test introspects `information_schema.columns` to
prove no card/cvv/pan/account/routing/secret column exists.

### Authorization (from `authorization.py`, unchanged)

* `payment.write` (treasurer, admin): record offline payments, refunds, voids.
* `donation.write` (treasurer, admin): record donations.
* `payment.read` / `donation.read`: lists, receipts, payment history. A payment-reader
  without `donation.read` does not see donation payments.
* `diagnostics.read` (admin only): failed webhook diagnostics.
* Ordinary members, `membership_editor`, `viewer`: no money access at all.

## 2. Behaviour and decisions

* **Offline dues renew in one transaction.** `record_offline_payment` inserts the
  payment, its status event, the renewal (`renew_membership(..., source_kind=
  'offline_payment', renewal_key='payment:<id>', connection=<same connection>)`), and
  the `payment.recorded` audit event atomically. A repeated `idempotency_key` returns
  the original payment and never renews twice; a different payment under a used key is
  refused (`IDEMPOTENCY_KEY_CONFLICT`).
* **Dues mismatch is flagged, not blocked** (`dues_mismatch`, `expected_dues_cents` in
  the result and audit metadata). Societies take discounted, partial, and overpaid
  dues by check; refusing them would push money off-ledger.
* **A refund does not shorten a membership.** The renewal ledger is append-only and
  "does a refund end the membership?" is a policy question (see §5). A refund of a dues
  payment that renewed a membership sets `payments.membership_review_required` and
  writes a `membership.review_required` audit event; an administrator decides (e.g.
  via the membership status workflow). `list_payments(..., membership_review_required=True)`
  is the work queue.
* **Void** is for offline data-entry mistakes with no downstream effect. It is refused
  once a renewal was applied (`PAYMENT_RENEWAL_APPLIED_USE_REFUND`), a donation receipt
  was issued (`PAYMENT_DONATION_RECEIPT_ISSUED_USE_REFUND`), a refund exists, or the
  payment is a provider payment.
* **Card refunds are issued in the Stripe dashboard**, not by this API
  (`PROVIDER_REFUND_MUST_BE_ISSUED_AT_PROVIDER`); the resulting `charge.refunded`
  webhook records them.
* **Receipts** (`get_receipt`) are structured data: organization name, receipt number,
  date, amount, method label (no check number, no provider id), designation, and a
  deductibility statement (full amount deductible unless `tax_deductible_cents` says
  goods/services were provided). No PDF.

## 3. Webhook processing

`handle_webhook(adapter, payload, signature_header, now)` runs as
`system:stripe-webhook`:

1. **Signature first.** `Stripe-Signature: t=<ts>,v1=<hex>` where
   `v1 = HMAC_SHA256(secret, f"{t}.{raw_body}")`. Multiple `v1` values are accepted
   (secret roll), comparison is constant time, and `|now - t| <= 300s`. Any failure raises
   `WebhookSignatureError` before database access; the route returns **400**.
2. **Routing metadata only from the signed payload.** When OC creates a Checkout
   Session it must set, on both the session `metadata` and
   `payment_intent_data.metadata` (so PaymentIntents and Charges carry it):
   `oc_organization_id`, `oc_purpose` (`membership_dues|donation|event|other`),
   `oc_membership_id` (dues), `oc_constituent_id`, optional `oc_designation`
   (donations) and `oc_renewal_key` (informational). Verified metadata is still
   re-checked against the tenant.
3. **Idempotency.** `INSERT ... ON CONFLICT (provider, provider_event_id) DO NOTHING`.
   A processed/ignored event redelivered returns `duplicate` with zero side effects. A
   different body under a used event id is never applied (`WEBHOOK_EVENT_PAYLOAD_CHANGED`).
   Money effects are additionally keyed by `idempotency_key = 'stripe:<pi_id>'` and the
   renewal key `payment:<payment_id>`, so `checkout.session.completed` and
   `payment_intent.succeeded` for the same payment produce one payment and one renewal.
4. **Events handled.**
   * `checkout.session.completed` (`payment_status=paid`) and `payment_intent.succeeded`
     → payment `succeeded` (+ renewal for dues, + donation/receipt for donations).
     `payment_status=unpaid` → `pending`.
   * `payment_intent.payment_failed` → `failed`; the membership is not activated. A later
     success on the same PaymentIntent moves `failed → succeeded` and renews once. A late
     failure never downgrades a settled payment.
   * `charge.refunded` → refund of the delta between Stripe's cumulative
     `amount_refunded` and the ledger total.
   * Anything else → `ignored`, nothing written.
5. **Failures and retries.** Domain failures roll back to a savepoint (no partial money
   rows), mark the event `failed` with an `error_code`, and audit
   `payment.webhook_failed`. Redelivery of a `failed` event reprocesses it (`attempts`
   increments). Codes a redelivery can fix (`WEBHOOK_UNKNOWN_PAYMENT`: a refund before
   its payment) return **503** so Stripe retries automatically; other recorded failures
   return **200** and appear in `failed_webhooks()` with an actionable message
   (e.g. `WEBHOOK_UNKNOWN_MEMBERSHIP`: metadata names a membership not in that society —
   including another society's membership, which is never re-routed).
6. **Unroutable events** (no/unknown `oc_organization_id`) write nothing (no tenant to
   own the row) and are logged with event id and type only.

## 4. Operator setup (Stripe)

Owner-gated: creating/authorizing the Stripe account and keys is an owner action.

1. In Stripe Dashboard → Developers → Webhooks, add an endpoint:
   `https://<backend-host>/api/society/webhooks/stripe` (the router in
   `app/constituent_platform/payment_routes.py`, once wired into `app/main.py`).
2. Select events: `checkout.session.completed`, `payment_intent.succeeded`,
   `payment_intent.payment_failed`, `charge.refunded`.
3. Copy the endpoint's signing secret (`whsec_...`) into the **Render** service
   environment as `OC_STRIPE_WEBHOOK_SECRET`. Never put it in GitHub (code, issues,
   Actions secrets for this purpose, or PR text), never in the CRM database, never in
   logs. Without it the endpoint returns 503 `WEBHOOK_NOT_CONFIGURED`.
4. Secret roll: Stripe signs with both secrets during the roll window; the adapter
   accepts any matching `v1`. Update the Render variable, then expire the old secret.
5. Test with Stripe test mode and "Send test webhook"; confirm the row in
   `provider_webhook_events` and, for a failed event, the admin diagnostics message.

## 5. Not implemented / owner decisions needed

* **Checkout Session creation** (calling the Stripe API with a secret key) is not
  implemented: it requires the owner to create/authorize a Stripe account and API keys.
  Until then, online payments only arrive via webhooks for sessions created elsewhere
  with the metadata in §3.2.
* **Refund policy (owner decision):** does a full or partial dues refund shorten or end
  the membership? Today: never automatically; `membership_review_required` is flagged.
* **Tax receipts (owner decision):** each society's tax-exempt status, legal name, and
  receipt wording must be confirmed before receipts are sent. Online donations default
  to fully deductible. A refunded donation keeps its receipt number; whether a
  corrected receipt is issued is a policy decision.
* **Per-society Stripe accounts / Connect:** v1 assumes one platform Stripe account and
  one webhook secret; routing is by signed metadata. Per-society accounts would need a
  per-organization secret/account mapping and a check that `event.account` matches.
* Not handled: subscriptions/recurring dues, `checkout.session.async_payment_*`,
  disputes (`charge.dispute.*`), bank transfers, multi-currency conversion, PDFs,
  authenticated HTTP admin endpoints (the service methods exist; routes wait for the
  society HTTP principal resolver).

## 6. Reconciliation procedure

1. Export charges/payments for a period from Stripe (Dashboard → Payments → Export),
   mapping each row to `provider_payment_ref` (PaymentIntent id), `amount_cents`,
   `currency`, and a ledger status (`succeeded`, `refunded`, `partially_refunded`,
   `failed`, `pending`).
2. Call `reconcile_payments(principal, org_id, rows, since=..., until=...)` (needs
   `payment.read`). It is read-only apart from a `payment.reconciliation_run` audit
   event and reports `matched`, `missing_in_oc`, `missing_in_provider`,
   `amount_mismatch`, `status_mismatch`, `duplicate_in_provider`.
3. Resolve: `missing_in_oc` → check `failed_webhooks()` and resend the event from
   Stripe; `status_mismatch` for refunds → resend `charge.refunded`; `amount_mismatch` →
   investigate before any manual entry (never record a card payment as an offline one).
4. Offline payments are reconciled against the bank deposit slip with
   `list_payments(method='check'|'cash', ...)` and receipts; voids and refunds carry reasons in
   `payment_events`.
