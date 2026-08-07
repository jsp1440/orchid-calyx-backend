# CALYX-CORE-REBASE-002A — Current-main ingestion recovery

## Purpose

Replace stale PR #530 with a clean implementation based on current `main`, preserving its validated occurrence, image, literature, and certification capabilities while removing 53 commits of stale branch history.

## Implemented

- bounded/resumable GBIF and iNaturalist occurrence staging;
- canonical taxon reconciliation and explicit unresolved review queues;
- licensed-image staging with Creative Commons allowlist enforcement and explicit rejection records;
- bounded literature staging with exact evidence-span, extraction-manifest, and content-hash preservation;
- checksum idempotency across all staging domains;
- read-only Calyx Core certification exposed at `GET /api/mission-control/calyx-core/certification` through the existing Calyx Core router;
- readiness reporting uses the current authentication contract: `CALYX_API_KEY`, `CALYX_OWNER_ACCESS_CODE`, and `CALYX_OWNER_SESSION_SECRET`;
- fail-closed module probes report import failures instead of crashing the certification endpoint.

## Validation history

The stale #530 head was rerun after GitHub Actions recovered. Its compile step and all five focused functional tests passed, and BUILD-088E passed. The sole failure was one Ruff `I001` import-format violation in the old certification module. This replacement removes that import pattern entirely and must pass its own exact-head focused workflow plus BUILD-088E before merge.

## Governance

No taxonomy activation, automatic publication, deployment authority, credential disclosure, or production Knowledge Graph mutation is granted. Staging output remains review/candidate material and `automatic_publication` remains false.
