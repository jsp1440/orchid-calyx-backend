# CALYX-VISION-ACTIVATION-004

Status: implementation complete on branch; hosted validation pending.

## Problem

The first governed production activation attempt exposed two distinct issues in the activation surface:

1. The workflow summary always printed that the required Vision tables and machine-review boundary were verified because the summary step used fixed text under `if: always()`. A failed PostgreSQL step could therefore produce a reassuring but false summary.
2. `/api/vision-lexicon/status` treated `migration_activated` as false whenever `CALYX_VISION_DURABLE_ENABLED` was false. That conflated two separate governance states: schema activation and permission to use durable writes. The production migration is intentionally allowed to precede durable-write enablement.

## Repair

- `app/vision_lexicon/activation.py`
  - `schema_ready()` now checks the governed PostgreSQL schema independently of the durable-write flag.
  - `migration_activated` truthfully reflects schema availability.
  - new `durable_persistence_enabled` reports the explicit write-enable flag separately.
  - `persistence_mode` remains `memory` until durable writes are explicitly enabled.
  - live provider inference remains false.
  - durable writes still fail closed if requested before the schema is ready.

- `.github/workflows/calyx-vision-production-activation.yml`
  - adds a read-only prerequisite check for the canonical `oc_concepts.concepts` dependency before attempting Vision DDL;
  - assigns step IDs to prerequisite, migration, and schema-verification stages;
  - the always-run summary now records actual step outcomes instead of claiming success unconditionally;
  - the deployed smoke test can now verify schema activation before durable writes are enabled.

- `tests/test_vision_lexicon_activation_status.py`
  - covers schema-active/durable-disabled state;
  - covers schema-active/durable-enabled state;
  - covers fail-closed durable request when schema is unavailable.

## Governance

This change does not run a production migration, enable durable writes, configure a Vision provider, promote Candidate Knowledge, publish scientific knowledge, activate taxonomy, or mutate the production Knowledge Graph. The next production workflow dispatch remains an explicit owner-governed action.

## Validation target

Hosted CI must pass the new status tests plus adjacent Vision-Lexicon regressions, Ruff/formatting, and workflow/governance checks before this branch is merge-eligible.
