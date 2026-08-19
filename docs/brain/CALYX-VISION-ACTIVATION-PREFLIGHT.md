# CALYX-VISION — Activation Readiness Preflight

**Status:** read-only implementation candidate; no migration, provider activation, or live inference activation.

## Purpose

Provide an owner-visible readiness check for activating the governed Vision-Lexicon subsystem without changing runtime state. The preflight separates four distinct questions that must not be collapsed into one generic ready/not-ready signal:

1. is a PostgreSQL database configured and reachable;
2. is the governed `oc_vision` persistence schema structurally ready;
3. is durable Vision persistence explicitly enabled;
4. is a governed inference provider configured and live inference explicitly enabled.

This makes activation sequencing observable while preserving the existing governance boundary.

## Read-only contract

`vision_activation_preflight()` performs only configuration inspection, a bounded PostgreSQL connection attempt, and the existing schema probe. It does not apply migrations, change environment variables, initialize a provider, invoke image inference, create Matrix evidence, or promote any result into the Knowledge Graph.

The response reports:

- database URL configuration state;
- database connectivity independently from schema inspection success;
- schema readiness and the exact schema blocker when known;
- schema-inspection errors independently from connection failures;
- whether durable persistence was requested;
- whether persistence is activation-ready and whether it is actually active;
- provider status/readiness;
- live-inference flag and final activation readiness;
- ordered blockers and the recommended activation order.

## Fail-closed blocker semantics

A production-ready state requires all layers to be satisfied. In particular, a ready schema and provider do **not** make the system activation-ready when `CALYX_VISION_DURABLE_ENABLED` remains false. The preflight emits `VISION_DURABLE_PERSISTENCE_DISABLED` so an operator or automation cannot interpret an empty blocker list while durable persistence is inactive.

Database connectivity and schema inspection are also deliberately separated. If the PostgreSQL connection succeeds but catalog/schema inspection fails because of permissions, statement timeout, or another inspection error, the response keeps `connectivity=true`, sets `schema_ready=false`, records the inspection error, and emits `VISION_SCHEMA_INSPECTION_FAILED`. It does not misreport that state as `VISION_DATABASE_UNREACHABLE`.

## Activation order

The preflight reports the following governed sequence:

1. activate and verify the `oc_vision` schema;
2. enable governed durable Vision persistence;
3. configure and verify a governed image-inference provider;
4. enable live inference only after provider validation;
5. retain human review before Matrix scoring or knowledge promotion.

The sequence is descriptive only. The preflight performs none of these mutations.

## Validation

Focused regressions cover persistence/live-inference separation, disabled durable-persistence blocking, missing database configuration, schema governance blockers, successful connectivity with schema-inspection failure, fully ready state, and runtime schema probing without mutation. The dedicated Vision readiness workflow, Matrix integrated validation, workflow-governance audit, and BUILD-088E validation are green on the current PR head.

## Governance boundary

This work does not authorize or perform database migrations, environment changes, provider credential registration, provider calls, live inference, Matrix evidence acceptance, taxonomy changes, Knowledge Graph mutation, deployment, publication, or spending. Those transitions remain separately governed and must be activated explicitly after the preflight reports that prerequisites are satisfied.
