# OCU-SCI-009K-B — Release-evidence snapshot correction

## Incident

PR #668 merged before two valid post-review findings were repaired. The affected release-evidence path is governance/readiness logic only; no production cutover was performed by this correction.

## Required correction

1. Manifest generation must read retained release-evidence bytes exactly once and derive parse/validation, release binding, and evidence SHA-256 from that same immutable in-memory snapshot. A file replacement after the initial read must not mix evidence versions.
2. `backend.release_identity` must be an object/mapping. Malformed string, list, numeric, boolean, or null values must fail closed through the documented evidence-validation result rather than raising an uncaught `AttributeError`.
3. Deterministic regressions must prove both guarantees.

## Implementation (PR #675)

### Immutable evidence snapshot — `scripts/generate_university_cutover_manifest.py` (commit b1188fd)

`generate_manifest()` reads `release_evidence` exactly once at the top of the function via `Path.read_bytes()`. The captured `evidence_snapshot: bytes | None` is forwarded to:

- `_preflight_from_snapshot(payload, ...)` — writes the snapshot to a `tempfile.TemporaryDirectory` and calls `preflight()` against that path; preflight therefore reads the same bytes.
- `_release_binding_bytes(payload)` — parses and validates the snapshot in memory.
- `evidence_digest_bytes(payload)` — computes the SHA-256 from the snapshot bytes.

No second file read can influence any of these results. The path-based helper `_release_binding(path)` was replaced by `_release_binding_bytes(payload)`.

### Fail-closed on non-mapping `backend.release_identity` — `scripts/validate_university_release_evidence.py` (commit b12b01c)

`release_commits()` now calls `_require(isinstance(identity, Mapping), ...)` before any field access. String, list, numeric, boolean, and null values all raise `EvidenceError`, which `_release_binding_bytes` catches and returns as `{"valid": False, "error": "..."}`. No `AttributeError` can reach the caller.

### Deterministic regressions

- `tests/test_university_cutover_manifest.py` (commit d45ba5f): `test_manifest_reads_retained_evidence_only_once` replaces the evidence file on disk after the first read and asserts that both `_release_binding_bytes` and `evidence_digest_bytes` received the original bytes, proving a single snapshot is used.
- `tests/test_university_release_evidence.py` (commit 19baeea): `test_non_object_backend_release_identity_is_rejected_without_attribute_error` is a parametric subtest over string, list, numeric, boolean, and null values; each must raise `EvidenceError` with the documented message, never `AttributeError`.

## Governance

No DNS, hosting, database migration, learner writes, reviewer grants, publication, Candidate Knowledge promotion, model calls, deployment, or production Knowledge Graph mutation are authorized by this correction.
