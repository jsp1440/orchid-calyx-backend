# BUILD-BRAIN-CI — Cross-Platform Canonical Brain Validation

## Purpose

Make the canonical Brain validation gate repeatable from GitHub Actions, Windows, macOS, Linux, Codespaces, and other Python-capable environments without maintaining separate command sequences.

## Implemented

- Added `scripts/validate_canonical_brain.py` as the canonical validation entry point.
- Discovers all `tests/test_canonical_brain_*.py` files deterministically and fails closed when none exist.
- Runs compile, Ruff, and pytest with the active Python interpreter.
- Writes a machine-readable receipt for both successful and failed validation attempts.
- Records the exact executable, Python version, commands, timestamps, and failed step.
- Retained `scripts/validate_canonical_brain.sh` as a thin compatibility wrapper.
- Updated GitHub Actions to invoke the Python runner directly.

## Commands

Windows, macOS, Linux, and Codespaces:

```text
python scripts/validate_canonical_brain.py
```

Optional receipt destination:

```text
python scripts/validate_canonical_brain.py --receipt artifacts/custom-validation.json
```

Bash compatibility:

```text
bash scripts/validate_canonical_brain.sh
```

## Invariants

- Validation does not merge, deploy, publish, or mutate production data.
- Missing test discovery is a validation failure.
- A failed step produces a failure receipt before exit.
- The receipt is evidence of execution, not authority to release.

## Unresolved external boundary

GitHub has continued to attach no workflow run or commit status to the feature-branch head. Issue #481 tracks the repository- or organization-level Actions settings investigation. This implementation removes platform and command drift but does not claim that GitHub Actions executed successfully.
