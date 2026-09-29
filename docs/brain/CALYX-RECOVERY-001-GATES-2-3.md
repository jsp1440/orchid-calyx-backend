# CALYX-RECOVERY-001 — Gates 2 and 3

## Status

Clean recovery implementation candidate on `repair/calyx-recovery-gates2-3-clean`,
targeting `oc-autonomous-integration`.

## Gate 2 — canonical research executor

The BUILD-051 research intake path now has a bounded executor contract:

`queued_waiting_for_executor -> queued -> running -> completed | blocked`

The implementation provides exactly-once/idempotent claiming, durable status
history, canonical research-project persistence, immutable result artifacts,
bounded blocker codes, idempotent GitHub feedback, replay safety, and explicit
governance flags that prohibit publication, Knowledge Graph mutation, taxonomy
activation, and production deployment.

A deterministic fake executor proves the state-machine contract without paid
provider use.

## Gate 3 — evidence acquisition/retrieval wiring

The stale `runtime.literature_acquisition` dependency is removed from Research
Station. External-literature query planning now recognizes arbitrary scientific
binomials rather than only a fixed genus list.

Literature search returns explicit availability states:

- `AVAILABLE`
- `EMPTY`
- `UNAVAILABLE`
- `INSUFFICIENT_EVIDENCE`

Source failure is represented explicitly and must not be converted into model-
fabricated science.

## Recovery branch hygiene

The original Claude branch for Gates 2/3 was created from a stale base and
diverged substantially from `oc-autonomous-integration`. Its five intended
Gate 2/3 files were ported onto this clean branch so unrelated historical
changes are not reintroduced.

## Governance

- Calyx remains the sole Orchid Continuum reasoning agent.
- No second persona/reasoning agent is introduced.
- No paid provider activation.
- No deployment.
- No production database migration.
- No publication.
- No taxonomy activation.
- No production Knowledge Graph mutation.
- No protected-locality relaxation.

Independent exact-head validation is required before integration.
