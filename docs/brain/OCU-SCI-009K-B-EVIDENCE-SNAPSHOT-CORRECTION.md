# OCU-SCI-009K-B — Release-evidence snapshot correction

## Incident

PR #668 merged before two valid post-review findings were repaired. The affected release-evidence path is governance/readiness logic only; no production cutover was performed by this correction.

## Required correction

1. Manifest generation must read retained release-evidence bytes exactly once and derive preflight validation, release binding, and evidence SHA-256 from that same immutable in-memory snapshot. A file replacement after the initial read must not mix evidence versions.
2. `backend.release_identity` must be an object/mapping. Malformed string, list, numeric, boolean, or null values must fail closed through `EvidenceError` rather than an uncaught `AttributeError`.
3. The correction must preserve current-main `OCU-SCI-009I-CUTOVER-MANIFEST-003` semantics, including separate `ready_to_apply_migration` and `ready_to_enable_durable` gates.
4. Deterministic regressions must prove all three guarantees.

## Current-main implementation

The stale PR #675 branch was already behind `main` and would have rolled back newer phased-cutover semantics if copied wholesale. The correction was therefore rebuilt on current `main`.

### Immutable evidence snapshot

`generate_manifest()` reads `release_evidence` once via `Path.read_bytes()`. The captured bytes are then used for:

- `_preflight_from_snapshot(payload, ...)`, which writes only those bytes to a temporary immutable validation file before invoking the existing read-only preflight;
- `_release_binding_bytes(payload)`, which parses and validates the same bytes in memory;
- `evidence_digest_bytes(payload)`, which computes the retained evidence SHA-256 from the same snapshot.

The current migration/durable gate separation and `CUTOVER-MANIFEST-003` contract are preserved.

### Fail-closed release identity validation

`release_commits()` verifies `frontend`, `backend`, and `backend.release_identity` are mappings before field access. Malformed scalar/list/null identities raise the documented `EvidenceError` and cannot escape as `AttributeError`.

### Regression coverage

- release-evidence tests cover malformed string/list/numeric/boolean/null identities and byte-vs-path digest equivalence;
- cutover-manifest tests prove the retained evidence path is read once and that preflight receives the captured bytes;
- existing phased-gate tests remain in place, including the rule that a missing durable schema does not block starting the database migration when the migration gate itself is ready.

## Governance

No DNS, hosting, database migration, learner writes, reviewer grants, publication, Candidate Knowledge promotion, model calls, deployment, taxonomy activation, or production Knowledge Graph mutation are authorized by this correction.
