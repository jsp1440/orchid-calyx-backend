# Calyx Brain operational capability inventory

**Baseline:** PR #145 (`060267d`) plus this branch. **Assessment rule:** a file or prior build name is not evidence of an operational handoff. `OPERATIONAL` means a callable, persisted, tested runtime path exists for the stated boundary.

## Capability inventory

| Capability | Status | Evidence | Entry Point | Persistence | API | Tests | Dependencies | Gaps | Recommended Next Action |
|---|---|---|---|---|---|---|---|---|---|
| Literature Intelligence | OPERATIONAL | `app/literature_extraction/service.py`, `pipeline.py`, `repository.py` | CLI/service and paper route | deterministic JSON bundles | authenticated paper retrieval | `test_literature_extraction_*`, dedicated CI | UTF-8 source | text only; no OCR/PDF/datasets | merge #145; add intake bindings |
| Semantic Knowledge / Concept Registry | PARTIAL | `app/concepts/*`, migrations 102a/102b | concept routers/services | PostgreSQL | authenticated concept APIs | BUILD-SEM-002A/B tests/CI | ontology compatibility layer | not used by literature normalization; releases incomplete | integrate resolver without changing evidence text |
| Knowledge Objects | IMPLEMENTED_NOT_INTEGRATED | `app/kernel/knowledge.py`, `assertions.py` | Python contracts/registries | in-process registries | no unified public Brain API | `tests/kernel/*` | kernel identity/governance | literature and candidate systems do not emit kernel objects | define reviewed conversion contract |
| Evidence and Provenance | PARTIAL | literature evidence/provenance; `app/candidate_knowledge/*`; `app/evidence_aggregation/*` | separate services | JSON, snapshot/PostgreSQL stores | separate APIs | literature, 086a, 086b tests | canonical source anchors | identities and storage are fragmented | preserve canonical binding across handoffs |
| Reasoning Ledger | DOCUMENTED_ONLY | Brain specification and Issue #142 | none | none | none | none | stable evidence/knowledge identities | no append-only reasoning event model | implement #142 after evidence pipeline integration |
| Working Memory | PARTIAL | `app/runtime/memory.py`, runtime engine | runtime internals | process/file state | no governed memory API | runtime tests | autonomous runtime | not linked to evidence or ledger; weak lifecycle | place behind ledger-derived session contract |
| Episodic Memory | PARTIAL | `app/runtime/discovery_memory.py` | discovery runtime | filesystem | no general Brain API | `test_discovery_memory.py` | runtime executions | episodes are not canonical reasoning events | derive episodes from ledger events |
| Semantic Memory | PARTIAL | concepts, semantic index, knowledge graph modules | multiple services | PostgreSQL/in-memory stores | fragmented APIs | component tests | concept registry | no canonical cross-store semantic memory | consolidate through concept/knowledge identities |
| Hypothesis Management | PARTIAL | research workspace hypothesis fields and interpretation proposals | workspace/interpretation services | PostgreSQL/snapshots | component APIs | workspace/087b tests | evidence packets | no hypothesis lifecycle, challenges, or decisions | specify hypothesis aggregate after ledger |
| Contradiction Detection | PARTIAL | `app/evidence_aggregation/service.py` | aggregation service/API | snapshot/PostgreSQL | aggregation API | `test_build_086b_evidence_aggregation.py` | candidate evidence | limited to aggregation inputs; not connected to literature automatically | orchestrate candidate-to-aggregation review path |
| Evidence Synthesis | PARTIAL | aggregation plus `app/scientific_interpretation/service.py` | component APIs | snapshot/PostgreSQL | separate APIs | 086b/087b tests | candidate knowledge | manual/disconnected transitions | add explicit reviewed orchestration |
| Uncertainty Tracking | PARTIAL | literature confidence/validation notes, candidate review state, aggregation uncertainty | per-component models | mixed | per-component | component tests | provenance | no shared uncertainty vocabulary or propagation policy | define ledger-carried uncertainty events |
| Data Intelligence | DOCUMENTED_ONLY | Issue #143; unrelated design-intelligence code is not dataset analysis | none for #143 scope | none | none | none | #142 reasoning/memory | profiling, validation, analysis execution absent | implement only after #142 foundations |
| Workflow Orchestration | PARTIAL | `app/workflow/*`, missions, runtime runner | workflow/runtime APIs | mixed PostgreSQL/file/in-memory | component APIs | workflow/runtime tests | missions/connectors | no single Brain state machine; handoffs remain manual | orchestrate governed scientific stages |
| Autonomous Research Planning | PARTIAL | autonomous discovery/runner modules and BUILD-014 docs | runtime runner | filesystem/runtime stores | limited runtime APIs | autonomous tests | workflow/connectors | not closed-loop with canonical evidence and reasoning | defer until ledger/query are operational |
| Query and Retrieval | PARTIAL | `app/evidence_retrieval/*`, `semantic_index/*`, graph queries, literature retrieval | multiple routes/services | multiple stores | fragmented APIs | 085 and component tests | indexes/evidence | no unified grounded Brain query | build facade after semantic/ledger integration |
| Governance and Review | PARTIAL | candidate reviews, interpretation routing, `knowledge_publication/*` | component services/APIs | PostgreSQL/snapshots | component APIs | 086a–088e tests | provenance and identities | policies are strong locally but handoffs are not unified | carry decisions through append-only ledger |
| Observability and Readiness | PARTIAL | health router, build-specific readiness and workflows | health/readiness endpoints | runtime state/logs | health APIs | readiness tests/CI | configured stores/connectors | no end-to-end Brain readiness signal or trace | add stage metrics and trace IDs after orchestration |
| API Integration | PARTIAL | routers are mounted in `app/main.py` | FastAPI | underlying component stores | many component endpoints | route tests | authentication/configuration | no stable end-to-end Brain facade | expose explicit handoffs, then a query facade |
| Persistence and Deployment Readiness | PARTIAL | migrations 086a/086b/087b/102a/102b; JSON and snapshot repositories | repository factories | heterogeneous | indirect | migration/component CI | PostgreSQL/filesystem | mixed production durability and transaction boundaries | converge critical path on PostgreSQL and validate rollback |

## Real execution flow

| Transition | Baseline state | Evidence / limitation |
|---|---|---|
| document or dataset → ingestion | PARTIAL | PR #145 accepts UTF-8 text; PDF/OCR and general datasets are outside its verified path. |
| ingestion → metadata/sections/entities/claims | VERIFIED | ordered extractors in `app/literature_extraction/pipeline.py`; deterministic tests cover the path. |
| claims → evidence/provenance | VERIFIED | source offsets and source hash are created from original text and retained in the paper bundle. |
| extraction → concept resolution | PARTIAL | normalization exists, but the Concept Registry is not its canonical resolver. |
| evidence → candidate knowledge | MISSING at baseline; VERIFIED FOR SUPPORTED, CANONICALLY BOUND RECORDS in 001A | `candidate_handoff.py` requires canonical revision/run/anchor IDs, blocks ambiguity, and invokes existing review-only extraction. |
| candidate → aggregation | PARTIAL | callable 086b API/service; no automatic governed orchestration. |
| aggregation → interpretation | PARTIAL | callable 087b contracts; transition is manual. |
| interpretation → canonical publication | PARTIAL | gates exist and assertions default unpublished; no automatic promotion is permitted. |
| reasoning → ledger | MISSING | Issue #142 is not implemented. |
| ledger → working/episodic/semantic memory | MISSING | existing memory modules are not ledger-derived. |
| memory → query → user/agent result | PARTIAL | independent retrieval paths exist; no unified grounded response path. |

The currently verified continuous flow is therefore:

`UTF-8 text → metadata → sections → entities → claims → evidence → provenance → authenticated paper API`

This branch extends it, only when intake-supplied canonical bindings exist:

`paper evidence → deterministic adapter → review-required candidate knowledge (unpublished)`

## Operational conclusions

- The Brain is not complete. Literature extraction is an operational subsystem, while reasoning, memory, and dataset intelligence remain absent or disconnected at their required architectural boundaries.
- Multiple mature component implementations already exist. Rebuilding candidates, aggregation, interpretation, or publication would duplicate working code.
- The largest immediate gap is not another extractor or schema; it is the lossless, governed transition from verified literature evidence into existing candidate knowledge.
- Canonical source IDs must come from intake/document intelligence. This slice intentionally refuses to synthesize them.

## Dependency-ordered completion program

1. **Stabilize the evidence source:** merge and retain PR #145 determinism/provenance tests.
2. **CALYX-BRAIN-001A (this slice):** deterministic literature-to-candidate adapter with explicit canonical bindings, ambiguity blocks, authentication, idempotency, and no publication.
3. **Canonical intake binding:** persist the relationship between literature paper/evidence IDs and document revision/extraction-run/anchor IDs so callers need not assemble it manually.
4. **Governed scientific orchestration:** connect candidate review, evidence aggregation, interpretation, and publication gates without bypassing human decisions.
5. **Issue #142 — Reasoning Ledger and Memory:** append-only decisions, inputs, uncertainty, contradictions, and derived working/episodic memory.
6. **Grounded query facade:** retrieve evidence, concepts, interpretations, and ledger decisions with traceable citations.
7. **Issue #143 — Data Intelligence:** add deterministic dataset profiling/validation/analysis on the same evidence and ledger contracts.
8. **Autonomous research loop:** enable planning only after governance, observability, failure recovery, and deployment persistence are verified end to end.

## Highest-priority next build

After 001A, implement **Canonical Literature Source Binding**: create an additive, transactional mapping owned by intake/document intelligence from `paper_id`/`evidence_id` to canonical document revision, extraction run, and source anchor identities. It removes the remaining manual precondition without weakening provenance or inventing identifiers.
