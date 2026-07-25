# BUILD-SEM-002B — Lexical & Definition Services

## Status

Implementation planning started from `main` after merged BUILD-SEM-002A (`dea0faf2833fa82c63d9a2124bb40caa4364656e`).

## Parent and dependency

- Parent epic: #123
- Build issue: #125
- Required predecessor: #124 / PR #128, merged

## Objective

Add governed, SKOS-aligned lexical and definition resources to the canonical concept registry so Literature Intelligence and other consumers can resolve recognized terms to stable concept identities without automatically promoting extracted candidates into canonical knowledge.

## Required scope

### Labels

Support versioned concept labels for:

- preferred labels
- alternate labels
- hidden/search labels
- historical labels
- abbreviations
- scientific names
- common names
- misspellings retained for resolution only

Enforce one preferred label per concept, language, and editorial context.

### Definitions

Support versioned definitions for:

- normative scientific definition
- concise glossary definition
- grower explanation
- learner explanation
- accessibility/plain-language explanation
- historical definition

Each definition must preserve language, script, provenance, review state, timestamps, and release metadata.

### Resolution

Provide normalized lookup across label classes while preserving ambiguity. Resolution must return candidate concepts with match provenance and must not silently select a canonical concept where multiple valid matches remain.

### API

Implement authenticated read-only routes:

- `GET /api/concepts/search`
- `GET /api/concepts/{id-or-uri}/labels`
- `GET /api/concepts/{id-or-uri}/definitions`

### Compatibility and safety

- Additive schema and contracts only.
- Preserve BUILD-SEM-002A identities and lifecycle rules.
- Preserve legacy ontology APIs and tables.
- No automatic Literature Intelligence promotion.
- No Knowledge Graph publication.
- No destructive migration.

## Validation

- migration is rerunnable and additive
- preferred-label uniqueness constraints
- language/script/editorial-context behavior
- normalized lookup and ambiguity preservation
- definition version and provenance behavior
- authenticated API tests
- ontology compatibility regressions
- application import and router mount checks
- dedicated PostgreSQL-backed GitHub Actions validation

## Literature Intelligence dependency

This build creates the lexical resolution layer required before BUILD-SEM-002D can link extracted terms, passages, evidence, and annotations to canonical concept URIs. Extraction candidates must remain separate and unresolved matches must remain explicit.
