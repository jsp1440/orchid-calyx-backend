# BUILD-616R — Mechanistic publication dry-run planner

## Canonical knowledge-state position

This slice consumes reviewed `MECHANISTIC_RELATIONSHIP` Candidate Knowledge and produces a deterministic **plan only** for the existing controlled publication boundary. It does not create a second knowledge store and does not change the Candidate Knowledge, Reasoning Ledger, reviewed-knowledge, or published-knowledge authorities.

## Provenance architecture

The plan preserves the reviewed Candidate Knowledge ID, exact evidence-link IDs, causal graph contract, experimental context, quantitative context, and source provenance carried by the reviewed candidate. Projected endpoint nodes use the explicit synthetic provenance namespace `synthetic.mechanistic_publication_plan`; they do not falsely claim to be rows in `oc_candidate_knowledge.candidates`. The projected causal edge references the reviewed Candidate Knowledge row by its real candidate ID.

## Gates

A plan is not ready unless the candidate is mechanistic, scientifically approved, unpublished, backed by exact evidence, free of open review/conflict blockers, valid under the controlled causal vocabulary, and healthy under canonical Knowledge Graph validation.

Even a ready plan returns `authorized=false`, `commit_capability=false`, `production_write_executed=false`, and `canonical_graph_mutated=false`. Publication requires the existing explicit controlled authorization boundary.

## Governance

Evidence remains evidence. The mechanistic assertion remains Candidate Knowledge until review. Approval produces reviewed knowledge, not published knowledge. This planner is a read-only bridge between reviewed knowledge and a later publication authorization; it never decides truth and never mutates production `oc_graph`.
