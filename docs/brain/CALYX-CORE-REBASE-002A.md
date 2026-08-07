# CALYX-CORE-REBASE-002A — Current-main ingestion recovery

## Purpose

Replace stale PR #530 with a clean implementation based on current `main`, preserving its validated occurrence, image, literature, and certification capabilities while removing 53 commits of stale branch history.

## Implemented

- bounded/resumable GBIF and iNaturalist occurrence staging;
- canonical taxon reconciliation and explicit review queues for every non-`resolved` reconciliation state, including missing crosswalks and missing taxon context;
- licensed-image staging with Creative Commons allowlist enforcement and explicit rejection records;
- bounded literature staging with exact evidence-span, extraction-manifest, and content-hash preservation;
- checksum idempotency across all staging domains;
- read-only Calyx Core certification exposed at `GET /api/mission-control/calyx-core/certification` through the existing Calyx Core router;
- readiness reporting uses the current authentication contract: `CALYX_API_KEY`, `CALYX_OWNER_ACCESS_CODE`, and `CALYX_OWNER_SESSION_SECRET`;
- certification derives operational status, blockers, capabilities, and next executable jobs from `runtime.graph_pipeline_readiness.build_graph_pipeline_readiness` instead of inferring readiness from module presence;
- staging module availability is reported separately from durable operational readiness so owner-facing Mission Control cannot overstate pipeline capability;
- fail-closed module probes report import failures instead of crashing the certification endpoint.

## Review corrections

Two post-validation review findings were accepted and repaired before merge:

1. Certification previously labeled occurrence and licensed-image pipelines `staging_pipeline_ready` merely because their staging modules existed. The report now exposes the authoritative graph-pipeline `partial` state and blockers, including missing durable persistence/checkpoints/canonical crosswalks and the image bridge.
2. Occurrence, image, and literature staging previously queued only the literal `unresolved` state. All non-resolved reconciliation states now enter human review, including `review_required` and `reconciliation_unavailable`.

Regression tests cover both behaviors.

## Validation history

The stale #530 head was rerun after GitHub Actions recovered. Its compile step and all five focused functional tests passed, and BUILD-088E passed. The sole failure was one Ruff `I001` import-format violation in the old certification module.

The initial #560 head then passed its focused validation and BUILD-088E. Post-validation review identified the two issues above, so that head was not merged. The corrected exact head must pass the focused workflow and BUILD-088E again before merge.

## Governance

No taxonomy activation, automatic publication, deployment authority, credential disclosure, or production Knowledge Graph mutation is granted. Staging output remains review/candidate material and `automatic_publication` remains false.
