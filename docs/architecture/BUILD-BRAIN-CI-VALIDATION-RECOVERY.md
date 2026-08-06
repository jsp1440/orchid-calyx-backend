# Canonical Brain CI Validation Recovery

Status: active validation recovery; draft branch only.

## Problem

The canonical Brain branch accumulated executable contracts and focused tests, but repeated checks of the PR head returned no workflow runs and no commit status contexts. This means there was no evidence that compile, Ruff, or pytest validation had executed. It was incorrect to treat the absence of runs as test success or test failure.

## Evidence

- Draft PR #425 remains open, mergeable, and unmerged.
- The repository already contains multiple GitHub Actions workflows on `main`.
- `.github/workflows/canonical-brain-validation.yml` originally listened only to `pull_request` and `workflow_dispatch`.
- The available workflow-run connector reports pull-request-triggered runs only, so push-triggered validation must be observed through commit statuses or GitHub Actions UI.

## Recovery change

The canonical Brain workflow now also listens to pushes on:

`feature/brain-canonical-architecture-registry`

The push trigger remains path-scoped to canonical Brain code, tests, architecture documentation, and the workflow itself.

## Validation gates

The workflow must complete all of the following before the branch may be represented as validated:

1. Install repository dependencies plus pytest and Ruff.
2. Compile `app/canonical_brain`.
3. Run Ruff across canonical Brain code and focused tests.
4. Run every `tests/test_canonical_brain_*.py` test.

## Governance boundary

This recovery change grants no merge, deployment, publication, production database, or production Knowledge Graph authority. If GitHub still produces no run after the push trigger, repository Actions settings or workflow-policy configuration must be inspected by an administrator before additional feature expansion.

## Decision

Do not add further horizontal feature batches until validation evidence exists or the remaining GitHub Actions configuration blocker is explicitly identified and recorded.
