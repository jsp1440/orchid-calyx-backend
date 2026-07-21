# BUILD-090B — Design Reasoning and Interface Planning Foundation

## Implementation summary

BUILD-090B adds the controlled, internal backend planning layer approved in BUILD-090A. It creates immutable Product Requests, Project Context snapshots, Design Evidence Packages, concise Design Reasoning Records, Material Conflict Records, Interface Plans, review decisions, and audit events. It generates no interface or frontend source and grants no implementation authority.

## Architecture compliance and artifact model

The implementation consumes BUILD-089 semantic retrieval through a read-only bounded adapter. Requirements remain independent from recommendations; evidence, reasoning, conflicts, plans, and reviews remain independent versioned artifacts. Deterministic SHA-256 fingerprints provide idempotency and stable identity. Changed inputs create monotonic successor versions. Frozen domain objects and PostgreSQL rejection triggers preserve history.

The context model records authority, provenance, rights, effective version, status, and hard-constraint state. Authority levels preserve the BUILD-090A precedence policy; stale or missing hard context fails closed. Material conflicts are explicit records requiring a decision-owner role.

## Lifecycle and human review

The enforced lifecycle ends at `APPROVED` or `SUPERSEDED`. `IMPLEMENTATION_AUTHORIZED`, `IMPLEMENTED`, and `VALIDATED` are explicitly rejected. Plans enter `REVIEW_REQUIRED` only through the transition service. Required roles approve the identical plan hash; conflicting same-role decisions fail atomically. Corrections remain structured review data and require a new plan version before content changes.

## Retrieval integration and corpus coverage

The adapter reuses BUILD-089B hybrid retrieval, classifications, deterministic embeddings, semantic-unit locations, citations, provenance, relationships, and ranking explanations. Queries and results are bounded and deterministic. Each requested domain is classified independently as `COVERED`, `PARTIALLY_COVERED`, `NOT_PRESENT_IN_SOURCE_CORPUS`, or `RETRIEVAL_UNAVAILABLE`. A source gap never becomes fabricated guidance, and provider failure never becomes a corpus-gap claim.

## Scientific-interface and accessibility contracts

Plans require an accessibility section, state/failure planning, responsive behavior, acceptance criteria linked to requirements/evidence, and rights/attribution planning. Scientific plans may preserve nomenclature, assertion status, provenance, uncertainty, conflicts, spatial/temporal and measurement context, conservation sensitivity, citations, and graph relationships without publishing them. Scientific uncertainty cannot be converted into false certainty.

## Rights and security

The BUILD-089C `USER_SUPPLIED_INTERNAL_RESEARCH_ONLY` and `NOT_SUPPLIED` classifications propagate into every package, with public redistribution prohibited. Only bounded excerpts are retained. Corpus content is untrusted evidence and cannot control authorization, policy, provenance, rights, lifecycle, or approval. Routes are internal and authenticated; caller-fabricated trusted fields and implementation authorization are rejected. Audit output contains identifiers and policy-safe rationale, not secrets, unrestricted corpus text, prompts, or hidden reasoning.

## Internal API

- `POST /api/design-planning/product-requests`
- `POST /api/design-planning/product-requests/{id}/versions`
- `GET /api/design-planning/product-requests/{id}`
- `POST /api/design-planning/product-requests/{id}/contexts`
- `POST /api/design-planning/product-requests/{id}/evidence-packages`
- `POST /api/design-planning/reasoning-records`
- `POST /api/design-planning/conflicts`
- `POST /api/design-planning/interface-plans`
- `POST /api/design-planning/interface-plans/{id}/submit`
- `POST /api/design-planning/interface-plans/{id}/reviews`
- `GET /api/design-planning/artifacts/{kind}/{logical_key}/history`
- `GET /api/design-planning/audit`
- `GET /api/design-planning/health`

## Migration, idempotency, concurrency, provenance, and audit

`migrations/090b_design_reasoning_interface_planning_foundation.sql` creates an isolated additive schema with one table per artifact family, version and fingerprint uniqueness, JSONB evidence references, operational indexes, append-only triggers, prohibited-future-state checks, and review uniqueness. PostgreSQL writes use transaction-scoped advisory locks. Equivalent writes converge by fingerprint; competing versions or final decisions return explicit conflicts. Audit append is part of each controlled operation.

## Validation results

Focused validation covers artifact construction/versioning, status distinctions, immutable history, stale context, hard constraints, BUILD-089 evidence linkage, honest coverage, retrieval failure, rights, bounded untrusted excerpts, concise rationale, structured plans, lifecycle guards, review authorization, conflicting decisions, audit, and route authentication. PostgreSQL 16 CI applies the migration twice and validates append-only triggers and future-state rejection. Final exact totals are recorded in the Draft PR after all checks complete.

## Performance observations

Retrieval is bounded at 20 results per normalized query and deterministically ordered. Repository lookups use identity, logical-version, fingerprint, lifecycle, review, and audit indexes. No unsupported production latency or throughput claim is made.

## Known limitations and explicit exclusions

- Production corpus/database population is excluded.
- Frontend, wireframe, component, source-code generation, deployment, and product-specific UI are excluded.
- Implementation authorization and execution states are excluded.
- Knowledge Graph publication and public corpus access are excluded.
- Reviewer UI and authentication management are excluded; existing backend authentication is reused.
- Production performance targets require operational measurement in a later build.

## BUILD-090C prerequisites and verdict

BUILD-090C may begin after this migration and foundation are merged, PostgreSQL 16 and regression workflows pass, and product-specific planning input is owner-authorized. BUILD-090C must preserve these immutable, rights, lifecycle, review, and no-implementation boundaries.

**READY FOR BUILD-090C**
