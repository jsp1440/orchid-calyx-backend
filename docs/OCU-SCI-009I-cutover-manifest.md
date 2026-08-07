# OCU-SCI-009I — Deterministic production cutover manifest

## Purpose

Generate a non-secret, machine-readable release packet before any durable University activation. The manifest binds the deployed frontend/backend commits and origins to the validated OCU-SCI-007 evidence artifact, durable migration checksum, read-only activation preflight, reviewer-grant counts, ordered activation phases, and rollback checkpoints.

## Command

```bash
python scripts/generate_university_cutover_manifest.py \
  --frontend-commit <40-char deployed frontend SHA> \
  --backend-commit <40-char deployed backend SHA> \
  --frontend-origin https://<frontend-origin> \
  --api-origin https://<calyx-origin>/api \
  --release-evidence university-production-evidence.json \
  --output university-cutover-manifest.json
```

The command performs no DNS, hosting, database, environment, reviewer, publication, Candidate Knowledge, or model-call mutations.

## Fail-closed requirements

The generator inherits every OCU-SCI-009H preflight blocker and additionally requires full lowercase 40-character Git SHAs and HTTPS origins. It only reports `ready_for_operator_cutover=true` when preflight is already ready while session writes and durable mode remain disabled.

## Manifest contents

The output includes:

- frontend deployed commit and HTTPS origin;
- backend deployed commit and HTTPS API origin;
- SHA-256 of `migrations/ocu_sci_008_durable_sessions.sql`;
- SHA-256 of the retained OCU-SCI-007 evidence artifact;
- the complete non-secret OCU-SCI-009H preflight result;
- reviewer qualification grant counts only (never subject IDs);
- ordered phases from read-only cutover through authenticated end-to-end testing;
- rollback checkpoints that disable writes without silently deleting audit records;
- explicit `mutations_performed=false` and `secrets_included=false` assertions.

## Safe phase ordering

0. Canonical read-only frontend/backend cutover and OCU-SCI-007 verification.
1. Database backup/rollback review and durable migration application while University learner writes remain disabled.
2. Read-only post-migration schema verification.
3. Explicit durable activation only after release evidence, learner identity, and a qualified science reviewer are present.
4. Authenticated learner/revision/submission/review and stale-revision tests.

Publication, automatic Candidate Knowledge promotion, and Calyx model calls remain outside this activation sequence.

## Governance boundary

The manifest does not assign a reviewer qualification. Adding a real subject to `MISSION_CONTROL_REVIEWER_QUALIFICATIONS_JSON` is a separate governance/operator action. Likewise, domain/DNS/hosting changes, production migration execution, and enabling production write flags require external production authority.
