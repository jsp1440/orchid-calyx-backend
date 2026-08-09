# Calyx Brain Canonical Memory and Reasoning Map Contract

## Status

Normative architecture companion to `CALYX_BRAIN_SPECIFICATION_V1.md`.

This document defines the execution boundary for the Orchid Continuum Brain, Knowledge Graph, evidence/provenance architecture, semantic indexing, Reasoning Map, Relationship Validator, and reasoning ledger.

It does not create a competing knowledge store. Existing evidence, candidate-knowledge, concept, interpretation, publication, workflow, and memory components remain authoritative for the responsibilities they already own.

## Canonical institutional memory

The Calyx Brain is the canonical institutional and knowledge memory for the Orchid Continuum.

Durable scientific state must be represented through explicit, versioned, attributable records. Runtime caches, model context, temporary prompts, local files, and agent scratch state are never canonical institutional memory unless they are promoted through a governed persistence contract.

The Brain must preserve both content and lineage: what is known, why it is believed, what evidence supports or challenges it, what inference transformed the evidence, who or what reviewed it, and whether it is eligible for publication.

## Knowledge-state ladder

Scientific artifacts must remain distinguishable throughout their lifecycle. These states are architectural categories, not interchangeable labels.

1. **Source Evidence**
   - immutable or versioned source material and exact source anchors
   - source hash, revision identity, access/display policy, and provenance
   - never rewritten to match an interpretation

2. **Machine Extraction / Observation**
   - entities, measurements, claims, tables, figures, relationships, or other extracted records
   - extractor/version/method/confidence retained
   - may be wrong or ambiguous

3. **Inference**
   - a structured derivation from one or more evidence records
   - must identify inputs, operation/method, assumptions, uncertainty, and counterevidence
   - does not become canonical knowledge merely because confidence is high

4. **Candidate Knowledge**
   - proposed taxon, trait, occurrence, relationship, conservation, cultivation, or other scientific assertion awaiting governance
   - must remain unpublished by default
   - duplicate, conflicting, and ambiguous candidates remain explicit

5. **Reviewed Knowledge**
   - candidate or interpretation that has passed the required review gate
   - reviewer identity, decision, rationale, and revision history retained
   - may still be blocked from publication

6. **Published Knowledge**
   - canonical assertion explicitly approved for the production knowledge surface
   - published identity must link backward to the complete evidence, inference, candidate, and review lineage

7. **Superseded / Retracted Knowledge**
   - prior published state retained for history and reproducibility
   - replacement or retraction never destroys prior provenance

No service may collapse these states into one generic `knowledge` object.

## Canonical identity rule

The same scientific proposition may appear in multiple representations, but each representation must retain its own stable identity and explicit links to adjacent stages.

Required identity links include, where applicable:

- source object -> source revision
- source revision -> extraction run
- extraction run -> source anchor
- source anchor -> evidence
- evidence -> claim
- evidence/claim -> candidate knowledge
- evidence/candidate -> reasoning record
- reasoning record -> interpretation/conclusion
- interpretation -> review decision
- review decision -> published assertion
- assertion -> concept and relationship identities

Identifiers must not be synthesized at a downstream stage when an upstream canonical owner already exists.

## Reasoning Map

The Reasoning Map is not a second knowledge graph. It is an auditable graph of reasoning relationships between already-governed identities.

### Core node classes

- Objective
- Question
- Hypothesis
- EvidenceSelection
- Assumption
- Method / ReasoningOperation
- IntermediateArtifact
- ConflictZone
- ValidationResult
- Conclusion
- ReviewDecision
- MemoryReference

### Core edge classes

- `addresses`
- `supports`
- `counters`
- `derived_from`
- `assumes`
- `uses_method`
- `produces`
- `conflicts_with`
- `validated_by`
- `supersedes`
- `reviewed_by`
- `references_memory`
- `eligible_for_publication`
- `blocked_from_publication`

Every reasoning edge must be attributable to a reasoning record/revision and may not silently mutate evidence or canonical concepts.

## Reasoning ledger contract

The reasoning ledger is the append-only institutional record of scientific reasoning events.

It records structured, auditable rationale and execution metadata; it must not store private model chain-of-thought.

Minimum durable record:

- reasoning record ID and schema version
- project/tenant scope
- objective/question
- ordered typed plan
- selected evidence and counterevidence IDs
- hypotheses
- assumptions
- operations and method identities
- intermediate artifact identities
- uncertainty/confidence
- unresolved conflicts
- validation results
- conclusion
- review/publication state
- actor/tool/model identities where applicable
- content/configuration hashes
- timestamps and append-only audit history

A reasoning conclusion without evidence lineage is invalid for canonical publication.

## Relationship Validator

The Relationship Validator is the governed boundary for proposing or validating scientific relationships before they enter published knowledge.

It must validate at minimum:

- source and target identities exist and are in an allowed lifecycle state
- predicate is from the governed relationship vocabulary
- directionality and symmetry rules are respected
- evidence anchors are present
- provenance is complete
- confidence/uncertainty is explicit
- contradictory relationships are surfaced, not overwritten
- taxonomic or concept mappings are not guessed when ambiguous
- required human review is satisfied

Validation output is a decision artifact, not a destructive edit to the evidence or candidate record.

## Evidence/provenance invariants

1. Exact source anchors are immutable once persisted for a source revision.
2. Derived objects always retain the IDs of the evidence records used to create them.
3. Normalization may add canonical mappings but must not rewrite original source text.
4. A source hash mismatch invalidates downstream anchor assumptions until revalidated.
5. Re-extraction creates a new execution identity when extractor versions, order, settings, or source revision change.
6. Conflicting evidence remains queryable even after a preferred interpretation is reviewed.
7. Publication never severs lineage back to source evidence.

## Semantic indexing boundary

Semantic indexes are retrieval accelerators, not canonical stores.

An index entry must point to canonical artifact IDs and carry enough version metadata to detect stale embeddings/index records. Reindexing may replace index entries but must not mutate the source artifact or its review/publication state.

Grounded retrieval should be capable of returning:

- source/evidence identities
- concept identities
- candidate/review state
- reasoning/conclusion identity when used
- publication state
- provenance needed to explain why the result was returned

## Memory architecture boundary

Working, episodic, semantic, procedural, project, and governance memory are views over governed records, not independent truth stores.

- working memory may be ephemeral but must reference durable IDs
- episodic memory should derive from sessions, executions, and reasoning-ledger events
- semantic memory should resolve through canonical concepts, reviewed knowledge, evidence, and relationships
- procedural memory should reference versioned workflows/methods/prompts/validation rules
- governance memory should reference decisions, exceptions, approvals, and audit events

Promotion from temporary memory to durable institutional memory requires an explicit persistence event.

## Required continuous scientific path

The target governed path is:

`source -> extraction -> evidence -> candidate knowledge -> aggregation -> interpretation/reasoning -> review -> published knowledge -> retrieval/memory`

Every handoff must be explicit, validated, attributable, idempotent where practical, and observable.

The Brain is not operationally complete while any required handoff is represented only by a manual copy, caller-invented identity, undocumented private helper, or disconnected storage layer.

## Current implementation priorities

Priority order after the verified literature pipeline:

1. Complete and merge the governed literature-to-candidate handoff without private implementation coupling.
2. Persist canonical literature-source bindings so `paper_id`/`evidence_id` resolve transactionally to canonical source revision, extraction-run, and anchor identities.
3. Implement the append-only reasoning ledger and Reasoning Map contracts.
4. Connect candidate review -> evidence aggregation -> interpretation -> publication through explicit governed orchestration.
5. Add the Relationship Validator to the reviewed relationship publication boundary.
6. Make semantic memory and retrieval reference canonical artifact IDs rather than parallel memory truth.
7. Add a grounded Brain query facade only after the above identities and handoffs are stable.
8. Add Data Intelligence on the same evidence, concept, reasoning, and provenance contracts.
9. Enable autonomous research planning only after governance, readiness, and failure recovery are verified end to end.

## Definition of done for a Brain handoff

A handoff is done only when:

- producer and consumer contracts are versioned
- source and destination identities are stable
- provenance survives the transition
- uncertainty/ambiguity survives the transition
- repeated execution is deterministic or explicitly versioned
- authorization and tenant/project scope are enforced
- failure states are structured and observable
- no automatic publication occurs across a governance boundary
- focused unit/integration tests pass
- an end-to-end test proves the handoff using real adjacent services
- public service interfaces are used instead of private route/repository internals

## Governance boundary

Autonomous execution must stop for human approval when an action would:

- publish or retract canonical scientific knowledge
- destructively migrate or delete durable knowledge
- change a governance policy or approval threshold
- expose restricted source content
- override an unresolved scientific conflict
- synthesize or substitute a canonical identity owned by another subsystem

All other additive, reversible, testable integration work should proceed within the existing architecture.