# BUILD-BRAIN-114L — External sandbox supervisor worker

## Objective

Complete the execution side of BUILD-BRAIN-114K without moving repository-code execution back into the Calyx application process. The worker is a separately deployed process that authenticates to the 114K supervisor API, claims one exact validation request, independently verifies the request and repository checkout, executes only a fixed validation preset inside a constrained container, and returns request-bound evidence.

## Implemented

- standalone `runtime/sandbox_supervisor_worker.py` with no dependency on the Calyx application runtime;
- HTTPS-only supervisor API configuration except explicit localhost development endpoints;
- high-entropy supervisor bearer token retained only in the external worker process and never forwarded to the validation container;
- immutable validator image requirement using an `@sha256:<digest>` reference;
- local recomputation of the canonical 114K request digest before any repository code executes;
- exact repository, `autonomy/*` branch, claim-worker, claim-token, and checkout-commit verification;
- exact SHA-256 verification for every target before validation;
- target path allowlist limited to `app/` and `tests/`, bounded target size, path-escape rejection, and rejection of symlinks in any target path component;
- fixed validation presets only: focused `pytest` or Ruff; no caller-provided shell or arbitrary argv;
- pre-validation sandbox probe using worker-owned code rather than repository code;
- Docker controls: network disabled, container root read-only, repository mount read-only, all capabilities dropped, `no-new-privileges`, unprivileged UID/GID, bounded PID/memory/CPU resources, and bounded `noexec,nosuid,nodev` tmpfs;
- child process environment reduced to `PATH`; application/database/cloud credentials are not forwarded;
- bounded stdout/stderr capture with process termination on output overflow or timeout;
- receipt includes request digest, sandbox policy digest, authorization ID, outcome, return code, and hashes of captured stdout/stderr;
- focused regression tests and a dedicated read-only GitHub Actions validation gate.

## Security and authority model

The application remains unable to execute repository code itself. BUILD-BRAIN-114K creates and persists the request and validates the returned evidence. BUILD-BRAIN-114L is the separately deployed execution worker. The two components therefore require separate credentials and runtime placement.

The worker trusts only the fixed supervisor API protocol plus its locally configured repository identity, exact checkout, immutable validator image, and hard-coded sandbox policy. It does not trust request-supplied commands. It recomputes the request digest rather than accepting the server-provided digest as sufficient.

The sandbox probe is embedded in the worker so a modified repository cannot redefine the checks used to establish read-only filesystem, no-network, no-new-privileges, and credential-absence expectations.

## Deployment requirements before activation

Activation requires a dedicated host or runner with Docker available, a clean repository checkout that can be pinned to the exact requested commit, a prebuilt validator image referenced by immutable digest and containing the approved Python/test dependencies, and a supervisor bearer token not present in the Calyx application environment.

Production deployment must keep the worker separate from the web application and must not provide GitHub write credentials, cloud deployment credentials, production database credentials, publication credentials, or Knowledge Graph mutation credentials.

## Permanent non-authorities

BUILD-BRAIN-114L grants no package installation during validation, arbitrary shell, caller-controlled argv, network access inside the validation sandbox, Git mutation, commit, push, branch creation, pull-request creation, merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

## Validation contract

The dedicated `BUILD-BRAIN-114L External Sandbox Worker Validation` workflow compiles the worker/tests, runs Ruff, executes focused regressions, asserts key authority boundaries statically, and runs diff hygiene. Exact-head CI must be green before this slice is considered release-ready.
