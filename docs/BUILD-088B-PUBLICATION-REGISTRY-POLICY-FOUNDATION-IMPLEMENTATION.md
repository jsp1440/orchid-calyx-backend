# BUILD-088B — Publication Registry and Policy Foundation

## Scope

BUILD-088B implements the persistence and decision foundation approved by BUILD-088A. It does not prepare or execute graph transactions and cannot publish a node, edge, taxon, claim, or aggregate.

## Implemented components

- `oc_knowledge_publication` is an additive, isolated PostgreSQL schema.
- Policy definitions are immutable versions. Separate append-only lifecycle events move a version through `DRAFT`, `ACTIVE`, and `RETIRED` without rewriting it.
- Publication candidates reference exact immutable BUILD-087 assertion and eligibility-decision records. Callers provide identifiers; the repository resolves scientific content, evidence packets, source revisions, anchors, provenance, and copyright controls from trusted tables.
- Candidate lifecycle transitions are append-only and database-enforced: `PUBLICATION_CANDIDATE` to `VALIDATING`, then `AUTHORIZED` or `REJECTED`.
- The Publication Authority is deterministic, version-bound, explainable, and fail-closed. It records every gate, failure, review reason, policy identity, and outcome.
- Candidate creation and authorization use transaction-scoped advisory locks and unique idempotency constraints. Candidate, transition, decision, and audit writes commit or roll back atomically.
- Read-only candidate and audit-history methods are available for later BUILD-088 components.

## Scientific and safety invariants

Source evidence, machine interpretations, and canonical assertions remain untouched. The registry stores a traceable trusted snapshot for reproducibility, while foreign keys preserve the exact source identities. Automatic authorization requires the approved automatic BUILD-087 path, complete provenance, permitted copyright, independent evidence, unambiguous taxonomy, no unresolved conflicts, and an active matching policy. Human and provisional pathways never auto-authorize; absent a trusted human authorization they terminate as a non-authorized `REVIEW_REQUIRED` outcome. Provisional publication must also be explicitly enabled by policy.

All BUILD-088B records are protected against update and delete at the database layer. The implementation contains no import of a graph writer, no graph mutation SQL, no publication endpoint, and no production in-memory repository.

## Operational behavior

Policy activation retires any previously active version of the same policy by adding a lifecycle event. Duplicate candidate submissions return the original row. Concurrent authorization attempts serialize on publication identity and return the previously recorded decision. PostgreSQL foreign keys, checks, unique constraints, transition triggers, and immutability triggers provide the authoritative invariants.

## Deferred by architecture

Graph transaction preparation, graph mutation, rollback of graph mutations, public serving, reviewer interfaces, and workflow dashboards belong to later BUILD-088 increments and are intentionally absent.
