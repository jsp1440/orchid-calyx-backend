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

The BUILD-BRAIN-114F aggregate workflow now compiles and lints the complete current-main autonomy surface and runs the repository-evidence, patch, static-validation, persisted-input, integrated patch→static-validation, and sandboxed executable-validation regression suites.

Focused executable-validation tests cover:
- marker-only rejection;
- rejected supervisor fail-closed behavior;
- fixed argv and scrubbed environment;
- stale-hash rejection;
- arbitrary command/preset rejection;
- nonzero and timeout authoritative receipts;
- default-registry non-eligibility and durable queued/zero-attempt behavior;
- explicit eligibility only when a supervisor is supplied.

## Remaining operational boundary

Repository code does not itself create Linux namespaces, seccomp, network namespaces, read-only mounts, or another OS sandbox. Production activation requires a trusted external supervisor that actually enforces network isolation, credential removal, subprocess confinement, and read-only repository access before issuing authorization.

Still unauthorized: arbitrary caller-supplied shell or argv, package installation, network, credentials, Git mutation/commit/push, Calyx-created PRs, merge, deployment, publication, taxonomy activation, production database mutation, and production Knowledge Graph mutation.

## Disposition

Implementation is staged on PR #551. Keep the PR draft until real GitHub Actions validation succeeds on the resulting current-main-derived head. Merge remains an explicit governance boundary.
