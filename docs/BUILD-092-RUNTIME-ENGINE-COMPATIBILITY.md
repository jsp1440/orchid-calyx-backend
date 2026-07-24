# BUILD-092 — RuntimeEngine Constructor Compatibility Repair

## Objective

Restore repository-wide compatibility for historical callers that construct `RuntimeEngine` without explicitly supplying runtime dependencies, while preserving dependency injection for the production runtime.

## Problem

`RuntimeEngine.__init__` required three keyword-only callbacks:

- `heartbeat`
- `enqueue_jobs`
- `execute_jobs`

Historical integration, authentication, operations, and Mission Control tests construct or import runtime components without those callbacks. Pytest therefore failed during collection before those suites or unrelated feature tests could run.

## Decision

The callbacks remain injectable and production callers continue to provide their real implementations. For compatibility-only construction, omitted callbacks resolve to deterministic no-op functions that:

- do not enqueue work
- do not execute work
- do not write state outside the in-memory runtime status object
- report `not_configured`
- produce zero completed and failed jobs

This is safer than weakening production call sites or updating many historical tests to invent fake production dependencies.

## Validation

BUILD-092 adds tests proving:

1. `RuntimeEngine()` can be constructed without callbacks.
2. Default callbacks are safe, deterministic no-ops.
3. Explicit callbacks remain authoritative.
4. The focused RuntimeEngine suite passes.
5. Historical suites that previously failed during collection can now be collected.

## Scope

- no database migration
- no API change
- no deployment
- no automatic runtime enablement
- no change to production dependency injection in `app/main.py`
