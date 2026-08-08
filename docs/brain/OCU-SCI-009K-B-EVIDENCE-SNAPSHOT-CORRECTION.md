# OCU-SCI-009K-B — Release-evidence snapshot correction

## Incident

PR #668 merged before two valid post-review findings were repaired. The affected release-evidence path is governance/readiness logic only; no production cutover was performed by this correction.

## Required correction

1. Manifest generation must read retained release-evidence bytes exactly once and derive parse/validation, release binding, and evidence SHA-256 from that same immutable in-memory snapshot. A file replacement after the initial read must not mix evidence versions.
2. `backend.release_identity` must be an object/mapping. Malformed string, list, numeric, boolean, or null values must fail closed through the documented evidence-validation result rather than raising an uncaught `AttributeError`.
3. Deterministic regressions must prove both guarantees.

## Governance

No DNS, hosting, database migration, learner writes, reviewer grants, publication, Candidate Knowledge promotion, model calls, deployment, or production Knowledge Graph mutation are authorized by this correction.
