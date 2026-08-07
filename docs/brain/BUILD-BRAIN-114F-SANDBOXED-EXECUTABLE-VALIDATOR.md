# BUILD-BRAIN-114F — Sandboxed fixed-command executable validator

## Objective

Advance Calyx from static post-patch validation to bounded executable validation without granting arbitrary shell, network, credential, Git, merge, deployment, publication, or production-scientific authority.

## Implemented

- Added the authoritative `isolated_workspace_executable_validator` role.
- Added a fail-closed sandbox marker contract bound to the exact repository and `autonomy/*` branch.
- The marker must assert that the external runtime has disabled network access, removed credentials, disabled shell access and package installation, and enforced subprocess confinement.
- Caller-supplied command strings are never executed. The only command sources are internal argv presets.
- Current presets are:
  - `pytest`: `python -m pytest -q -p no:cacheprovider <explicit test paths>`;
  - `ruff`: `python -m ruff check --no-cache <explicit app/test paths>`.
- Validation targets are limited to `app/` and `tests/`, bounded by file count and byte ceilings, and bound to exact SHA-256 post-patch hashes.
- Targets are rehashed after command completion; any change aborts authoritative validation.
- Checkout branch/commit identity is verified before and after execution.
- Environment inheritance is disabled. The child receives only a minimal explicit Python validation environment.
- Stdin is closed, `shell=False`, execution timeout is capped, and captured stdout/stderr are bounded and represented by hashes/byte counts in the receipt rather than copied into durable evidence.
- A non-zero validator result becomes an authoritative `BLOCKED` receipt rather than an exception masquerading as infrastructure failure.
- Timeout becomes an authoritative blocked/timed-out receipt.
- The executor registry truthfully reports this role as `repository_code_execution=true` while `workspace_mutation=false`.
- The persistent assignment factory grants `repository_code_execution` only to this role. Existing patch/static/read-only roles do not inherit it.

## Persistent-program integration

BUILD-BRAIN-114E already persists bounded per-job input manifests. BUILD-BRAIN-114F consumes those manifests through the standard assignment factory using a `validation` object containing:

- fixed `preset`;
- explicit `targets`;
- exact `expected_sha256` for every target;
- bounded timeout.

The validation role is therefore claimable through the same lease-governed autonomous program cycle as the earlier read/patch/static-validation roles.

## Validation surface

Focused tests cover:

- success receipt generation;
- fixed internal argv construction;
- scrubbed environment and non-inheritance of a synthetic secret;
- non-zero validation result → blocked receipt;
- timeout → bounded blocked receipt;
- sandbox marker mismatch;
- arbitrary command/preset rejection;
- stale hash rejection before subprocess launch;
- protected target rejection;
- mutating-job rejection;
- missing execution-capability rejection;
- registry capability truthfulness;
- persisted-program assignment grants execution authority only to the sandboxed validator.

## Important trust boundary

This Python adapter **does not create an OS/network sandbox by itself**. It is authoritative only when launched in a pre-created trusted sandbox whose marker truthfully represents enforcement outside the process. A marker without actual runtime enforcement is not sufficient operationally. Production activation must therefore bind marker creation to the sandbox supervisor rather than user-controlled workspace content.

Until that supervisor exists and is independently validated, this capability remains draft engineering infrastructure.

## GitHub Actions incident

Backend hosted-runner incident #533 currently causes jobs to fail before the first step (`steps=null`). A zero-step result is infrastructure evidence, not evidence that this implementation compiled, linted, or passed tests.

## Governance

Still unauthorized:

- arbitrary shell or subprocess commands;
- caller-provided argv;
- package installation;
- network access;
- credential access;
- Git branch creation/switching/commit/push;
- PR creation by Calyx;
- merge;
- deployment;
- publication;
- taxonomy activation;
- production database mutation;
- production Knowledge Graph mutation.

Issue: #543
