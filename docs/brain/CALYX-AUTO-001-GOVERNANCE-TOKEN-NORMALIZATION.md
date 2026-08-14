# CALYX-AUTO-001 — Governance Action Token Normalization

## Status

IMPLEMENTED ON FEATURE BRANCH / NON-PRODUCTION / EXECUTABLE CI PENDING

## Defect closed

The pre-claim governance classifier previously lowercased action names but did not canonicalize separator spelling. Equivalent owner/review-bound intents such as `force-push`, `branch deletion`, `Production Database Mutation`, `production-migration`, or governance class `owner-only` could therefore fail to match underscore-form authority tokens.

## Hardening

`app/calyx_orchestrator/auto_mission.py` now canonicalizes action tokens by case-folding, converting whitespace/hyphen runs to underscores, collapsing duplicate underscores, and trimming separators before classification. The same normalization is applied to action-field names, action values, capability lists, direct nested action flags, and explicit governance class values.

Mapping-valued scientific metadata remains non-action data. Disabled/false action flags remain non-requests. This preserves the existing false-positive boundary while closing superficial spelling bypasses.

## Regression coverage

`tests/test_calyx_auto_001_action_aliases.py` covers hyphenated, spaced, mixed-case, list-valued, direct nested, and explicit governance-class spellings, plus negative metadata/disabled-flag cases.

## Validation boundary

The repository's private GitHub-hosted Actions incident remains active: jobs are being created with no executable steps. These changes therefore make no executable-green claim until a job receives a runner and executes the focused tests, compile, Ruff, and adjacent CALYX-AUTO-001 suite.

## Authority

No merge, deployment, production migration, taxonomy activation, scientific publication, credential access, spending, force-push, branch deletion, or production Knowledge Graph mutation authority is introduced.