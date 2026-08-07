# Canonical Brain — Validation Provenance Binding

## Objective

Bind every Canonical Brain validation result to the exact source and test bytes that were validated, rather than relying only on a branch name, commit label, or workflow timestamp.

## Receipt schema 1.1

`python scripts/validate_canonical_brain.py` now fingerprints all validation inputs before compile, Ruff, or pytest runs.

The fingerprint set includes:

- every `app/canonical_brain/**/*.py` source file;
- every discovered `tests/test_canonical_brain_*.py` focused test;
- `scripts/validate_canonical_brain.py` itself;
- `.github/workflows/canonical-brain-validation.yml`.

For each file the receipt records its repository-relative path, byte length, and SHA-256 digest. The validator also computes `validated_tree_sha256`, a deterministic aggregate SHA-256 over the sorted `(file_digest, path)` manifest.

A validation receipt therefore proves both **what commands ran** and **which exact bytes those commands evaluated**.

## Fail-closed behavior

Validation fails before compile/lint/test execution when:

- the focused test set is empty;
- any required validation input is missing;
- compile fails;
- Ruff fails;
- pytest fails.

The receipt records the first failed phase and preserves all fingerprints collected before that failure.

## Authority boundary

Content fingerprinting does not grant merge, deploy, publication, credential, production-database, or production-Knowledge-Graph authority. A passing receipt is validation evidence only.

## Incident #533

GitHub-hosted runners currently terminate before job step 1 across unrelated workflows. That administrative incident remains tracked in issue #533. Until runner execution is restored, no current PR #525 receipt is claimed as fully passing.

When runner execution resumes, PR #525 must be reconciled to the then-current `main`, and the passing receipt's `validated_tree_sha256` must correspond to that reconciled head before the PR can advance beyond draft validation status.
