# BUILD-020 — Shared CI Repair Validation Record

## Scope

PR #509 repairs shared CI blockers affecting BUILD-087B, BUILD-089A, and BUILD-090B validation lanes.

## Intended corrections

- provide an explicit `DATABASE_URL` fallback when `TEST_DATABASE_URL` is intentionally unset;
- correct Ruff violations in `app/design_intelligence`;
- correct Ruff violations in `app/design_planning`;
- preserve FastAPI dependency defaults while documenting the required lint exception.

## Validation rule

The original PR head was authored by automation and GitHub returned `action_required` with no executed jobs. That state is not validation evidence. This owner-authored record intentionally synchronizes the branch so all affected workflows can execute on a new exact head.

The PR must remain unmerged unless the BUILD-087B, BUILD-088E, BUILD-089A/B/C, and BUILD-090B/C lanes complete successfully on the unchanged synchronized head.

## Governance

This repair changes CI configuration and formatting only. It grants no deployment, publication, taxonomy activation, credential, automatic merge, or production Knowledge Graph authority.
