# BUILD-614 — Scientific Causal Vocabulary and Validation

## Status

Implemented on `feature/build-614-scientific-causal-vocabulary`, pending final validation and merge.

Validation hardening completed in this implementation cycle:

- the initial dedicated gate stopped on import ordering before behavioral tests; the import order was corrected;
- the next run passed Ruff but stopped on formatter normalization; the exact formatter output was applied to the reasoning engine, causal vocabulary, validator, and regression test;
- broader CALYX graph integration, workflow governance, Brain end-to-end, publication, and interpretation regressions remained green on the pre-format functional head;
- the formatter-only head triggered GitHub `action_required` workflow state rather than executing jobs, so this owner-authored Brain update intentionally retriggers the same validation without bypassing any gate.

No BUILD-614 production graph mutation or scientific publication has occurred.

## Purpose

BUILD-614 makes the BUILD-612/613 reasoning layer structurally compatible with the canonical Orchid Continuum Knowledge Graph.

The original graph vocabulary and cross-domain validator were designed for a taxon-centered biodiversity graph: a taxon points to an image, occurrence, trait, climate record, pollinator, literature object, and similar domain node. That model is still correct for those relationships, but it cannot represent mechanistic biological pathways such as:

`environment -> physiology -> development -> phenotype`

or:

`gene -> protein -> signaling -> cell/tissue -> physiology -> development -> phenotype`

BUILD-614 adds a controlled causal vocabulary and a separate validation contract for those cross-scale scientific relationships while preserving the legacy graph rules.

## Controlled node vocabulary

New canonical node types include:

- gene and genetic variant;
- protein and enzyme;
- hormone and signal;
- cell, tissue, and organ;
- physiology and process;
- developmental process;
- phenotype and symptom;
- environment;
- cultivation, plant, specimen, treatment, and nutrient;
- pathogen and pest.

Existing node types such as taxon, species, genus, trait, climate, habitat, elevation, pollinator, fungus, molecular record, publication, assertion, evidence, hypothesis, and research question may also participate as controlled causal-context endpoints.

## Controlled relationship semantics

The new registry centrally defines role, polarity, and causal status for relationships including:

- positive causal: `causes`, `promotes`, `activates`, `induces`, `enables`, `results_in`, `expressed_as`, `increases`, `stimulates`, `facilitates`;
- inhibitory causal: `inhibits`, `suppresses`, `reduces`, `blocks`, `represses`;
- regulatory: `regulates`, `modulates`, `responds_to`, `depends_on`, `requires`, `precedes`, `influences`;
- evidence: `supports`, `contradicts`, `observed_as`, `derived_from`, `has_evidence`, plus existing canonical evidence/literature aliases.

The Brain reasoning map now consumes this central registry instead of maintaining a second hard-coded interpretation table. This prevents the canonical graph and the reasoning engine from silently disagreeing about edge meaning.

## Validation model

Legacy non-taxonomy domain edges retain the prior rule:

`taxonomy source -> target whose node domain matches the edge domain`

Controlled causal/evidence edges use a separate rule:

`approved causal-reasoning endpoint -> approved causal-reasoning endpoint`

They may cross domains intentionally. This permits molecular, anatomical, physiological, developmental, environmental, phenotypic, ecological, and cultivation mechanisms to be linked without weakening validation for existing biodiversity relationships.

Unknown relationships remain noncanonical and are not promoted into causal meaning by inference.

## Governance

This build changes vocabulary and validation only. It does not:

- load new scientific claims into production;
- mutate production Knowledge Graph state;
- automatically publish candidate knowledge;
- relax evidence requirements;
- infer causal truth from graph connectivity.

Scientific edges still require provenance and remain subject to the existing publication and Reasoning Ledger governance boundaries.

## Validation

`tests/test_build_614_scientific_causal_vocabulary.py` verifies:

- new mechanistic node types are canonical and assigned to explicit domains;
- Brain semantics and graph semantics are sourced from the same registry;
- legacy evidence/literature domain assignments remain stable;
- a complete gene/protein/cell/physiology/development/phenotype/environment causal graph passes canonical validation;
- an unapproved causal endpoint fails validation;
- unknown relationships remain noncanonical context.

A dedicated BUILD-614 workflow compiles, lints, formatter-checks, and executes BUILD-614 plus BUILD-612 reasoning regressions and existing Knowledge Graph API/traversal/orchestrator tests.

## Next highest-value work after validation

1. Add evidence-governed adapters that transform extracted physiology/development/genetics claims into these canonical node and edge types.
2. Add quantitative mechanism metadata such as dose/response direction, units, developmental stage, tissue, environmental range, and experimental context.
3. Add hypothesis comparison and contradiction accounting over competing causal pathways.
4. Add Matrix session-context adapters so measured cultivation observations can be reasoned against canonical mechanisms without publishing the session observations as scientific truth.
