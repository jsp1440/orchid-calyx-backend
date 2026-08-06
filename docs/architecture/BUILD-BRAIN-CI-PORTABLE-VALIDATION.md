# BUILD-BRAIN-CI — Portable Validation Boundary

Status: implemented candidate; administrative Actions dispatch remains unresolved.

## Purpose

Provide one repeatable validation entrypoint for the canonical Brain so GitHub Actions, Codespaces, and local development execute the same compile, lint, and focused test commands.

## Implemented

- `scripts/validate_canonical_brain.sh`
- strict shell failure handling;
- Python compile validation for `app/canonical_brain`;
- Ruff validation for canonical Brain code and focused tests;
- pytest execution for `tests/test_canonical_brain_*.py`;
- deterministic command manifest in a JSON validation receipt;
- explicit `publication_enabled: false` and `deployment_enabled: false` receipt fields;
- GitHub Actions workflow delegation to the portable runner;
- branch/PR/manual triggers and concurrency cancellation;
- issue #481 for the repository-level Actions dispatch boundary.

## Validation receipt

Default path:

`artifacts/canonical-brain-validation.json`

The receipt records suite identity, status, failed step, timestamps, commands, and safety boundaries. A failed compile, lint, or test step writes a failed receipt before exiting non-zero.

## Remaining boundary

GitHub currently reports no workflow runs and no commit statuses for PR #425 heads. Because existing workflows are present on `main`, administrative inspection of repository or organization Actions policy is required. This boundary is tracked in issue #481.

## Governance

No merge, deployment, publication, credential use, production database mutation, or production Knowledge Graph mutation is authorized by this build.
