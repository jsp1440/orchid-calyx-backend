# BUILD-089C — Design Intelligence Corpus Population and Review Readiness

## Archive identity and provenance

- Google Drive ID: `1z_aiDTAHsGMqPfWU1FCYgIRKKU7AKw5L`
- Archive: `BUILD-089C_Design_Intelligence_Corpus_v1.zip.zip`
- SHA-256: `aaf27bf015e544b802296fc047ccc5979d9bd7a8012f96480abb52cdf5634a4c` (verified)
- Supplied by: Jeffery Parham for Orchid Continuum
- Source type: user-supplied internal research archive
- Rights state: `USER_SUPPLIED_INTERNAL_RESEARCH_ONLY`
- Reuse or redistribution license: `NOT_SUPPLIED`
- Public redistribution: prohibited unless rights are supplied and approved

The archive and every internal archive path are retained as immutable provenance. The important Gemini/Calyx research document, `Calyx_Research_Acquisition_Report.docx`, is included and ingested. Its content refers to Gemini; no author is present in its DOCX metadata, so authorship remains `AUTHOR_NOT_SUPPLIED`.

## Complete imported-document inventory (42)

1. `Calyx_Research_Acquisition_Report.docx`
2. `calyx.agent.final.md`
3. `calyx.agent.outline.md`
4. `calyx_ref.md`
5. `calyx_sec00.md`
6. `calyx_sec01.md`
7. `calyx_sec02.md`
8. `calyx_sec03.md`
9. `calyx_sec04.md`
10. `calyx_sec05.md`
11. `calyx_sec06.md`
12. `calyx_sec07.md`
13. `calyx_sec08.md`
14. `calyx_sec09.md`
15. `calyx_sec10.md`
16. `calyx_sec11.md`
17. `calyx_sec12.md`
18. `calyx_work.converted.md`
19. `calyx_work.md`
20. `plan.md`
21. `md2docx_out/calyx_work.base.docx`
22. `md2docx_out/calyx_work.footnote.docx`
23. `research/calyx_cross_verification.md`
24. `research/calyx_dim01.md`
25. `research/calyx_dim02.md`
26. `research/calyx_dim03.md`
27. `research/calyx_dim04.md`
28. `research/calyx_dim05.md`
29. `research/calyx_dim06.md`
30. `research/calyx_dim07.md`
31. `research/calyx_dim08.md`
32. `research/calyx_dim09.md`
33. `research/calyx_dim10.md`
34. `research/calyx_dim11.md`
35. `research/calyx_dim12.md`
36. `research/calyx_insight.md`
37. `research/calyx_wide01.md`
38. `research/calyx_wide02.md`
39. `research/calyx_wide03.md`
40. `research/calyx_wide04.md`
41. `research/calyx_wide05.md`
42. `research/calyx_wide06.md`

## Complete skipped-file inventory (5)

Each file remains in the immutable inventory. PNG is outside BUILD-089B's Markdown, DOCX, PDF, and plain-text extraction support; no image content is claimed as ingested.

| Filename | Archive path | Reason | Recommended action |
|---|---|---|---|
| `calyx_cover_bg.png` | `assets/calyx_cover_bg.png` | Unsupported PNG image | Add approved image extraction/OCR and an anchored text companion. |
| `orchid_dissertations_by_region.png` | `charts/orchid_dissertations_by_region.png` | Unsupported PNG chart | Add chart extraction/OCR with labels and data provenance. |
| `sec01_record_counts.png` | `charts/sec01_record_counts.png` | Unsupported PNG chart | Add chart extraction/OCR with labels and data provenance. |
| `sec04_pipeline_mermaid.png` | `charts/sec04_pipeline_mermaid.png` | Unsupported PNG diagram | Add diagram OCR or the authoritative Mermaid source. |
| `sec10_phase_gantt.png` | `charts/sec10_phase_gantt.png` | Unsupported PNG chart | Add chart extraction/OCR with labels and data provenance. |

## Deterministic population and validation

- Documents processed/imported: 42
- Semantic units: 7,911
- Deterministic embeddings: 7,911
- Relationships: 178,167
- Classification assignments: 1,354
- Provenance coverage: 100%
- Exact normalized duplicate units: 3,136 (retained for curator review)
- `CONTRADICTS` relationship candidates: 38,184 (retained; never overwritten or deleted)
- Obsolete/deprecated/superseded/retracted mentions: 51
- Units without a recognized inline citation token: 6,520
- Units without a supported semantic classification: 6,792

Domain counts are Accessibility 25, Color Systems 60, Information Architecture 104, Interaction Design 9, Learning Sciences 1, Motion Design 11, Typography 28, UI 79, and UX 10. Knowledge-type counts are Accessibility Requirement 299, Anti-pattern 102, Design Principle 15, Educational Theory 1, Guideline 146, Pattern 219, and Standard 221.

An identical rerun is idempotent: it processes the same logical documents but creates zero new document versions, reviews, publication events, audit events, semantic units, embeddings, or relationships.

## Retrieval outcomes

Every returned result includes source anchors, provenance, confidence decomposition, classifications, and related concepts. Source absence is an honest corpus finding, not retrieval failure.

| Requested domain | Outcome | Evidence |
|---|---|---|
| Dashboard Design | `NOT_PRESENT_IN_SOURCE_CORPUS` | No `DASHBOARD_DESIGN` unit and no complete lexical source statement. |
| UX guidance | `COVERED` | 10 UX-classified units are retrievable. |
| Accessibility | `COVERED` | 25 Accessibility-classified units are retrievable. |
| Educational Psychology | `NOT_PRESENT_IN_SOURCE_CORPUS` | No `EDUCATIONAL_PSYCHOLOGY` unit and no complete lexical source statement. |
| Scientific Visualization | `NOT_PRESENT_IN_SOURCE_CORPUS` | No `SCIENTIFIC_VISUALIZATION` unit and no complete lexical source statement. |
| Motion Design | `COVERED` | 11 Motion Design-classified units are retrievable. |
| Branding | `NOT_PRESENT_IN_SOURCE_CORPUS` | No `BRANDING` unit and no complete lexical source statement. |
| Component Libraries | `PARTIALLY_COVERED` | A semantic unit contains the complete lexical concept, but no unit meets the deterministic `COMPONENT_LIBRARIES` classification rule. |

Component Libraries is partially covered under the deterministic rule: the complete query concept appears lexically, but the source does not contain a unit classified in that domain.

## Authorship, rights, and licensing

Unknown authorship is represented as `AUTHOR_NOT_SUPPLIED`, not as corruption or fabricated authorship. Missing reuse permission is represented as `NOT_SUPPLIED`. These explicit values complete internal metadata handling, allow authorized internal ingestion and retrieval, and prevent public redistribution. Publication dates and publishers remain unknown unless explicitly present in source metadata.

## PostgreSQL and deployment status

PostgreSQL 16 CI validates BUILD-089A persistence, the additive BUILD-089B migration, append-only guards, and BUILD-089C behavior. PR #94's latest completed run passed `design-intelligence-postgresql`, `design-knowledge-semantic-reasoning`, `design-corpus-population`, and `publication-pipeline-operational-readiness`.

An encrypted repository secret named `DATABASE_URL` exists, but its target, intended purpose, authorization for production corpus population, and availability of real BUILD-082 revision/extraction/anchor/evidence records cannot be verified without exposing or using the secret. It was therefore not used. No local production database variables are configured. Production population remains blocked until an owner explicitly authorizes a target and confirms the prerequisite BUILD-082 provenance registry. No credentials or provenance identifiers were fabricated.

This is a deployment-population blocker, not an implementation-review blocker.

## Future acquisition recommendations

Acquire curator-approved, rights-cleared sources for Dashboard Design, Educational Psychology, Scientific Visualization, Branding, and Component Libraries; obtain explicit author and reuse-license metadata where available; provide anchored OCR/text companions for the five PNG assets; and review duplicate, contradiction, obsolete-material, and citation findings before broader use.
