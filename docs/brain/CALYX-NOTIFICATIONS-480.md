# CALYX-480 — Notification, escalation, digest, and owner-attention service

Status: IMPLEMENTED / VALIDATION PENDING / PROVIDER-NEUTRAL

## Delivered

- Governed actionable event types for delivery blockers, retries, dead letters, review requests, stale approvals, deployment failures, approaching deadlines, grant responses, harvester failures, and care alerts.
- Recipient preferences with timezone, quiet hours, minimum severity, digest grouping, and in-app-only channel policy.
- Deterministic deduplication by explicit or derived dedupe key with duplicate count and last-seen timestamp.
- Quiet-hours behavior that defers noncritical events while allowing critical events to remain immediately actionable.
- Digest grouping, acknowledgement, explicit owner-triggered escalation, and provider-neutral delivery receipts.
- Protected Mission Control APIs for preferences, events, pending attention, digests, acknowledgement, escalation, receipts, and readiness.

## Provider and commitment boundaries

This build does not send email, SMS, push, Slack, or any other external message. Channels are restricted to `in_app`; any other channel is rejected. Delivery receipts accept only fixture providers and never imply a real send. No provider secret is stored.

Escalation is an internal attention-state transition, not an external commitment. The service cannot accept grants, commit funds, promise deadlines, authorize deployments, or make personnel/scientific decisions.

## Validation

Focused tests cover preference/channel governance, deduplication, quiet hours, critical-event bypass, digest grouping, acknowledgement, escalation, provider-neutral receipts, and permanent no-external-send/no-secret-storage/no-autonomous-commitment boundaries. Hosted GitHub Actions remain affected by the repository-wide pre-step runner provisioning failure.
