# BUILD-070 Repository Intake and Implementation Placement

**Task:** B070-T01  
**Status:** Complete  
**Decision level:** Level 1  
**Selected repository:** `jsp1440/orchid-calyx-backend`  
**Selected package boundary:** top-level Python package `ocadf/`

## Candidate repositories inspected

### `jsp1440/Orchid-Continuum-Brain`

Role: authoritative governance, specifications, decisions, task graphs, and institutional memory.

Decision: not selected as the executable implementation repository. The Brain must remain primarily declarative and reviewable. Executable code placed there would blur the separation between institutional authority and runtime behavior.

### `jsp1440/orchid-continuum-backend`

Role: small legacy or transitional backend repository with insufficient evidence of the current testing, persistence, and operational conventions needed for BUILD-070.

Decision: not selected.

### `jsp1440/orchid-calyx-backend`

Role: active Python backend with FastAPI, Pydantic, SQLAlchemy, PostgreSQL adapters, established repository abstractions, extensive pytest coverage, build documentation, and recent knowledge-graph orchestration work.

Decision: selected as the smallest safe executable integration point available now.

## Placement decision

BUILD-070 will be implemented as an isolated top-level package:

```text
ocadf/
    __init__.py
    schemas/
    brain/
    registry/
    dependency/
    planning/
    workers/
    orchestration/
    approvals/
    documentation/
    cli/
```

Tests will live under:

```text
tests/ocadf/
```

## Isolation rules

1. No FastAPI route is added during BUILD-070.
2. No existing Calyx runtime path imports `ocadf` automatically.
3. No production database table or migration is required for the initial implementation.
4. Initial persistence uses replaceable repository interfaces and deterministic local implementations.
5. No production writes, deployment changes, credentials, external API calls, or autonomous merges are authorized.
6. Brain access is read-only.
7. The package must remain extractable into a dedicated repository later without rewriting its domain model.

## Existing conventions retained

- Python and Pydantic for typed records and validation.
- Repository abstractions for replaceable persistence.
- Pytest for unit and integration testing.
- Deterministic in-memory fixtures before PostgreSQL integration.
- Build-specific implementation and validation documentation.
- Explicit provenance, idempotency, rollback, and safety assertions.

## Why this is safe

The selected package boundary reuses the mature development and testing environment without coupling OCADF to the public API or production graph. It allows BUILD-070 to be implemented and validated immediately while preserving the Brain as the authoritative source of instructions.

## Completion evidence

- Candidate roles documented.
- Existing architecture and test conventions identified.
- Executable repository selected and justified.
- Package boundary defined.
- Production behavior unchanged.

## Next task

Proceed automatically to **B070-T02 — Define core record schemas**.
