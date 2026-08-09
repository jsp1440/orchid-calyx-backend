# BUILD-616-R2 — Mechanistic Publication Dry-Run Planner

BUILD-616-R2 is rebuilt directly on the merged BUILD-615 canonical mainline.

It does not create a publication engine or knowledge store. It reads existing Candidate Knowledge and exact evidence links, requires scientific review approval and no open review/conflict blockers, reconstructs the controlled causal graph contract, validates the projected graph with the canonical Knowledge Graph validator, and returns an immutable dry-run mutation plan.

The planner always returns `authorized=false`, `commit_capability=false`, `production_write_executed=false`, and `canonical_graph_mutated=false`. A clean result means only that the reviewed candidate is structurally ready to be presented to the existing controlled publication gate; it is not publication authorization.

Knowledge state remains: evidence → Candidate Knowledge → reviewed Candidate Knowledge → publication plan → separately authorized published knowledge.

The planner preserves endpoint canonical identity (`canonical_key == node_type:source_pk`), causal polarity, experimental/quantitative context, provenance, candidate identity, and evidence-link identity. Missing evidence, unresolved review/conflict state, invalid causal contracts, malformed canonical keys, graph-validation failure, or already-published state fail closed.

Dedicated validation covers BUILD-616 behavior, merged BUILD-615 regressions, causal vocabulary/Reasoning Map regressions, route verification, lint/format/compile, and hygiene.

No contradiction resolution, review approval, semantic-index authority, Knowledge Graph mutation, production database mutation, taxonomy activation, deployment, or automatic scientific publication is granted.
