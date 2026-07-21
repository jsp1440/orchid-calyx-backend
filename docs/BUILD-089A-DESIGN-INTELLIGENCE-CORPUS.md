# BUILD-089A — Design Intelligence Corpus Foundation

## Scope

BUILD-089A creates the canonical, curated design and educational knowledge domain used by future interface-generation work. It does not implement a website, My Conservatory, a UI generator, or any interface. It reuses immutable document revisions, document-intelligence extraction runs and anchors, evidence references, authenticated backend access, review semantics, publication lifecycle, and append-only audit conventions from BUILD-082 through BUILD-088.

## Architecture

The domain is an additive boundary under `app.design_intelligence` and PostgreSQL schema `oc_design_intelligence`:

1. Existing BUILD-082/084 ingestion owns source bytes, revisions, extraction runs, and exact anchors.
2. A Design Corpus document version references those immutable identities and stores source, author, date, type, topic, and licensing metadata.
3. Deterministic versioned classification assigns one or more controlled domains and knowledge types with evidence and decomposed confidence.
4. Review and publication are separate append-only event histories. Only the latest approved and published logical document version is retrievable.
5. Authenticated, read-only retrieval returns curated metadata, confidence, license controls, exact provenance, and evidence linkage for future UI-generation consumers.

No BUILD-082–088 table, service, policy, graph object, or public behavior is replaced. No design guidance is published into the scientific Knowledge Graph.

## Data model

- `documents`: immutable logical-key/version identity, bibliographic metadata, document type, source revision, extraction run, content hash, license, and source metadata.
- `document_provenance`: exact source system/ID, revision, extraction run, anchor, evidence references, locator, and fingerprint.
- `classifications`: versioned classifier result, controlled domain/type, confidence, evidence, and fingerprint.
- `topics`: document topic assignments with confidence.
- `review_events`: approved, changes-requested, or rejected decisions with actor, rationale, and evidence.
- `publication_events`: published, retired, or retracted lifecycle events.
- `retrieval_documents`: copyright-authorized anchored text and PostgreSQL full-text index.
- `audit_events`: append-only trace for every corpus action.

All tables are additive and protected from update/delete by database triggers. New document content creates a new monotonically increasing version; it never overwrites an earlier version.

## Classification

The controlled domains are UX, UI, graphic design, information architecture, interaction design, dashboard design, accessibility, motion/animation, educational design, learning sciences, scientific visualization, branding/visual identity, design systems, and component libraries.

The controlled knowledge types are Design Principle, Pattern, Anti-pattern, Guideline, Standard, Best Practice, Educational Theory, Accessibility Requirement, Visualization Technique, and Interaction Pattern. `089a-design-rules-1` produces deterministic assignments, confidence, and matched classification evidence. Insufficient evidence fails closed; explicit curator hints cannot raise confidence beyond the conservative classifier limit.

## Retrieval flow

An authenticated consumer sends a normalized query with optional domain, knowledge-type, and topic filters. The service:

1. loads only current published logical versions;
2. expands controlled design vocabulary, including dashboard, accessibility, Mayer multimedia learning, motion, and scientific-visualization concepts;
3. applies deterministic lexical scoring plus classification confidence;
4. returns stable ordering, pagination, review/publication state, bibliographic and licensing metadata, exact anchors/evidence provenance, matched terms, and confidence.

Draft, unreviewed, rejected, retired, and retracted records are excluded. The API is read-only at `/api/design-intelligence/search`; ingestion, review, and publication remain internal service operations for later operational composition.

## Future integration

- **My Conservatory:** retrieve accessible dashboard, navigation, interaction, component, and educational patterns before interface generation.
- **Mission Control:** retrieve dense-dashboard, status, alert, workflow, and information-architecture guidance.
- **Orchid University:** retrieve Mayer multimedia-learning, cognitive-load, accessibility, and educational-design guidance.
- **Research Platform:** retrieve scientific-visualization, uncertainty, evidence-display, and research-workflow guidance.
- **Species Explorer:** retrieve information architecture, accessible visualization, comparative interaction, and responsive component guidance.

Future generators should treat this service as a mandatory pre-generation retrieval step. They must cite returned corpus versions and provenance and may not convert corpus publication into scientific Knowledge Graph publication.

## Validation

Unit coverage verifies all 14 domains and 10 knowledge types, deterministic classification, immutable version history, exact source provenance, evidence linkage, review gating, append-only publication, five required retrieval questions, confidence/provenance responses, draft exclusion, route authentication compatibility, and additive migration safeguards.

- Targeted BUILD-089A: `6 passed, 1 PostgreSQL test skipped` locally because `TEST_DATABASE_URL` is unavailable.
- BUILD-082 through BUILD-089A targeted regression: `129 passed, 8 skipped`.
- BUILD-087 through BUILD-089A final regression: `41 passed, 6 skipped`.
- Full backend: `724 passed, 25 skipped, 1 failed`; the sole failure is the independently reproduced, unchanged BUILD-085 Windows subprocess-environment failure.
- BUILD-089A scoped Ruff, repository compileall, and `git diff --check`: passed. Repository-wide Ruff reports pre-existing violations outside BUILD-089A.
- PostgreSQL 16 authoritative repository/migration validation is enforced by `.github/workflows/build-089a-validation.yml`.

## Remaining limitations

- BUILD-089A establishes the corpus contracts and PostgreSQL foundation; bulk curator tooling and user interfaces are intentionally excluded.
- Semantic vector retrieval can be composed with the existing BUILD-083/085 provider in a later build after a design-specific evaluation corpus is approved; deterministic controlled-vocabulary retrieval is the safe foundation here.
- Corpus content acquisition is separate from this infrastructure build. Licensing and review approval remain mandatory for each imported source.

READY FOR REVIEW
