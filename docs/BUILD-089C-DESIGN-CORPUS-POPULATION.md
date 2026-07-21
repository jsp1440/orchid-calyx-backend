# BUILD-089C — Design Intelligence Corpus Population and Knowledge Validation

## Source and ingestion

The authoritative Google Drive archive `BUILD-089C_Design_Intelligence_Corpus_v1.zip.zip` was retrieved from Drive file `1z_aiDTAHsGMqPfWU1FCYgIRKKU7AKw5L`. Its SHA-256 is `aaf27bf015e544b802296fc047ccc5979d9bd7a8012f96480abb52cdf5634a4c`. The readable archive contained 47 files: 39 Markdown, 3 DOCX, and 5 PNG.

The 42 supported documents were acquired, reviewed, internally published, decomposed, classified, embedded, and linked through the existing BUILD-089A/089B services. Each record retains the Drive identifier, archive-relative filename, immutable content hash, document version, revision, extraction run, anchor binding, review event, publication event, and audit history. The supplied archive contained no authoritative author or reuse-license metadata; the importer therefore preserves explicit `AUTHOR_NOT_SUPPLIED` and `USER_SUPPLIED_INTERNAL_RESEARCH_ONLY` values and raises curator findings rather than inventing metadata.

## Imported documents (42)

`calyx.agent.final.md`, `calyx.agent.outline.md`, `calyx_ref.md`, `Calyx_Research_Acquisition_Report.docx`, `calyx_sec00.md` through `calyx_sec12.md`, `calyx_work.converted.md`, `calyx_work.md`, `plan.md`, `md2docx_out/calyx_work.base.docx`, `md2docx_out/calyx_work.footnote.docx`, `research/calyx_cross_verification.md`, `research/calyx_dim01.md` through `research/calyx_dim12.md`, `research/calyx_insight.md`, and `research/calyx_wide01.md` through `research/calyx_wide06.md`.

## Skipped files (5)

All five are PNG assets, which are outside the approved Markdown/DOCX/PDF/plain-text acquisition formats: `assets/calyx_cover_bg.png`, `charts/orchid_dissertations_by_region.png`, `charts/sec01_record_counts.png`, `charts/sec04_pipeline_mermaid.png`, and `charts/sec10_phase_gantt.png`. Recommended correction: supply OCR-backed Markdown, DOCX, PDF, or UTF-8 text companions if their visual content must become independently retrievable knowledge. The original PNGs remain in the versioned archive directory and were not deleted.

## Deterministic quality metrics

- Documents imported/skipped: 42 / 5
- Semantic units / deterministic embeddings: 7,911 / 7,911
- Relationships: 178,167
- Classification assignments: 1,354
- Exact normalized duplicate units: 3,136
- relationships marked `CONTRADICTS`: 38,184 (curator-review candidates, not automatic deletions)
- Obsolete/deprecated/superseded/retracted mentions: 51
- Provenance coverage: 100%
- Units without a supported semantic classification: 6,792
- Units without a recognized inline citation token: 6,520

Classified domain counts are Accessibility 25, Color Systems 60, Information Architecture 104, Interaction Design 9, Learning Sciences 1, Motion Design 11, Typography 28, UI 79, and UX 10. Classified knowledge-type counts are Accessibility Requirement 299, Anti-pattern 102, Design Principle 15, Educational Theory 1, Guideline 146, Pattern 219, and Standard 221.

## Retrieval validation

Every retrieval response uses the existing hybrid retrieval contract and includes supporting source locations, provenance, confidence decomposition, classifications, and related concepts. Objective classified-domain coverage is 3/8: UX guidance, Accessibility, and Motion Design are represented. Dashboard Design, Educational Psychology, Scientific Visualization, Branding, and Component Libraries have no matching classified units in this authoritative archive. Semantic search can still return lexical/vector neighbors for those queries, but those neighbors are not counted as successful domain coverage.

## Validation report and remaining gaps

The source is principally a Calyx research-acquisition thesis/architecture corpus rather than a comprehensive interface-design library. The system intentionally reports rather than overwrites duplicates, conflicts, obsolete references, absent authorship/licensing, sparse citations, unclassified material, and missing retrieval domains. Production PostgreSQL population requires real BUILD-082 provenance bindings and an authorized target database; CI validates the PostgreSQL-backed BUILD-089A/089B repositories, while this repository packages the immutable content and deterministic population service without fabricating a production deployment result.

BUILD-090 should acquire curator-approved sources for the five missing retrieval domains, resolve author/licensing metadata, review high-volume conflict candidates, and add visual-asset text companions. Until those gaps are corrected and PostgreSQL production population is executed with real provenance records, the corpus is not review-ready under BUILD-089C's stated completion gate.
