# BUILD-089B — Design Knowledge Acquisition and Semantic Reasoning

## Architecture

BUILD-089B is an additive reasoning layer over the immutable, reviewed BUILD-089A Design Intelligence Corpus. Source documents remain the authority. Derived semantic units, embeddings, relationships, and audit events are append-only and retain document version, source anchors, exact line locators, and content hashes. The layer does not generate interfaces or publish into the production Knowledge Graph.

The pipeline is:

1. authorized source bytes and curator metadata;
2. normalized BUILD-089A document input and immutable provenance;
3. reviewed and published corpus document;
4. deterministic semantic decomposition;
5. multi-label classification and local embedding;
6. provenance-bearing design relationships;
7. authenticated, read-only hybrid reasoning retrieval.

## Acquisition pipeline

`DesignDocumentAcquirer` accepts Markdown, UTF-8 plain text, DOCX, and PDF. It extracts authorized text without changing the source artifact and carries identifier, version inputs, authors, publisher, URI, license, publication date, ingestion provenance, review compatibility, and publication compatibility into BUILD-089A. Unsupported formats and empty content fail closed. Corpus content licensing and review remain BUILD-089A publication gates.

## Semantic decomposition

`SemanticDecomposer` produces stable units for headings, paragraphs, bullets, numbered procedures, tables, captions, code, quotes, recommendations, warnings, anti-patterns, and best practices. Each unit stores its parent heading, ordinal, document ID and version, exact source line range, inherited anchor IDs, and SHA-256 content hash. Reprocessing identical versions is idempotent.

## Classification model

The versioned `089b-rules-1` classifier supports all required UX, UI, interaction, dashboard, information architecture, accessibility, motion, animation, typography, color, branding, design-system, component-library, education, learning-science, visualization, knowledge-graph visualization, and scientific-communication domains. Units may have multiple domains, knowledge types, and educational classifications including Bloom, Mayer, Cognitive Load Theory, UDL, Active Learning, and Inquiry Learning. Classification evidence and confidence are stored with every unit.

BUILD-089A vocabularies are deliberately unchanged. BUILD-089B classifications form a separate derived layer so existing corpus behavior remains backward compatible.

## Relationship model

The deterministic `089b-relationships-1` generator creates `SUPPORTS`, `CONTRADICTS`, `EXTENDS`, `SPECIALIZES`, `RELATED_TO`, `USED_BY`, `IMPROVES`, `REQUIRES`, and `REFERENCES` relationships from explicit cues or shared classified concepts. Each relationship stores confidence, rationale, and both endpoint source locations. These are private design-corpus relationships, not production Knowledge Graph publications.

## Embedding strategy

The existing semantic-index provider contract is reused. The default restricted-data-safe local provider generates normalized, reproducible 32-dimensional vectors and records provider, model, version, dimension, distance metric, execution location, and data-handling metadata. A production provider can be injected through the same contract without changing stored provenance or retrieval behavior.

## Retrieval architecture

`POST /api/design-intelligence/reasoning-search` is authenticated and read-only. Ranking is deterministic: 45% keyword overlap, 35% cosine semantic similarity, and 20% classification confidence. Queries can filter by semantic domain, knowledge classification, and citation. Results include confidence, classification, supporting citation and provenance, related concepts, and a score explanation. Stable ordering uses score, document, ordinal, and unit ID.

## Future UI integration

Future My Conservatory, Mission Control, Research Platform, Species Explorer, Orchid University, Public Website, and Administration Dashboard builds can request reviewed design guidance before generating interfaces. Consumers receive evidence and explanations rather than generated components. BUILD-089B implements no UI, dashboard, or interface-generation behavior.

## PostgreSQL and auditability

Migration `089b_design_knowledge_acquisition.sql` adds semantic units, relationships, and semantic audit events under `oc_design_intelligence`. Foreign keys link every unit to its BUILD-089A document. GIN indexes support text, domain, and classification retrieval. Mutation triggers reject updates and deletes. Repository writes are idempotent inserts and all new artifacts receive audit events.

## Known limitations

- No document collection was bundled with the build request; acquisition tooling is complete, but corpus population depends on separately supplied, licensed sources.
- PDF extraction handles embedded text; OCR for image-only PDFs is future acquisition work.
- The deterministic local embedding provider prioritizes reproducibility and CI safety. Design-specific vector-quality evaluation and production embedding-provider selection remain future work.
- Relationship generation is deliberately conservative and requires later curator evaluation for domain quality.
- Interface generation, My Conservatory, curator UI, and public Knowledge Graph publication are excluded.
