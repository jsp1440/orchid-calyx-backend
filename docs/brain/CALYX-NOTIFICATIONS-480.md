# CALYX-480 — Notification, escalation, digest, and owner-attention service

Status: IMPLEMENTED / STATIC REVIEW HARDENED / EXECUTABLE VALIDATION BLOCKED / PROVIDER-NEUTRAL

## Delivered

- Governed actionable event types for delivery blockers, retries, dead letters, review requests, stale approvals, deployment failures, approaching deadlines, grant responses, harvester failures, and care alerts.
- Recipient preferences with timezone, quiet hours, minimum severity, digest grouping, and in-app-only channel policy.
- Deterministic deduplication by explicit or derived dedupe key with duplicate count and last-seen timestamp.
- Quiet-hours behavior that defers noncritical events while allowing critical events to remain immediately actionable.
- Digest grouping, acknowledgement, explicit owner-triggered escalation, and provider-neutral delivery receipts.
- Protected Mission Control APIs for preferences, events, pending attention, digests, acknowledgement, escalation, receipts, and readiness.

## Static-review hardening

A post-implementation audit corrected four state-integrity defects before executable CI becomes available:

1. Reusing an existing `event_id` with different content could overwrite the prior event. Event creation now uses an immutable deterministic `event_digest`; exact replay is idempotent and conflicting ID reuse fails closed with `NOTIFICATION_IMMUTABLE_EVENT_CONFLICT`.
2. Mutable acknowledgement, deduplication, escalation, and receipt state previously changed without a corresponding state identity. The immutable event-content digest is now separated from a recomputed `state_digest`.
3. `digest_enabled=false` was stored but ignored. Digest assembly now returns no grouped digest when the recipient explicitly disables digesting.
4. Digest events were sorted lexicographically by severity rather than operational severity. Groups are now ordered critical → high → medium → low → info, then deterministically by event ID.

Focused regressions cover exact replay/conflicting reuse, digest preference enforcement, severity ordering, and immutable-content versus mutable-state digest behavior.

## Provider and commitment boundaries

This build does not send email, SMS, push, Slack, or any other external message. Channels are restricted to `in_app`; any other channel is rejected. Delivery receipts accept only fixture providers and never imply a real send. No provider secret is stored.

Escalation is an internal attention-state transition, not an external commitment. The service cannot accept grants, commit funds, promise deadlines, authorize deployments, or make personnel/scientific decisions.

## Validation

Hosted GitHub Actions remain affected by canonical incident #481. Private-repository hosted jobs terminate before checkout with `steps=null`; these hardened regressions therefore do not yet have an executable exact-head CI verdict. No zero-step run is treated as code validation.
