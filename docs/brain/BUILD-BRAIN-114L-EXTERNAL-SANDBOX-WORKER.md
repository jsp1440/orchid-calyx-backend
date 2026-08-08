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
- fail-closed clean-checkout verification using `git status --porcelain=v1 --untracked-files=all`, so tracked modifications and untracked files both block execution before snapshot creation;
- exact SHA-256 verification for every target from the immutable archived checkout that is actually executed;
- target path allowlist limited to `app/` and `tests/`, bounded target size, path-escape rejection, and rejection of symlinks in any target path component;
- fixed validation presets only: focused `pytest` or Ruff; no caller-provided shell or arbitrary argv;
- pre-validation sandbox probe using worker-owned code rather than repository code;
- Docker controls: network disabled, container root read-only, repository mount read-only, all capabilities dropped, `no-new-privileges`, unprivileged UID/GID, bounded PID/memory/CPU resources, and bounded `noexec,nosuid,nodev` tmpfs;
- every probe and validation container receives a unique explicit daemon-visible `--name`;
- child process environment reduced to `PATH`; application/database/cloud credentials are not forwarded;
- bounded stdout/stderr capture with explicit daemon-side `docker stop -t 2` followed by `docker rm -f` on timeout, output overflow, unfinished-process cleanup, and runner exceptions; cleanup is repeated safely in the outer `finally` so terminating the local Docker client cannot leave an unnamed/orphaned validation container;
- receipt includes request digest, sandbox policy digest, authorization ID, outcome, return code, and hashes of captured stdout/stderr;
- focused regression tests and a dedicated read-only GitHub Actions validation gate.

## Mainline integration state

BUILD-BRAIN-114K was merged to `main` as PR #655. PR #664 was then retargeted from the former stacked 114K branch to current `main`. The runtime delta remains purely additive.

PR #664 remains open and unmerged. The P1 security corrections below were validated against the PR merge result with then-current `main` at `70a1aff3f72f38486a6bbeb3b482b358583aa004`.

## Post-review security corrections

Two P1 review findings were accepted before merge and are addressed in the branch implementation.

1. **Immutable execution identity and clean checkout.** The worker refuses a configured checkout containing either tracked modifications or untracked files. It then verifies the requested HEAD and creates `git archive --format=tar <exact commit>`. Target path, symlink, size, and SHA-256 verification occurs only inside that immutable archived snapshot, and the same snapshot is mounted read-only into Docker. Regression coverage proves dirty checkout rejection before snapshot/container execution, proves a differing mutable checkout cannot change the mounted/hash-verified file, and proves a snapshot mismatch blocks even when a live file happens to match the request.
2. **Explicit container identity and daemon cleanup.** Every Docker run receives a unique `calyx-sbx-*` name before execution. `_run_docker_bounded` requires that name, uses it for daemon-side cleanup, and unconditionally executes `docker stop -t 2 <name>` plus `docker rm -f <name>` from `finally`. The bounded-process layer invokes the same cleanup on timeout/output overflow and when an unfinished process must be killed. Regression coverage verifies timeout cleanup, output-overflow cleanup, unique names, and cleanup when the runner itself raises.

Neither correction broadens authority.

## Exact validation receipt

Behavioral code/test head: `f0ae1e120d53c2137476d0d8d16f79fafe7d3e61`.

The pull-request workflow checked out merge ref `971f4e1864a9cdbce89e258492d2589949426f8a`, integrating that head with then-current `main` `70a1aff3f72f38486a6bbeb3b482b358583aa004`.

Exact-head results on 2026-08-08:

- `BUILD-BRAIN-114L External Sandbox Worker Validation` run #14 / Actions run `31279745869`: **success**;
  - compile: passed;
  - Ruff lint: passed;
  - Ruff format check: passed;
  - focused pytest: **13 passed in 0.17s**;
  - static authority/P1 assertions: passed;
  - diff hygiene: passed.
- `CALYX Workflow Governance Audit` run #518 / Actions run `31279745886`: **success**.
- `BUILD-088E Validation` run #1254 / Actions run `31279745871`: **success**.

A preceding run #12 intentionally failed before tests because the newly added Ruff format check found two unformatted files. That failure was corrected mechanically; no security behavior was weakened to obtain the passing run.

The documentation-bearing head created by this receipt must itself complete the same exact-head gates before the PR is treated as review-ready.

## Security and authority model

The application remains unable to execute repository code itself. BUILD-BRAIN-114K creates and persists the request and validates the returned evidence. BUILD-BRAIN-114L is the separately deployed execution worker. The two components therefore require separate credentials and runtime placement.

The worker trusts only the fixed supervisor API protocol plus its locally configured repository identity, a clean exact checkout, immutable validator image, and hard-coded sandbox policy. It does not trust request-supplied commands. It recomputes the request digest rather than accepting the server-provided digest as sufficient.

The sandbox probe is embedded in the worker so a modified repository cannot redefine the checks used to establish read-only filesystem, no-network, no-new-privileges, and credential-absence expectations.

## Deployment requirements before activation

Activation requires a dedicated host or runner with Docker available, a repository containing the exact requested commit with no tracked or untracked dirt, a prebuilt validator image referenced by immutable digest and containing the approved Python/test dependencies, and a supervisor bearer token not present in the Calyx application environment.

Production deployment must keep the worker separate from the web application and must not provide GitHub write credentials, cloud deployment credentials, production database credentials, publication credentials, or Knowledge Graph mutation credentials.

## Permanent non-authorities

BUILD-BRAIN-114L grants no package installation during validation, arbitrary shell, caller-controlled argv, network access inside the validation sandbox, Git mutation, commit, push, branch creation, pull-request creation, merge, deployment, publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation authority.

## Validation contract

The dedicated `BUILD-BRAIN-114L External Sandbox Worker Validation` workflow compiles the worker/tests, runs Ruff lint and format checks, executes focused regressions, asserts key authority boundaries statically, and runs diff hygiene. CALYX Workflow Governance Audit and BUILD-088E are also required. Exact-head CI must be green after these post-review corrections before this slice is review-ready. Merge remains a separate governance decision.
