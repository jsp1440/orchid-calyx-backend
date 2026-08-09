# BUILD-617R3 — Mechanistic contradiction accounting

## Canonical knowledge-model role

This slice is a read-only analytical projection over the existing Candidate Knowledge repository. It does not persist a second contradiction/truth store and does not resolve scientific disagreements.

A contradiction is recorded only when active mechanistic Candidate Knowledge assertions share the same declared source/target canonical keys, taxon scope, experimental context, and quantitative context, while controlled causal vocabulary assigns opposite polarity. Different declared scopes are not collapsed into contradiction.

## Provenance and state boundaries

Evidence links remain attached to Candidate Knowledge. Contradiction clusters reference Candidate Knowledge IDs and summarize evidence counts; they do not rewrite evidence, confidence, review state, or graph state. `resolved=false` and `truth_decision=false` are deliberate: resolution belongs to qualified scientific review and the existing Reasoning Ledger/review architecture.

## Publication interaction

The BUILD-616R read-only publication planner consumes contradiction IDs as blockers. Contradiction membership therefore prevents a mechanistic assertion from being reported ready for controlled publication, but this analyzer cannot approve, reject, retract, or publish anything.

## Governance

- candidate mutation: false
- graph mutation: false
- truth decision: false
- automatic publication: false
- production Knowledge Graph mutation: false

The Brain remains the canonical institutional/knowledge memory; this is a derived evaluation surface only.
