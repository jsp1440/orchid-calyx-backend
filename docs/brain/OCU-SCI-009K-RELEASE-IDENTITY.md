# OCU-SCI-009K — Deployed backend release identity

## Purpose

Provide a public, non-secret, fail-closed identity for the exact backend Git commit that a deployed Orchid Continuum service claims to be running. This closes a deployment-verification gap used by University release checks and broader Calyx deployment preflight work.

## Implementation

- `GET /api/release-identity` is mounted through the existing health aggregate router.
- The endpoint accepts only a full lowercase 40-character hexadecimal Git SHA as attested.
- Release identity is read only from explicit deployment metadata in priority order: `OCU_RELEASE_SHA`, `CALYX_DEPLOYED_COMMIT`, `RENDER_GIT_COMMIT`, `GIT_COMMIT`, `COMMIT_SHA`.
- Missing or short values fail closed with `attested=false` and `commit_sha=null`.
- The response contains no database URL, API key, owner credential, publication state, or other secret/runtime mutation data.
- The University release-contract workflow compiles and tests the route contract.

## Current-main recovery

Original PR #662 was fully green but became non-mergeable after `main` advanced. The implementation was rebuilt byte-for-byte where additive and with only the two intended `health.py` routing lines on current `main` in `feature/ocu-sci-009k-release-identity-current-main`.

## Governance

This endpoint is attestational only. It does not deploy a release, mutate production state, enable autonomy, publish scientific knowledge, alter Candidate Knowledge, activate taxonomy, or mutate the production Knowledge Graph. A deployment must still set trustworthy release metadata before the endpoint can attest a commit.
