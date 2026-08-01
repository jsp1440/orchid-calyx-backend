# Calyx Brain Capability Audit — July 2026

Status: repository-grounded audit complete for the merged Knowledge Graph and Reasoning Center chain.

## Executive conclusion

The Calyx Brain is no longer documentation-only. The canonical backend chain exists on `main` and is divided into four governed layers:

1. **Canonical Knowledge Graph** — `runtime.knowledge_graph` and the BUILD-088 controlled publication services remain authoritative for published nodes and edges.
2. **Deterministic Brain inference** — `app/brain/reasoning.py` reads the canonical graph and produces evidence-bearing candidate inferences across 13 scientific inference families. It does not publish.
3. **Reasoning Ledger governance** — `app/reasoning_ledger/` persists immutable revisions, evidence, hypotheses, conclusions, conflicts, conflict dispositions, uncertainty, audit events, exact-version review and human approval.
4. **Controlled ledger-to-graph publication** — `app/reasoning_publication/` revalidates the exact ledger version, review-content hash, approval, evidence, canonical assertion and publication policy before delegating to the existing BUILD-088 publication and graph transaction gate.

The remaining priority is therefore **operational completion and certification**, not construction of a second graph or a second reasoning store.

## Verified operational capabilities

### Knowledge Graph

- PostgreSQL-backed canonical graph repository.
- Authenticated Brain node and relationship retrieval.
- Controlled publication through the existing Knowledge Publication and Controlled Graph Publication services.
- Atomic canonical graph publication remains outside the Reasoning Ledger, preventing inference from becoming knowledge merely because it was generated or approved.

### Reasoning engine

`app/brain/reasoning.py` implements deterministic graph-pattern inference for:

- habitat similarity
- pollinator similarity
- cultivation similarity
- conservation risk
- evolutionary relationship
- probable mycorrhizal partner
- missing ecological interaction
- climate compatibility
- restoration suitability
- hybrid compatibility
- likely flowering period
- geographic expansion
- undiscovered population

Each candidate contains a stable rule ID and version, bounded confidence, matched graph-edge IDs, source-table/source-record references, citations, literature references when present, canonical subject/object identities, connector IDs, source hashes and a deterministic SHA-256 content identity.

### Brain API and governed handoff

`app/brain/routes.py` exposes authenticated graph reads, graph queries, inference requests and connector calls. The governed handoff endpoint recomputes the inference server-side and submits it to the Reasoning Ledger only when the canonical identities and inference-content hash match.

The handoff never approves or publishes. Duplicate inference content is deterministically reused.

### Reasoning Ledger

The merged Reasoning Ledger is the sole owner of reasoning persistence. It provides:

- immutable versioned revisions
- optimistic concurrency through expected versions
- evidence and provenance bindings
- hypotheses and conclusions
- explicit uncertainty
- immutable conflicts plus typed `resolved` and `superseded` dispositions
- append-only audit history
- current-version review-content hashes
- exact-version human approval
- automatic invalidation of stale approval after content changes
- publication blockers for unresolved conflicts, missing conclusions, low-confidence conclusions and missing current human approval

Private chain-of-thought is neither accepted nor persisted. Only externally reviewable rule traces, evidence, concise rationale, conflicts and conclusions are stored.

### Controlled publication

`app/reasoning_publication/service.py` and `gateway.py` implement the canonical bridge from an eligible ledger to the existing graph publication gate. Publication requires:

- exact current ledger version
- exact current review-content hash
- exactly one current approval
- exactly one publication conclusion
- supported graph operation
- unambiguous canonical subject/object identity
- supporting evidence, literature evidence IDs and source-document hashes
- canonical assertion ID/version
- active publication policy ID/version
- successful BUILD-088 authorization and graph transaction

Failed attempts remain auditable. Published artifact identity is deterministic and immutable.

## Canonical dependency path

```text
Literature / source evidence
        ↓
Candidate Knowledge / canonical assertions
        ↓
Canonical Knowledge Graph evidence retrieval
        ↓
Deterministic Brain inference candidate
        ↓
Reasoning Ledger immutable revision
        ↓
Human review + exact-version approval
        ↓
Reasoning publication adapter
        ↓
BUILD-088 publication authorization
        ↓
Atomic canonical Knowledge Graph transaction
```

## Duplicate and superseded work

- Closed PR #182 must not be revived as an alternate Brain implementation. Its useful inference work was rationalized into merged PR #188; its duplicate connector, inference persistence and literature ownership were removed.
- Candidate Knowledge remains the unpublished normalized-claim owner. The Reasoning Ledger must not become a second Candidate Knowledge database.
- Literature Intelligence remains the evidence/anchor/source-hash owner. The Brain must not create a second literature store.
- `runtime.connector_registry` is canonical. Do not restore `app/brain/connectors.py` as a competing registry.
- BUILD-088B/088C remain the canonical publication gate. Do not add direct graph SQL to Brain or Reasoning Ledger services.
- Archive Manager entities and relationships remain archive-local until they enter the existing governed evidence/candidate path.

## Promised but not yet fully proven operational

1. **Production migration and deployment certification** — merged migrations 101, 103, 104 and 105 require verified staging/production application evidence; repository merge status alone does not prove deployed availability.
2. **Single end-to-end certification scenario** — the complete path from real literature evidence through inference, ledger review, approval and canonical graph publication needs one disposable-PostgreSQL integration workflow and one controlled staging smoke test.
3. **Post-publication lifecycle** — ledger-origin linkage for re-evaluation, supersession, withdrawal and retraction remains the next governed lifecycle slice.
4. **Brain operational telemetry** — Mission Control should expose graph availability, inference readiness, ledger persistence, publication-gate readiness, migration versions and recent failures without granting scientific authority.
5. **Rule calibration** — inference weights and vocabulary aliases are deterministic but require domain-expert calibration and versioned evaluation datasets.
6. **Large-graph performance** — some Brain query paths use repository-wide reads and require bounded SQL traversal/query plans for production scale.
7. **Live connector certification** — connector contracts exist, but each external connector still requires credentialed health checks, rate limits, provenance tests and failure isolation before being called operational.
8. **Frontend reasoning workspace** — there is no verified Mission Control interface for inspecting evidence, comparing conflicts, editing externally reviewable conclusions, recording review and initiating controlled publication.

## Priority completion plan

### BRain Completion 001 — End-to-end certification

Create a dedicated disposable-PostgreSQL workflow that applies migrations in dependency order and proves:

1. seed canonical graph nodes/edges and source evidence;
2. generate one deterministic inference;
3. submit it to a project-scoped ledger;
4. append a publication-form conclusion;
5. record exact-version human approval;
6. publish through the real BUILD-088 gate;
7. verify the resulting canonical graph version and full provenance chain;
8. verify stale version, stale review hash, unresolved conflict and missing evidence all fail closed.

This is the highest-priority next build.

### Brain Completion 002 — Operational readiness and telemetry

Add a read-only Brain readiness endpoint and Mission Control projection covering database configuration, migration presence, graph counts, rule families, connector health, ledger availability, publication gate availability and last governed execution state.

### CALYX-BRAIN-004 — Post-publication lifecycle

Link immutable reasoning artifacts to BUILD-088D monitoring, re-evaluation, supersession, withdrawal and retraction events without rewriting historical reasoning or provenance.

### Brain Completion 003 — Query performance

Replace repository-wide graph reads in production-facing Brain queries with bounded, indexed PostgreSQL traversal and explain-plan regression tests.

### Brain Completion 004 — Reviewer workspace contract

Define backend contracts for evidence inspection, conflict comparison, conclusion preparation, approval and controlled publication. The interface must show sources and uncertainty and must never expose or request private chain-of-thought.

## Dependency-safe execution order

1. Finish and preserve BUILD-080C as an unmerged, independently reviewable archive hardening PR.
2. Implement Brain Completion 001 end-to-end certification from current `main`.
3. Add readiness/telemetry only after certification identifies the authoritative checks.
4. Implement CALYX-BRAIN-004 post-publication lifecycle.
5. Optimize graph traversal and then connect the frontend reviewer workspace.
6. Activate production migrations/deployment only through explicit environment authorization.

## Release definition

The Knowledge Graph and Reasoning Center may be called complete only when a controlled test can demonstrate:

- canonical graph evidence retrieval;
- deterministic, reproducible inference;
- immutable reasoning history and provenance;
- explicit conflict and uncertainty handling;
- exact-version human approval;
- fail-closed controlled publication;
- canonical graph result identifiers;
- post-publication monitoring linkage;
- operational status visible in Mission Control;
- no unreviewed inference written as canonical knowledge.

Until those conditions are demonstrated together, the subsystem is **implemented but not fully operationally certified**.
