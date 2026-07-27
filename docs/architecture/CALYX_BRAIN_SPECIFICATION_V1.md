# Orchid Calyx Brain Specification v1.0

## Purpose

Orchid Calyx is a governed scientific reasoning system. It must preserve not only facts and outputs, but also the evidence, assumptions, methods, uncertainty, execution context, review state, and lineage that produced them.

This document is the canonical architectural reference for the Calyx brain.

## Core principles

1. **Evidence before assertion** — conclusions must point to supporting evidence.
2. **Provenance everywhere** — every artifact must be traceable to source inputs and transformations.
3. **Deterministic where possible** — equivalent inputs and parameters should produce equivalent outputs.
4. **Uncertainty is first-class** — confidence, ambiguity, disagreement, and missing evidence must be retained.
5. **Reasoning is inspectable** — plans, operations, decisions, and validations must be reviewable.
6. **Human governance** — sensitive, destructive, publication-grade, or high-impact actions require review.
7. **No hidden state** — durable system behavior must be represented in explicit data structures and events.
8. **Composable architecture** — literature, concepts, datasets, workflows, models, and agents share the same brain substrate.

## Brain layers

### 1. Source and ingestion layer

Accepts literature, datasets, observations, files, databases, APIs, and user-authored material.

Required capabilities:
- immutable source identifiers and hashes
- source versioning
- parser and extractor version capture
- access policy and sensitivity metadata
- ingestion event log

### 2. Knowledge layer

Stores normalized scientific knowledge.

Primary components:
- Concept Registry
- Entity Registry
- Literature Corpus
- Evidence Graph
- Claim Graph
- Dataset Registry
- Method Registry

### 3. Reasoning layer

Represents how conclusions are formed.

A reasoning record contains:
- question or objective
- typed plan
- hypotheses considered
- evidence selected
- assumptions
- operations performed
- intermediate artifacts
- uncertainty and confidence
- counterevidence and unresolved conflicts
- conclusion
- validation results
- reviewer state

Reasoning records must not expose private model chain-of-thought. They store concise, auditable rationales, structured plans, citations, and execution traces suitable for scientific review.

### 4. Execution layer

Runs governed tools and workflows.

Components:
- sandboxed Python runtime
- governed SQL executor
- workflow engine
- connector gateway
- model/agent gateway
- resource and cost controls
- deterministic seed and environment capture

Every execution produces a manifest containing code or query, dependencies, parameters, environment, inputs, outputs, warnings, timing, and hashes.

### 5. Memory layer

Memory is divided into:
- **episodic memory** — prior sessions, analyses, and decisions
- **semantic memory** — concepts, entities, claims, and relationships
- **procedural memory** — reusable workflows, methods, prompts, and validation rules
- **project memory** — project-specific conventions, goals, constraints, and decisions
- **governance memory** — approvals, exceptions, policy decisions, and audit events

Memory retrieval must be scoped, attributable, permission-aware, and versioned.

### 6. Governance layer

Defines:
- permissions and tenancy
- approval requirements
- publication state
- model and tool policy
- retention and deletion
- sensitive-data handling
- audit logs
- reproducibility thresholds

Suggested artifact states:
- draft
- machine-validated
- human-reviewed
- approved
- published
- superseded
- retracted

## Literature intelligence pipeline

The minimum end-to-end pipeline is:

1. ingest document
2. identify metadata and canonical source record
3. segment document into sections and passages
4. extract entities and concepts
5. extract claims
6. bind claims to exact evidence spans
7. normalize identifiers and terminology
8. preserve ambiguity and extraction confidence
9. validate schema and provenance
10. publish results to the evidence and claim graphs
11. expose results to search and reasoning services

A literature pipeline is not considered operational until an integration test proves the complete path from source document to queryable claims and evidence.

## Data Intelligence workspace

The Calyx Data workspace should provide Julius-style conversational analysis while preserving scientific traceability.

Capabilities:
- CSV, XLSX, JSON, Parquet, database, and scientific-table ingestion
- schema profiling and data-quality reports
- natural-language analysis planning
- filtering, aggregation, joins, pivots, and reshaping
- entity and concept reconciliation
- visualization
- descriptive and inferential statistics
- model fitting and forecasting
- notebook and workflow reuse
- exportable tables, figures, reports, and manifests

Required result package:
- dataset versions and hashes
- columns and rows used
- cleaning and transformation history
- generated Python or SQL
- parameters and random seeds
- assumptions and warnings
- charts and result tables
- statistical methods and diagnostics
- provenance links
- review and publication state

## Reasoning Engine services

Suggested services:
- `reasoning-planner`
- `evidence-retriever`
- `hypothesis-manager`
- `analysis-executor`
- `result-validator`
- `confidence-evaluator`
- `memory-retriever`
- `reasoning-ledger`

The planner emits a typed plan. The executor may only invoke allowlisted tools. The validator checks schema, evidence coverage, reproducibility, and policy. The ledger records the final auditable trace.

## User interface system

Primary workspaces:
- Knowledge
- Literature
- Data
- Research
- Workflows
- Publications
- Governance

Every workspace should share:
- global project context
- evidence drawer
- concept inspector
- provenance viewer
- activity and review timeline
- artifact status
- search and command interface

### Data-analysis interaction

1. Select or upload datasets.
2. Inspect automatically generated profile.
3. Ask a question in natural language.
4. Review the proposed analysis plan.
5. Run in a sandbox.
6. Inspect results, code, assumptions, and provenance.
7. Save as a reusable workflow.
8. Request review or publish.

## API conventions

All durable outputs require:
- stable identifier
- project or tenant scope
- schema version
- creation timestamp
- actor
- source references
- provenance record
- status
- content hash

Operations should be idempotent where practical. APIs should return structured errors and avoid silently repairing invalid scientific data.

## Implementation phases

### Phase 1 — verify the existing brain
- prove literature extraction end to end
- verify metadata, sections, entities, claims, evidence, and provenance
- add operational health checks and fixtures
- document current service boundaries

### Phase 2 — reasoning ledger
- typed reasoning plans
- execution manifests
- validation records
- confidence and conflict representation

### Phase 3 — Data Intelligence MVP
- CSV/XLSX ingestion
- profiling
- natural-language filtering and aggregation
- basic charts
- sandboxed Python
- saved manifests and exports

### Phase 4 — reusable scientific workflows
- database connectors
- dataset joins
- statistical methods
- reusable notebooks and workflows
- review and publication controls

### Phase 5 — advanced brain
- hypothesis management
- counterevidence analysis
- experiment recommendations
- cross-project procedural memory
- multi-agent review

## Definition of done

A capability is done only when:
- its contract is documented
- unit and integration tests pass
- provenance is recorded
- permissions are enforced
- failures are observable
- outputs are queryable through supported APIs
- user-facing state is understandable
- an end-to-end acceptance test exists
