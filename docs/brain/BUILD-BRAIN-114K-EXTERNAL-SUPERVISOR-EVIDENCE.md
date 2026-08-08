# BUILD-BRAIN-114K — Durable external-supervisor authorization evidence

## Objective

Move executable-validation authority outside the Calyx application process. The application may create a hash-bound validation request and persist an externally returned receipt, but it does not execute repository code and cannot authenticate as the supervisor from configuration alone.

## Implemented

- canonical validation request envelope bound to repository, `autonomy/*` branch, exact checkout commit, fixed preset (`pytest` or `ruff`), exact target paths and SHA-256 hashes, and bounded timeout;
- one-way supervisor credential verification using only `CALYX_SANDBOX_SUPERVISOR_TOKEN_SHA256` in the application environment; the high-entropy bearer token remains external;
- durable `calyx_sandbox_validation_requests` lifecycle with idempotent request creation, bounded claim ownership, opaque claim token, claim expiry, bounded attempts, request/receipt digests, authorization ID, sandbox policy digest, evidence URI, outcome, and completion timestamp;
- expired supervisor claims are recoverable and bounded rather than permanently wedging validation work;
- Python-side lease comparisons normalize persisted timestamps to UTC so SQLite test round-trips and PostgreSQL TIMESTAMPTZ semantics cannot create a backend-specific authorization bypass or crash;
- supervisor-only claim and completion routes separated from owner/API-key request/read routes;
- exact request-digest verification before a supervisor receipt can complete a request;
- optional program-job binding is owner-scoped and rejects mutating jobs or repository/branch identity mismatches;
- owner snapshots never expose the supervisor claim token;
- no executable-validation adapter is registered in the autonomous worker registry by this build.

## Authority boundary

BUILD-BRAIN-114K deliberately inverts the earlier repository-subprocess design. Repository code does not run `pytest` or Ruff itself. A separately deployed supervisor must authenticate with the external bearer token, claim a request, enforce the OS-level sandbox, execute the fixed validation preset, and return evidence bound to the exact request digest.

The application stores only the SHA-256 verifier for the supervisor credential, so possessing application configuration is insufficient to derive the supervisor bearer token.

## Permanent non-authorities

This build grants no arbitrary shell/argv, package installation, network access, Git mutation, commit, push, PR creation, merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

## Validation history

The first dedicated run exposed six Ruff modernization/import failures. Those were corrected before expanding. A later focused run exposed a real cross-backend lease bug: SQLite round-tripped `DateTime(timezone=True)` as a naive timestamp and Python rejected comparison with the aware UTC clock. The service now normalizes persisted lease timestamps to UTC before authorization comparisons.

On code head `8c4eb4194e691b4b25b11a57a107cb341688c700`, BUILD-BRAIN-114K Validation run `31276480389` passed checkout, dependency installation, compile, Ruff, focused supervisor evidence regressions, migration contract, and diff hygiene. On the same head, CALYX Workflow Governance Audit, CALYX-AUTONOMY-OPERATIONS-002, CALYX-AUTONOMY-004, BUILD-BRAIN-114A, and CALYX-AGENT-003 also passed. BUILD-088E and BUILD-MC-200 were still running when this receipt was written; they remain required before release readiness is asserted.

This Brain update changes documentation only, so a final exact-head CI pass is still required before the PR may leave draft state.
