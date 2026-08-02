# CALYX-SUPERVISED-PILOT-001

## Purpose

Prepare one owner-approved, low-risk, draft-only engineering package for the taxonomy-to-image coverage report.

## Activation gates

The pilot runs only when all of the following are true:

1. The persistent runtime state is enabled.
2. Owner approval is recorded in the runtime state.
3. The runtime is not paused.
4. `CALYX_SUPERVISED_PILOT_ENABLED=true` is present in the backend environment.
5. The authenticated owner invokes the run-once control.

## Current pilot boundary

The pilot selects exactly one predefined task and prepares a draft pull-request package. It stops before connector execution. It does not create a GitHub branch or pull request by itself.

Prohibited actions remain: merge, deploy, scientific publication, production deletion, external communication, permission changes, and governance changes.

## Pilot task

`audit-taxonomy-image-coverage-report`

The task may change files only under `runtime`, `app/routers`, `tests`, `docs`, and `.github/workflows`.

## Promotion criteria

Connector execution must not be enabled until the package has been reviewed, the production owner-session controls pass smoke tests, and a separate connector adapter is validated with draft-only GitHub permissions.
