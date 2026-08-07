# BUILD-BRAIN-114FG — Sandboxed executable validation with trusted supervisor authorization

## Objective

Advance the autonomous engineering program from patch + static validation to bounded executable validation without granting arbitrary shell, network, credential, Git, merge, deployment, publication, or production-scientific authority.

## Implemented

- Added `isolated_workspace_executable_validator`.
- Only internal fixed argv presets are executable: bounded `pytest` on explicit `tests/` targets and `ruff check` on explicit `app/`/`tests/` targets.
- Caller command strings and argv are rejected.
- Every target is bound to an expected SHA-256 hash, checked before and after execution, with file-count and byte ceilings.
- Child environment is explicitly scrubbed; pytest plugin autoloading and Python bytecode writes are disabled; stdin is closed; `shell=False`; timeout and captured output are bounded.
- Nonzero validation produces an authoritative BLOCKED receipt; timeout produces TIMED_OUT/BLOCKED rather than being confused with infrastructure failure.

## Trusted supervisor correction

A repository-local sandbox marker is necessary but never sufficient. `SandboxValidationAuthorizer` is an external-runtime protocol that must independently authorize the exact workspace, repository, branch, and asserted sandbox controls. The default `AuthoritativeExecutorRegistry` does not register the executable-validation role. It becomes claimable only when a trusted supervisor authorizer is injected.

Supervisor evidence is non-secret and receipt-bound through authorization ID, evidence URI, and policy digest. Missing or rejected supervisor authorization fails before subprocess launch.

## Durable autonomous-program integration

BUILD-BRAIN-114E persists bounded per-job input manifests. The assignment factory now grants `repository_code_execution` only to the executable-validator role while preserving `workspace_write` only for the isolated patcher. Default autonomous workers therefore cannot claim executable-validation jobs unless the trusted runtime supplies authorization.

Focused tests cover marker-only rejection, supervisor rejection, fixed argv, scrubbed environment, secret non-inheritance, stale hashes, arbitrary-command rejection, nonzero/timeout receipts, default-registry non-eligibility, durable queued state with zero attempts when no supervisor exists, and explicit eligibility when a supervisor is injected.

## Current validation status

GitHub-hosted backend runners recovered during this work. A prior BUILD-BRAIN-114F run executed real checkout/setup/install/compile/Ruff/pytest/diff-hygiene steps successfully after correcting a Ruff import issue. The inherited BUILD-BRAIN-114B/114C/114D/114E workflows then exposed ordinary lint defects, proving the former `steps=null` runner-allocation incident was no longer masking code validation. Those inherited lint corrections were incorporated into the current BUILD-BRAIN-114E base before this clean consolidation branch was created.

This clean branch is based on the current BUILD-BRAIN-114E head rather than the earlier diverged 114F branch.

## Remaining operational boundary

Repository code does not itself create Linux namespaces, seccomp, container network isolation, read-only mounts, or another OS sandbox. Production activation requires an external supervisor implementation that actually enforces the asserted controls before issuing authorization. Until that supervisor exists and is independently validated, executable repository-code validation remains draft engineering infrastructure.

Still unauthorized: arbitrary shell/subprocess commands, caller-provided argv, package installation, network, credentials, Git mutation/commit/push, PR creation by Calyx, merge, deploy, publication, taxonomy activation, production database mutation, and production Knowledge Graph mutation.

Issues: #543, #546
