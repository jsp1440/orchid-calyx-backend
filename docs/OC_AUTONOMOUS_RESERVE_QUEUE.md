# Orchid Continuum Autonomous Reserve Queue

The continuous-completion plane should maintain a bounded reserve of safe engineering work so idle execution lanes do not depend on repeated owner prompts.

## Policy

- Target reserve: 5 eligible `oc-queued` engineering issues across the active completion portfolio.
- Refill only when eligible queue depth falls below 3.
- Never generate more than 3 new reserve items in a single refill pulse.
- Candidates must derive from explicitly authorized repository objectives, existing backlog, failing health-contract invariants, incomplete integration work, missing tests, or documented operational gaps.
- Do not invent scientific facts, provenance records, locality data, production activations, destructive operations, spending authority, or governance policy.
- Protected work may be represented as parked/owner-gated, but must never be counted as executable reserve.
- Every synthesized reserve item must carry a stable semantic fingerprint so repeated planner pulses cannot recreate equivalent work.
- Dependencies must be explicit. A child task whose prerequisite is unfinished is not eligible reserve.
- Queue exhaustion is healthy only when no safe authorized work remains. Planner/provider failure must be reported separately as degradation, not as healthy emptiness.

## Preferred reserve categories

1. Control-plane correctness and regression coverage.
2. Exact-head CI and validation hardening.
3. Integration backlog convergence.
4. Observability and operations-monitor readiness.
5. Data ingestion reliability and provenance-preserving tests.
6. Documentation generated from implemented behavior.

This policy is intentionally bounded: its purpose is to prevent idle autonomy, not to create an unbounded issue factory.