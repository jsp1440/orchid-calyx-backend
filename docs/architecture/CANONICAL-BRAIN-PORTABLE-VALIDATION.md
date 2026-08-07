# Canonical Brain — Portable Validation Contract

## Purpose

Provide one deterministic validation entry point for the Canonical Brain integration that can run from GitHub Actions, Codespaces, Linux/macOS terminals, or Windows Python environments without maintaining separate compile/lint/test command sets.

## Authoritative command

```text
python scripts/validate_canonical_brain.py
```

The GitHub Actions workflow delegates to this same command after installing its focused dependencies.

## Validation sequence

The runner performs these gates in order and stops on the first failure:

1. discovers every `tests/test_canonical_brain_*.py` file and fails closed if none exist;
2. compiles `app/canonical_brain` recursively with the active Python interpreter;
3. runs Ruff through the same interpreter with `python -m ruff`;
4. runs the complete focused Canonical Brain test set through the same interpreter with `python -m pytest`.

Using `python -m ...` prevents accidental use of a different Ruff or pytest installation from another environment.

## Machine-readable receipt

By default the validator writes:

`artifacts/validation/canonical-brain-validation.json`

The destination can be overridden with `CANONICAL_BRAIN_VALIDATION_RECEIPT`.

The receipt records:

- validator schema version;
- Python executable and version;
- repository root;
- exact discovered test files;
- exact command arguments for every validation step;
- start/completion timestamps;
- per-step pass/fail state and return code;
- the first failed step;
- overall validation state;
- explicit authority flags showing that validation cannot merge, deploy, publish, access credentials, mutate a production database, or mutate the production Knowledge Graph.

The receipt is evidence of validation execution only. It is not publication, deployment, scientific approval, or merge authority.

## Current GitHub Actions incident

Repository-wide GitHub-hosted runner allocation is currently blocked and tracked in issue #533. A zero-dependency workflow containing only one `ubuntu-latest` echo step was accepted and queued but terminated before the first step was instantiated. Unrelated workflows and PRs show the same zero-step behavior, while PR #516 successfully executed multiple hosted-runner workflows immediately before the incident window.

Therefore zero-step workflow conclusions during incident #533 are not interpreted as application test failures.

When GitHub-hosted runner execution is restored, `Canonical Brain Validation` must run this portable validator against the then-current PR head. A passing receipt plus the workflow result is required before PR #525 can progress beyond draft validation status.

## Local validation status during incident

The portable validator source itself has been syntax-compiled in the implementation environment. Earlier Canonical Brain slices separately achieved authoritative passing compile/Ruff/focused-pytest evidence before the runner incident. Files changed during the later current-main authority hardening have also been syntax-compiled locally where reported.

No claim is made that the complete current PR #525 test set has passed until the portable validator executes successfully in an environment containing all repository dependencies.
