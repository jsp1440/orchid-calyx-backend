# BUILD-077 — Ontology & Evidence Registry

BUILD-077 adds a controlled, versioned resolution layer between BUILD-076B review candidates and the future BUILD-078 publication process. It never publishes to the canonical Knowledge Graph.

## Schema and versioning

The additive `oc_ontology` schema stores ontology registries, terms, synonyms, candidate-resolution history, references to immutable semantic evidence, versioned publication-readiness evaluations, and audit events. A registry is identified by namespace and version and may represent taxonomy, glossary, trait, habitat, pollinator, mycorrhiza, geography, organization, person, literature, media, or conservation vocabularies from any declared authority. Namespace, version, and checksum become immutable after activation.

## Resolution workflow

Candidate entities retain their original BUILD-076B text. Local deterministic matching checks canonical keys, preferred labels, normalized labels, synonyms, then conservative fuzzy suggestions. All matches remain proposed until an authenticated reviewer accepts them. Fuzzy matches are never automatically accepted. Manual assignments also remain proposed until review. Resolution history is append-only and one accepted resolution is permitted per candidate.

Normalization uses Unicode NFKC, whitespace and case normalization, conservative punctuation handling, and scientific-name-aware hybrid-marker normalization. It does not infer spelling corrections or taxonomic synonymy.

## Evidence registry

The registry references `oc_semantic.evidence_objects`; it does not copy or modify them. Validation checks the immutable evidence hash, evidence source SHA-256, preserved intake-document SHA-256, and provenance. Revalidation changes only the registry validation result and creates an audit event.

## Publication readiness

Readiness requires accepted candidate review, a semantic session in `READY_FOR_REVIEW`, complete provenance, accepted resolution against an active ontology for entities, and valid evidence plus ready subject/object entities for relationships. Every failure produces explicit blockers. A readiness row is advisory and cannot publish data.

## API

Authenticated owner-session/API-key routes are under `/api/ontology`: registry lifecycle and versions, terms and synonyms, candidate/session resolution, resolution review, evidence registration/validation, and candidate/session readiness evaluation. Errors distinguish missing records, conflicts, invalid scientific state, and unavailable database configuration.

## Audit behavior

Registry, term, synonym, resolution, evidence-validation, and readiness mutations create `ontology_audit_events` records containing actor, action, target, prior/resulting state, reason, and time.

## Explicit non-goals

BUILD-077 does not contact external authorities, alter taxonomic names, accept matches automatically, overwrite semantic evidence, add publication endpoints, or write canonical graph/taxonomy records. BUILD-078 is responsible for any separately reviewed publication workflow.

## Migration and deployment

Apply migrations in order: `076a_universal_intake.sql`, `076b_semantic_extraction.sql`, then `077_ontology_evidence_registry.sql`. Production requires `DATABASE_URL`, the existing owner-session/API-key secrets, and a PostgreSQL role permitted to create and use `oc_ontology`. Back up the database, apply the additive migration, verify triggers/indexes, then deploy the backend. No destructive migration or data rewrite is required.
