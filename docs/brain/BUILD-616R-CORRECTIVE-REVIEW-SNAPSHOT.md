# BUILD-616R corrective review-snapshot hardening

## Status

PROPOSED / VALIDATION REQUIRED on PR #795. This PR is repurposed as a focused correction to the canonical BUILD-616R + BUILD-617R3 implementation already merged on `main`; it is no longer a competing publication-planner implementation.

## Corrections

- Refresh persistent Candidate Knowledge state before publication-plan reads so multi-worker deployments do not plan from a stale process-local snapshot.
- Bind `plan_id` to the exact latest scientific approval record and to a digest of the candidate/evidence content that was reviewed.
- Preserve BUILD-617R3 mechanistic-contradiction blockers.
- Emit no graph operations when any review, conflict, contradiction, evidence, active-state, publication-state, or graph-validation blocker exists.
- Separate endpoint canonical identity from Candidate Knowledge provenance and resolve projected edge endpoints by canonical key rather than planner-local numeric IDs.
- State truthfully that no canonical execution adapter currently accepts this plan rather than directing operators to an unsupported gate.
- Resolve the exact canonical Candidate Knowledge conflict when a `RESOLVE_CONFLICT` review decision is recorded; the conflict resolution does not approve the candidate.

## Governance

No scientific approval is created by this correction. No production Knowledge Graph write, publication, taxonomy activation, production database migration, deployment, or semantic-index truth mutation is authorized.

## Validation

UNVALIDATED until exact-head compile, Ruff lint/format, BUILD-616 regressions, Candidate Knowledge review regressions, BUILD-615 prerequisites, causal vocabulary / Reasoning Map regressions, route verification, broad Brain integration checks, and diff hygiene complete successfully.
