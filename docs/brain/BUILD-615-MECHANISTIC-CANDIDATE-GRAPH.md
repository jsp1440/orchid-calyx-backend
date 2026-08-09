# BUILD-615 — Evidence-Governed Mechanistic Candidate Graph

## Status

Implemented on `feature/build-615-mechanistic-candidate-graph`, pending validation and merge.

## Purpose

BUILD-615 connects extracted scientific mechanisms to the Candidate Knowledge review system without granting them canonical graph or publication authority.

BUILD-614 established the controlled causal vocabulary. BUILD-615 uses that vocabulary to transform a mechanistic claim into two linked artifacts:

1. a review-required Candidate Knowledge record with exact source evidence; and
2. an in-memory graph preview that must pass canonical vocabulary and cross-domain validation before the candidate is accepted for review.

The graph preview is never written to `oc_graph` by this adapter.

## Mechanistic claim contract

A claim includes:

- source endpoint: controlled node type, label, stable key, optional attributes;
- controlled causal relationship;
- target endpoint: controlled node type, label, stable key, optional attributes;
- claim confidence;
- exact evidence text and source anchors;
- canonical document/revision/extraction identifiers;
- experimental context;
- quantitative context;
- provenance metadata.

Examples include:

`environment --promotes--> physiology`

`gene --activates--> protein`

`hormone --regulates--> developmental_process`

`pathogen --causes--> symptom`

`cultivation --inhibits--> physiological_process`

## Pre-handoff validation

Before a Candidate Knowledge run exists, the adapter requires:

- the relationship to exist in the BUILD-614 controlled causal registry;
- the relationship to be causal or regulatory rather than merely contextual/evidentiary;
- both endpoints to be approved causal-reasoning node types;
- the complete two-node/one-edge graph preview to pass canonical Knowledge Graph validation.

Invalid relationships and invalid endpoint types are rejected before candidate creation, so they cannot pollute review queues.

## Candidate Knowledge integration

Valid claims use the existing Candidate Extraction Service with the new `MECHANISTIC_RELATIONSHIP` candidate kind.

Candidate qualifiers preserve:

- source and target graph node types;
- deterministic canonical candidate keys;
- relationship role, polarity, and causal status;
- experimental context;
- quantitative context;
- provenance;
- graph-validation status;
- reasoning identifier.

Existing Candidate Knowledge behavior remains in force:

- exact source anchors are retained;
- duplicate and conflict detection remains available;
- human review is required;
- candidate publication remains false;
- review approval does not itself publish to the canonical graph.

## API

Authenticated endpoint:

`POST /api/platform/brain/mechanistic-candidate`

The response contains the Candidate Knowledge run/candidate identifiers plus the validated graph preview and explicit governance flags.

## Governance boundary

BUILD-615 deliberately does not implement candidate-to-canonical publication.

It cannot:

- write nodes or edges to production `oc_graph`;
- treat extracted wording as proven causality;
- publish a claim after candidate review alone;
- bypass scientific interpretation/publication controls;
- convert Matrix or cultivation observations into general scientific truth.

Promotion from reviewed mechanistic candidate to canonical graph knowledge remains a separate governed build.

## Validation

`tests/test_build_615_mechanistic_candidate_graph.py` verifies:

- valid causal claims enter Candidate Knowledge as `MECHANISTIC_RELATIONSHIP`;
- graph previews pass BUILD-614 validation;
- inhibitory polarity is preserved;
- uncontrolled relationships fail before candidate creation;
- unapproved endpoint types fail before candidate creation;
- exact evidence anchors, experimental context, quantitative context, and provenance survive handoff;
- canonical graph mutation and automatic publication remain false.

The dedicated BUILD-615 workflow also runs BUILD-614/612 reasoning regressions, Candidate Knowledge regression tests, route import checks, lint, formatting, compile, and hygiene.

## Next highest-value work after validation

1. Add a reviewed-candidate publication planner that produces a dry-run graph mutation plan but still cannot commit without the existing controlled publication gate.
2. Add contradiction grouping for mechanistic claims with the same source/predicate identity but incompatible targets or polarity.
3. Add taxon/context scoping so a mechanism can be explicitly global, taxon-specific, tissue-specific, developmental-stage-specific, or cultivation-session-specific.
4. Add Matrix adapters that submit observed plant responses as local candidate observations without generalizing them into canonical mechanisms.
