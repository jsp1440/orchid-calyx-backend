# BUILD-616 — Mechanistic Candidate Publication Plan

## Purpose

BUILD-616 converts a reviewed `MECHANISTIC_RELATIONSHIP` Candidate Knowledge record into a deterministic, read-only graph publication plan. It does not publish the candidate, write to `oc_graph`, set `published=true`, or invoke the atomic publication engine.

This is the planning boundary between Candidate Knowledge review and a later controlled publication authorization step.

## Institutional status

**FACT** — BUILD-615 / PR #733 is merged into canonical `main`. Hosted GitHub Actions are executing normally; the historical zero-step runner incident is not the current blocker.

**IMPLEMENTED** — PR #740 / branch `feature/build-616-mechanistic-publication-plan` has been reconstructed on current `main`. Its diff is limited to the five BUILD-616 files: planner, authenticated read route, dedicated workflow, focused regressions, and this Brain record.

**IMPLEMENTED** — Review remediation separates graph identity from scientific provenance:

- projected validation nodes use synthetic planning provenance so endpoint canonical identity remains internally valid;
- emitted node operations identify nodes by canonical key and separately bind provenance to the real Candidate Knowledge row (`oc_candidate_knowledge.candidates`, candidate ID);
- emitted edge operations resolve endpoints by `from_canonical_key` / `to_canonical_key` rather than planner-local node IDs;
- no operations are emitted while scientific review, evidence, conflict, graph-validation, or already-published blockers remain;
- `reviewed_candidate` and reviewed evidence labels are derived from actual `APPROVED` review state rather than asserted unconditionally.

**VALIDATED** — Pre-reconstruction head `7d72e826cf67c05a831ae9da2aceb0d16d6eac1e` passed BUILD-616 run `31324103347`: compile, Ruff lint, Ruff formatting, focused BUILD-616 regressions, BUILD-615 prerequisite regressions, causal-vocabulary regressions, read-only route verification, and diff hygiene. The same head also had successful Candidate Handoff, BUILD-086A, CALYX-BRAIN-001A, OC Platform Routes, OC Parallel Platform, and workflow-governance checks while several broader checks were still completing.

**UNVALIDATED CURRENT HEAD** — The current-main reconstruction and this documentation commit require a fresh exact-head workflow verdict before merge classification can change to ready.

**BLOCKED** — Three review threads on PR #740 remain unresolved in GitHub even though their P1/P2 findings have been implemented. Reviewer acknowledgement/closure remains a merge gate.

## Preconditions

A candidate is ready for a publication plan only when all of the following hold:

- candidate kind is `MECHANISTIC_RELATIONSHIP`;
- scientific candidate review state is `APPROVED`;
- candidate is not already marked published;
- at least one exact Candidate Knowledge evidence link exists;
- no candidate-specific review item remains open;
- no unresolved conflict group contains the candidate;
- the BUILD-615 graph contract contains approved source and target causal node types;
- the relationship remains a controlled BUILD-614 causal/regulatory relationship;
- the projected two-node/one-edge validation graph passes canonical Knowledge Graph validation.

Any failed condition is returned as an explicit blocker and suppresses publication operations.

## Output contract

The planner returns `calyx-mechanistic-publication-plan-v2` with:

- deterministic `plan_id`;
- candidate and evidence identity;
- when and only when ready: two canonical-key `UPSERT_NODE` projections and one canonical-key-resolved `UPSERT_EDGE` projection;
- resolvable Candidate Knowledge provenance separate from endpoint identity;
- canonical graph validation report;
- blocker list;
- `ready_for_controlled_publication_gate`;
- `authorized=false`;
- `commit_capability=false`;
- `production_write_executed=false`;
- `canonical_graph_mutated=false`;
- `requires_explicit_publication_authorization=true`.

A clean plan is evidence that prerequisites and projected structure are suitable for later controlled review. It is not publication authorization.

## API

Authenticated read endpoint:

`GET /api/platform/brain/mechanistic-candidates/{candidate_id}/publication-plan`

The route only produces a plan. It has no graph-write repository and exposes no commit operation.

## Governance guarantees

BUILD-616 cannot:

- approve scientific review;
- resolve evidence conflicts;
- invent missing provenance;
- write to production Knowledge Graph tables;
- set Candidate Knowledge `published=true`;
- authorize publication;
- execute the atomic publication engine;
- generalize a scoped observation into a broader mechanism.

## Validation contract

`tests/test_build_616_mechanistic_publication_plan.py` covers:

- unreviewed candidates produce blockers and zero operations;
- unresolved conflicts and missing evidence suppress operations;
- approved candidates produce deterministic three-operation plans;
- edge endpoints are canonical-key resolved, not planner-local numeric IDs;
- candidate-row provenance is resolvable and distinct from endpoint canonical identity;
- causal polarity and experimental/quantitative context are preserved;
- authorization/write capability remains absent.

The dedicated workflow additionally runs BUILD-615 prerequisite and causal-vocabulary regressions, route verification, compilation, Ruff lint/format, and diff hygiene.

## Remaining scientific work

**PROPOSED** — Add contradiction aggregation across mechanistic candidates before any controlled-publication submission.

**PROPOSED** — Add explicit taxon/tissue/developmental/environmental scope models so causal claims cannot silently broaden beyond their evidence.
