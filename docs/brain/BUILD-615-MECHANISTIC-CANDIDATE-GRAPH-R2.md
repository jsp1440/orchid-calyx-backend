# BUILD-615-R2 — Evidence-Governed Mechanistic Candidate Graph

## Status

Current-main reconstruction of BUILD-615. This branch replaces the stale/non-mergeable historical integration path while preserving only the intended scientific and governance delta.

## Canonical architecture role

BUILD-615-R2 does not create a knowledge or reasoning store. It bridges mechanistic evidence into the existing Candidate Knowledge lifecycle and validates a non-persistent graph preview against the existing canonical Knowledge Graph vocabulary/validator.

Knowledge-state boundaries are explicit:

- source text and exact source anchors are evidence;
- a mechanistic extraction is Candidate Knowledge, not reviewed or published knowledge;
- the graph preview is validation-only and never writes `oc_graph`;
- scientific orchestration classifies mechanistic candidates as scientific inference even at high confidence;
- human review remains required;
- reviewed knowledge still requires the existing governed publication boundary before becoming published canonical graph knowledge.

## Contract

`POST /api/platform/brain/mechanistic-candidate` is owner/API-key protected.

The adapter requires a controlled causal relationship, approved causal endpoint node types, exact evidence anchors, canonical source/revision/extraction identity, confidence, and optional experimental/quantitative/provenance context.

Before Candidate Knowledge creation it constructs a two-node/one-edge in-memory graph preview and requires the canonical Knowledge Graph validator to report healthy. Endpoint metadata cannot override the internal `candidate_only=true` governance marker.

Valid claims enter the existing Candidate Extraction Service as `MECHANISTIC_RELATIONSHIP`. Evidence aggregation maps that kind to `MECHANISTIC_RELATIONSHIP_AGGREGATE`, and scientific orchestration routes it at `LEVEL_2_SCIENTIFIC_INFERENCE` or higher rather than routine provisional knowledge.

## Governance

The build cannot automatically approve evidence, publish scientific knowledge, resolve contradictions, write the canonical Knowledge Graph, alter the semantic index as canonical truth, activate taxonomy, mutate production data, or deploy.

## Validation

Dedicated CI covers compile, Ruff, formatting, focused behavioral regressions, BUILD-614 causal vocabulary and BUILD-612 Reasoning Map regressions, Candidate Knowledge regressions, protected route verification, and hygiene. Exact-head executable results must be recorded before readiness.
