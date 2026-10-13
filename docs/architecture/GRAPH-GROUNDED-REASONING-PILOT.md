# Graph-Grounded Scientific Reasoning Pilot

**Mission:** evaluate and integrate the transferable architecture of Shu et al. (2026), *DeepSeek-Lattice-KG: A Compact Language Model With Knowledge Graph Augmentation for Lattice Structure Design*, Materials Genome Engineering Advances 4(2) e70064, <https://doi.org/10.1002/mgea.70064>; reference code <https://github.com/YanChen32/DeepSeek-Lattice-KG> at `d2babd18c86172e983c2a478d9c784bbaf55c31e`.

**Classification:** `CONTINUE`. Draft PR #1775 (`docs/architecture/DEEPSEEK_LATTICE_KG_OC_INTEGRATION_ASSESSMENT.md`, branch `jsp1440-attached-request`) already holds the repository-level audit, the component comparison, the licensing review and the Neo4j / fine-tuning decisions. Its §16 proposed one bounded experiment and stated it was **not implemented**. This document and this PR implement that experiment and add the paper-level comparison that #1775 did not have, because #1775 read the README and code but not the paper. #1775 is not superseded and is not repeated here.

**Base:** `main` at `6444eb696f46ed57daf5c45b6abed8c19e3ee471`.

**Boundary:**
- What changed: one new package (`app/graph_grounded_reasoning/`), one benchmark directory, one script, one test file, one validation workflow, and this document.
- No route was registered and no migration was added.
- No database, Knowledge Graph or semantic-index write.
- No model provider call.
- No change to `app/calyx_orchestrator/`, autonomy, scheduler, publication, or any existing module.

## 1. Repository audit: capability state

"Merged" means present on `main` at the base SHA. "Deployed" and "Operational" were **not verified in this session**: there was no production access and no live database. Where a repository document asserts production state, it is cited as that document's claim.

| Capability | Implemented (code on `main`) | Tested (suite exists) | Mounted route | Deployed / operational |
|---|---|---|---|---|
| KG storage and traversal | `runtime/knowledge_graph/` (`GraphRepository`, `PostgresGraphRepository`, `traverse()` Python BFS, `MAX_DEPTH=3`) over `oc_graph.kg_nodes`/`kg_edges` | `test_knowledge_graph_traversal.py`, `test_canonical_taxonomy.py`, `test_build_066/067` | `/api/knowledge-graph/*`, `/calyx/knowledge-graph` | `docs/Orchid_Continuum_Scientific_Knowledge_Graph_Completion_Report.md` reports a taxonomy-only graph (34,519 nodes; only `genus_contains_species`/`species_belongs_to_genus` edges) at its base commit. This is not re-verified. |
| Governed assertion graph | `app/knowledge_publication/graph_mapping.py::AssertionGraphMapper` builds the `qualified_assertion` node plus support/conflict operations (migration 088c) | `test_build_088c_atomic_graph_publication.py` | publication paths | not verified |
| Canonical taxonomy and synonymy | `runtime/knowledge_graph/canonical_taxonomy.py::CanonicalRegistry` (World Plants authority; `resolve()` silently follows synonyms) | `test_canonical_taxonomy.py`, `test_world_plants_synonyms_001.py` | indirect | activation is owner-gated (`AGENTS.md`, Hassler acceptance) |
| Calyx question answering | `app/calyx_conversation/routes.py` (`/calyx/query`: hybrid retrieval → deterministic composer); `speak_routes.py` (LLM via `provider_runtime`) | `test_calyx_*` | yes | not verified |
| Calyx entity step | `continuum_context.candidate_genera`: a capitalised-token genus regex with **no synonym resolution** | yes | n/a | n/a |
| Abstention | SCIAN-002 `InferenceState` (`app/scientific_inference/models.py`). Outside its own package, `app.scientific_inference` is imported only by `app/brain_mission/routes.py`. `speak_routes.py` instead falls back to `general_knowledge_with_retrieval_gap` when retrieval is empty. | `test_scientific_inference.py`, `test_scientific_inference_resolver.py` | partial | not verified |
| Hybrid evidence retrieval | `app/evidence_retrieval/engine.py::RetrievalEngine` (`085b-rank-1`) with exact-anchor citations | `test_build_085b/c/d` | `/api/evidence-retrieval/*` | The embedding provider wired in `routes.py` is `DeterministicLocalProvider`, an 8-dimensional SHA-256 vector, so its "semantic" score carries no semantic meaning. There is no pgvector. |
| Matrix identification | `runtime/matrix_identification.py::rank_candidates`, `app/multimodal_intelligence/engine.py` | ~30 `test_matrix_identification_*` | `/api/matrix-identification` | `docs/CALYX-MATRIX-022-DEPLOYMENT.md` disclaims production state |
| Vision → Matrix transfer | `runtime/matrix_identification_vision.attach_vision_analysis`; `matrix_observations_from_vision` (confidence cap 0.95) | `test_matrix_identification_vision_*`, `test_vision_matrix_proof.py` | yes | `docs/CALYX-VISION-PRODUCTION-ACTIVATION.md` does not enable live inference |
| Literature extraction and provenance | `app/literature_extraction/*` (`Claim`, `Evidence`, `SourceSpan`, binding resolver) | `test_literature_extraction_*` | yes | full path still tracked by #181 |
| Scientific QA benchmark | none: only the component retrieval metrics `app/evidence_retrieval/evaluation.py::evaluate` | — | — | — |

**Overlapping open work:**
- #1775 is this mission's parent assessment.
- #1812, #1796 and #1801 cover the Matrix/KG/identifier chain. They are untouched, and this pilot does no identification.
- #1810 covers the offline Literature → Taxonomy → Evidence → Calyx path. Its taxon-resolution contracts would be a natural future replacement for `resolution.py`.
- #1811 and #1813 cover TraitBank.
- #901 covers KG materialization.

There is no open PR or branch implementing a graph evidence packet. The autonomy-engine convergence PRs (#1788, #1790, #1792, #1795, #1806) and their files are not touched.

## 2. Paper and reference implementation comparison

Sources:
- The full open-access paper text (Wiley HTML; abstract, §1–§4.7 and the data statement). The Supporting Information `.docx`, which holds the prompts in Figures S14/S17/S18 and the schema lists, was **not read**.
- Every file at the pinned repository revision. No code from it was executed.

| Dimension | DeepSeek-Lattice-KG (paper) | Reference repo, as evidenced | Orchid Continuum today | Transferable? |
|---|---|---|---|---|
| 1. KG construction | About 96k Web of Science records, screened to 50,000 **abstracts**. DeepSeek-R1-670B extracts SPO triples into "12 entity categories / 28 relation types". LLM synonym clustering makes the highest-degree node the canonical label. 658,623 entities and 622,344 relations (§2.1/§4.2). | Zero-shot `entity\|rel\|entity` strings via DashScope. No schema, typing, confidence, conflict or DOI. The Neo4j importer stores name-keyed `Entity` nodes. Extractor and importer formats are **incompatible**, and no converter is supplied. | Typed literature claims/evidence/spans; World Plants canonical taxonomy; versioned qualified-assertion publication. | The *idea* of source-linked extraction, yes. LLM-chosen canonical labels, **no**: OC taxonomy authority is World Plants. |
| 2. Domain-adapted LM | "DeepSeek-R1-14B", LoRA r=48, 4-bit. Continual pre-training on 2,500 articles, then 35,282 LLM-generated Q&A pairs scored by an LLM. **Only 21 pairs were manually reviewed.** 30 epochs each. | No training code, weights or data. | Provider abstraction. No orchid model. | Not now (see #1775 §9). Untrained-on-orchid evidence. |
| 3. Graph-augmented generation | Fine-tuned model extracts single-word keywords → exact-name Cypher match (the example is one hop, `LIMIT 30`) → undefined "weighted fusion" with model knowledge. | Absent. The paper's `/LLM+KG` path does not exist in the repo. | Separate primitives: graph traversal, hybrid retrieval, deterministic composers. No single packet joins them. | Yes, as typed bounded retrieval. **No** model-generated Cypher. |
| 4. Evidence validation and attribution | Claims "source traceability", but no citation format or answer-to-graph check is described. Build-time conflict screening by LLM; 109 "true-conflict" triples **removed**. On update, the **higher-impact journal wins**. | No provenance stored, so answers cannot cite. | Rich provenance primitives. The answer-level citation check was missing. | Answer-level validation, yes. **Deleting the minority claim or ranking by journal impact is rejected**: OC retains conflicting claims. |
| 5. Benchmarking | 2,100 **multiple-choice** items called "expert-curated" with no curation method described. Accuracy 94.8% (paper Fig. 4c; the repo README says 94.2%). Base 14B 71.7%, 14B+KG 84.2%, fine-tuned without KG 82.9%, R1-670B 88.2%. Temporal test: 100 LLM-generated questions (77% → 93%). No CIs or repeats. | No question set, runner or results in the repo; all paper-listed artifacts are absent. | Component retrieval metrics only. | Benchmark-first discipline, yes. The reported numbers are not reproducible, so they are not evidence. |
| 6. Dynamic knowledge updates | New papers are re-extracted and LLM conflict-checked. No retraining; "hours" per batch. | Absent. | Source/run/version lineage plus governed publication. Human review is mandatory. | Decoupling knowledge updates from model updates, yes. That is inherent in this pilot: it reads the graph at query time. |
| 7. Compute and infrastructure | "RTX 4090 GPUs (48 GB)" with count unstated (a stock 4090 has 24 GB). Training and inference cost not reported. Extraction depends on hosted R1-670B. Neo4j 5.26.2. | — | PostgreSQL. No GPU serving. | PostgreSQL is sufficient for one-hop bounded reads (#1775 §7; Brain GRAPH-001 and KO-0042 also defer a graph database). |

**Materials-to-botany caution:** lattice design has a closed engineering vocabulary and largely non-conflicting property relations. Orchid science has nomenclatural instability (synonymy, homonymy, concept splits), sparse and contested ecological evidence, and sensitive locality. None of the paper's results is assumed to transfer.

## 3. Gaps in Orchid Continuum this pilot addresses

Each gap was observed in code on `main`.

1. **No synonym-aware entity resolution in Calyx.** The genus regex ignores species names and synonyms, and `CanonicalRegistry.resolve()` follows a synonym without recording the hop.
2. **No join of graph assertions with exact literature anchors.** Graph traversal and `RetrievalEngine` are separate surfaces.
3. **No answer-level validator.** Nothing checks that every claim cites a retrieved, anchored item, that a declared conflict was not dropped, or that a no-evidence question was not answered.
4. **Abstention is not enforced on the conversational path.** `speak_routes.py` has a `general_knowledge_with_retrieval_gap` mode.
5. **No paired baseline-versus-grounded benchmark.**
6. **Lexical matching weakness** (observed by the benchmark baseline, not fixed here because it belongs to the retrieval lane). `RetrievalEngine.search` tokenises on whitespace only, keeps punctuation, has no stop-word handling, and matches with `term in text` (substring). Common words like "a" and "the" therefore count as lexical matches against most documents.

## 4. Reuse-versus-build decision matrix

| Pipeline step | Decision | Component |
|---|---|---|
| Scientific question | **Build (thin)** | `contracts.ScientificQuestion`. The intent (`Facet`) is typed and there is no free-text intent parsing. |
| Entity resolution | **Reuse + wrap** | `CanonicalRegistry`/`canonical_name_of`. The wrapper (`resolution.py`) adds explicit `RESOLVED_VIA_SYNONYM`/`AMBIGUOUS`/`UNRESOLVED` states. #1810's taxon-resolution contracts are the expected later replacement. |
| KG retrieval | **Reuse** | `GraphRepository` read methods behind a new `ReadOnlyGraphView` that exposes no write method. One hop; at most 25 edges. |
| Literature retrieval | **Reuse** | `RetrievalEngine.search` with the existing `filters={"document_id": ...}` scope, to resolve each graph assertion's declared source to revision + anchor + content hash. At most 10 lookups. |
| Observation retrieval | **Reuse (graph occurrence/geography edges)** | Sensitive-locality records are withheld, and payload is allowlisted so coordinates never travel. |
| Evidence assembly | **Build** | `retrieval.assemble_packet` → `EvidencePacket`. Each assertion is kept separate, with provenance, anchor state and declared conflicts. |
| Calyx reasoning | **Build (deterministic)** | `reasoning.compose` restates packet items and selects the SCIAN-002 state. It takes a pluggable `Composer`, so a future model-backed composer slots in **behind the same validator**. |
| Validation | **Build** | `validation.validate`. It is independent of the composer and fails closed to `VALIDATION_FAILED` with claims withheld. |
| States | **Reuse** | `app/scientific_inference/models.py::InferenceState` (SCIAN-002), plus `VALIDATION_FAILED`. |
| Graph database | **Reject Neo4j** | No demonstrated requirement (#1775 §7; Brain GRAPH-001). |
| Model hosting / fine-tune | **Reject for now** | No orchid corpus rights, gold set or baseline (#1775 §9). |
| NL→Cypher, LLM conflict deletion, journal-impact tie-break | **Reject** | Unbounded query surface; erases scientific disagreement. |

## 5. Implementation (`app/graph_grounded_reasoning/`)

`question → resolve_question_taxon → assemble_packet (ReadOnlyGraphView one-hop + RetrievalEngine document-scoped anchoring) → compose → validate → cited result`

**Contract `oc-graph-grounded-reasoning-v1`.**
- **Limits:** `GRAPH_DEPTH=1`, `MAX_GRAPH_RECORDS=25`, `MAX_EVIDENCE_RECORDS=10`, `MAX_TAXA_PER_QUESTION=3`, `MAX_QUESTION_LENGTH=500`.
- **Every result carries:**
  - resolution, including authority and any synonym hop;
  - state;
  - claims, each citing packet refs;
  - citations: document, revision, anchor IDs, locator, content hash;
  - conflicts, uncertainty markers and gaps;
  - the full evidence packet;
  - the validation verdict;
  - governance flags: `review_required: true`, `published: false`, `knowledge_graph_mutation: false`, `confidence_is_probability: false`, `provider_calls`.

**Safeguards, each covered by a focused test.**
- **Taxonomy:** a synonym is resolved to the accepted World Plants taxon and the hop is recorded. An unresolved or ambiguous name abstains **without reading the graph**.
- **Graph identity:** the registry→graph key mapping is a required input, and the focal node's label must equal the accepted canonical name (`FOCAL_NODE_IDENTITY_MISMATCH`). This prevents reading another taxon's edges when registry IDs differ from graph source keys.
- **Provenance:** a claim is emitted only for an assertion whose declared source resolves to an exact anchor. `SOURCE_UNDECLARED` and `ANCHOR_UNAVAILABLE` assertions are reported in the packet but never cited.
- **Conflicts:** declared conflicts (`conflicting_assertion_ids` and negative-polarity edges) are kept as separate claims and force `CONFLICT_REVIEW_REQUIRED`. The validator fails a composer that drops one.
- **Uncertainty:** markers cover synonym resolution, single source, unreviewed/unverified assertions, excluded unanchored assertions and declared conflicts.
- **Insufficient evidence:** `INSUFFICIENT_EVIDENCE` is an explicit, claim-free state with a named gap.
- **Read-only:** `ReadOnlyGraphView` has no write attribute. A spy repository records zero writes. An AST scan finds no write, DB-driver, provider or query-language surface in the package.
- **Locality:** `sensitive_locality`/`WITHHELD` records are excluded, and the payload allowlist prevents coordinate keys reaching the result.

**Mutation evidence:** each of the following made the focused suite fail, with a byte-identical restored tree passing again:
- removing conflict pairing;
- removing locality withholding;
- removing the unknown-ref validator check;
- removing unresolved-taxon abstention.

Runs used `python -B -m pytest -q -p no:cacheprovider tests/test_graph_grounded_reasoning.py` with `__pycache__` purged between runs.

## 6. Benchmark

- `benchmarks/graph_grounded_reasoning/fixture.json` is a **synthetic** fixture: fictional genus *Exemplaria*, fictional organisms, places and documents. It holds no botanical facts.
- `cases.json` holds 14 cases across taxonomy/synonymy, morphology, species description, pollination, mycorrhiza, distribution, conflicting literature, and uncertain/incomplete evidence.
- Labels have `label_source: FIXTURE_CONSTRUCTION` and `expert_reviewed: false`. No expert-reviewed orchid answers were available, and none were fabricated.
- Run with `PYTHONPATH=. python scripts/run_graph_grounded_benchmark.py`. The output in `results/latest.json` records the fixture and case SHA-256 hashes.

Both systems answer the same questions under the same scoring. The baseline is the existing literature-only path: one `HYBRID` `RetrievalEngine` search over the raw question, answering from the top 3 lexically matched documents.

| Metric | Literature-only baseline (`085b`) | Graph-grounded pilot |
|---|---|---|
| State accuracy | 0.2143 | 1.0 |
| Answer/abstain decision accuracy | 0.5714 | 1.0 |
| Mean citation precision | 0.0714 | 1.0 |
| Mean citation recall | 0.2143 | 1.0 |
| Unsupported citations (total) | 38 | 0 |
| Abstention recall (6 abstain cases) | 0.0 | 1.0 |
| Conflict retention (2 conflict cases) | 0.0 | 1.0 |
| Median latency (in-memory, this container) | ≈0.25–0.29 ms | ≈0.55 ms |
| Provider calls / cost | 0 / $0 | 0 / $0 |

**How to read these numbers.** The expected labels were derived from the same fixture the graph path reads, so the pilot's 1.0 scores are **circular by construction**. They show that the safeguards are wired correctly and enforced on identical inputs. They are **not** an estimate of accuracy on real orchid literature.
- The baseline's low scores mostly reflect two things: it has no abstention or conflict state, and it inherits the lexical-matching weakness in §3.6.
- State accuracy is partly unreachable for the baseline, which can only output `CANDIDATE` or `INSUFFICIENT_EVIDENCE`. The answer/abstain metric is the fairer comparison.
- Latency differences are sub-millisecond in-memory figures and say nothing about PostgreSQL latency.
- **No LLM baseline was run.** NO-API mode and the minimal-spend constraint apply, and no comparison model is wired into the benchmark.

**Not covered:**
- reverse identification ("which taxon has these traits"), which remains the Matrix lane;
- implicit conflict detection (incompatible values with no declared link);
- multi-hop reasoning;
- real-data accuracy.

## 7. Success-criterion verdict

- **Evidence traceability: demonstrated** on a synthetic fixture. Every emitted claim cites an anchored, hash-bearing source. Unsupported citations went from 38 to 0 on identical inputs, and conflicts are retained.
- **Scientific safeguards: preserved and strengthened.** Synonym resolution is recorded, abstention is enforced, locality is withheld, and the whole path is read-only.
- **Accuracy on real orchid science: not demonstrated.** This is blocked; see §9.
- **Computational efficiency: no change.** The pilot needs no GPU, model or new database. The added in-memory cost is under 1 ms per question on this fixture; PostgreSQL latency was not measured.

## 8. Deployment and rollback plan

This PR deploys nothing. The pilot has no route, no scheduler hook, no migration and no configuration flag. Removing it means deleting the added files; there is no data or state to clean up.

Proposed activation sequence. Each step is a separate PR and the gates are as stated.
1. **Payload contract (Lane 1/KG, owner/scientific review).** The contract itself is now defined: `oc-claim-provenance-v1` (`runtime/knowledge_graph/claim_provenance.py`, see `docs/architecture/CLAIM-PROVENANCE-CONTRACT.md`), and the pilot reads only that key. What remains is for the governed publishers (#901, 088c) to emit it, and for the pilot to also read the 088c `qualified_assertion` two-hop shape. Until then, real graph edges are `SOURCE_UNDECLARED` and the pilot abstains on them. That is the safe failure mode.
2. **Registry→graph key mapping.** The verified, fail-closed name mapping is now `runtime/knowledge_graph/canonical_graph_mapping.py` (see `docs/architecture/TAXON-GRAPH-MAPPING.md`). What remains is to run it against a real `oc_graph.kg_nodes` taxon export and review its ambiguous links.
3. **Read-only internal route** behind existing authentication and a default-off flag (`CALYX_GRAPH_GROUNDED_PILOT=0`), with read-only DB credentials. **Rollback:** turn the flag off or revert the route PR; nothing persists.
4. **Expert-reviewed orchid gold set** (Brain OC-EVALS-001; backend #1182): licensed sources, held-out by source and taxon, adjudicator disagreements kept. Re-run the same harness against a disposable PostgreSQL snapshot.
5. **Optional model-backed composer**, only after step 4. It must implement `Composer`, passes through the unchanged validator, and its provider calls and cost are measured by the harness. Owner spending approval is required.

Merging to `main`, production deployment, any graph or taxonomy activation, and any spending remain owner-gated.

## 9. Unresolved blockers

| Blocker | Who or what can resolve it |
|---|---|
| No expert-reviewed orchid QA set, so real accuracy cannot be measured | Owner/scientific reviewers; Brain OC-EVALS-001 gold-set direction (backend #1182) |
| Production graph assertions do not carry the source/assertion/conflict payload the packet consumes (the repo report describes a taxonomy-only graph) | KG publication lane (#901, 088c publisher), with scientific review |
| No verified registry-ID → `oc_graph` taxon-key mapping | #1810 taxon-resolution contracts, or a canonical taxon source key |
| Live PostgreSQL latency and fan-out not measured | Disposable PostgreSQL loaded with a sanitized snapshot; no production access is needed |
| Paper Supporting Information (prompts, schema) not read | Low priority; it does not affect the pilot |

## 10. Relationship Impact Assessment (KO-0002 / GRAPH-001)

- **Relationships read:** one-hop outgoing edges of one accepted taxon node.
- **Relationships created or changed:** none.
- **Evidence-state distinctions preserved:**
  - supported (anchored and reviewed) vs. review-required (unreviewed or unverified);
  - contradicted (declared conflict, both sides kept);
  - unknown / not ingested (`NO_GRAPH_EVIDENCE_FOR_FACET`, `FOCAL_TAXON_NODE_NOT_IN_GRAPH`);
  - source undeclared vs. anchor unavailable;
  - withheld (sensitive locality).
- Missing data is reported as a gap, never as biological absence.
- **Inference:** none beyond restating packet items. The composer adds no knowledge, and confidence is not expressed as a probability.
