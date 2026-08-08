# BUILD-BRAIN-114K — Durable external-supervisor authorization evidence

## Objective

Move executable-validation authority outside the Calyx application process. The application may create a hash-bound validation request and persist an externally returned receipt, but it does not execute repository code and cannot authenticate as the supervisor from configuration alone.

## Implemented

- canonical validation request envelope bound to repository, `autonomy/*` branch, exact checkout commit, fixed preset (`pytest` or `ruff`), exact target paths and SHA-256 hashes, and bounded timeout;
- one-way supervisor credential verification using only `CALYX_SANDBOX_SUPERVISOR_TOKEN_SHA256` in the application environment; the high-entropy bearer token remains external;
- durable `calyx_sandbox_validation_requests` lifecycle with idempotent request creation, bounded claim ownership, opaque claim token, request/receipt digests, authorization ID, sandbox policy digest, evidence URI, outcome, and completion timestamp;
- supervisor-only claim and completion routes separated from owner/API-key request/read routes;
- exact request-digest verification before a supervisor receipt can complete a request;
- owner snapshots never expose the supervisor claim token;
- no executable-validation adapter is registered in the autonomous worker registry by this build.

## Authority boundary

BUILD-BRAIN-114K deliberately inverts the earlier repository-subprocess design. Repository code does not run `pytest` or Ruff itself. A separately deployed supervisor must authenticate with the external bearer token, claim a request, enforce the OS-level sandbox, execute the fixed validation preset, and return evidence bound to the exact request digest.

The application stores only the SHA-256 verifier for the supervisor credential, so possessing application configuration is insufficient to derive the supervisor bearer token.

## Permanent non-authorities

This build grants no arbitrary shell/argv, package installation, network access, Git mutation, commit, push, PR creation, merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

## Validation

Fresh exact-head GitHub Actions validation is required before release. The dedicated BUILD-BRAIN-114K workflow runs compile, Ruff, focused request/credential/claim/receipt regressions, migration checks, and diff hygiene.
