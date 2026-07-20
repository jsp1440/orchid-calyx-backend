# BUILD-087A — Context-Preserving Scientific Evidence Interpretation and Review Architecture

## Status and scope

This document defines the architecture for turning preserved scientific evidence into reviewable interpretations and, only through a future controlled publication boundary, canonical scientific assertions. It introduces no database schema, migration, endpoint, interface, queue, authorization mechanism, or production implementation. BUILD-082 through BUILD-086 remain unchanged.

The governing rule is: **loss of context is a scientific error**. Throughput, convenience, and confidence never justify discarding context required to understand, reproduce, qualify, or challenge an interpretation.

## Architectural invariants

1. Source Evidence, Machine Interpretation, and Canonical Scientific Assertion are separate layers with separate identities and histories.
2. No layer overwrites another. Corrections create new versions or decisions and retain prior states.
3. Source Evidence is preserved exactly as permitted by copyright policy. Normalization occurs only in derived layers.
4. An Evidence Packet is the minimum review unit. A detached sentence or fragment is not independently promotable.
5. Every interpretation is reproducible from identified source revisions, packet construction rules, extractor/ruleset versions, and configuration.
6. Confidence is transparent, decomposed, calibrated, and never represented as truth probability.
7. Independent corroboration is based on source lineage, not document count or repeated wording.
8. Contradiction, ambiguity, qualification, retraction, and supersession remain visible.
9. Automation may promote only within an explicitly versioned policy. It cannot bypass copyright, taxonomy, conservation-risk, or publication controls.
10. No BUILD-087 component publishes to the Knowledge Graph. Canonical assertions are publication-eligible records, not published facts.
11. Every state transition, reviewer action, policy decision, and machine decision is auditable.
12. Reprocessing is idempotent for the same immutable inputs and versioned rules.

## Three-layer scientific model

### Layer 1 — Source Evidence

Layer 1 records exactly what a source contains and how it was obtained. Its logical contract includes the immutable source revision; original wording or an access-controlled reference to it; complete contextual passage; page and section; table, figure, caption, footnote, and bibliography relationships; citation and publication metadata; source lineage; copyright and access policy; extraction coordinates; and provenance.

Layer 1 performs no scientific normalization, paraphrase, unit conversion, taxon resolution, or correction. Where copyright policy prohibits storing or displaying text, the layer retains stable anchors, hashes, metadata, permissions, and retrieval instructions sufficient to prove identity without copying restricted content. A later permission change creates a new policy event; it does not rewrite the historical source record.

### Layer 2 — Machine Interpretation

Layer 2 records a reproducible, versioned interpretation of one or more Evidence Packets. It may identify entities, taxa, organs, traits, relationships, measurements, units, life stages, populations, localities, experimental conditions, qualifiers, negation, comparison structure, confidence factors, reasoning traces, ambiguities, and alternative interpretations.

An interpretation identifies all packet versions it consumed, its model/extractor and ruleset versions, normalization vocabularies, configuration, deterministic preprocessing, creation time, and any earlier interpretation it supersedes. It never changes Layer 1. A correction yields a new interpretation version or a reviewer decision linked to the original.

### Layer 3 — Canonical Scientific Assertion

Layer 3 is normalized, versioned knowledge that may become eligible for a future publication workflow. It retains links to all supporting and conflicting interpretations and packets, scope, qualifiers, confidence decomposition, review/promotion decision, policy version, and assertion history. It never embeds restricted source text or overwrites Layers 1 or 2.

Canonical does not mean certain, final, or published. Assertions may be provisional, disputed, superseded, retracted, or withdrawn. A separate future publication authority must verify eligibility and create Knowledge Graph changes. BUILD-087A grants no such authority.

## Overall workflow and component responsibilities

```text
Immutable source revision
  -> Context boundary analysis
  -> Evidence Packet construction and completeness validation
  -> Machine interpretation plus alternatives
  -> Cross-document evidence reconciliation (BUILD-086)
  -> Risk and promotion policy evaluation
       -> automatic promotion to publication-eligible assertion
       -> provisional scientific assertion
       -> exception review
  -> auditable decision and versioned canonical assertion
  -> future publication gate (outside BUILD-087)

Reviewer decision
  -> assertion/review state transition
  -> structured correction record
  -> future extractor evaluation input (no immediate retraining)
```

The architecture consists of logical responsibilities, not prescribed services:

- **Source Evidence Custodian:** resolves immutable source revisions and copyright-safe content access; rejects mutable or incomplete provenance.
- **Context Boundary Analyzer:** identifies semantically complete candidate contexts and relationships among paragraphs, sentences, tables, figures, methods, results, treatments, and citations.
- **Evidence Packet Builder:** assembles versioned packets, records inclusion decisions, and proves that required context is present or explicitly unknown.
- **Interpretation Engine:** produces reproducible primary and alternative interpretations without changing evidence.
- **Evidence Reconciler:** reuses BUILD-086 duplicate, dependence, conflict, taxonomy, temporal, geographic, and measurement analysis.
- **Context Completeness Assessor:** evaluates whether taxon, scope, qualifiers, negation, methods, and other required dimensions are resolved enough for a proposed assertion.
- **Risk and Promotion Evaluator:** applies a versioned, explainable routing policy and produces factors, thresholds, pathway, and rationale.
- **Review Orchestrator:** presents context-complete review items, records decisions, supports escalation, and never makes scientific decisions itself.
- **Assertion Registry:** maintains versioned Layer 3 assertions and eligibility state without publishing them.
- **Correction Record Registry:** captures reusable structured feedback linked to evidence, interpretation, decision, and policy versions.
- **Audit and Observability Boundary:** records lineage, transitions, latency, calibration, drift, queue health, and policy outcomes without leaking restricted text or secrets.
- **Future Publication Gate:** an explicit, separately authorized downstream boundary; absent from BUILD-087 implementation scope.

## Evidence Packet architecture

### Packet identity and versioning

A packet is a versioned manifest over immutable source anchors. Its identity derives from the source revision, ordered anchors, packet-construction policy, boundary-analysis version, and copyright-display policy. Repeating construction with identical inputs reuses the packet version. Changed boundaries, source revisions, policies, or relationships create a new version and retain the old one.

A packet contains references to source material rather than a rewritten summary. It records packet type, anchor order, structural relationships, included and excluded context, completeness assessment, provenance, copyright controls, and construction rationale.

### Supported context forms

- complete paragraph or linked paragraph sequence;
- linked sentences whose antecedents, qualifiers, negations, and comparisons are resolved;
- table row plus column headers, units, title, notes, caption, and relevant methods;
- figure region or result plus axes/legend, caption, and relevant methods;
- methods plus linked result where interpretation depends on protocol;
- taxonomic treatment including name usage, diagnosis/context, specimen/locality links, and cited concept;
- semantically complete multi-part context identified by explicit relationships.

Packet type is descriptive, not a license to omit context. A packet may span non-contiguous anchors when the source explicitly connects them; their order and connection rationale must remain visible.

### Context completeness contract

For each proposed interpretation, the builder records every applicable dimension as `PRESENT`, `EXPLICITLY_ABSENT`, `NOT_APPLICABLE`, `AMBIGUOUS`, or `UNKNOWN`:

- taxon and taxon concept/name usage;
- organ or biological structure;
- trait or relationship;
- measurement, original value, and units;
- life stage, sex, developmental state, or phenological state;
- population, specimen, sample, and sample size;
- geographic locality and spatial scope;
- temporal scope;
- experimental and environmental conditions;
- methods, instrument, treatment, comparator, and controls;
- qualifiers, modality, uncertainty, and negation;
- comparisons, baselines, and referents;
- citations and source-dependence relationships;
- surrounding biological context needed to constrain meaning.

`AMBIGUOUS` or `UNKNOWN` is preserved, never guessed away. Any dimension material to the assertion blocks automatic promotion until resolved or routed provisionally under an explicit policy. Incomplete provenance, unresolved pronouns, detached units, orphan table cells, missing legends, or missing methods make the packet ineligible for automatic promotion.

### Packet construction safeguards

Boundary expansion continues until references and qualifiers are resolved or a configured source boundary is reached. The builder favors excess context over silent truncation but enforces copyright-display limits. It records why each anchor was included. It never fabricates missing context, merges contexts from different source revisions, or treats citation text as independent evidence. Packet validation detects anchor drift using immutable revision identity and content hashes.

## Evidence and review lifecycle

### Evidence lifecycle states

```text
SOURCE_REGISTERED
  -> PACKET_CANDIDATE
  -> PACKET_COMPLETE | PACKET_INCOMPLETE | PACKET_RESTRICTED
  -> INTERPRETED
  -> RECONCILED
  -> ROUTED
  -> ASSERTION_ELIGIBLE | ASSERTION_PROVISIONAL | EXCEPTION_REVIEW
  -> SUPERSEDED | RETRACTED | WITHDRAWN
```

`PACKET_INCOMPLETE` and `PACKET_RESTRICTED` remain available for later re-evaluation. Retraction and supersession never delete packets or interpretations. Failures transition the affected work item to a retryable or terminal failure state while completed immutable artifacts remain intact.

### Review lifecycle states

```text
OPEN
  -> CLAIMED
  -> DECIDED
       -> ACCEPTED
       -> ACCEPTED_WITH_CORRECTION
       -> PROVISIONAL
       -> REJECTED_INTERPRETATION
       -> DUPLICATE_MERGED
       -> ESCALATED
  -> SUPERSEDED
```

A claim lease prevents accidental simultaneous decisions but does not confer scientific authority. Expired claims return to `OPEN`. `ESCALATED` creates a linked specialist review with the original history intact. Reopening creates a new review version; it does not erase the prior decision.

Every decision records reviewer identity and declared specialty where applicable, action, rationale, timestamp, evidence/interpretation/assertion versions, displayed context manifest, policy version, and before/after state. Accept-with-correction records structured corrected fields and scope rather than editing evidence. Duplicate merge preserves every evidence link and dependence assessment.

## Risk-based automation lifecycle

### Routing pathways

**Automatic Promotion** creates a publication-eligible Layer 3 assertion without routine human review. It requires all mandatory gates and cannot publish the assertion.

**Provisional Scientific Assertion** creates a clearly labeled, non-final Layer 3 assertion when evidence is useful but limited, conditional, or not independently corroborated. Provisional assertions remain visible to internal scientific workflows with their limitations and cannot masquerade as established consensus.

**Exception Review** routes material ambiguity, conflict, risk, policy failure, or low confidence to the appropriate reviewer specialty.

### Mandatory gates for automatic promotion

All gates must pass under a versioned policy:

1. source revision and provenance are complete and immutable;
2. copyright policy permits the intended internal processing and review display;
3. packet context is complete for every scientifically material dimension;
4. extraction and interpretation are reproducible and supported by allowed model/ruleset versions;
5. entity and taxon resolution are unambiguous at the asserted scope;
6. measurements and methods are compatible with the proposed normalization;
7. qualifiers, negation, population, geography, time, and experimental conditions are preserved in assertion scope;
8. no unresolved contradiction, retraction, supersession, or material alternative interpretation exists;
9. source-independence analysis shows either sufficient independent agreement or a policy-approved direct authoritative source class;
10. calibrated confidence and per-factor minima exceed type-specific thresholds;
11. the assertion is not in a high-impact conservation, safety, nomenclatural, or other mandatory-review category;
12. policy, calibration, and drift monitors are healthy.

A single failed hard gate prevents automatic promotion. Scores cannot compensate for missing provenance, context, copyright permission, unresolved contradiction, or mandatory specialist review.

### Objective routing factors

The evaluator records, separately, source quality, anchor completeness, context completeness, extraction confidence, entity/taxon certainty, relation certainty, measurement compatibility, independent support, contradiction severity, ambiguity, copyright eligibility, impact class, novelty, model calibration cohort, and policy exceptions. It emits the chosen pathway, every gate result, threshold values, and a human-readable rationale.

Thresholds are versioned by assertion type and scientific domain. They are calibrated on adjudicated corpora and monitored for precision, exception escape rate, reviewer reversal rate, taxonomic and geographic subgroup performance, and abstention. Aggregate scores remain prioritization aids, never truth probabilities.

### Automation state transitions

```text
UNEVALUATED -> POLICY_EVALUATED
POLICY_EVALUATED -> AUTO_ELIGIBLE | PROVISIONAL_ELIGIBLE | REVIEW_REQUIRED
AUTO_ELIGIBLE -> ASSERTION_ELIGIBLE
PROVISIONAL_ELIGIBLE -> ASSERTION_PROVISIONAL
REVIEW_REQUIRED -> REVIEW_OPEN
any decision -> REEVALUATION_REQUIRED when evidence, policy, taxonomy, model, or source status changes
```

Promotion is idempotent for identical evidence membership, interpretation versions, reconciliation result, and policy version. New contradictory evidence, retraction, taxonomy changes, or policy changes trigger re-evaluation and may supersede eligibility; they never silently rewrite an assertion.

## Rapid scientific review contract

One review item must provide everything needed for the decision without external searching:

- proposed canonical assertion with full scientific scope;
- supporting, qualifying, and conflicting evidence grouped by independence;
- complete original packet context in source order, subject to copyright controls;
- source metadata, citation graph, and exact anchors;
- primary and alternative machine interpretations;
- transparent confidence factors, gate results, and routing rationale;
- taxonomic concept, temporal/geographic scope, methods, units, conversions, and compatibility;
- duplicate, derivation, supersession, and retraction relationships;
- previous reviews, corrections, and audit history.

The contract supports Accept, Accept with correction, Mark provisional, Reject interpretation, Merge duplicate evidence, Escalate to specialist review, and Record rationale. Actions are constrained by role in a future authorization design, but authorization itself is out of scope here.

Review prioritization uses scientific risk and expected information gain, not confidence alone. High-impact, contradictory, novel, drift-affected, or widely reused assertions rise first. Routine high-confidence assertions meeting every hard gate bypass manual review. Sampling policies send a small, stratified portion of automatic promotions to blind quality review to measure escape rates and bias without creating a universal human bottleneck.

## Structured feedback lifecycle

A reviewer decision produces an immutable correction record containing:

- the evidence packet, interpretation, assertion, review, and policy versions;
- error category and affected structured field;
- original machine value and corrected value or disposition;
- scientific rationale and reviewer specialty;
- context dimensions responsible for the correction;
- whether the issue is source-specific, rule-specific, model-specific, vocabulary-specific, or policy-specific;
- applicability constraints and suggested reusable correction pattern;
- adjudication and consensus status;
- privacy, copyright, and permitted-use classification.

Correction records are evaluation inputs, rule-development evidence, prompt/example candidates, calibration data, and future training candidates only after quality and rights approval. They do not immediately retrain or mutate a model, silently alter prior interpretations, or become global rules from one decision.

Feedback states are `CAPTURED`, `QUALITY_CHECKED`, `ADJUDICATED`, `APPROVED_FOR_EVALUATION`, `APPROVED_FOR_FUTURE_LEARNING`, `REJECTED`, and `SUPERSEDED`. Conflicting reviewer feedback is retained and routed to adjudication. A future extraction release declares which correction-record cohort it used, enabling before/after evaluation and rollback.

## Failure handling and recovery

- **Missing or malformed source:** quarantine the item, preserve diagnostics without source text, and do not interpret.
- **Incomplete context:** retain the packet candidate with missing dimensions and route for source enrichment or review; never infer absent context.
- **Anchor drift or source revision:** invalidate derived eligibility, construct a new packet version, and preserve the earlier lineage.
- **Model/ruleset failure:** retry from the last immutable boundary; deterministic identifiers prevent duplicate interpretations.
- **Partial batch failure:** isolate the item; completed packets and interpretations remain valid and auditable.
- **Timeout or cancellation:** checkpoint only at immutable artifact boundaries and resume with the same versions and policy.
- **Conflicting evidence:** preserve all sides, prevent automatic promotion, and route by domain and severity.
- **Retraction or supersession:** create a source-status event, re-evaluate all dependent assertions, and retain historical states.
- **Copyright-policy failure:** suppress restricted display/output, retain lawful metadata and anchors, and fail closed.
- **Taxonomy-service unavailable:** retain original name usage, mark resolution unavailable, and block taxon-dependent promotion.
- **Promotion-policy unavailable or unhealthy:** fail closed to provisional or review according to the last approved policy; never auto-promote under an unknown policy.
- **Reviewer concurrency:** use exclusive decision semantics and immutable competing drafts; no last-write-wins scientific decision.
- **Audit write failure:** do not commit the scientific state transition.

Retries use bounded backoff and idempotency keys. Poison items enter an exception path without blocking unrelated evidence. Operational logs contain identifiers, status, timing, and error classes—not secrets or restricted evidence text.

## Scale and performance architecture

The logical model supports millions of evidence records by partitioning work on stable source, packet, interpretation, and assertion identities; processing asynchronously in bounded batches; and materializing review projections separately from immutable scientific records. Components exchange identifiers and compact manifests rather than repeatedly copying full text. Restricted content is resolved only for authorized review display.

Packet construction and interpretation are embarrassingly parallel by immutable source revision. Reconciliation is partitioned by scientifically meaningful candidate identity and scope. Promotion evaluation operates on versioned reconciliation snapshots. Review queues are derived projections that can be rebuilt from authoritative histories.

Backpressure is applied per stage. Large packets, clusters, and citation networks have bounded work units with continuation tokens/checkpoints. Hot read projections may cache complete review packets, but caches are disposable and keyed by all relevant versions. No scale optimization may truncate context or collapse provenance.

Capacity measures include packet and interpretation throughput, reconciliation latency, routing latency, review age by risk, retry rate, memory per work unit, large-cluster latency, cache hit rate, and re-evaluation fan-out. Scientific quality measures are never traded silently for throughput.

## Bias controls and scientific governance

Bias can enter through available literature, language, geography, taxonomic coverage, publication practices, source access, extractor performance, reviewer composition, and promotion thresholds. The architecture therefore requires:

- stratified quality metrics by taxon, geography, language, source type, publication era, evidence type, and assertion class;
- visibility of missingness and underrepresented cohorts;
- calibrated abstention and conservative routing outside validated cohorts;
- versioned policies and correction cohorts with named scientific ownership;
- sampled audits of automatic promotions and provisional assertions;
- reviewer-disagreement and reversal metrics;
- no use of citation frequency as a proxy for independent truth;
- no majority-vote resolution of scientific conflict;
- explicit documentation of model, corpus, and policy limitations;
- rollback to a prior approved promotion policy when quality degrades.

Automation targets may be set only with both quality and coverage constraints. A high precision measured on an unrepresentative subset is insufficient.

## Reproducibility and audit contract

Given the same immutable source revisions, packet policy, extractor/model, ruleset, vocabularies, reconciliation snapshot, and promotion policy, the system must reproduce the same packet manifest, interpretation, routing result, and assertion candidate. Non-deterministic model output is captured as a versioned artifact with invocation metadata and must pass deterministic validation before promotion.

The audit chain records artifact identity and version, actor or component, input versions, action, reason, policy, timestamps, state transition, correlation/run identity, and integrity hashes. Audit history is append-only. Scientific artifacts remain addressable after supersession. Confidence calculations expose inputs, transformations, weights or rules, thresholds, missing values, and calibration cohort.

## Future extension points

- multiple independent reviewers and configurable consensus/adjudication policies;
- reviewer specialties by taxonomy, ecology, morphology, molecular biology, conservation, statistics, and geography;
- community review with reputation and conflict-of-interest signals;
- institutional and journal-partner review spaces with scoped governance;
- blinded review and inter-rater reliability evaluation;
- Orchid Zoo review projections implementing the review contract;
- multilingual evidence and terminology mappings without rewriting sources;
- new packet types and scientific domains through versioned construction policies;
- future learning systems consuming approved correction cohorts;
- a separately authorized Knowledge Graph publication workflow with eligibility revalidation, dry-run diff, approval, lineage, rollback, and public evidence-class display.

Extensions must preserve the three layers, immutable lineage, context completeness, and the separate publication boundary.

## Validation against architectural goals

### Scientific defensibility

The design distinguishes observation, interpretation, and canonicalization; retains conflicts and alternatives; makes confidence and scope transparent; requires immutable provenance; and prevents automatic promotion when hard scientific gates fail. **Pass.**

### Context preservation

Evidence Packets are source-anchored manifests over semantically complete contexts with explicit completeness states. Tables, figures, methods, qualifiers, negation, scope, and citations remain connected. Missing context is represented rather than guessed. **Pass.**

### Large-scale automation

Routine assertions can bypass review only after all hard gates pass. Provisional and exception pathways, stratified sampling, partitioned processing, bounded work, and derived review projections support millions of records without requiring universal manual review. **Pass.**

### Performance

Immutable identities permit parallel work, idempotent retries, caches, incremental re-evaluation, and bounded batches. Context is referenced rather than duplicated, and no optimization is allowed to truncate meaning. **Pass at architecture level; implementation benchmarks belong to later builds.**

### Maintainability

Logical responsibilities, versioned contracts, explicit transitions, rebuildable projections, and policy isolation limit coupling to BUILD-082–086 and allow independent evolution. **Pass.**

### Extensibility

Packet policies, assertion-type policies, reviewer specialties, consensus models, correction cohorts, and the separate future publication gate are versioned extension points. **Pass.**

### Risk of scientific bias

The design identifies major bias sources and requires stratified calibration, abstention, sampling, disagreement monitoring, explicit missingness, and rollback. Residual bias cannot be eliminated; it remains measurable and reviewable. **Pass with ongoing governance required.**

## BUILD-087B implementation boundary

BUILD-087B may translate these logical contracts into a detailed data/API implementation plan, but it must not collapse the three layers, make fragments promotable, mutate source evidence, treat confidence as truth, erase conflicts, count derivative sources as independent, or couple assertion creation to graph publication. It must define measurable context-completeness, routing, calibration, idempotency, audit, and performance acceptance criteria before production implementation.

## Final verdict

**READY FOR BUILD-087B**
