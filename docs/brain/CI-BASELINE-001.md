# CI-BASELINE-001 — Current-main broad-suite classification

## Purpose

Establish a truthful repository-wide validation baseline on authoritative `main` before promoting any broad suite to a blocking merge gate.

## Scope

This slice repairs demonstrated harness defects only:

- install `pytest-asyncio` alongside pytest/httpx so async tests collect and execute instead of failing because the plugin is absent;
- align `tests/test_ci_baseline_001.py` with the current BUILD-087B workflow step names;
- assert that async pytest support remains installed;
- preserve the repository-wide backend suite as a diagnostic/non-blocking step until its current-main failure categories are classified and repaired.

## Governance

This work does not grant or exercise deployment authority, publication authority, taxonomy activation, credential mutation, production database mutation, Knowledge Graph mutation, or autonomous runtime activation.

The broad backend suite must not be declared blocking until failures are demonstrated to be current product regressions rather than stale contracts, environment assumptions, expected-failure certification cases, optional dependency gaps, or historical test debt.

## Validation gate

The exact PR head must execute real GitHub Actions steps and pass the focused CI-BASELINE-001 contract plus the existing BUILD-087B, BUILD-088E, Brain, agent, and workflow-governance regressions that are triggered by this change. `action_required` or zero-step runs are infrastructure/approval states and are not validation evidence.

## Next step

Use the broad diagnostic result to group current-main failures by root cause. Repair one demonstrated category at a time, keeping the broad suite informational until the remaining failures are all actionable product regressions. Only then promote it to a blocking repository-wide gate.
