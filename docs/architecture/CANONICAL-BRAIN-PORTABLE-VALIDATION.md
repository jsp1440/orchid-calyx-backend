# Canonical Brain — Portable Validation Contract

## Purpose

Provide one deterministic validation entry point for Canonical Brain across GitHub Actions, Codespaces, Linux/macOS, and Windows Python environments.

## Authoritative command

`python scripts/validate_canonical_brain.py`

GitHub Actions delegates to this same command after installing focused dependencies.

## Validation sequence

The validator fails closed and runs, in order:

1. focused test discovery (`tests/test_canonical_brain_*.py`);
2. validation-input existence checks;
3. SHA-256 fingerprinting of every Canonical Brain source, focused test, validator script, and validation workflow;
4. recursive compilation of `app/canonical_brain`;
5. Ruff through `python -m ruff`;
6. focused pytest through `python -m pytest`.

Using `python -m ...` keeps compile, lint, and tests bound to the same Python environment.

## Machine-readable receipt

Default path:

`artifacts/validation/canonical-brain-validation.json`

Override:

`CANONICAL_BRAIN_VALIDATION_RECEIPT`

Receipt schema `1.1` records:

- Python executable and version;
- repository root;
- discovered focused tests;
- every validated file's path, byte length, and SHA-256;
- deterministic aggregate `validated_tree_sha256`;
- exact validation command arguments;
- step timestamps, return codes, and pass/fail state;
- first failed step;
- overall validation status;
- explicit no-merge/no-deploy/no-publication/no-production-mutation authority flags.

A receipt is validation evidence only. It is not merge, publication, deployment, or scientific approval authority.

## Authoritative passing receipt

PR #525 code head:

`5511fa059657b8b87e6031b048a79362bfef46b1`

Canonical Brain Validation run #109 / Actions run `31209013612` completed successfully against GitHub's merge ref with then-current `main`.

Results:

- compile: passed;
- Ruff: passed;
- pytest: **52 passed**;
- receipt emission: passed;
- `validated_tree_sha256`: `1e1429a09fac210e88dd7a03f8484d8ad3e40fcc2563089972c1049f5a023837`.

Independent BUILD-088E run #887 also passed.

The authoritative evidence is recorded in `PR-525-AUTHORITATIVE-VALIDATION-RECEIPT.md`.

## Runner incident #533

The earlier repository-wide zero-step GitHub Actions incident is recovered and issue #533 is closed. Its exact external cause remains unconfirmed.

If a future workflow fails with no instantiated steps, first diagnose runner/account infrastructure with a zero-dependency probe. Do not modify application code until a real validation step executes and produces a code-level failure.

## Base-branch policy

`main` may advance after a passing receipt. Before merge:

1. inspect new base changes for Canonical Brain and Calyx authority dependencies;
2. if those dependencies changed materially, require a fresh merge-ref validation receipt;
3. if new commits are unrelated and GitHub's merge ref remains conflict-free, avoid churn-only restacking;
4. never interpret a stale receipt as authorization to merge after a material authority-contract change.

## Public execution-receipt types

Canonical Brain exposes explicit names:

- `CanonicalExecutionReceipt` — Canonical queue/orchestration state;
- `CalyxAuthoritativeExecutionReceipt` — authoritative Calyx executor evidence.

`ExecutionReceipt` remains a compatibility alias for the Canonical state receipt.

## Safety

The validator cannot merge, deploy, publish, access production credentials, mutate production databases, activate taxonomy, or mutate the production Knowledge Graph.
