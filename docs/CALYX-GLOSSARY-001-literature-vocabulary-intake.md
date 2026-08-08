# CALYX-GLOSSARY-001 — Literature Vocabulary Intake

## Purpose

Add the first operational bridge from Literature Intelligence into the Scientific Language / Glossary system without bypassing the Canonical Concept Registry.

## What this slice does

- registers a deterministic `glossary` extraction stage after entity extraction and before claim extraction;
- emits `GlossaryTerm` records already present in the Literature Intelligence contract;
- derives candidates from supported scientific entities, publication keywords, and a conservative orchid-morphology seed lexicon;
- assigns deterministic term IDs from source hash, normalized term, and extractor version;
- preserves exact source character spans where the term appears in the paper;
- marks every extracted term as `candidate` with no `glossary_entry_id`;
- exposes the candidates automatically through the existing persisted `PaperKnowledge` bundle and authenticated literature-result API;
- never creates or activates a canonical concept automatically.

## Pipeline order

`metadata → sections → entities → glossary → claims → normalization/review`

The glossary stage is intentionally upstream of claim extraction so later reasoning and consumer layers can reference the same vocabulary candidates while preserving the original source record.

## Governance boundary

This implementation does **not**:

- create Concept Registry entries;
- choose among ambiguous concept matches;
- publish glossary candidates;
- write to the Knowledge Graph;
- generate definitions from unsupported sources;
- generate figures automatically.

Canonical matching and promotion require the governed Concept Registry and human review.

## Current candidate sources

1. Supported non-taxonomic scientific entities (`anatomical_structure`, `trait`, `method`, `chemical`, `environmental_factor`, `habitat`).
2. Publication keywords.
3. Conservative orchid morphology seed terms used only for deterministic recognition:
   - velamen
   - pollinium / pollinia
   - rostellum
   - labellum / labella
   - pseudobulb
   - gynostemium
   - sepal
   - petal

The seed list is deliberately small. Future vocabulary expansion should come from governed lexicon releases and reviewed literature candidates rather than unconstrained hard-coded growth.

## Next dependent slices

1. **CALYX-GLOSSARY-002 — Candidate Resolution Queue**
   - resolve candidate terms through `/api/concepts/search`;
   - classify `matched`, `ambiguous`, and `new` without automatic promotion;
   - persist review decisions and provenance.

2. **CALYX-GLOSSARY-003 — Figure & Media Request Queue**
   - associate reviewed concepts with figure-needed status;
   - store requested figure type, audience, source concept IDs, prompt, caption requirements, and review state;
   - support existing Figure Labs/manual generation workflow without coupling Calyx to a single vendor.

3. **CALYX-GLOSSARY-004 — Interactive Scientific Language API**
   - serve definitions, pronunciation metadata, roots/combining forms, figures, photographic examples, traits, relationships, and source literature from the canonical concept identity.

## Validation

Dedicated CI runs Ruff plus the glossary-specific tests and existing Literature Intelligence E2E/regression tests. The E2E contract now requires the ordered `glossary` stage and confirms that glossary candidates are serialized through the existing API.
