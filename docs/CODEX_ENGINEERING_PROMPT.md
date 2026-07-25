# Codex Engineering Prompt — Orchid Calyx

You are working in the Orchid Calyx repository. Orchid Calyx is a governed scientific reasoning system, not a generic CRUD application or chat wrapper.

## Mission

Implement changes that preserve evidence, provenance, reproducibility, uncertainty, reviewability, and explicit system state.

Before coding, read:
- `docs/architecture/CALYX_BRAIN_SPECIFICATION_V1.md`
- the relevant service, schema, migration, API, and test files
- any issue-specific acceptance criteria

## Non-negotiable constraints

1. Do not bypass the Concept Registry, Entity Registry, Evidence Graph, Claim Graph, Dataset Registry, or provenance layer when the feature logically belongs there.
2. Do not create durable hidden state in prompts, process memory, caches, or agent conversations.
3. Do not discard ambiguity, conflicting evidence, missing values, confidence, or extraction warnings.
4. Do not present generated conclusions as verified facts unless validation and review state support that claim.
5. Do not add destructive migrations without explicit approval, rollback analysis, and tests.
6. Do not make network access available to analysis sandboxes by default.
7. Do not log secrets, private document content, credentials, or sensitive data.
8. Do not expose private model chain-of-thought. Store concise structured rationales, plans, evidence references, and execution traces.
9. Do not make implementation behavior depend on undocumented prompt wording.
10. Do not silently coerce scientifically meaningful values, units, identifiers, or nulls.

## Required workflow

### 1. Inspect

Map the current behavior before editing:
- entry points
- service boundaries
- schemas and migrations
- existing tests
- CI workflows
- provenance and audit behavior

State assumptions explicitly in the PR description.

### 2. Plan

Create a minimal typed implementation plan:
- affected components
- contracts changed
- migration requirements
- security and tenancy impact
- provenance impact
- tests required
- compatibility risks

Prefer additive changes and small composable commits.

### 3. Implement

Use the existing repository conventions. Keep domain logic in services rather than routers. Keep persistence code explicit. Prefer stable identifiers, versioned schemas, idempotent operations, and structured errors.

Every durable artifact should carry, directly or by reference:
- stable ID
- tenant/project scope
- schema version
- actor
- timestamps
- provenance
- status
- content hash where applicable

Every generated analysis or extraction should preserve:
- input versions and hashes
- extractor/model/tool version
- parameters
- execution environment
- warnings
- confidence
- validation result

### 4. Test

At minimum, add:
- focused unit tests
- integration tests across the changed boundary
- failure-path tests
- deterministic-output tests where relevant
- tenancy and permission tests for governed resources
- migration validation for schema changes

For literature extraction, an end-to-end test must prove:
source document → metadata → sections/passages → entities/concepts → claims → exact evidence spans → provenance → queryable API result.

For data analysis, an end-to-end test must prove:
dataset version → profile → typed plan → sandbox execution → result artifacts → manifest/provenance → reproducible rerun.

### 5. Validate

Before declaring completion, run the repository's required formatting, linting, type-checking, unit, integration, migration, and workflow validation commands. Fix the code rather than weakening checks.

### 6. Document

Update architecture and API documentation when behavior, contracts, or durable data change. Include examples for non-obvious operations.

## Reasoning-system design rules

Represent reasoning as inspectable records, not free-form hidden transcripts.

A reasoning record should support:
- objective/question
- typed plan
- hypotheses
- selected evidence and counterevidence
- assumptions
- operations
- intermediate artifacts
- confidence and uncertainty
- unresolved conflicts
- validation
- conclusion
- review state

The system must be able to answer:
- What produced this result?
- Which evidence supports it?
- Which evidence conflicts with it?
- Which code, query, model, parameters, and data versions were used?
- Can the result be reproduced?
- Who reviewed or approved it?
- Has it been superseded or retracted?

## Literature extraction priority

Keep the literature pipeline operational while new brain features are developed. Do not replace working extraction stages with speculative abstractions.

Required stages:
1. ingest and hash source
2. normalize metadata
3. segment sections/passages
4. extract entities and concepts
5. extract claims
6. bind claims to exact evidence spans
7. record confidence and ambiguity
8. validate schema/provenance
9. publish to evidence and claim graphs
10. expose query and health-check endpoints

If any stage is absent or unverified, create or update tests and implementation to close that gap before marking the pipeline complete.

## Data Intelligence rules

Natural-language requests must compile to a typed reviewable plan before execution. Sandboxes must be isolated, resource-limited, and network-denied by default. Generated SQL must be read-only unless an explicitly governed workflow authorizes mutation.

Persist an analysis manifest including:
- dataset IDs and versions
- row/column selection
- transformations
- code or SQL
- dependencies
- random seed
- outputs
- diagnostics
- assumptions
- warnings
- provenance
- review state

## Pull request completion checklist

A PR is not complete until all applicable items are true:
- [ ] issue acceptance criteria satisfied
- [ ] architecture remains consistent with the Brain Specification
- [ ] tests added and passing
- [ ] lint, formatting, and type checks passing
- [ ] migrations additive and validated
- [ ] provenance and audit behavior covered
- [ ] permissions and tenancy covered
- [ ] documentation updated
- [ ] no secrets or private reasoning exposed
- [ ] CI green
- [ ] PR explains risks, limitations, and follow-up work

When uncertain, favor explicit state, traceability, narrow scope, and tests over cleverness.