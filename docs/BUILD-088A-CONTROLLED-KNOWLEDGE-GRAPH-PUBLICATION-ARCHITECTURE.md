# BUILD-088A — Controlled Knowledge Graph Publication Architecture

## 1. Executive summary

BUILD-088 defines the only future boundary by which publication-eligible BUILD-087 Layer 3 Canonical Scientific Assertions may create or change scientific Knowledge Graph state. It does not implement that boundary. A canonical assertion is not a published fact: publication is a separate, governed, versioned, auditable scientific decision.

The boundary validates authoritative repository records, never caller-supplied eligibility or provenance; authorizes under an immutable publication policy; prepares an immutable graph change set; commits that change atomically; and records graph versions, provenance, and audit history. It preserves all prior evidence, interpretations, assertions, publications, and graph-object versions.

**Governing rule: no scientific assertion may enter or modify the Knowledge Graph except through the BUILD-088 controlled publication boundary.** Existing graph writers remain unchanged in BUILD-088A, but later implementation must place every production-capable writer behind this boundary.

## 2. Current repository integration analysis

### 2.1 Evidence through assertion identity

The merged BUILD-082–087 chain represents scientific identity as follows:

- BUILD-082 immutable document revisions identify ingested source bytes and provenance.
- BUILD-084/086 evidence links retain source object type/ID, source revision, extraction run, and exact source anchors. Candidate and aggregate layers remain unpublished.
- BUILD-087 Evidence Packets use `packet_id`, logical `packet_key`, monotonic `version`, and unique deterministic `fingerprint`. Their payload contains ordered immutable source references, anchor IDs/types/locators/content hashes, copyright policy, publication metadata, provenance, context form, structural relationships, and completeness states.
- Machine Interpretations use `interpretation_id`, `interpretation_key`, `version`, and `fingerprint`. Their reproducibility manifest identifies packet fingerprints, model, ruleset, vocabularies, and configuration hash; supersession is explicit.
- Routing Decisions use `routing_decision_id`, policy name/version, path, gate results, factors, explanation, and fingerprint. `AUTOMATIC_PROMOTION` is the only current path that makes an assertion publication-eligible.
- Canonical Scientific Assertions use `assertion_id`, `assertion_key`, `version`, and `fingerprint`; retain supporting/conflicting interpretation IDs, scientific scope, routing decision and policy; and enforce `published=false`. Eligibility is repository-derived, not an authorization to publish.
- Corrections append new interpretation/assertion versions. All BUILD-087 artifacts and audit events reject update/delete at the database boundary.

Layer 4 must reference these exact stored identifiers and versions. It must reload and compare their fingerprints inside the publication transaction; an API payload cannot reproduce or override them.

### 2.2 Current graph representation and provenance

`oc_graph.kg_nodes` is represented by `Node`: `kg_node_id`, `node_type`, deterministic `canonical_key`, display label, `source_table`, `source_pk`, evidence class, confidence score/label, and payload. `oc_graph.kg_edges` is represented by `Edge`: `kg_edge_id`, edge type, endpoints, source table/PK, evidence class, confidence, rule name, and payload. Edges have additive temporal/supersession fields (`valid_from`, `valid_to`, `relationship_status`, `superseded_by_edge_id`).

Current lightweight provenance is embedded in `source_table`, `source_pk`, `rule_name`, evidence class/confidence, payload, and BUILD-078 publication metadata/audit records. The graph canon also anticipates `kg_node_lineage` and `kg_edge_lineage`, but availability must be verified at implementation time. BUILD-088 cannot assume embedded fields alone form a complete Layer 1-to-4 chain.

### 2.3 Existing graph-writing paths to govern

1. `app.publication` BUILD-078 exposes authenticated dry-run, publish, and rollback routes. It loads accepted `oc_semantic` candidates plus ontology readiness, constructs manifests, requires caller-provided approval/authority strings, and writes graph nodes/edges through `PostgresPublicationRepository`. It predates BUILD-087 assertions.
2. `runtime.knowledge_graph.publisher.publish_domain` maps domain rows into `NodeSpec`/`EdgeSpec` and calls repository `upsert_node`/`upsert_edge`.
3. `runtime.knowledge_graph.orchestrator.BuildOrchestrator` can run `PUBLISH`/`RESUME` with `authorized_to_publish=True`; domain adapters cover occurrences, traits, pollinators, mycorrhiza, conservation, climate, literature, images, and phenotype.
4. `runtime.knowledge_graph.production_publish` constructs the writable production repository.
5. `WritablePostgresGraphRepository` holds the production advisory lock and writes `kg_nodes`/`kg_edges`. Identical objects are no-ops, but changed node content currently uses conflict-update semantics; edge identity is deduplicated in memory during a single-writer transaction.

BUILD-088B must inventory these and any database roles, scripts, maintenance jobs, and direct SQL grants. BUILD-088C must make the controlled engine the only role permitted to invoke production graph mutation. Legacy BUILD-078 and batch writers may become approved change-set producers or remain for non-scientific canonical sources, but they may not bypass the Layer 4 authority for scientific assertions. No current path is changed by this architecture build.

## 3. Architectural invariants

1. Layers 1–4 have independent, immutable identities and version histories.
2. Eligibility is necessary but never sufficient for publication.
3. The authority reads eligibility, provenance, reviews, policy, taxonomy, and graph version from trusted repositories.
4. Callers supply only an assertion reference and request context; they cannot supply authoritative decisions.
5. Publication does not reinterpret evidence or modify Layers 1–3.
6. Every scientific graph object resolves to one or more publication events and complete Layer 4-to-1 provenance chains.
7. Scientifically material scope is represented, never flattened away.
8. A graph transaction is atomic: all graph objects, lineage, indexes, version metadata, publication state, and audit commit together or the graph remains unchanged.
9. Updates create new object/publication versions or status events. Historical scientific state is not overwritten.
10. Hard gates fail closed; aggregate scores cannot compensate.
11. Publication policies are immutable after approval and explicitly versioned.
12. Publication fingerprints and graph object identities are deterministic and idempotent.
13. Provisional, disputed, withdrawn, retracted, and historical states are never silently exposed as authoritative.
14. Audit failure prevents a scientific state transition.
15. Technical rollback does not erase valid scientific history.
16. Only a least-privilege publication-service database role may commit Layer 4 graph transactions.

## 4. Four-layer scientific model

### Layer 1 — Immutable Source Evidence

Exact source revision, wording or copyright-safe reference, contextual anchors, publication metadata, provenance, and rights. Never normalized or overwritten.

### Layer 2 — Versioned Machine Interpretation

Reproducible extraction meaning, entities, reasoning, confidence decomposition, ambiguity, and alternatives. Never changes Layer 1.

### Layer 3 — Canonical Scientific Assertion

Normalized, scoped, versioned scientific assertion with supporting/conflicting interpretations and an eligibility decision. Never changes Layers 1–2 and remains `published=false`.

### Layer 4 — Governed Knowledge Graph Publication

An immutable publication event authorizing a specific assertion version and change-set fingerprint under a specific policy and graph baseline. Its logical record contains:

- publication ID, logical publication key, and version;
- canonical assertion ID, version, and fingerprint;
- eligibility/routing decision ID, fingerprint, path, and policy version;
- publication policy ID/version/fingerprint;
- authority identity and required reviewer/specialist decision references;
- pathway and intended graph operations;
- affected graph object identities and versions;
- complete assertion-to-source provenance manifest;
- scientific scope, qualifiers, limitations, and conflicts;
- taxonomy concept IDs and taxonomy snapshot/version;
- publication status and immutable transition history;
- requested/authorized/prepared/published timestamps;
- graph transaction ID and change-set digest;
- graph version before/after;
- supersession, correction, withdrawal, retraction, restoration, and rollback lineage;
- deterministic idempotency fingerprint.

The publication contains references and copyright-safe review projections, not fabricated evidence, detached claims, or caller-authored eligibility.

## 5. Publication authority

The Publication Authority is a logical decision component between the assertion registry and graph transaction engine. It may decide whether an unchanged, versioned assertion is authorized under a versioned publication policy. It may not interpret packets, correct assertions, resolve scientific conflicts, rewrite taxonomy, or write graph objects.

### Required trusted inputs

- exact assertion ID/version/fingerprint and current status;
- persisted eligibility decision and all BUILD-087 hard-gate results;
- packet/interpretation/provenance completeness result;
- conflicts, alternatives, dependence, correction, supersession, withdrawal, and retraction state;
- approved publication policy and policy health;
- reviewer/specialist decisions from an authorized future review registry;
- taxonomy concept and version health;
- current graph version, object conflicts, and service health;
- model/calibration and monitoring health;
- intended downstream effect-radius analysis.

### Authority and authorization boundaries

Future identity/role enforcement is outside BUILD-088A, but authorization must be service-to-service, least privilege, and non-delegable by ordinary callers. Automatic authority is a policy-bound service identity. Human decisions require a verifiable decision record from an appropriately scoped reviewer identity; a string such as `publication_authority` is not proof.

Domain specialists are required for policy-marked domains. Taxonomic/nomenclatural assertions require taxonomy review. Conservation-sensitive assertions require conservation review and geographic-sensitivity controls. High-impact, novel, weakly corroborated, contradictory, policy-exception, or broad/irreversible changes require human authorization.

The authority refuses when any required record is missing, stale, inconsistent, unhealthy, or unauthorized. Refusal produces an immutable rejection/blocked decision; it does not reject or delete Layer 3. Eligibility and publication authorization always remain separate decisions.

## 6. Publication lifecycle

### States

- `PUBLICATION_CANDIDATE`: immutable assertion version nominated; no authority decision.
- `VALIDATING`: trusted inputs, policy, provenance, taxonomy, and graph baseline are being verified.
- `AUTHORIZED`: authority approved the exact assertion/policy/change intent.
- `REJECTED`: authority refused under evaluated policy/conditions; Layer 3 unchanged.
- `TRANSACTION_PREPARED`: immutable change set validated against recorded graph baseline.
- `PUBLISHING`: transaction lock acquired; atomic commit in progress.
- `PUBLISHED`: graph, lineage, audit, versions, and projections committed atomically.
- `PUBLICATION_FAILED`: preparation or commit failed without a valid completed publication.
- `REEVALUATION_REQUIRED`: a dependency changed or became suspect.
- `SUPERSEDED`: a newer valid publication replaces it in current projections.
- `WITHDRAWN`: publisher no longer endorses it; history retained.
- `RETRACTED`: publication is scientifically/formally invalid; propagation recorded.
- `ROLLBACK_REQUIRED`: committed transaction is technically invalid and requires controlled technical reversal.
- `ROLLED_BACK`: technical inverse committed; original event remains visible.

### Allowed transition matrix

| From | To | Preconditions and responsible component | Immutable records | Retry/terminal |
|---|---|---|---|---|
| none | `PUBLICATION_CANDIDATE` | Registry resolves exact Layer 3 version | candidate event, input fingerprint | idempotent |
| `PUBLICATION_CANDIDATE` | `VALIDATING` | Validator claims current candidate | validation-attempt event | recoverable |
| `VALIDATING` | `AUTHORIZED` | Authority verifies all gates/reviews | authorization decision, policy snapshot | recoverable until transaction |
| `VALIDATING` | `REJECTED` | Any authorization requirement fails | rejection reasons and evaluated inputs | terminal for this evaluation; new version/policy may create candidate |
| `VALIDATING` | `PUBLICATION_FAILED` | Technical validation unavailable/error | failure classification/checkpoint | retryable if transient |
| `AUTHORIZED` | `TRANSACTION_PREPARED` | Planner maps assertion and validates baseline | immutable manifest/change set | regenerate if baseline changes |
| `AUTHORIZED` | `REEVALUATION_REQUIRED` | Assertion/policy/taxonomy/evidence status changed | invalidation event | recoverable via new validation |
| `TRANSACTION_PREPARED` | `PUBLISHING` | Engine acquires serialization lock and baseline still matches | transaction-start event | safe retry by fingerprint |
| `TRANSACTION_PREPARED` | `REEVALUATION_REQUIRED` | Manifest stale or dependency changed | invalidation event | revalidate/replan |
| `PUBLISHING` | `PUBLISHED` | All graph, lineage, audit, version, projection writes succeed atomically | transaction receipt and graph versions | terminal success |
| `PUBLISHING` | `PUBLICATION_FAILED` | Transaction rolls back fully | failure/rollback receipt | retryable with same fingerprint after cause cleared |
| `PUBLISHING` | `ROLLBACK_REQUIRED` | Commit outcome uncertain or post-commit integrity fails | integrity incident | recoverable only by controlled rollback |
| `PUBLICATION_FAILED` | `VALIDATING` | Transient cause cleared; inputs reloaded | retry attempt | bounded retry |
| `PUBLICATION_FAILED` | `REJECTED` | Failure is a permanent policy/scientific blocker | rejection decision | terminal for version/policy |
| `PUBLISHED` | `REEVALUATION_REQUIRED` | New conflict, taxonomy/policy change, source retraction, or provenance loss | dependency-change event | current projection policy may quarantine |
| `PUBLISHED` | `SUPERSEDED` | New publication transaction commits replacement | bidirectional supersession lineage | terminal historical |
| `PUBLISHED` | `WITHDRAWN` | Authorized withdrawal decision commits status projection | withdrawal event/reason | may later restore via new event |
| `PUBLISHED` | `RETRACTED` | Authorized retraction decision and dependency propagation commit | retraction event/scope | terminal unless formal restoration policy permits new event |
| `PUBLISHED` | `ROLLBACK_REQUIRED` | Technical integrity defect in original transaction | incident and inverse plan | recoverable |
| `REEVALUATION_REQUIRED` | `VALIDATING` | Exact dependencies are snapshotted anew | evaluation attempt | recoverable |
| `REEVALUATION_REQUIRED` | `SUPERSEDED` | replacement publishes | supersession event | terminal historical |
| `REEVALUATION_REQUIRED` | `WITHDRAWN`/`RETRACTED` | authorized scientific decision | status event | historical |
| `WITHDRAWN` | `PUBLISHED` | `RESTORE_PUBLICATION` authorized under current policy and recorded as a new status event | restoration event | recoverable current state; history retained |
| `ROLLBACK_REQUIRED` | `ROLLED_BACK` | inverse transaction validates and commits atomically | inverse change set, graph versions, audit | terminal technical outcome |
| `ROLLBACK_REQUIRED` | `PUBLICATION_FAILED` | inverse attempt fails with graph unchanged from pre-attempt state | failure event | retry/escalate |

All transitions require actor/component, reason, old/new state, input versions, timestamp, correlation ID, and integrity hash in the same commit. Self-transitions are prohibited except an idempotent replay returning the existing event. Any transition not listed is prohibited. `REJECTED`, `SUPERSEDED`, `RETRACTED`, and `ROLLED_BACK` cannot transition directly to publication; a new Layer 3/publication version or explicitly authorized restoration event is required.

## 7. Publication pathways

### A. Automatic governed publication

Allowed only for an explicitly publication-eligible Layer 3 assertion when every BUILD-087 hard gate passed; policy allows automation for the assertion/domain; no specialist/impact category applies; no contradiction or material alternative exists; provenance is complete; taxonomy/graph/policy/model/calibration monitoring is healthy; and effect radius is within the automatic limit. The automated authority identity and exact policy are recorded.

### B. Human-authorized publication

Required for conservation-sensitive, taxonomic/nomenclatural, high-impact, novel, weakly corroborated, contradictory, exception, broad-effect, or difficult-to-reverse assertions. Policy names required specialties and consensus. Human authorization cannot cure missing provenance, copyright prohibition, stale eligibility, or an unhealthy graph baseline.

### C. Provisional publication

BUILD-088 permits provisional publication only when a domain policy explicitly enables it and a human authority approves it. Automatic publication of provisional Layer 3 assertions is prohibited. A provisional graph object is placed only in the provisional projection, carries limitations/uncertainty and reevaluation deadline, is excluded from authoritative reasoning/conservation decisions, and schedules reevaluation. Domains may prohibit provisional publication entirely. This retains useful uncertain knowledge without presenting it as established fact.

### D. Rejection

Rejection records that one assertion version is not authorized under one policy and condition snapshot. It never modifies, rejects, or deletes Layer 3 and can never be interpreted as a scientific refutation.

## 8. Publication policy

A policy is immutable after approval, versioned, domain- and assertion-type-aware, explainable, auditable, testable, rollback-capable, and fail-closed. Activation points to an approved version; rollback changes the active pointer with an audit event rather than editing policy content.

Hard gates include trusted eligibility, complete provenance, permitted copyright use, assertion/current-version integrity, absence or approved handling of conflicts/alternatives, taxonomy certainty, required reviewer decisions, service health, audit availability, and graph baseline validity. Factors include assertion/domain, evidence independence, contradiction severity, decomposed confidence, source authority, conservation/nomenclatural/geographic impact, novelty, downstream effect radius, model/calibration health, and graph health. No aggregate score offsets a hard-gate failure.

Each result records every input, gate, threshold, outcome, rationale, policy fingerprint, and health snapshot. Policy evaluation is deterministic for the recorded inputs.

## 9. Assertion-to-graph mapping

The mapping contract consumes only a stored assertion and its stored provenance. It produces deterministic graph object specs and never accepts detached claim text.

- subject becomes or resolves to a versioned node under a taxonomy/concept snapshot;
- predicate maps through an approved vocabulary version;
- an entity object resolves to a node; a literal/normalized value remains typed with original value/unit provenance;
- geography, time, population, life stage, experimental/environmental conditions, methods, units, uncertainty, qualifiers, comparison, and negation remain explicit;
- conflicting/supporting evidence and independence classifications become provenance/relationship structures, not hidden counters;
- confidence remains decomposed and labeled as a decision aid;
- provisional/disputed status is first-class.

A direct subject-predicate-object edge is allowed only when it preserves all scientifically material meaning. Otherwise the mapper creates a qualified assertion node connected to subject, object/value, scope, methods, evidence, conflict, taxonomy concept, and publication event. Negated assertions are never encoded as positive edges with a flag consumers may ignore. Mapping policies and vocabulary/taxonomy versions are part of the change-set fingerprint.

## 10. Graph transaction architecture

1. **Resolve:** load exact assertion, eligibility, provenance, policy, review, taxonomy, and current graph version.
2. **Authorize:** Publication Authority emits an immutable decision.
3. **Plan:** mapper creates deterministic node/edge/provenance/index/projection operations.
4. **Manifest:** freeze ordered operations, expected object versions, baseline graph version, checksums, and inverse technical operations.
5. **Validate:** schema/vocabulary, endpoints, provenance closure, conflicts, duplicate identity, effect radius, and projection effects are checked in a read-consistent snapshot.
6. **Prepare:** persist immutable change set and transaction intent without graph mutation.
7. **Serialize:** acquire a graph-wide version lock plus deterministic object-key locks in sorted order; compare baseline and assertion dependencies again.
8. **Commit atomically:** append graph object versions, provenance links, publication event/state, graph version, audit, indexes, and authoritative/provisional projections in one PostgreSQL transaction.
9. **Verify:** read-after-write integrity validation produces a receipt. A failed in-transaction check rolls back everything.
10. **Notify:** downstream projection/cache events are emitted from an outbox committed with the transaction; delivery is retryable and does not fabricate publication state.

Change sets are immutable and bounded. Large safe batches are a parent batch plus independent item transactions unless a policy declares cross-item scientific atomicity. No database commit occurs mid-publication event. Resume restarts at an immutable item boundary and revalidates current dependencies. Concurrent identical fingerprints return `NO_OP_DUPLICATE`; conflicting fingerprints serialize or fail with a version conflict.

## 11. Graph versioning and supported operations

Each successful scientific transaction increments a monotonic graph version and records before/after versions. Graph objects use stable logical identity plus immutable object versions, validity interval/status, publication ID, and supersession lineage. Current projections point to accepted versions; history remains append-only.

Supported operations:

- `CREATE_NODE`, `CREATE_EDGE`: append initial graph object version.
- `ADD_ASSERTION_SUPPORT`, `ADD_CONFLICTING_EVIDENCE`: append provenance/evidence relationship versions.
- `UPDATE_PUBLICATION_STATUS`: append a status event and refresh projections; never edit history.
- `SUPERSEDE_NODE_VERSION`, `SUPERSEDE_EDGE_VERSION`: append replacement and link prior/new versions.
- `WITHDRAW_PUBLICATION`, `RETRACT_PUBLICATION`, `RESTORE_PUBLICATION`: append authorized status event and projection changes.
- `CORRECT_PROVENANCE`: append corrected provenance version linked to prior; source evidence remains unchanged.
- `NO_OP_DUPLICATE`: record/reuse existing transaction by fingerprint without graph change.

Destructive overwrite, in-place scientific content refresh, hard delete, caller-chosen graph version, and unversioned direct upsert are not supported Layer 4 operations.

## 12. Provenance architecture

Required chain:

`graph object version → publication event → canonical assertion version → machine interpretation version → Evidence Packet version → immutable source evidence → source revision/publication metadata`.

Forward provenance answers what a source/assertion produced. Reverse provenance answers why a graph object exists. The manifest retains supporting and conflicting evidence; dependence/citation-copy classification; reviewer and specialist decisions; eligibility/publication policy versions; taxonomy, model, ruleset, vocabulary, and calibration versions; transformation/mapping rules; copyright-safe access policy; and integrity hashes.

Provenance validation resolves every link and fingerprint before authorization and before commit. Restricted text is fetched only through authorized Layer 1 access; graph/publication records store references and safe excerpts, not leaked text. If provenance becomes temporarily unavailable, current authoritative consumers receive an explicit degraded/quarantined status according to policy and reevaluation begins. If it is irrecoverably invalid, withdrawal or retraction is required. No orphan graph fact remains authoritative.

## 13. Supersession and correction

Supersession preserves the earlier publication/object versions, publishes a newly authorized assertion version, links both directions, and moves current projections only after the replacement commits. Historical queries continue to resolve the earlier state.

Correction begins in Layer 3: a corrected assertion version must exist first. It receives a new eligibility and publication decision and produces a new Layer 4 version/change set. Publication code never edits the original assertion or publication.

## 14. Withdrawal and retraction

Withdrawal means the publisher no longer endorses a publication without necessarily declaring the source scientifically invalid. Retraction records formal/scientific invalidity in a source, evidence, interpretation, assertion, or publication and propagates reevaluation to dependents.

Both retain complete history and leave historical views visible with status. Authoritative projections exclude them; reasoning systems invalidate dependent conclusions; caches receive versioned invalidation; educational content displays correction/withdrawal and stops teaching it as settled; conservation systems fail closed and alert responsible reviewers; dependent assertions/publications enter reevaluation queues. Retraction has stronger warning/propagation semantics than withdrawal.

## 15. Rollback policy

- **Technical rollback:** reverses an incomplete, corrupt, or wrongly committed graph transaction using a validated inverse change set. It restores the prior graph version/projection and records both events.
- **Scientific supersession:** newer authorized science replaces earlier current state.
- **Withdrawal:** publisher endorsement is removed.
- **Retraction:** scientific/formal invalidity is recorded and propagated.

Technical rollback is not a mechanism for responding to later evidence and never erases publication history. Rollback requires authority separate from the original transaction, graph-version validation, audit availability, and post-rollback integrity verification. Failed rollback leaves `ROLLBACK_REQUIRED`, blocks affected authoritative projections when necessary, and raises an operational incident.

## 16. Current and historical projections

- **Authoritative current graph:** latest active, non-provisional, non-disputed, non-withdrawn, non-retracted publications.
- **Provisional graph:** explicitly provisional publications with limitations and deadlines.
- **Disputed graph:** unresolved conflict or reevaluation-required publications.
- **Historical graph:** graph state at a publication/graph version or time.
- **Retracted-publication view:** retracted objects, reasons, dependencies, and replacements.
- **Complete provenance view:** all Layer 4-to-1 links, subject to access policy.

Projection membership is deterministic from immutable events. Consumers must explicitly select accepted states; absence of a selection defaults to authoritative-only. Projection rebuilds are deterministic and checked against graph-version receipts.

## 17. Downstream consumer contract

Every consumer receives graph object logical/version ID, publication ID/version/status/pathway, graph version, assertion ID/version, scientific scope/qualifiers, evidence class and decomposed confidence, conflict/provisional flags, taxonomy version, provenance link, policy version, valid time, and supersession/retraction/withdrawal state.

Public search, species pages, genus traversal, illustrated glossary, breeding tools, and AI explanations default to authoritative current state and label any explicitly requested provisional/disputed content. Reasoning systems also receive premise/publication versions and invalidation triggers. Conservation tools accept only policy-approved authoritative states and fail closed on reevaluation. Scientific review tools may request all projections. Adaptive learning and education must link simplifications to the authoritative publication and never silently convert provisional/disputed knowledge into settled content.

## 18. Reasoning-graph compatibility

Layer 4 exposes stable identities and typed relationships sufficient for future reasoning: assertion supported/contradicted by evidence, publication authorized by policy/reviewer, publication supersedes publication, graph fact derived from assertion, and conclusion depends on premise. It records decision rationale, gate results, conflicts, dependencies, and reevaluation triggers so a future reasoning graph can explain what is believed, why, who/what authorized it, supporting/conflicting evidence, possible invalidators, and change over time. BUILD-088A implements no reasoning engine.

## 19. Future educational graph integration boundary

An educational graph may reference immutable publication/object versions through a read-only scientific-publication reference. Educational theory, learning objectives, modalities, prerequisites, misconceptions, assessments, and learner adaptations live outside the scientific graph and cannot modify scientific publications. Educational claims record derivation and refresh when a referenced publication changes status. BUILD-088 does not implement this graph.

## 20. Security and authorization

Future roles:

- publication service: read Layers 1–3/policies; create candidate/manifests; no graph commit;
- publication authority: create authorization decisions only;
- scientific reviewer/domain specialist/taxonomy reviewer/conservation reviewer: scoped decision records only;
- graph transaction service: execute authorized immutable change sets with narrow graph/registry write grants;
- administrator: activate policies/roles and initiate technical recovery, with dual control for high risk;
- read-only consumer: projection/provenance reads appropriate to access class.

No public or ordinary authenticated endpoint has graph publication grants. Callers cannot supply/override eligibility, policy outcome, reviewer approval, provenance, graph version, audit identity, taxonomy version, or affected object IDs. Service identities are authenticated, decisions are signed or otherwise integrity-bound, secrets never enter manifests/logs, and restricted evidence access is separately enforced. Direct SQL, legacy publisher, and maintenance roles must be audited and reduced before enforcement is complete.

## 21. Failure handling

| Failure | Required behavior |
|---|---|
| assertion missing/version mismatch/superseded | reject or reevaluate; no graph write |
| assertion no longer eligible | reevaluate/reject; ignore caller claim |
| fabricated eligibility/provenance/approval | security event and refusal |
| missing provenance/policy or unhealthy policy | fail closed; immutable reason |
| taxonomy unavailable | retry; no taxon-dependent authorization |
| graph repository unavailable | `PUBLICATION_FAILED`; bounded retry |
| graph version conflict | release locks, revalidate/replan; never force overwrite |
| duplicate request | return existing event/`NO_OP_DUPLICATE` |
| concurrent publication | deterministic locks; one commit, others replay/conflict |
| partial transaction failure | database rollback leaves graph unchanged |
| audit write failure | transaction rollback; state does not advance |
| retraction during publication | serialize/invalidation check; abort or immediately require rollback if commit outcome preceded signal |
| assertion superseded during publication | dependency recheck aborts stale transaction |
| copyright restriction change | stop display, reevaluate affected publication, withdraw/retract if required |
| downstream projection failure | authoritative transactional projection rolls back; asynchronous cache failure retries from outbox |
| rollback failure | retain `ROLLBACK_REQUIRED`, quarantine affected projection, alert/escalate |

All retries use the same fingerprint, bounded backoff, and current dependency checks. Error logs contain identifiers/classes, not restricted text, secrets, or private reviewer detail.

## 22. Observability and governance

Metrics include publication volume/latency by domain/path; rejection/gate reasons; automatic/human authorization; provisional volume/age; supersession, withdrawal, retraction, rollback, duplicate suppression, provenance failure, graph conflict, projection failure, retry, reviewer reversal, policy/model drift, and effect radius. Quality slices cover domain, taxon, geography, language/source cohort, conservation risk, publication pathway, and reviewer specialty to reveal bias.

Audit records include immutable input/output fingerprints, state transitions, authority/reviewer references, policy/gate results, graph versions, change-set/inverse digests, transaction/outbox IDs, failure classification, and timestamps. Governance requires periodic automatic-publication sampling, policy-owner review, access/grant audit, direct-writer inventory, bias review, recovery exercises, and publication/provenance reconciliation. Operational logs minimize private identities and never expose source text or credentials.

## 23. Scale and performance

The design supports millions of evidence records/assertions using indexed logical IDs/fingerprints, current-state projections, partitionable append-only histories, and indexed reverse provenance. Change sets stream bounded ordered operations and need not load full graph/history. Asynchronous workers process safe independent items; batch parents track independent atomic child publications. Large scientifically coupled changes use one bounded transaction or are refused/split at a scientifically valid boundary.

Publication is resumable only between immutable item transactions. Current queries never scan full history; historical reconstruction uses graph-version/event indexes and checkpoints. Deterministic replay consumes recorded manifests and versions. Start with existing PostgreSQL, advisory locks, graph repository, and outbox patterns; add partitioning/replicas only from measured need, not speculative distribution.

## 24. Recommended BUILD-088 implementation sequence

### BUILD-088B — Publication Registry and Policy Foundation

- **Objective:** additive Layer 4 registry, immutable policies, lifecycle/authority decisions, trusted BUILD-087 resolvers, writer/grant inventory, dry-run manifests.
- **Dependencies:** merged BUILD-087B; existing BUILD-078/graph schemas.
- **Likely components:** new isolated publication-boundary domain; policy/registry repositories; read-only adapters to scientific interpretation and graph; migration; tests/docs. Existing writers unchanged except optional fail-closed enforcement feature flag after inventory.
- **Tests:** migration idempotency, immutable versioning, trusted-input rejection, transition matrix, policy gates, provisional/human/automatic decisions, authorization assumptions, provenance closure, no graph writes.
- **Acceptance:** every candidate/decision is deterministic/audited; no caller eligibility; no production graph mutation.
- **Risks:** confusing BUILD-078 readiness with BUILD-087 eligibility; incomplete direct-writer inventory.
- **Rollback boundary:** disable new registry entrypoint; additive records remain.

### BUILD-088C — Atomic Graph Transaction and Publication Engine

- **Objective:** deterministic mapping/change sets, graph versions, atomic commit, provenance, idempotency, serialization, outbox, legacy-writer interposition.
- **Dependencies:** approved 088B policy/registry and complete writer inventory.
- **Likely components:** transaction planner/engine; versioned graph/provenance additions; controlled adapter around existing repository; database grants; no public direct-write route.
- **Tests:** operation mapping, qualified assertions, concurrency, duplicate requests, graph conflicts, partial failures, audit failures, bounded batches, replay, full provenance, unchanged graph on failure.
- **Acceptance:** only controlled role writes scientific graph; atomic publication and version receipt proven in PostgreSQL; all legacy scientific paths governed.
- **Risks:** legacy upsert semantics, graph schema variability, long transactions.
- **Rollback boundary:** disable engine/grants and restore pre-activation writer role only under audited emergency procedure; committed Layer 4 history retained.

### BUILD-088D — Supersession, Withdrawal, Retraction, Restoration, and Rollback

- **Objective:** status operations, inverse technical transactions, dependency propagation, projections and cache invalidation.
- **Dependencies:** versioned 088C graph objects/events.
- **Likely components:** lifecycle services, projection builder, reevaluation/outbox handlers, additive status/dependency indexes.
- **Tests:** every allowed/prohibited transition, historical/current queries, dependent reasoning/conservation effects, rollback failure, retraction during publish, deterministic projection rebuild.
- **Acceptance:** no history erasure; authoritative views exclude invalid states; rollback and scientific change remain distinct.
- **Risks:** downstream consumers ignoring state, propagation fan-out.
- **Rollback boundary:** freeze new status actions and rebuild projections from immutable events.

### BUILD-088E — Publication Integrity and End-to-End Validation

- **Objective:** adversarial and scientific validation at scale; enforce production readiness.
- **Dependencies:** 088B–D.
- **Likely components:** deterministic corpus, PostgreSQL integration/chaos/concurrency tests, provenance reconciler, security/grant audit, performance report.
- **Tests:** millions-scale estimates/large fixtures, all failure cases, authorization bypass, direct-writer detection, policy bias, provenance traversal, replay/reconstruction, regression BUILD-082–088.
- **Acceptance:** zero orphan authoritative facts; no bypass path; objective quality/security/performance thresholds; recovery exercise passes.
- **Risks:** production schema drift and unobserved external writers.
- **Rollback boundary:** keep publication disabled until every gate passes.

No implementation build may enable production publication before its acceptance criteria and prior dependencies pass.

## 25. Risks and unresolved decisions

1. The exact deployed `oc_graph` schema and lineage-table availability must be verified before 088B schema design.
2. BUILD-078 publishes pre-BUILD-087 semantic candidates and must be classified: migrate behind Layer 4 for scientific assertions, constrain to non-Layer-4 domains, or retire after parity. It cannot remain a bypass.
3. Runtime domain publishers write canonical relational data directly and sometimes update node content in place; 088C must adapt them to immutable change sets without breaking non-scientific taxonomy/operational builds.
4. The canonical representation of qualified assertion nodes and vocabulary additions needs repository-backed vocabulary review before implementation.
5. Provisional publication is permitted architecturally only by explicit domain policy plus human authorization; each domain must decide whether to prohibit it.
6. Graph-wide versus object-key serialization and transaction-size ceilings require PostgreSQL benchmarks.
7. Reviewer identity, digital decision integrity, dual-control thresholds, and institutional authority require an approved security/governance specification.
8. Downstream consumer adoption must be complete before authoritative projection enforcement; otherwise old queries may ignore status.
9. Retraction dependency propagation may be large; bounded fan-out/checkpoint rules need benchmark validation.

These are implementation decisions with safe fail-closed defaults, not blockers to the architecture. BUILD-088B must resolve items 1–3 before enabling any writer enforcement; later builds resolve the rest before production activation.

## 26. Final readiness verdict

READY FOR BUILD-088B
