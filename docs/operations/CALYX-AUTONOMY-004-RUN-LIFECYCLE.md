# CALYX-AUTONOMY-004 — Governed autonomous run lifecycle

This build extends the existing durable Calyx orchestrator without enabling production execution or scientific publication.

## State model

Jobs may be `queued`, `running`, `blocked_approval`, `completed`, `cancelled`, `failed`, or `dead_letter`.

A failed read-only attempt is rescheduled only when attempts remain. The next attempt is delayed with bounded exponential backoff. Exhausted jobs enter `dead_letter` and require explicit owner action.

## Safety classes

- `read_only_research`: may execute unattended when the worker is separately enabled.
- `candidate_generation`: may prepare unpublished review material only.
- `review_required`: stops at a human approval boundary.
- `owner_only`: publication, deployment, migration, external communication, and destructive actions remain prohibited.

## Invariants

- Owner identity is derived from authentication.
- Worker mutations require the current lease token.
- Retry scheduling is deterministic and bounded.
- Cancelled, completed, and dead-letter jobs are terminal.
- No autonomous path can publish scientific knowledge, deploy code, merge pull requests, run migrations, or communicate externally.
- Private chain-of-thought is not accepted or stored.

## Operational recovery

Mission Control status exposes retry-waiting and dead-letter jobs. An owner may requeue a dead-letter job only after reviewing its error and attempts. Requeue clears the terminal error and retry clock while preserving the prior attempt count for auditability.

## Deployment boundary

The migration is additive. This PR does not apply it to production, start a worker, schedule jobs, publish graph data, or activate autonomous execution.
