# CALYX taxonomy intake — upload-before-smoke ordering correction

Date: 2026-08-08
Issue: #386
Predecessor: PR #647 / main `32993c3a6c6acb67c88a38109bb6f7bd6ba83af1`

## Production evidence

A post-#647 read-only deployed discovery run confirmed that migration 107 is structurally verified and PostgreSQL durable intake is active. The previous persistent-volume and stale staging-schema blockers are gone.

The deployed intake store still contains zero releases. The exact Hassler release `WorldOrchids 26-08 (Aug 2 2026).csv` with SHA-256 `e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f` is not yet present.

The only remaining blocked operational gate reported by production is `smoke_fixture`. No upload, staging, taxonomy activation, publication, or Knowledge Graph mutation occurred during discovery.

## Ordering defect

Readiness previously counted `smoke_fixture` as an intake/upload prerequisite. That creates a circular dependency: the system requires a Hassler-format upload/readback smoke before allowing the upload needed to create an inspected release for that smoke.

The corrected lifecycle is:

1. migration 107 verified;
2. durable intake available;
3. release upload/inspection allowed;
4. smoke/readback required for the inspected release;
5. bounded staging allowed only after smoke verification;
6. comparison/review;
7. separate owner-controlled activation boundary.

`smoke_fixture` remains a visible blocked gate and still prevents bounded staging. It is excluded only from the gates used to calculate `ready_for_upload`, alongside the already non-upload `owner_promotion_approval` gate.

## Regression guarantees

Tests explicitly prove both sides of the boundary:

- verified durable intake with no release and no smoke verification reports `ready_for_upload=true`, `pipeline_state=ready_for_release_upload`, and next job `upload_world_orchids_release`;
- once a release is inspected, missing smoke verification reports `release_inspected_staging_smoke_required` and next job `verify_taxonomy_staging_smoke`;
- bounded staging remains unavailable until the smoke gate passes;
- promotion remains blocked.

## Governance

This correction changes readiness ordering only. It does not upload the real Hassler file, write staging rows, activate taxonomy, approve review items, publish knowledge, or mutate the Knowledge Graph.

The next production state-changing action remains the real-release upload/inspection followed by the bounded smoke/readback. That action is intentionally not executed by this implementation slice.
