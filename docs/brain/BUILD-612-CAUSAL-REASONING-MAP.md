# BUILD-612 — Causal Reasoning Map

## Status

Implemented on `feature/build-612-causal-reasoning-map` in PR #622. The BUILD-612 implementation and strengthened blocking Brain integration gate are green and the build is ready to merge.

## Purpose

BUILD-612 separates two concepts that were previously conflated in the Brain: candidate inference and causal reasoning maps. The existing `InferenceEngine` proposes candidate relationships from deterministic graph patterns. The new `ReasoningMapEngine` assembles multi-step, evidence-bearing explanatory pathways over canonical Knowledge Graph state without mutating or publishing that state.

This is the foundation for reasoning across genetics, regulation, anatomy, morphology, physiology, development, environment, phenotype, cultivation, and conservation.

## Implemented capability

`app/brain/reasoning_map.py` adds:

- forward, backward, and bidirectional traversal;
- explicit reasoning profiles for biological mechanism, phenotype expression, cultivation diagnosis, evidence tracing, and unrestricted graph reasoning;
- causal semantics for promoting, inhibitory, regulatory, evidence, and contextual relationships;
- path polarity propagation;
- deterministic confidence propagation using the weakest evidence edge plus a depth penalty;
- evidence/provenance extraction for every edge and complete path;
- cycle prevention at the pathway level;
- configurable depth, edge filters, causal-only traversal, and result limits;
- deterministic node/edge/path ordering;
- a fail-closed governance envelope declaring reasoning maps read-only explanatory artifacts.

## API

`POST /brain/reasoning-map`

Example request:

```json
{
  "subject_node_id": 101,
  "direction": "forward",
  "profile": "phenotype_expression",
  "max_depth": 5,
  "limit": 200,
  "causal_only": true
}
```

The response includes the focal subject, map configuration, participating nodes, semantically annotated edges, complete reasoning paths, depth layers, summary counts, evidence references, path confidence, path polarity, and governance state.

## Scientific model

The engine is intentionally ontology-tolerant. It does not require every scientific domain to be fully populated before it can operate. As the Knowledge Graph gains entities and relationships such as:

`gene -> protein -> hormone/signaling -> cell/tissue -> anatomy/physiology -> developmental process -> phenotype -> ecological or cultivation outcome`

BUILD-612 can expose those chains immediately as inspectable reasoning maps.

The same engine can trace backward from an observed phenotype or symptom toward plausible upstream mechanisms when those causal relationships are present in the graph.

## Relationship to the Matrix and Calyx

This engine is the reusable causal substrate for later Matrix work. The Matrix can supply environmental measurements, cultivation interventions, phenotypic observations, and quantitative analyses; the reasoning map can then connect those observations to Knowledge Graph mechanisms and evidence.

Calyx conversational analysis can consume the map as structured context rather than inventing an opaque narrative chain. This preserves the Continuum-first epistemic policy established in BUILD-610/611.

## Governance boundary

BUILD-612 does not:

- create canonical Knowledge Graph nodes or edges;
- publish inferred scientific claims;
- bypass the Reasoning Ledger or publication controls;
- treat an explanatory path as proof of causality merely because the path exists.

Any new scientific claim derived from a map remains candidate knowledge subject to evidence and publication governance.

## Validation

The blocking `.github/workflows/calyx-brain-integration-validation.yml` gate was strengthened so the BUILD-612 suite is linted, formatter-checked, executed with the governed Brain tests, included in secret/hygiene scanning, and the `/brain/reasoning-map` route is asserted in the compiled application OpenAPI surface.

Run `31253664618` completed successfully on the live PR merge result against the current `main`. The following stages all passed:

- Ruff;
- Ruff formatting;
- governed Brain bridge and BUILD-612 behavioral tests;
- PostgreSQL 16 migration integration;
- adjacent Knowledge Graph, literature, candidate-knowledge, and research-workspace regressions;
- compile and route import, including `/brain/reasoning-map`;
- secret scan and repository hygiene.

`tests/test_build_612_reasoning_map.py` specifically covers:

- relationship polarity and semantic classification;
- multi-step gene-to-phenotype causal traversal;
- backward environmental-cause tracing;
- evidence preservation;
- confidence propagation;
- cycle prevention;
- exclusion of non-causal context in causal-only mode;
- authenticated API behavior;
- read-only governance;
- fail-closed unknown-node and invalid-payload behavior.

## Next highest-value extensions

1. Add controlled causal predicates to the scientific Knowledge Graph ontology and loaders so physiology/development relationships are first-class canonical edges.
2. Connect `ReasoningMapEngine` to Calyx conversational analysis as optional structured reasoning context.
3. Add Matrix adapters that translate measured environmental/cultivation variables and observations into noncanonical session nodes, then reason against canonical mechanisms without contaminating canonical graph state.
4. Add hypothesis comparison so competing causal pathways can be ranked by evidence coverage, contradictions, confidence, and missing observations.
5. Add a public visualization contract for homepage/book pathways and educational explanations.
