# BUILD-BRAIN-114H — Request-bound supervisor authorization

## Objective

Prevent trusted-supervisor authorization from being replayed across a different executable-validation request.

## Implemented

The sandboxed executable validator now computes a canonical SHA-256 authorization request digest before subprocess launch. The digest binds:

- repository;
- autonomy branch;
- exact checkout commit SHA;
- complete validated sandbox marker assertions;
- fixed validation preset;
- target list and exact target SHA-256 values;
- effective bounded timeout.

The digest is passed to `SandboxValidationAuthorizer`. `SandboxAuthorization` must return the same request digest. Mismatch, invalid digest, missing supervisor, or supervisor rejection fails closed before subprocess execution.

The accepted request digest is included in the authoritative execution output and evidence URI set as `sandbox-request:<sha256>`.

Target hashes are verified before supervisor authorization, so stale or changed input files cannot cause an authorization request to be issued for unverified content.

## Regression coverage

Focused tests prove:

- repository marker alone cannot authorize execution;
- a supervisor sees the exact canonical request digest;
- stale/mismatched authorization evidence is rejected before subprocess launch;
- stale target hashes fail before the supervisor is called;
- arbitrary command fields and presets remain rejected;
- fixed argv, scrubbed environment, blocked nonzero results, timeout behavior, default-registry non-eligibility, and explicit supervisor-only eligibility remain intact.

## Validation evidence

Current-main consolidation code head `c942ab23b7c761d44f68c5fd2f35622f0f70fea1` passed real GitHub-hosted validation on 2026-08-07.

- BUILD-BRAIN-114F run `31211906137`: success — checkout, setup, install, compile, Ruff, focused current-main autonomy regressions, migration compatibility, and diff hygiene all passed.
- BUILD-BRAIN-114E run `31211906088`: success.
- BUILD-BRAIN-114D run `31211906057`: success.
- BUILD-BRAIN-114C run `31211905704`: success.
- BUILD-BRAIN-114B run `31211906072`: success.
- BUILD-BRAIN-114A run `31211905827`: success.
- BUILD-BRAIN-108-113A run `31211906092`: success.
- CALYX-AGENT-003 run `31211905774`: success.
- BUILD-088E run `31211906035`: success.

## Remaining trust boundary

This request binding proves what the trusted supervisor authorized; it does not itself provide the OS sandbox. Production activation still requires an external supervisor that actually enforces network isolation, credential removal, subprocess confinement, and repository read-only behavior before issuing authorization.

No arbitrary shell/argv, package installation, network, credentials, Git mutation, merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is authorized by this slice.

Tracking: #553. Staged on PR #551. Merge remains an explicit governance boundary.
