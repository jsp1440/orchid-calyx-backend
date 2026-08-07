# BUILD-BRAIN-114FG — Current-main supervisor-authorized executable validation

## Objective

Extend the current-main autonomous engineering consolidation from persisted patch/static-validation orchestration to bounded executable validation without granting arbitrary shell, network, credential, Git, merge, deployment, publication, or production-scientific authority.

## Implemented

- Added `isolated_workspace_executable_validator` on the current-main consolidation branch.
- Only internal fixed argv presets are supported: bounded `pytest` against explicit `tests/` targets and `ruff check` against explicit `app/`/`tests/` targets.
- Every target is bound to an expected SHA-256 digest and rechecked after execution.
- Target count, per-file bytes, aggregate bytes, timeout, stdout capture, and stderr capture are bounded.
- Child process receives a scrubbed environment, closed stdin, `shell=False`, no inherited credentials, disabled pytest plugin autoload, and disabled Python bytecode writes.
- Nonzero validation produces an authoritative BLOCKED receipt; timeout produces TIMED_OUT/BLOCKED.

## Trusted supervisor boundary

A repository-local sandbox marker is necessary but never sufficient. `SandboxValidationAuthorizer` is the trusted-runtime protocol that must authorize the exact workspace, repository, branch, and sandbox policy assertions before any subprocess launch.

The default `AuthoritativeExecutorRegistry` does not register the executable-validation role. It becomes eligible only when a supervisor authorizer is injected. Missing or rejected supervisor authorization fails before subprocess execution.

The assignment factory grants `repository_code_execution` only to this role. `workspace_write` remains exclusive to the isolated patch executor. Registry status reports both capabilities independently.

## Validation scope

The BUILD-BRAIN-114F aggregate workflow compiles and lints the complete current-main autonomy surface and runs the repository-evidence, patch, static-validation, persisted-input, integrated patch→static-validation, and sandboxed executable-validation regression suites.

Focused executable-validation tests cover:
- marker-only rejection;
- rejected supervisor fail-closed behavior;
- fixed argv and scrubbed environment;
- stale-hash rejection;
- arbitrary command/preset rejection;
- nonzero and timeout authoritative receipts;
- default-registry non-eligibility and durable queued/zero-attempt behavior;
- explicit eligibility only when a supervisor is supplied.

## Authoritative CI evidence

Current-main-derived head `f14c4f2a77f186cc53a5eaddbba99eea999a1cee` received real GitHub-hosted validation on 2026-08-07.

- BUILD-BRAIN-114F run `31211627055`: success. Checkout, setup, dependency install, compile, Ruff, focused autonomy regressions, migration compatibility, and diff hygiene all executed and passed.
- BUILD-BRAIN-114E run `31211626799`: success.
- BUILD-BRAIN-114D run `31211627433`: success.
- BUILD-BRAIN-114C run `31211626841`: success.
- BUILD-BRAIN-114B run `31211626509`: success.
- BUILD-BRAIN-114A run `31211627451`: success.
- BUILD-BRAIN-108-113A run `31211626750`: success.
- CALYX-AGENT-003 run `31211626515`: success.
- BUILD-088E run `31211626547`: success.

This is executable validation evidence, not a zero-step infrastructure result.

## Remaining operational boundary

Repository code does not itself create Linux namespaces, seccomp, network namespaces, read-only mounts, or another OS sandbox. Production activation requires a trusted external supervisor that actually enforces network isolation, credential removal, subprocess confinement, and read-only repository access before issuing authorization.

Still unauthorized: arbitrary caller-supplied shell or argv, package installation, network, credentials, Git mutation/commit/push, Calyx-created PRs, merge, deployment, publication, taxonomy activation, production database mutation, and production Knowledge Graph mutation.

## Disposition

Implementation and validation are complete on PR #551. The PR remains draft because merge is an explicit governance/release boundary, not routine autonomous implementation authority.
