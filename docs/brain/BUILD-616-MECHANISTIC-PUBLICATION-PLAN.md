# BUILD-616 — Mechanistic Candidate Publication Plan

## Status

Implemented on stacked branch `feature/build-616-mechanistic-publication-plan`, based on BUILD-615. It must not merge before BUILD-615 and executable repository CI are both restored.

## Purpose

BUILD-616 converts a reviewed `MECHANISTIC_RELATIONSHIP` Candidate Knowledge record into a deterministic, read-only graph mutation plan. It does not publish the candidate and does not write to `oc_graph`.

This is intentionally a planning boundary between Candidate Knowledge review and the existing controlled publication system.

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
- the projected two-node/one-edge graph passes canonical Knowledge Graph validation.

Any failed condition is returned as an explicit blocker.

## Output

The planner returns contract `calyx-mechanistic-publication-plan-v1` with:

- deterministic `plan_id`;
- candidate and evidence identity;
- projected `UPSERT_NODE`, `UPSERT_NODE`, and `UPSERT_EDGE` operations;
- canonical graph validation report;
- blocker list;
- `ready_for_controlled_publication_gate`;
- `authorized=false`;
- `commit_capability=false`;
- `production_write_executed=false`;
- `canonical_graph_mutated=false`;
- `requires_explicit_publication_authorization=true`.

The same unchanged reviewed candidate produces the same plan ID.

## API

Authenticated read endpoint:

`GET /api/platform/brain/mechanistic-candidates/{candidate_id}/publication-plan`

The route only produces a plan. It has no graph-write repository and exposes no commit operation.

## Relationship to existing publication controls

The existing Knowledge Graph controlled dry-run architecture already separates projected publication from explicit owner authorization. BUILD-616 follows that principle rather than bypassing it.

A BUILD-616 plan that reports `ready_for_controlled_publication_gate=true` means only that its prerequisites and projected graph structure are clean enough to be submitted to a later governed publication step. It is not authorization.

## Governance guarantees

BUILD-616 cannot:

- approve scientific review;
- resolve evidence conflicts;
- invent missing provenance;
- write to production Knowledge Graph tables;
- set Candidate Knowledge `published=true`;
- authorize publication;
- execute the existing atomic publication engine;
- generalize a cultivation observation into a species-wide mechanism.

## Validation

`tests/test_build_616_mechanistic_publication_plan.py` covers:

- unreviewed candidate blocking;
- open review blocking;
- deterministic three-operation plans after review approval;
- unresolved conflict blocking;
- exact-evidence requirements;
- causal polarity and experimental/quantitative context preservation;
- explicit absence of authorization/write capability.

A focused BUILD-616 workflow is included, but repository Actions remain blocked by issue #481 (`steps=null` before checkout). Therefore this branch remains stacked and unmerged until executable CI returns.

## Next work after executable validation

1. Validate BUILD-615, merge it, then rebase/retarget BUILD-616 cleanly.
2. Run BUILD-616 focused tests and Candidate Knowledge/causal vocabulary regressions.
3. Add contradiction aggregation across mechanistic candidates before any controlled-publication submission.
4. Add explicit taxon/tissue/developmental/environmental scope models so causal claims cannot silently broaden beyond their evidence.
