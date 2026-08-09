# BUILD-616R corrective review-snapshot hardening

## Status

VALIDATED on PR #795 as a focused correction to the canonical BUILD-616R + BUILD-617R3 implementation already merged on `main`. The PR is no longer a competing publication-planner implementation: current `main` is its merge base and only the corrective planner, canonical Candidate Knowledge repository, canonical BUILD-616R workflow, focused tests, and this Brain record differ.

## Corrections

- Refresh persistent Candidate Knowledge state before publication-plan reads so multi-worker deployments do not plan from a stale process-local snapshot.
- Bind `plan_id` to the exact latest scientific approval record and to a digest of the candidate/evidence content that was reviewed.
- Preserve BUILD-617R3 mechanistic-contradiction blockers.
- Emit no graph operations when any review, conflict, contradiction, evidence, active-state, publication-state, or graph-validation blocker exists.
- Separate endpoint canonical identity from Candidate Knowledge provenance and resolve projected edge endpoints by canonical key rather than planner-local numeric IDs.
- State truthfully that no canonical execution adapter currently accepts this plan rather than directing operators to an unsupported gate.
- Resolve the exact canonical Candidate Knowledge conflict when a `RESOLVE_CONFLICT` review decision is recorded; the conflict resolution does not approve the candidate.
- Consolidate corrective CI into the existing canonical `BUILD-616R Mechanistic Publication Plan Validation` workflow; the older duplicate BUILD-616 workflow was removed from the PR surface.

## Validation evidence

Exact corrective code head `b03e6f88bc061d790c85487a297a783a110d620f` passed all nine applicable executable suites on 2026-08-09:

- BUILD-616R Mechanistic Publication Plan Validation — run `31325806765` — success;
- BUILD-617R3 Mechanistic Contradiction Validation — run `31325806705` — success;
- BUILD-086A validation — run `31325806706` — success;
- BUILD-086D review-readiness corrections — run `31325806719` — success;
- BUILD-088E Validation — run `31325806716` — success;
- CALYX-BRAIN-001A Validation — run `31325806701` — success;
- CALYX Brain End-to-End Certification — run `31325806700` — success;
- Calyx Brain Integration Validation — run `31325806711` — success, including PostgreSQL 16 migration integration, adjacent subsystem regressions, route import, secret scan, and hygiene;
- CALYX Workflow Governance Audit — run `31325806731` — success.

The focused BUILD-616R gate passed compile, Ruff lint, Ruff formatting, BUILD-616R behavioral regressions, Candidate Knowledge review regressions, BUILD-615 prerequisite regressions, causal vocabulary and Reasoning Map regressions, route import, and diff hygiene.

This documentation update requires one final exact-head verification before merge so the recorded validation and current repository head remain aligned.

## Governance

No scientific approval is created by this correction. No production Knowledge Graph write, publication, taxonomy activation, production database migration, deployment, semantic-index truth mutation, or external scientific communication is authorized.

## Remaining dependency

A publication plan remains readiness evidence only. `publication_adapter_available=false` is intentional until a separately governed canonical adapter is designed and authorized. The current correction must not be interpreted as publication authority.
