# CALYX-BRAIN-001 — Literature Extraction End-to-End Verification

## Result

The supported verification path is `extract_and_persist`: UTF-8 document ingestion, metadata and section extraction, deterministic entity and claim extraction, exact-span evidence, ambiguity-preserving normalization, review/publication blocking, durable output-bundle persistence, and authenticated API retrieval.

This build does not claim that PDF/OCR ingestion, model-based extraction, or automatic Concept Registry resolution is operational. It does not publish extracted candidates to the canonical Knowledge Graph.

No migration is introduced. Persistence remains additive and uses the pre-existing output-bundle contract (`paper.json`, `manifest.json`, `metrics.json`, and byte-exact `raw.txt`).

## Acceptance mapping

| Requirement | Evidence |
| --- | --- |
| Real deterministic fixture | `tests/fixtures/literature/calyx_brain_001_orchid_study.txt` |
| Metadata and sections | E2E assertions on title, year, methods, results, and discussion |
| Entities/concepts | ATP, PCR, and *Escherichia coli* are extracted; absent external identifiers remain unresolved |
| Claims and exact evidence | Every fixture evidence span is checked against the original source bytes decoded as UTF-8 |
| Provenance | Source hash, extractor names/versions/confidence, input fingerprint, and configuration fingerprint are persisted |
| Persistence | Existing JSON/raw output bundle, addressed by deterministic paper ID |
| Query API | Authenticated `GET /api/literature-extraction/papers/{paper_id}` |
| Failure semantics | Empty required stages and invalid spans raise `LiteraturePipelineError(stage, code, detail)`; failed artifacts remain inspectable |
| Repeat execution | Paper and analysis IDs are content/configuration addressed and stable across retries |
| Governance | Normalized candidates create review items and remain blocked from publication |

## Operator validation

Set `LITERATURE_EXTRACTION_ROOT` to durable storage for API retrieval. Run:

```text
pytest -q tests/test_calyx_brain_001_literature_e2e.py tests/test_literature_extraction_*.py
```

Success requires the E2E test and all literature regression tests to pass. A source that produces no metadata title, sections, entities, claims, or evidence is not readiness-qualified and fails with a named stage. Failed results are persisted for diagnosis.

The same checks run in `.github/workflows/calyx-brain-001-validation.yml`. Operational status must remain **not verified** until that pull-request check passes.

## Architecture impact

This is an additive integration repair aligned with `docs/architecture/CALYX_BRAIN_SPECIFICATION_V1.md` and `docs/CODEX_ENGINEERING_PROMPT.md`. Existing extractor models, output files, ontology APIs, semantic candidate-review tables, Concept Registry, and publication gates are preserved. The repository adapter makes the established file persistence boundary explicit; it does not introduce a parallel scientific schema or bypass review.

Known limitations: the supported ingester is UTF-8 text only; extraction rules are intentionally narrow; author and journal parsing remain incomplete; filesystem durability depends on operator configuration; there is no listing endpoint; and concept resolution is ambiguity retention rather than canonical mapping.
