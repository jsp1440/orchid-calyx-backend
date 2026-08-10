# CALYX-SYN-010 — Scientific Language Integration

## Mission

Complete the Orchid Continuum evidence-grounded synthesis module by connecting the literature glossary, Canonical Concept Registry, botanical word roots/combining forms, and a practical Botanical Latin background to the scientific interpretation and research-to-article workflow.

## Integrated path

`question → discovery → verified bibliography → governed source acquisition → literature extraction → exact source binding → evidence matrix → reviewed evidence classification → synthesis claims → grounded article → audit → figure briefs`

Scientific language now sits beside that path:

`literature extraction glossary → canonical concept search → lexical/etymological hints → Botanical Latin context`

The language layer is available beneath the authenticated Scientific Interpretation API so Research Station, Calyx, University, and future Orchid Continuum clients can consume the same service without creating a parallel vocabulary store.

## Canonical ownership

The Canonical Concept Registry remains authoritative for concept identity, labels, definitions, review state, and promotion. Literature Intelligence remains authoritative for extracted glossary candidates and their source provenance. CALYX-SYN-010 does not auto-create concepts, definitions, taxonomy, or Knowledge Graph assertions.

## APIs

- `POST /api/scientific-interpretation/research-article/run`
  - reviewed evidence classification
  - cross-study synthesis
  - grounded article generation
  - quantitative/citation audit
  - Figure Labs evidence briefs
  - human review required; no automatic publication

- `GET /api/scientific-interpretation/language/papers/{paper_id}`
  - loads the paper's persisted `glossary_terms`
  - searches `/api/concepts` through the canonical Concept Registry service
  - returns resolution state, concept candidates, word elements, and Botanical Latin context

- `POST /api/scientific-interpretation/language/analyze`
  - interactive term analysis with canonical concept search

- `GET /api/scientific-interpretation/language/word-elements`
  - versioned dictionary of high-value Latin and Greek botanical roots/combining forms

- `GET /api/scientific-interpretation/language/botanical-latin`
  - practical background on Latinized botanical naming, grammatical agreement, epithet types, common suffix patterns, and the distinction between nomenclature and biological identification

## Word-element governance

Word-root decomposition is explicitly returned as `MORPHOLOGICAL_HINT`. It is useful for learning and interpretation but is not treated as proof of:

- a taxon's diagnostic morphology;
- the intent of the original author of a scientific name;
- nomenclatural validity or priority;
- synonymy or accepted taxonomic status;
- a scientific claim in the Knowledge Graph.

The first release is `OC-BOTANICAL-LANGUAGE-001`. Future expansion should be versioned and reviewed rather than silently changing meanings.

## Botanical Latin background

The service teaches the operational points most useful inside Orchid Continuum:

- genus + specific epithet forms a species name;
- epithets may be adjectives, genitives, or nouns in apposition;
- adjectival forms normally agree with the grammatical gender of the genus;
- botanical vocabulary frequently combines Latin and Latinized Greek elements;
- endings such as `-ensis`, `-oides`, `-phyllus/-phylla/-phyllum`, and `-florus/-flora/-florum` carry recurring structural meanings;
- nomenclatural correctness and biological identification are separate questions;
- pronunciation traditions vary, while spelling, authorship, typification, and governed nomenclatural status remain the data-critical properties.

## Failure behavior

If the Canonical Concept Registry is temporarily unavailable, lexical analysis remains available but concept resolution is returned as `UNAVAILABLE`; the service never fabricates a concept match. Missing papers return 404. All APIs inherit owner/API-key authentication from Scientific Interpretation.

## Validation

Dedicated CI covers:

- foliar-feeding research-to-article benchmark;
- SYN-001 grounding validation;
- SYN-004 exact-source evidence matrix;
- CALYX-GLOSSARY-001 intake;
- Concept Registry lexical services;
- root/combining-form analysis;
- Botanical Latin background;
- authenticated paper-glossary → Concept Registry integration;
- application import.

## Knowledge-model impact

No new competing knowledge store is introduced. The word-element dictionary is explanatory reference data. Canonical concepts, scientific evidence, interpretations, assertions, publication state, and Knowledge Graph promotion remain governed by their existing Orchid Continuum owners.
