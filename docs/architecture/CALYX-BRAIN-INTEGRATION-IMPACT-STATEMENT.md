# Calyx Brain Integration and Architecture Impact Statement

## Decision

PR #172 is the persistence and governance dependency for PR #182. The integration branch is stacked on PR #172 and ports PR #182 as a facade and deterministic candidate generator. It removes PR #182's competing inference and literature persistence and adds one authenticated inference-to-ledger handoff.

Candidate inference is not canonical knowledge. Reasoning Ledger approval is not automatic publication. Canonical graph publication requires the existing controlled Knowledge Graph publication gate. Private chain-of-thought is neither requested nor persisted.

## Current subsystem inventory and canonical ownership

| Subsystem | Canonical ownership |
|---|---|
| Literature Intelligence | Papers, extraction runs, evidence, source offsets, source hashes, source anchors and literature bundles |
| Candidate Knowledge | Deterministically identified proposed normalized scientific claims in review-required, unpublished state |
| Reasoning Ledger | Assumptions, support, counterevidence, conflicts, hypotheses, conclusions, immutable revisions, audit events, review, approval and eligibility |
| BUILD-OCB-010 inference engine | Deterministic candidate generation, rule identifiers/versions, confidence, evidence-edge selection, citations and concise reviewable rule traces |
| Knowledge Graph | Canonical published scientific nodes and edges through existing controlled publication |
| Connector Registry | Registration, versioned capabilities, health, execution contract and entry-point discovery |
| Outreach graph | Isolated non-scientific relationship model; non-operational pending privacy and consent governance |

The inference engine does not own permanent reasoning history, literature storage, graph storage, approval or publication. Migration 104 now owns only connector metadata and the isolated outreach graph.

The duplicate `app.brain.connectors` implementation from PR #182 is removed. Brain endpoints delegate to the established `runtime.connector_registry`, which is extended additively with collision-safe registration, entry-point discovery, catalog metadata and declared literature manifests.

## Dependency graph and merge order

```text
main (includes merged PR #146)
  |
  +-- PR #172: Reasoning Ledger + migration 103
        |
        +-- integration PR: adjusted PR #182 + governed bridge + migration 104
              |
              +-- later controlled publication adapter (not implemented here)
```

The integration PR should remain stacked on `feature/calyx-brain-002-reasoning-ledger` until PR #172 is merged. It can then be rebased or retargeted to current `main`. Neither source PR is modified or merged by this build.

## Governed data flow

```text
Literature Intelligence
  -> verified evidence and source anchors
  -> Candidate Knowledge (unpublished normalized proposal)
  -> Reasoning Ledger evidence references
  -> deterministic graph inference candidate
  -> immutable ledger revision + append-only audit event
  -> human review
  -> ledger eligibility evaluation
  -> existing controlled Knowledge Graph publication gate
  -> canonical graph node/edge only after separate authorization
```

There is no automatic handoff from inference, literature extraction, a ledger conclusion, or an outreach recommendation into canonical scientific knowledge.

## Inference-to-ledger sequence

1. An authenticated caller requests deterministic inference from `/brain/infer` or `/brain/reason`.
2. The engine returns a candidate with subject/candidate canonical node identities, proposed relationship, confidence, rule ID/version, evidence edge IDs, citations, source hashes, literature evidence references, connector IDs, rule trace and SHA-256 inference content hash.
3. The caller submits that exact hash through `POST /brain/inferences/{subject_node_id}/submit-to-ledger`, supplying the canonical ledger, Research Station project, expected ledger version, inference family and candidate node.
4. The server recomputes the inference from the canonical graph. Caller-supplied evidence or reasoning is not accepted.
5. The bridge rejects missing evidence, hash mismatch, ambiguous canonical keys, cross-owner access, cross-project scope and stale ledger versions.
6. Under the locked ledger-head row, the Reasoning Ledger deterministically reuses an existing inference hash or appends a `hypothesis` entry.
7. A new immutable revision and `INFERENCE_CANDIDATE_APPENDED` audit event are committed atomically when created. Duplicate reuse creates neither another revision nor another audit event.
8. Any mutation changes the current review-content hash and invalidates stale approval.
9. The bridge explicitly records `automatically_approved=false` and `automatically_published=false`.

The persisted rule trace contains only the rule applied, matched evidence edge IDs and candidate result. It is an externally reviewable artifact, not private model chain-of-thought.

## API ownership

| Endpoint | Owner | Behavior |
|---|---|---|
| `GET /brain/node/{id}` | Knowledge Graph via Brain facade | Canonical read |
| `GET /brain/relationships/{id}` | Knowledge Graph via Brain facade | Canonical read |
| `GET /brain/reason` | Inference engine | Deterministic candidate only |
| `POST /brain/infer` | Inference engine | Deterministic candidate only |
| `POST /brain/query` | Knowledge Graph via Brain facade | Bounded structured read |
| `POST /brain/connect` | Connector Registry | Safe `describe`/`health` only in this slice |
| `POST /brain/inferences/{subject_node_id}/submit-to-ledger` | Brain facade delegating to Reasoning Ledger | Governed candidate handoff |
| `/api/reasoning-ledgers...` | Reasoning Ledger | Canonical ledger lifecycle, history, validation and review |
| Existing controlled publication endpoints | Knowledge Graph publication subsystem | Separate authorized canonical publication |

No existing route is removed or redefined.

## Migration integration

Deployment order is:

1. `101_research_workspace_foundation.sql` — enables `pgcrypto`, creates canonical Research Station projects with UUID identity, owner scope and timezone-aware timestamps.
2. `103_reasoning_ledger.sql` — creates `reasoning_ledger.ledger_heads`, immutable `ledger_revisions` and append-only `audit_events`, all project/owner scoped.
3. `104_orchid_continuum_brain.sql` — creates `oc_brain.connector_registrations` plus isolated `outreach_nodes` and `outreach_edges`.

Migrations 103 and 104 are additive and idempotent on PostgreSQL 16. Migration 103 depends on migration 101's `research_station.projects`. Migration 104 has no foreign keys into Reasoning Ledger, Literature Intelligence or `oc_graph`, avoiding a second source of truth. UUIDs used for project and ledger identity remain PostgreSQL UUIDs; outreach/connector-local keys retain their existing types. All persisted operational timestamps are `timestamptz`.

Rollback order is 104 then 103. The 104 rollback drops only `oc_brain`; the 103 rollback drops only `reasoning_ledger`. Migration 101 has no repository rollback and is retained as the shared Research Station foundation. Rollbacks are for disposable/pre-production validation or explicitly approved recovery, never automatic production actions.

## Security and tenancy

- Every Brain and Reasoning Ledger endpoint uses the existing owner-session or API-key dependency.
- Actor, ledger author, collector and audit actor derive from authenticated context, never request JSON.
- Ledger heads and revisions are owner/project scoped.
- Research Station project ownership and archive state are checked through the canonical project model.
- Cross-owner ledger access resolves as not found. Cross-project submission is rejected.
- Optimistic concurrency requires `expected_version`; the repository also locks the ledger head with `SELECT FOR UPDATE`.
- Strict Pydantic schemas forbid unknown request fields. Private-reasoning keys are not accepted by Reasoning Ledger metadata contracts, and the bridge accepts no caller-authored trace.

## Connector operational status

| Status | Meaning |
|---|---|
| `declared` | Manifest and capabilities exist; no credentialed network execution is available |
| `operational` | Credentialed adapter, rate limiting, errors, provenance and network-independent tests are implemented |
| `degraded` | Operational adapter is configured but health or upstream availability is impaired |
| `disabled` | Execution is administratively unavailable |

Crossref, OpenAlex, Semantic Scholar, PubMed, GBIF, BHL and JSTOR remain `declared`, not operational. Live literature connectors are not operational until credentialed and tested. JSTOR remains metadata-only.

## Outreach isolation boundary

Outreach nodes and edges live only in `oc_brain` and have no foreign key or publication path to canonical scientific graph objects. Outreach recommendations remain disabled pending approved privacy, consent, retention and access-control policy. Engagement history must not be interpreted as scientific evidence.

## Known limitations and production prerequisites

- PR #172 must be reviewed and merged before this stacked integration PR is retargeted to `main`.
- PostgreSQL 16 must receive migrations 101, 103 and 104 in order through the normal release process.
- Existing database, owner-session/API-key secrets and durable Literature Intelligence bundle storage must be configured.
- Inference rules and confidence weights require domain-expert calibration.
- Brain structured queries currently use bounded repository-wide reads and need indexed query methods before very large graph workloads.
- No live provider or literature connector is enabled by this integration.
- No inference-to-publication adapter is included.
- No production migrations, deployments, merges or frontend changes are performed by this build.

## Next dependency-ordered build

After PR #172 and this integration PR are merged and migrations are validated in staging, implement a separate controlled publication adapter. It should consume only an eligible, currently approved ledger version, revalidate its exact review-content hash, create a publication candidate, and pass through the existing controlled Knowledge Graph authorization and atomic publication gate. It must not publish directly from inference output.
