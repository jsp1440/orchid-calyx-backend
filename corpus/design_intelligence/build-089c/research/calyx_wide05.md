# Calyx Wide-Exploration Report — Facet wide05

**Facet:** Document AI & Scientific-Reasoning-Extraction Technology Landscape
**Agent date:** 2026-07-21 · **Searches:** 12 batches / ~35 independent queries + 8 official repo/doc pages opened (GROBID, Docling, Marker, MinerU, gnfinder, ScienceParse, CERMINE, ParsCit, anystyle, pymupdf4llm)
**Confidence tags:** [HIGH] = verified this session via official source or benchmark; [MED] = consistent secondary evidence or well-established fact not re-verified; [LOW] = single weak source / inference.

---

## Facet: Document AI & Reasoning Extraction

### Key Findings

1. **The 2024–2026 PDF→structure landscape has bifurcated into (a) deterministic pipeline tools and (b) end-to-end VLMs — and for faithful corpus-scale extraction of theses, pipelines + hybrid LLM assist are the defensible choice.** The olmOCR paper frames the split: pipeline systems (GROBID, MinerU, Marker, VILA, PaperMage) chain specialized ML components; end-to-end models (Nougat, GOT-OCR, GPT-4o) map page images → text, which is powerful but expensive ("converting a million pages using GPT-4o can cost over $6,200") and hallucination-prone [^10^]. OmniDocBench (CVPR 2025) corroborates: pipeline tool MinerU leads on English text edit distance (0.061) vs Nougat (0.365) and GPT-4o (0.144) [^8^] [HIGH].

2. **Long-document (200+ page dissertation) handling is a known weak point, but 2025–2026 releases directly target it.** MinerU 3.0 (2026-03) added "a sliding-window mechanism, significantly reducing peak memory usage in long-document scenarios, so documents with tens of thousands of pages no longer need to be split manually" plus streaming writes and multi-threaded inference [^7^]. Marker's own troubleshooting still recommends splitting long PDFs on OOM [^6^]. READoc v2 added a Zenodo subset (1,343 docs, "many exceeding 30 pages… posters, reports, **theses**, and books… 27 languages") specifically to stress long documents; its central finding: **hierarchical Table-of-Contents tree construction is the largest cross-system weakness** (pipeline tools drop ~22 TEDS points from heading-concat to ToC-tree scores), while reading order is nearly solved (Tesseract baseline already ~97 token-level Kendall-tau similarity) [^11^][^12^] [HIGH].

3. **GROBID remains the citation/metadata workhorse and its 2025–2026 numbers are production-grade.** Official docs: header extraction ~36 PDF/s; full processing ~2.5 PDF/s on 8 threads; "complete fulltext processing at around 10.6 PDF per second (around 915,000 PDF per day)… 11.3M PDF were processed in 6 days by 2 servers without crash" [^2^]. Reference extraction ≈0.87 F1 (PMC 1943 PDFs, 90,125 refs; ~0.90 on bioRxiv set, Deep Learning models); reference parsing in isolation >0.90 F1 instance-level; citation-context resolution 0.76–0.91 F1; DOI/PMID resolution >0.95 F1 after consolidation [^3^]. Used in production by OpenAlex, Semantic Scholar, ResearchGate, HAL, scite.ai, CERN [^4^] [HIGH].

4. **Bibliographic consolidation is a solved engineering pattern with two viable backends; OpenAlex is now the pragmatic primary.** GROBID consolidation gives "+.12 to .13 in F1-score" on header fields and resolves references via Crossref REST API (default; ~25 queries/s rate limit, mailto required) or self-hosted biblio-glutton (Elasticsearch-backed, scales to several PDF/s, adds PubMed/PMC/ISTEX/Unpaywall OA-URL) [^5^]. A 2025 patent-citations study used OpenAlex as primary consolidator (title search w/ relevance-score ≥600 threshold, else metadata permutation search) with Crossref/GROBID fallback; manual validation: title matches 70→96% correct across relevance quartiles, metadata matches 99/100 correct [^29^]. OpenAlex reference coverage for 2015–2022 shared-corpus records is comparable to WoS/Scopus [^28^] [HIGH].

5. **Marker is the speed/quality sweet spot for born-digital scientific PDFs; Docling is the license/enterprise sweet spot; MinerU is the accuracy ceiling (esp. CJK/scanned/complex layout) — all three are viable Calyx parsers, none handles thesis chapter semantics natively.** Marker: pipeline of surya/texify models, benchmark LLM-judge 4.24 vs Docling 3.70, llamaparse 3.98, mathpix 4.16; single-page 0.18 s/page; "projected throughput is 122 pages per second on an H100"; FinTabNet table alignment 0.816 (0.907 with `--use_llm`) [^6^]. Docling (IBM, LF AI & Data): MIT license, DocLayNet RT-DETR layout model + TableFormer, qpdf-based `docling-parse` backend, fully local/air-gapped, ~1–4 s/page CPU [^9^]. MinerU 3.x: OmniDocBench v1.6 hybrid 95.39 / pipeline 86.2; CPU-capable pipeline backend; 109-language OCR (PP-OCRv6) [^7^]. None natively models "Chapter 3" semantics — sectioning must be layered on via TOC/bookmarks + heading detection (Marker emits `table_of_contents` metadata and `section_hierarchy`; Docling emits group/section hierarchy; pymupdf4llm has explicit `TocHeaders`) [^6^][^9^][^13^] [HIGH].

6. **Legacy scholarly-parsing tools are effectively end-of-life; do not build on them.** Science Parse (AllenAI): v3.0.0, superseded by SPv2, no recent development [^30^]. CERMINE: AGPL-3.0, current release 1.13 (2018-era) [^31^]. ParsCit: "While we continue to partially support the codebase, we highly recommend you to use our neural version… Neural-ParsCit" [^32^]. Camelot table extraction: successor fork `pypdf_table_extraction` **archived Apr 11, 2025, read-only**; Camelot remains heuristic (Stream/Lattice/Network/Hybrid) and digital-PDF-only [^33^]. anystyle (BSD, Ruby): maintained at low intensity (copyright 2011–2023), still unique in being **user-trainable** (`anystyle train`) — relevant for thesis bibliographies with idiosyncratic styles [^34^] [HIGH].

7. **Biodiversity entity extraction has a mature, fast, purpose-built stack: gnfinder → gnverifier → GBIF/POWO/WFO/IPNI.** gnfinder (Go binary, REST API, Docker): "able to process 15 million pages per hour" on a laptop; 50M pages in ~3h on 40 threads; detects nomenclatural annotations (`sp. nov.`, `comb. nov.`, `nom. nov.`); optional verification against many name authorities via gnverifier [^17^]. Independent evaluation on Dryad-linked publications: **F1 0.86 (P 0.91, R 0.82)**; weaknesses: irregular abbreviations, unexpected capitalization [^18^]. BHL re-indexed 58M+ pages with gnfinder (name detection 35 days → 5 hours) [^19^]. Resolution: GBIF `name_backbone`/species-match returns matchType EXACT/FUZZY/HIGHERRANK/NONE + confidence + full higher taxonomy [^20^]; POWO exposes a public API (`https://powo.science.kew.org/api/2/search`, no key, rate-limited, backed by WCVP+IPNI) and IPNI the nomenclatural layer; WFO is the accepted-name anchor for vascular plants [^21^] [HIGH].

8. **For taxonomic treatments and specimen data, the Plazi stack is the reference implementation — highly relevant to monographic theses.** GoldenGATE Imagine + TreatmentBank liberate treatments, figures, and **material citations** from PDFs into TaxonX/TaxPub XML, mint DataCite DOIs via the Biodiversity Literature Repository (Zenodo), and export Darwin Core Archives to GBIF; a dedicated "MaterialCitation" Darwin Core term now distinguishes specimen citations in literature; taxonomic hierarchy attached from Catalogue of Life or GBIF backbone [^22^]. Morphological character/trait extraction from descriptions: CharaParser reaches "85 to over 90% precision and recall" (FNA set P/R 91%/90%; Treatise invertebrates 80%/87%) and powers the ETC toolkit (Text Capture, Matrix Generation, Key Generation); caveat: CharaParser+EQ "not maintained at this time" [^23^][^24^]. MicroPIE covers prokaryote-style physiological traits [^25^] [HIGH].

9. **Reasoning-category extraction is uneven: hedging/uncertainty and claim/evidence are well-tooled; assumptions, alternative explanations, and speculation-vs-hypothesis distinctions are thin.** Hedging: BioScope corpus (>10% of sentences negated or hedged; Conclusions sections significantly more speculative) [^36^]; CoNLL-2010 shared task established cue+scope detection [^37^]; SciBERT fine-tunes beat BioBERT on the biological subcorpus [^38^]; hedge cues are "high-precision markers of uncertainty, though… highly domain-dependent" [^39^]. Certainty as a graded construct: Rubin's certainty framework/corpus and sentence+aspect-level certainty modeling in science communication (Pei & Jurgens) [^40^][^41^]. Claims/evidence: 2025 LLM argument-mining survey documents claim detection, evidence detection, and relation classification as mature subtasks, with LLM-synthesized supervision now outperforming few-shot fine-tuning for some AM tasks [^42^]. Reasoning-chain extraction (implicit assumptions/inferences) is frontier: ARCHE (2026) benchmarks "extracting latent reasoning chains from scientific papers… revealing the limitations of current LLMs" [^46^] [HIGH/MED].

10. **Fine-tuned small models still beat zero/few-shot LLMs on precise span-level tasks; LLMs win where schemas evolve or no training data exists — so route by category.** Hinglish NER: fine-tuned HingBERT F1 79.7 vs Gemini zero-shot 62.2 [^49^]. Clinical NER on-prem: fine-tuned BioGottBERT F1 0.84 vs GLiNER zero-shot 0.45–0.66 and Mistral-Nemo worse, "zero-shot models… essentially incapable of capturing subtle variations… particularly complex negation forms" [^50^]. Controlled comparison: BERT-base 277 samples/s vs Gemma-2-2B 12 samples/s (~20× throughput), while zero-shot LLM wins by default with zero training data and when categories change frequently [^51^]. Taxonomic NER: "LLMs often do not outperform smaller, task-specific models like BERT when it comes to precise entity annotation"; context-span-then-locate prompting closes much of the gap [^52^] [HIGH].

11. **Structured-output reliability is solved at the syntax layer (constrained decoding), not at the semantics layer.** "Constrained decoding has become the de facto standard, adopted by both proprietary LLM providers and open-source infrastructures" (vLLM, SGLang, XGrammar, Outlines, LM Format Enforcer; JSONSchemaBench: 10,000 real schemas) [^53^]. Failure mode measured: "NAIVE prompting yields 0% output accuracy despite substantial task accuracy" on 7–9B models; constrained decoding guarantees validity "but introduces large latency overhead and, in several settings, reduces task performance" [^54^]. SLOT post-processor: fine-tuned Mistral-7B + constrained decoding hits 99.5% schema accuracy, 94.0% content similarity [^55^]. Practical pattern: JSON-schema/GBNF constraint + Pydantic validation + retry; >95% first-attempt pass with tuned prompts [^56^]. **Syntax validity ≠ extraction truth: span-anchored verification against the parsed document is still required for hallucination control** [^53^][^54^] [HIGH].

12. **Cost/latency at thesis-corpus scale favors CPU-classical or GPU-pipeline parsing + selective LLM passes.** Reference points: GROBID 10.6 PDF/s full-text on one 16-CPU server [^2^]; Marker ~25–122 pages/s H100-class [^6^]; MinerU pipeline backend runs pure-CPU [^7^]; olmOCR "<$176 per million PDF pages" vs "> $6,200" GPT-4o per million pages [^10^]; Gemini Batch ≈ "$1 for 6,000 pages" for LLM-grade OCR/conversion [^14^]; one 200k-PDF project benchmarked GROBID/MinerU/Marker and chose Marker on a single RTX 4090 (6 workers), with optional GPT-4o-assisted accuracy pass + human audits [^15^]. A 500-thesis × 250-page corpus ≈ 125k pages: ~3.5 h on one GROBID server, ~0.5–1.5 h on one H100 with Marker — parsing is cheap; LLM reasoning passes are the cost driver, so scope them to classified sections [HIGH].

13. **Knowledge-graph targets exist and are compatible with per-claim provenance — nanopublications fit Calyx's "extract reasoning with evidence" goal better than a flat triple store.** Nanopublication = assertion graph + provenance graph + publication-info graph, signed with a trusty URI (hash-in-identifier); convention: one atomic citable claim per nanopub; provenance graph carries evidence (e.g., ECO evidence classes) [^47^]. ORKG models research contributions as semantic entities/relations with comparison tooling (ORKG-Leaderboards >90% F1 on task-dataset-metric extraction) [^44^][^45^]. Parser coordinate outputs (GROBID TEI coords; Marker/Docling bounding boxes + section hierarchy) make page/section-level provenance directly attachable [^3^][^6^][^9^] [HIGH].

14. **Citations inside theses need GROBID + tolerance for non-DOI long-tail literature.** Floras, herbarium monographs, and 19th/20th-century works often lack DOIs; Crossref reports 71% of deposited references arrive without DOIs and uses Search-Based Matching with Validation (SBMV F1 0.966) — the same two-stage (candidate retrieval → field-similarity validation) pattern Calyx should implement against OpenAlex/Crossref/biblio-glutton [^26^][^27^]. Citation-context extraction (0.76–0.91 F1) and citation-intent classification (SciCite 3-class; ACL-ARC 6-class; cloze-prompting and multi-dataset fine-tuning variants) enable "why cited" signals; argumentative-zoning labels are being reused for citation recommendation [^43^] [HIGH/MED].

---

### Tool Profiles

#### PDF → structure / text

| Tool | Function | License | Maturity | Strengths | Weaknesses | Throughput | Integration potential |
|---|---|---|---|---|---|---|---|
| **GROBID** (v0.8.x, INRIA) | PDF → TEI XML: header, full text w/ section markup, references, coordinates; consolidation to Crossref/biblio-glutton; trainable (CRF+DeLFT DL) | Apache 2.0 [MED] | Very high; prod at OpenAlex/S2/HAL/CERN [^4^] | Best-in-class refs+sections (DocBank benchmark context); citation contexts; coordinates; CPU-only; fine-tunable with thesis training data | Struggles w/ non-article layouts (title pages, front/back matter), no chapter/TOC model, OCR not built-in | 10.6 PDF/s full-text; 36 PDF/s header [^2^] | **Primary citation + section layer**; REST service, Docker, batch CLI |
| **Docling** (IBM / LF AI & Data) | Multi-format → unified JSON/Markdown; DocLayNet layout model (RT-DETR) + TableFormer; `docling-parse` qpdf backend; optional VLM (GraniteDocling); chunking for RAG | **MIT** (verbatim: "The Docling codebase is under MIT license") [^9^] | High, fast-growing (10k stars in a month post-release) [^9^] | Permissive license, air-gapped/local, provenance (page+bbox per item), reading-order robust, table structure good | Metadata/reference extraction "coming soon" per tech report [^9^]; slow on CPU (~1–4 s/page) [^14^]; GPU needs 4–8 GB | ~65 s / 50-page doc CPU (indep.) [^14^] | **Structure+provenance layer**; Python lib; pairs with GROBID for refs |
| **Marker** (datalab-to) | PDF → MD/JSON/HTML; surya (layout/OCR) + texify (equations) pipeline; optional `--use_llm` hybrid; structured-extraction beta; TOC + section_hierarchy in JSON | **GPL-3.0 code** + model weights "modified AI Pubs Open Rail-M license… free for research, personal use, and for startups under $2M in funding/revenue" [^6^] | High, very active (v1.10.x, 2026) | Best speed/quality ratio (LLM-judge 4.24; FinTabNet 0.816→0.907 w/ LLM); inline equations→LaTeX; TOC metadata | License friction for commercial use; suggests manually splitting very long PDFs on OOM [^6^]; heuristic tables trail MinerU (OmniDocBench table TEDS 0.57 vs 0.78) [^8^] | 0.18 s/page single; "projected… 122 pages per second on an H100" [^6^] | **Fast layout parser for born-digital theses**; Python/CLI/server |
| **MinerU / MinerU 2.5-3.x** (OpenDataLab) | PDF → MD/JSON; pipeline backend (layout+OCR+formula+table) or 1.2B VLM (MinerU2.5-Pro) w/ hybrid modes | **"MinerU Open Source License", Apache-2.0-based custom** (from AGPLv3 as of v3.1.0, 2026-04-18) — verify terms before redistribution [^7^] | Very high, extremely active; OmniDocBench pipeline leader | Best accuracy ceiling (OmniDocBench v1.6: hybrid 95.39, pipeline 86.2) [^7^]; 109-lang OCR (PP-OCRv6); sliding-window long-doc mode ("tens of thousands of pages no longer need to be split") [^7^]; CPU-capable pipeline | VLM mode needs GPU; throughput lower than Marker (READoc: 214.9 s/doc vs Marker 27.7 s/doc) [^12^]; custom license | Varies; pipeline CPU-slow, GPU ~seconds/page | **Accuracy-first parser** esp. scanned/CJK/complex theses; API + local |
| **olmOCR / olmOCR 2** (AllenAI) | VLM (Qwen2-VL-7B fine-tune) + document-anchoring PDF→text, training data + eval open | Apache 2.0 [MED] | High (2025) | Cheap LLM-grade conversion at scale (<$176/M pages) [^10^]; strong on old/dirty scans; silver-data methodology (GPT-4o-anchored) reusable | Hallucination risk of generative OCR; needs GPU; no semantic sectioning | 5–8× cheaper than frontier APIs [^10^] | Batch OCR/conversion layer for scanned theses |
| **Nougat** (Meta) | End-to-end academic PDF→Markdown (Donut-style) | MIT code [MED] | Low-maintenance; superseded | Equations; single-model simplicity | Documented repetition/hallucination loops on long docs [^16^]; weakest reading order in OmniDocBench (0.365 EN text edit dist) [^8^]; | ~slow GPU | Not recommended for 200+ pp theses |
| **pymupdf4llm** | PyMuPDF wrapper → LLM-friendly MD; `TocHeaders` class for TOC-based heading extraction; images, tables, chunks | **AGPL-3.0** (verbatim: "GNU Affero General Public License v3.0 (AGPL)") [^13^] | High, maintained 2026 | Extremely fast (pure text extraction); TOC utilities; simple integration | Text-based only (no OCR); no layout ML; ranked below MinerU/Marker on READoc [^11^]; AGPL | ~real-time | Quick first-pass text/TOC extraction; pre-filter before heavy parsing |
| **unstructured.io** | Multi-format partitioning → elements; hi-res layout models; RAG chunking | Apache 2.0 (core) [^14^] | High, commercial backing | Broad format support; pipeline ecosystem; API | Below Docling/Marker on independent structure benchmarks (TEDS/GRITS) [^14^]; slow hi-res mode | ~25 s/doc (indep.) [^14^] | Optional; useful for non-PDF (docx/html) theses |
| **CERMINE** | PDF → NLM JATS XML | AGPL-3.0 [^31^] | Stale (v1.13, 2018-era) | JVM; JATS output | Superseded | ~ | Legacy only |
| **Science Parse** (AllenAI) | Metadata+refs from PDF | Apache 2.0 [MED] | End-of-life (v3.0.0, SPv2 also stale) [^30^] | — | Unmaintained | — | Avoid |
| **pdfact** | Layout-aware text/structure extraction (TU Dortmund) | Apache 2.0 [MED] | Low activity | Logical structure units | Small community | — | Optional experimental |

#### References / citations

| Tool | Function | License | Notes |
|---|---|---|---|
| **GROBID refs + consolidation** | ref segmentation/parsing + DOI/PMID/OpenAlex resolution | Apache 2.0 | 0.87–0.90 F1 ref extraction; +0.12–0.13 F1 w/ consolidation; >0.95 F1 DOI resolution; biblio-glutton for scale [^3^][^5^] |
| **biblio-glutton** | High-throughput biblio lookup (Crossref+PubMed+ISTEX+Unpaywall) | Apache 2.0 [MED] | Elasticsearch-backed; "several PDF per second" end-to-end [^5^] |
| **Neural-ParsCit** | Neural citation parser (ParsCit successor) | open (repo) | Officially recommended over ParsCit [^32^]; still aging |
| **anystyle** | CRF citation parser/finder, **trainable** (`anystyle train my-model.mod`) | **BSD-style** (verbatim) [^34^] | Ruby gem + web app; unique user-training hook for thesis reference styles; low-intensity maintenance (2011–2023) [^34^] |
| **Camelot / Tabula** | Heuristic table extraction | MIT | Camelot successor fork **archived read-only 2025-04-11** [^33^]; digital-only, cell-merging heuristics — superseded by TableFormer/surya/VLM approaches |

#### Biodiversity / taxonomy

| Tool | Function | License | Maturity | Notes |
|---|---|---|---|---|
| **gnfinder** | Taxonomic name detection (Latin + vernacular), `sp. nov.`/`comb. nov.` annotation, REST/gRPC/CLI/Docker | open (Go; MIT-family) [MED] | High; BHL production [^19^] | F1 0.86 (P .91/R .82) [^18^]; 15M pages/h [^17^]; feeds gnverifier |
| **gnverifier** | Name verification vs 100+ authorities (GBIF, IPNI, POWO/WCVP, CoL…) | open | High | Returns matched name + classification + data-source [^17^] |
| **TaxonFinder / NetiNeti** | Legacy name finders | open | End-of-life | Superseded by gnfinder (its own lineage) [^18^] |
| **GBIF species match API** | Name → backbone taxon (EXACT/FUZZY/HIGHERRANK/NONE + confidence) | CC0 data, open API | Very high | No key; rate limits; returns usageKey + full classification [^20^] |
| **POWO API** (`/api/2/search`) | Accepted-name + distribution lookup for plants (WCVP backbone) | Public, no key, rate-limited (Kew terms; attribution required) [^21^] | High | Orchid names anchor; pair w/ **IPNI** (nomenclature/publication) and **WFO** (consensus classification) [^21^] |
| **Plazi GoldenGATE + TreatmentBank** | Treatment/material-citation extraction, TaxonX/TaxPub XML, DOIs, DwC-A→GBIF | open/CC-BY outputs | Very high; community standard | The reference pipeline for monograph/treatment chapters in theses [^22^] |
| **CharaParser / ETC** | Morphological character → structured (entity, quality) matrices | open (BSD-family) | Medium (CharaParser+EQ "not maintained at this time" [^24^]) | P/R 85–90%+ on flora sets [^23^]; direct fit for orchid descriptions |
| **MicroPIE** | Trait extraction (prokaryote-style) | open | Medium | Method template for sentence-level trait IE [^25^] |

---

### Reasoning-Category → Method Map

Methods: **C** = classical/fine-tuned small model; **L** = LLM zero/few-shot; **H** = hybrid recommended. Evidence strength graded per category.

| # | Category | Best current approach | Key evidence & tools | Confidence |
|---|---|---|---|---|
| 1 | **Observations** | **H**: sentence-level rhetorical/scientific-discourse classifier (fine-tuned SciBERT/DeBERTa on AZ-type labels; FACT class of de Waard taxonomy) + LLM fallback; for taxon occurrence observations, Plazi material-citation extraction (C) | AZ lineage (Teufel & Moens 1999) → MuLMS-AZ (CODI 2023) and hierarchical rhetorical-role labeling models (2026) show AZ still actively used/extended [^57^][^58^]; material citations → GBIF DwC [^22^] | [HIGH] methods exist; [MED] on thesis-domain transfer |
| 2 | **Measurements** | **C/H**: grobid-quantities (3-stage CRF cascade: quantities → units → values, SI normalization) [^35^]; CharaParser measurement extraction for morphology [^23^]; LLM with unit-constraint validation as cross-check | grobid-quantities used in materials IE (STEREO) [^35^]; CharaParser P/R 85–90%+ [^23^] | [HIGH] |
| 3 | **Experimental evidence** | **H**: claim–evidence argument mining (evidence detection + support/attack relation classification); fine-tuned models for volume, LLM for schema evolution | 2025 LLM-AM survey: claim detection, evidence detection, argument component/relation classification are established subtasks; LLM-synthesized supervision now competitive [^42^]; open-LLM AM evaluation shows mixed zero-shot results → fine-tune for stability [^59^] | [HIGH] |
| 4 | **Author interpretations** | **H**: discourse-role classification separating RESULT vs INTERPRETATION sentences (de Waard GOAL/FACT/HYPOTHESIS; AZ CONTRAST/BASIS/OTHER) + LLM span extraction with section context | Discourse taxonomies + hierarchical models [^57^][^58^]; Sci-Arg-style claim extraction ~0.79–0.84 F1 (orchestrator context) | [MED] |
| 5 | **Assumptions** | **L**: few-shot LLM extraction + human review; no mature dedicated corpus | ARCHE (2026): latent-reasoning-chain extraction "revealing the limitations of current LLMs" [^46^]; assumption extraction appears in reasoning-chain tasks (ARQ/Sci-QA line) | [LOW–MED] — one of 3 riskiest |
| 6 | **Hypotheses** | **H**: AIM-zone classification + hypothesis-cue patterns; LLM extraction of hypothesis statements w/ evidence links; hypothesis-generation benchmarks exist (detection weaker than generation) | AZ AIM class [^57^]; hypothesis-generation/validation survey (2026) lists standardized hypothesis benchmarks emerging [^60^]; de Waard HYPOTHESIS class | [MED] |
| 7 | **Inferences** | **H**: argument-relation classification (support/attack between sentences/claims) + LLM rationale extraction; implicit-inference linking is hard | AM relation classification mature at component level [^42^]; cross-sentence/cross-section inference chains → ARCHE gap [^46^] | [MED] |
| 8 | **Alternative explanations** | **L**: LLM extraction keyed on contrast/discourse markers + AZ CONTRAST class; thin dedicated tooling | AZ CONTRAST/BASIS classes [^57^]; epistemic-stance detection handles contrastive commitments [^61^] | [LOW–MED] — riskiest tier |
| 9 | **Predictions** | **H**: future-tense/modal + "we predict/expect" cue detection + hedging classifier; LLM structured extraction w/ falsifiability fields | Hedge/modal cue machinery (BioScope/CoNLL-2010) [^36^][^37^]; certainty scoring [^40^][^41^] | [MED] |
| 10 | **Recommendations** | **H**: sentence classification (conclusion/recommendation classes; "should/ought/implications" cues) + LLM normalization into (action, target, strength) | Discourse classification literature [^57^][^58^]; LLM structured outputs reliable at syntax layer [^53^] | [MED] |
| 11 | **Limitations** | **H**: limitation-section detection + sentence classifier ("limitation", "caveat", "shortcoming"); hedging overlap; LLM extraction w/ span anchoring | Hedging/uncertainty stack [^36^][^37^][^38^]; rhetorical-role models label weakness/contrast moves [^58^] | [MED] |
| 12 | **Uncertainty / hedging** | **C**: fine-tuned SciBERT/DeBERTa on BioScope + domain data, cue+scope; calibrate certainty (Rubin framework; sentence+aspect-level) | BioScope: >10% sentences hedged/negated; Conclusions more speculative [^36^]; CoNLL-2010 cue/scope task [^37^]; SciBERT > BioBERT on BioScope biological subcorpus [^38^]; cues "high-precision… highly domain-dependent" [^39^]; certainty corpora [^40^][^41^] | [HIGH] — most mature category |
| 13 | **Speculation** | **C**: speculation-cue detection + **scope resolution** (which proposition is speculative) — treat as distinct from mere hedge presence; separate speculation from hypothesis/opinion via context classifiers | CoNLL-2010 scope subtask [^37^]; BioScope scope annotations [^36^]; speculation-vs-fact separation motivated original BioScope IE work [^36^] | [HIGH] for detection, [MED] for scope in theses |
| 14 | **Opinion** | **C/H**: epistemic stance / subjectivity classification (RoBERTa-based stance models proven strong); author-vs-other attribution (who holds the belief) | Blodgett et al. 2022: simple RoBERTa multi-source stance model outperformed more complex SOTA [^61^]; subjectivity/objectivity + factuality literature (Saurí & Pustejovsky; Rubin) [^40^] | [MED] |

**Cross-cutting pattern:** for every category, store (a) verbatim span, (b) page/section coordinates from the parser (GROBID TEI coords; Docling/Marker bbox+section_hierarchy [^3^][^6^][^9^]), (c) category confidence, (d) hedging/certainty score — this makes downstream human audit and KG provenance (nanopub-style) mechanical rather than aspirational [^47^].

### Taxonomy/Biodiversity Extraction Stack (recommended Calyx configuration)

```
PDF ──► parser (Marker/MinerU/GROBID hybrid)
  ├─► Taxon names: gnfinder (15M pp/h; F1 0.86; sp. nov./comb. nov. flags) [^17^][^18^]
  │     └─► verify: gnverifier ──► resolve:
  │           ├─ GBIF species match (usageKey, matchType EXACT/FUZZY/HIGHERRANK, confidence) [^20^]
  │           ├─ POWO api/2 (accepted name, distribution; WCVP backbone) [^21^]
  │           ├─ IPNI (nomenclatural act, protologue) / WFO (consensus classification) [^21^]
  │           └─ conflict log when backbones disagree (accepted vs synonym)
  ├─► Treatments & specimens (monograph chapters):
  │     ├─ Plazi-style: GoldenGATE → TaxonX/TaxPub XML → TreatmentBank → Biodiversity
  │     │   Literature Repository (DataCite DOIs) → DwC-A → GBIF [^22^]
  │     └─ material citations → specimen/occurrence records (institution codes, barcodes,
  │         coordinates, collectors) → GBIF occurrence linking [^22^]
  ├─► Morphology: CharaParser/ETC-style character extraction
  │     (entity–quality pairs, measurement values; P/R 85–90%+ on floras) [^23^][^24^]
  └─► Names-in-collections cross-check: BHL name services (gnfinder-indexed 58M+ pp) [^19^]
```

**Notes:** LLM-based taxonomic NER does **not** beat purpose-built tooling — "LLMs often do not outperform smaller, task-specific models like BERT when it comes to precise entity annotation"; if LLMs are used, context-span-then-locate prompting is the strongest pattern [^52^]. gnfinder's known weakness — irregular abbreviations, unexpected capitalization — matters for OCR-degraded scans; keep abbreviation-expansion and OCR-quality gates upstream [^18^]. Multi-backbone reconciliation (GBIF vs POWO vs WFO) should be logged, not silently resolved, since orchid taxonomy is actively disputed at generic boundaries (inference — orchid-specific, [LOW]).

---

### LLM-vs-Classical Trade-off Analysis

| Dimension | Classical / fine-tuned small models | Frontier & open LLMs (zero/few-shot) |
|---|---|---|
| **Span-precise tasks (NER, ref fields, measurements)** | Win on F1 and cost: fine-tuned encoders 0.79–0.84+ vs LLM zero-shot 0.45–0.66 on clinical NER [^50^]; HingBERT 79.7 vs Gemini 62.2 [^49^]; ~20× throughput (BERT 277 vs Gemma-2-2B 12 samples/s) [^51^] | Lose on exact span localization; context-span prompting narrows gap [^52^] |
| **Schema fluidity (14 evolving reasoning categories)** | Retrain per schema change; annotation cost | Win: prompt = schema; categories editable weekly [^51^] |
| **Cold start (no training data)** | Blocked | Win by default [^51^] |
| **Document-scale cost** | GROBID 10.6 PDF/s CPU [^2^]; Marker 25–122 pp/s GPU [^6^]; MinerU pipeline CPU-capable [^7^] | GPT-4o conversion >$6,200/M pages vs olmOCR <$176/M [^10^]; Gemini Batch ~$1/6k pages [^14^] — viable only scoped to classified sections |
| **Faithfulness** | Deterministic: text comes from the PDF; errors are omissions/mislabels, not inventions | Generative hallucination documented (Nougat repetition loops [^16^]); constrained decoding guarantees *syntax*, not *truth* [^53^][^54^] |
| **Structured-output reliability** | Native (CRF tags) | "De facto standard" constrained decoding (vLLM/SGLang/XGrammar/Outlines) [^53^]; naive prompting → 0% output accuracy on some 7–9B models [^54^]; SLOT 99.5% schema accuracy [^55^]; Pydantic-validate+retry >95% first-pass [^56^] |
| **On-prem / sensitive corpora** | All local by default | Llama/Qwen-class on-prem viable; small fine-tuned open models (SLOT-Mistral-7B) near-frontier schema accuracy [^55^]; GraniteDocling-class small VLMs for parsing [^9^] |
| **Reasoning depth (assumptions, alternatives, chains)** | Weak — no corpora | Only option, but ARCHE shows latent-chain extraction still exceeds current LLMs [^46^] |

**Recommended operating point (evidence-backed):** deterministic parse (GROBID refs + Marker/MinerU/Docling layout) → classical section/discourse classification → **scoped LLM passes** (per-section JSON-schema-constrained extraction with span-anchored verification against parser text) → fine-tune small models to replace LLM passes for any category that stabilizes (certainty/hedging first — best corpora). RAG-over-theses: chunk on parser structure (Docling chunker; Marker section_hierarchy; GROBID TEI sections) rather than fixed windows; per-chunk provenance enables claim-level audit [^6^][^9^]. KG emission: nanopublication-per-claim (assertion + provenance + pubinfo, trusty-URI hash) aligns with ORKG-style contribution graphs and keeps every extracted reasoning item traceable to page/span [^47^][^44^].

### Recommended Deep-Dive Areas

1. **Thesis-scale segmentation benchmark (highest priority).** Build a 20–30 thesis gold set (bookmarks + chapter starts + section hierarchy annotated); evaluate GROBID vs Marker vs MinerU vs Docling(+PyMuPDF TOC) hybrids. READoc v2's finding that ToC-tree construction is the universal weak point (~22 TEDS drop) makes this the pipeline's #1 risk [^11^][^12^]. Candidate public assets: READoc-Zenodo (includes theses) [^12^]; ETD-ODv2 long-document layout dataset (Virginia Tech) [^62^]. Also decide chapter semantics: PDF bookmarks fail often in ETDs → need heading-font/pattern model ("Chapter", "CHAPTER 3", numbered headings) + ToC-page alignment as fallback.
2. **Certainty/hedging fine-tune on orchid/botany prose.** SciBERT/DeBERTa on BioScope + ~1k domain sentences; output graded certainty (Rubin 4-level) not binary; evaluate against LLM few-shot baseline; target ≥0.80 F1 cue detection, ≥0.65 scope [^36^][^37^][^38^][^40^].
3. **Taxon-name + treatment extraction on monographic thesis chapters.** gnfinder+gnverifier baseline; measure lift from OCR-quality gating and abbreviation expansion; prototype Plazi GoldenGATE workflow on one monographic thesis (TaxonX XML → DwC-A → GBIF test ingestion); evaluate CharaParser vs LLM extraction on orchid descriptions (character matrix accuracy) [^17^][^22^][^23^].
4. **Reference-resolution harness for non-DOI long tail.** GROBID refs → OpenAlex primary (title+author fuzzy w/ relevance threshold [^29^]) → Crossref SBMV fallback → unmatched queue with anystyle-retrained parser for idiosyncratic styles [^26^][^34^]; measure match rate on 5 thesis bibliographies (expect many 1900s flora/herbarium citations).
5. **Reasoning-chain extraction evaluation.** Annotate ~10 thesis chapters across the 14 categories (double-annotate hedging/speculation/opinion boundaries); benchmark frontier LLM (constrained JSON + span anchors) vs fine-tuned classifiers per category; publish schema aligned to ORKG/nanopub provenance [^46^][^47^].
6. **Throughput/cost validation at scale.** Time 100-thesis batch end-to-end on target hardware (GROBID CPU server + 1 GPU for Marker/MinerU + LLM API budget); confirm the ~$176/M-page on-prem OCR ceiling and Gemini-Batch ~$1/6k-pages external option; set per-category LLM token budgets [^10^][^14^].

---
### Citations / URLs

[^1^] Meuschke et al. 2023 benchmark (DocBank) — orchestrator-provided context (verified there).
[^2^] GROBID documentation, Introduction & benchmarking — https://grobid.readthedocs.io/en/latest/Introduction/
[^3^] GROBID benchmarking results (references F1, citation contexts, consolidation gains) — https://grobid.readthedocs.io/en/latest/Benchmarking/ (figures via readthedocs benchmark pages; PLoS/PMC/bioRxiv sets)
[^4^] GROBID org / "used in production" (OpenAlex, Semantic Scholar, HAL, CERN…) — https://github.com/grobidOrg ; https://github.com/grobidOrg/grobid/blob/master/Readme.md
[^5^] GROBID consolidation (Crossref vs biblio-glutton, 25 q/s, +0.12–0.13 F1) — https://grobid.readthedocs.io/en/latest/Consolidation/
[^6^] Marker repo (GPL+OpenRAIL weights, 122 pp/s H100, benchmark table, TOC metadata, section_hierarchy, `--use_llm`, structured extraction) — https://github.com/datalab-to/marker
[^7^] MinerU repo (v3.x, sliding-window long-doc mode, OmniDocBench 95.39/86.2, license change to MinerU Open Source License 2026-04-18, PP-OCRv6 109 langs) — https://github.com/opendatalab/MinerU
[^8^] OmniDocBench (CVPR 2025) — https://arxiv.org/html/2412.07626v2
[^9^] Docling tech report + repo (MIT license verbatim, DocLayNet/TableFormer, local execution, metadata "coming soon") — https://arxiv.org/html/2501.17887v1 ; https://github.com/docling-project/docling
[^10^] olmOCR paper (pipeline vs end-to-end framing; $6,200 vs $176 per M pages) — https://arxiv.org/abs/2502.18443 (olmOCR, AllenAI)
[^11^] READoc benchmark (long-document parsing; ToC weakness; pymupdf4llm ranking) — https://arxiv.org/abs/2409.05137
[^12^] READoc v2 (OpenReview; Zenodo subset w/ theses; ~22 TEDS ToC drop; Marker 27.74 s/doc vs MinerU 214.94) — https://openreview.net/pdf?id=WbDouroc2O ; https://github.com/icip-cas/READoc
[^13^] pymupdf4llm repo (AGPL-3.0 verbatim; TocHeaders) — https://github.com/pymupdf/pymupdf4llm
[^14^] Independent PDF-parsing benchmark (Docling vs unstructured vs Marker vs MinerU vs Gemini; timings; Gemini Batch $1/6k pages) — https://www.ertas.ai/blog/pdf-parsing-accuracy-benchmark-docling-unstructured ; https://procycons.com/en/blogs/pdf-data-extraction-benchmark/
[^15^] 200k-PDF pipeline case study (GROBID/MinerU/Marker compared; Marker chosen, RTX 4090, 6 workers, GPT-4o spot-checks) — https://openreview.net/pdf/cb89222b0bc910b6256d1dc2c60756373e4912ec.pdf
[^16^] Nougat repetition/hallucination on long docs (LOCR paper) — https://arxiv.org/html/2403.02127v1
[^17^] gnfinder repo (15M pages/h; sp. nov./comb. nov.; gnverifier; REST/gRPC) — https://github.com/gnames/gnfinder
[^18^] GNFinder evaluation (F1 0.86, P 0.91/R 0.82; abbreviation/capitalization weaknesses) — https://biss.pensoft.net/article/90026/ (Thessen et al. 2022, BISS)
[^19^] BHL taxonomic name services w/ gnfinder (58M+ pages; 35 days→5 h) — https://blog.biodiversitylibrary.org/2020/07/bhl-improvestaxonomic-name-services-gnfinder.html
[^20^] GBIF name_backbone match semantics (EXACT/FUZZY/HIGHERRANK/NONE, confidence, classification) — https://www.erikkusch.com/courses/gbif/backbone/ ; API: https://api.gbif.org/v1/species/match
[^21^] POWO public API (`https://powo.science.kew.org/api/2/search`; Kew data terms; WCVP+IPNI backbone) — https://powo.science.kew.org/ ; https://www.kew.org/science/collections-and-resources/data-and-digital/terms-of-use ; WFO: https://www.worldfloraonline.org/ ; IPNI: https://www.ipni.org/
[^22^] Plazi workflow (GoldenGATE, TreatmentBank, material citations, DwC-A→GBIF, BLR/Zenodo DOIs) — https://europeanjournaloftaxonomy.eu/index.php/ejt/article/download/1597/5629 ; https://plazi.org/
[^23^] CharaParser/ETC (85–90%+ P/R; FNA 91/90, Treatise 80/87) — https://pmc.ncbi.nlm.nih.gov/articles/PMC5114841/
[^24^] Arizona Biosemantics tools page ("CharaParser+EQ not maintained at this time") — https://infosci.arizona.edu/biosemantic-research-group
[^25^] MicroPIE — https://doi.org/10.1186/s12859-016-1396-8
[^26^] Crossref reference matching (71% refs w/o DOI; SBMV F1 0.966) — https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/ (matching docs; figures per Crossref documentation)
[^27^] OpenAlex as consolidator for GROBID refs (two-stage; validation 96–100% correct) — https://pmc.ncbi.nlm.nih.gov/articles/PMC12963361/
[^28^] OpenAlex reference-coverage comparability (2015–2022) — https://arxiv.org/html/2401.16359v1
[^29^] OpenAlex title-match validation thresholds (relevance score quartiles) — https://pmc.ncbi.nlm.nih.gov/articles/PMC12963361/
[^30^] Science Parse repo (v3.0.0; SPv2) — https://github.com/allenai/science-parse
[^31^] CERMINE repo (AGPL-3.0; v1.13) — https://github.com/CeON/CERMINE
[^32^] ParsCit repo ("partially supported… highly recommend… Neural-ParsCit"; LGPL) — https://github.com/knmnyn/ParsCit
[^33^] Camelot docs + archived successor fork — https://camelot-py.readthedocs.io/ ; https://github.com/py-pdf/pypdf_table_extraction/issues/210
[^34^] anystyle (BSD-style license verbatim; `anystyle train`; 2011–2023) — https://github.com/inukshuk/anystyle ; https://anystyle.io/
[^35^] grobid-quantities described/used in materials IE (cascade of CRF models, SI normalization) — https://arxiv.org/pdf/2103.14124v1 ; repo: https://github.com/grobidOrg/grobid-quantities
[^36^] BioScope corpus (>10% hedged/negated; Conclusions more speculative) — https://pmc.ncbi.nlm.nih.gov/articles/PMC2586758/
[^37^] CoNLL-2010 shared task (hedge cues + scope) — https://aclanthology.org/W10-3113/
[^38^] BERT uncertainty detection (SciBERT > BioBERT on BioScope biological subcorpus) — https://github.com/PeterZhizhin/BERTUncertaintyDetection
[^39^] Epistemic-rhetorical miscalibration framework (hedge cues "high-precision… highly domain-dependent") — https://arxiv.org/html/2604.19768
[^40^] Rubin certainty framework/corpus (certainty as multi-level construct) — discussion: https://www.researchgate.net/publication/260178341 (Veracity Roadmap citing Rubin 2006/2010)
[^41^] Pei & Jurgens, sentence+aspect-level (un)certainty in science communication — https://ar5iv.labs.arxiv.org/html/2109.14776
[^42^] LLM argument-mining survey (claim/evidence detection, relation classification; LLM-synthesized supervision) — https://arxiv.org/html/2506.16383v3
[^43^] Citation-intent / typed claim networks (SciCite, ACL-ARC; AZ for citation recommendation) — https://arxiv.org/html/2605.30966v1
[^44^] ORKG approach — https://arxiv.org/pdf/2308.12981
[^45^] ORKG-Leaderboards (>90% F1 task-dataset-metric) — https://arxiv.org/abs/2305.11068
[^46^] ARCHE reasoning-chain extraction benchmark (2026; LLM limitations) — cited via https://arxiv.org/pdf/2605.25964
[^47^] Nanopublication model (assertion/provenance/pubinfo; trusty URI; ECO evidence classes) — https://link.springer.com/article/10.1007/s00799-025-00431-x
[^49^] Hinglish NER controlled comparison (fine-tuned 79.7 vs Gemini 62.2) — https://arxiv.org/pdf/2509.02514
[^50^] On-prem clinical NER (BioGottBERT 0.84 vs GLiNER zero-shot 0.45–0.66) — https://www.frontiersin.org/journals/digital-health/articles/10.3389/fdgth.2025.1623922/full
[^51^] "Beating BERT?" controlled study (277 vs 12 samples/s; zero-shot wins w/o training data) — https://alex-jacobs.com/posts/beatingbert/
[^52^] Taxonomic/NER LLM-vs-BERT + context-span prompting (2026) — https://www.scitepress.org/Papers/2026/143026/143026.pdf
[^53^] Structured-output / constrained-decoding survey ("de facto standard"; JSONSchemaBench 10k schemas; vLLM/SGLang/XGrammar/Outlines) — https://arxiv.org/html/2601.17717v3
[^54^] Small-LM structured reliability (naive prompting 0% output accuracy; constrained decoding latency/quality costs) — https://arxiv.org/html/2605.02363v1
[^55^] SLOT (Mistral-7B 99.5% schema accuracy, 94.0% content similarity) — https://arxiv.org/abs/2505.04016
[^56^] Practical structured-output engineering (schema constraint + Pydantic + retry) — practitioner literature, e.g. https://alex-jacobs.com/posts/ and vendor docs [LOW confidence on exact 95% figure — treat as heuristic]
[^57^] Argumentative zoning lineage & MuLMS-AZ (CODI 2023) — https://aclanthology.org/2023.codi-1.1/ [MED]
[^58^] Hierarchical rhetorical-role labeling (2026) — https://arxiv.org/html/2603.03856v1
[^59^] Open-source LLM argument-mining evaluation — https://arxiv.org/html/2411.05639
[^60^] Hypothesis-generation benchmark survey (2026) — https://arxiv.org/html/2604.12243v2
[^61^] Epistemic stance detection (RoBERTa; Blodgett et al. 2022) — https://www.catalyzex.com/author/Ankita%20Gupta (listing); https://aclanthology.org/2022.nlpcss-1.16/ [MED]
[^62^] ETD-ODv2 long-document layout dataset (Virginia Tech) — via curated list https://github.com/qyhou/curated-document-layout-analysis [MED]

**Verbatim license/benchmark excerpts** (as retrieved): Docling — "The Docling codebase is under MIT license." [^9^] · pymupdf4llm — "GNU Affero General Public License v3.0 (AGPL)" [^13^] · Marker — "The weights for the models are licensed under a modified AI Pubs Open Rail-M license… free for research, personal use, and for startups under $2M in funding/revenue" [^6^] · MinerU — "the project is now officially released under the MinerU Open Source License. This is a custom license based on Apache 2.0 with additional conditions" [^7^] · GROBID — "complete fulltext processing at around 10.6 PDF per second (around 915,000 PDF per day)" [^2^] · gnfinder — "able to process 15 million pages per hour" [^17^] · ParsCit — "While we continue to partially support the codebase, we highly recommend you to use our neural version" [^32^] · CharaParser+EQ — "not maintained at this time" [^24^].

*End of report.*
