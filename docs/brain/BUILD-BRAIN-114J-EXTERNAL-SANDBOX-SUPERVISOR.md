# BUILD-BRAIN-114J — External sandbox supervisor proof

Date: 2026-08-07
Base main: `ea0932adcd8cc1e279b2c555ad8e7872c56f7da4`
Release PR: #579
Implementation head: `057b035f7aa8481dde6e9732e10067de2ecbc712`

## Objective

Turn the executable-validation trust boundary from a repository-only contract into a demonstrable OS-level sandbox proof without granting production activation, merge, deployment, publication, taxonomy activation, database mutation, or Knowledge Graph mutation authority.

## Implemented

The BUILD-BRAIN-114J workflow launches a disposable Docker runtime with:

- `--network=none`;
- read-only container root filesystem;
- repository mounted read-only;
- all Linux capabilities dropped;
- `no-new-privileges` enforced;
- unprivileged uid/gid 65534;
- bounded tmpfs for `/tmp` with `noexec,nosuid,nodev`;
- no repository/application credentials passed into the container.

`scripts/verify_calyx_sandbox_runtime.py` fails closed unless it can independently demonstrate:

- expected credential variables are absent;
- `/proc/self/status` reports `NoNewPrivs: 1`;
- writes to the repository fail;
- writes to the container root filesystem fail;
- an outbound TCP connection cannot be established.

## Relationship to BUILD-BRAIN-114I

The safe non-executable BUILD-BRAIN-114I subset is already released on current main through PR #576 at `ea0932adcd8cc1e279b2c555ad8e7872c56f7da4`. That release deliberately excludes repository-code execution and keeps `repository_code_execution_authorized: false`.

BUILD-BRAIN-114J supplies an executable proof pattern for the external runtime controls that a future trusted supervisor must enforce. It does not wire a production service to issue authorizations, does not make an executable-validation role claimable, and does not run repository tests inside the proof container.

## Current-main validation evidence

Implementation head `057b035f7aa8481dde6e9732e10067de2ecbc712` passed all triggered current-main gates:

- BUILD-BRAIN-114J Sandbox Supervisor Validation `31225637538` — success;
- CALYX Workflow Governance Audit `31225637493` — success;
- BUILD-088E Validation `31225637482` — success.

The BUILD-BRAIN-114J job executed and passed each substantive stage:

1. repository checkout;
2. Python compilation of the supervisor verifier;
3. `Verify isolated runtime controls` Docker proof;
4. diff hygiene.

The isolated-runtime proof therefore actually executed on the GitHub-hosted runner; this is not an action-required or zero-job result.

## What this proof does and does not establish

The workflow demonstrates that the described disposable Docker invocation can enforce the tested controls in GitHub Actions. It is evidence for a supervisor implementation pattern, not a production authorization credential and not proof that an arbitrary future runtime is isolated.

A production supervisor still needs durable authorization issuance/evidence plumbing and deployment outside the repository process. The repository may not self-authorize executable validation based solely on this workflow, this Brain record, or a marker file.

## Authority state

No arbitrary shell/argv acceptance, package installation inside the sandbox, network, credentials, Git mutation, autonomous PR creation, automatic merge, deployment, scientific publication, taxonomy activation, production database mutation, or production Knowledge Graph mutation is authorized.

Repository-code execution remains disabled in current Calyx main. The blocked executable-validator/authorization wiring from stale PR #562 is intentionally not part of PR #579.

A final documentation head must rerun BUILD-BRAIN-114J before release.
