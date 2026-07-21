# Calyx Deep-Dive dim07 — Document Structure Extraction at Thesis Scale

**Date:** 2026-07-21 · **Basis:** 16+ targeted searches (this session) + wide05 landscape report (12 batches, verified tool/benchmark numbers) + primary sources opened (READoc v1 arXiv HTML, ETD-OD/ETD-ODv2 thesis, GROBID changelog, MinerU LICENSE, ETD-MS v2.0, DataCite linking pattern, CoreSC, TEDS literature).
**Confidence tags:** [HIGH] verified via official repo/paper this session or in wide05; [MED] established/consistent secondary evidence; [LOW] inference or single weak source.

---

## 0. Executive summary

Theses (100–400 pp) are structurally different from journal articles: chapter granularity, front/back matter, heterogeneous heading conventions, frequent **missing or flat PDF bookmarks**, monograph/treatment chapters in taxonomy, and supplementary files shipped *outside* the PDF. No current parser models "Chapter 3" semantics natively [^6^][^9^][^11^]. The defensible architecture is:

1. **PyMuPDF pass** (TOC/bookmarks + font stats + text) as a cheap structural prior.
2. **Docling (MIT)** as the default layout/structure+provenance engine; **MinerU 3.x** (custom Apache-2.0-based license, commercial use allowed below 100M MAU / $20M monthly revenue) as the accuracy-first engine for scanned/complex theses; **Marker** only where its GPL-3.0 code + OpenRAIL-M weights (free for research/startups <$2M) are acceptable [^6^][^7^][^9^].
3. **GROBID 0.8.2 (Apache-2.0)** for references/citations/consolidation (biblio-glutton or Crossref), with its TEI coordinates as a second opinion on section boundaries [^2^][^3^][^20^].
4. A **hybrid chapter-segmentation algorithm** with a 5-level fallback chain (bookmarks → TOC-page alignment → heading classifier → font/pattern rules → LLM over candidate headings).
5. A **15-element mapping layer** combining heading lexicon, fine-tuned sentence classifiers (CoreSC/AZ lineage), and scoped LLM passes — with every element carrying page+bbox provenance in a **custom JSON schema (Docling-style prov)**, exported to TEI/JATS only as an interchange format.

---

## 1. Thesis-scale segmentation: evidence and algorithm

### 1.1 The three recognition routes and their measured behavior

**(a) PDF bookmarks (outline).** Zero-ML, instant via PyMuPDF `doc.get_toc()`. Theses are exactly the genre where bookmarks are unreliable: institutional accessibility mandates ("Bookmarks are created for all first level headings") are recent (WCAG 2.1 AA required for public-institution ETDs only by April 2026) and adoption is patchy; older ETDs, LaTeX-produced PDFs without `hyperref` bookmarks, and scanned theses have none [^17^][^18^] [HIGH on the mandate existence, MED on prevalence]. Expect bookmarks to be present and correct in roughly the majority of post-2015 born-digital theses but flat, truncated, or wrong-titled in a large minority — treat as a *prior*, never ground truth [MED/inference].

**(b) TOC-page parsing.** Nearly universal in theses (institutional format rules require a Table of Contents listing chapters *and appendices* [^16^]). Two concrete implementations: pymupdf4llm's `TocHeaders` (identifies the printed TOC pages and lifts heading candidates) [^13^] and Marker's `table_of_contents`/`section_hierarchy` metadata emitted from its layout model [^6^]. TOC pages give *titles + page numbers*, which must then be resolved to body pages (offset: front matter is usually roman-numbered — align by matching heading text near the target page ±2). Failure modes: multi-page TOCs, dot leaders merged into titles by text extraction, list-of-figures/tables confusion, TOC entries for front matter ("Acknowledgements") polluting the chapter list [MED].

**(c) Font/pattern heading detection.** The layout-model route: Docling's DocLayNet RT-DETR model detects `section-header` items and builds a group/section hierarchy [^9^]; MinerU detects headings with levels [^7^]; Marker detects section hierarchy, and Datalab's production models added explicit "multi-page section hierarchy detection" improvements in late 2025 [^21^]. For ETDs specifically, the only domain-matched training data is **ETD-OD / ETD-ODv2** (Virginia Tech): ~25K pages/200 ETDs/~100K boxes (v1) plus ~20K scanned pages (v2), with a class taxonomy that includes `Chapter Title` (2,211 instances), `Section` (9,337), `Reference Heading` (313), figure/table+captions, metadata fields — trained YOLOv7/Faster-RCNN reach AP@0.5 ≈ 0.86–0.93 for title/author classes on digital documents, dropping to 0.34–0.69 on scanned; captions/paragraphs high, `Algorithm` (96 instances) near floor [^10^] [HIGH]. **This is the only thesis-native layout dataset; use it to fine-tune or at least to sanity-evaluate DocLayNet-family models.**

**(d) READoc v2 — the benchmark warning.** READoc v2's Zenodo subset (1,343 long docs explicitly including **theses**) established that *hierarchical ToC-tree construction is the largest cross-system weakness*: pipeline tools lose **~22 TEDS points** going from heading-concatenation (Concat-EDS) to ToC-tree evaluation (avg decrease on READoc-arXiv = 22.00), while reading order is nearly solved (Tesseract heuristic baseline: 96.70/98.48 token-level Kendall-tau on arXiv/GitHub) [^11^][^12^] [HIGH]. Nougat-base collapses cross-domain (88.50 TEDS arXiv → 37.01 GitHub) [^11^]. Reported per-doc latency: Marker 27.7 s/doc vs MinerU 214.9 s/doc [^12^]. **Implication: single-engine heading hierarchies will silently mis-nest ~1 in 5 heading levels on theses; the hybrid chain below is mandatory, and the gold benchmark (§6) must score tree structure, not just boundary F1.**

### 1.2 Hybrid chapter-segmentation algorithm (fallback chain)

```
Input: thesis PDF
1. PREFLIGHT (PyMuPDF): page count, has-TOC-flag (bookmarks), born-digital vs scanned
   (text-layer coverage), font histogram. ~ms/doc. [^13^]
2. BOOKMARKS: if outline exists with ≥3 entries and ≥1 title matching
   /chapter|introduction|conclusion|references|appendix/i → adopt as skeleton S_b.
3. TOC-PAGE ALIGNMENT: locate printed TOC pages (pymupdf4llm TocHeaders / regex
   "Table of Contents|Contents"); parse entries (title, printed page#); resolve to
   physical pages via roman→arabic offset + fuzzy title match (rapidfuzz ≥85)
   near target page ±2 → skeleton S_t.
4. LAYOUT HEADINGS: run Docling (default) or MinerU (scanned/complex); collect
   section-header items with (text, page, bbox, level); ETD-ODv2-fine-tuned model
   optional upgrade for `Chapter Title` recall [^9^][^10^].
5. PATTERN/FONT RULES: chapter-opener detection — page-top large-font line matching
   /^(chapter|chapitre|kapitel)?\s*(\d+|[IVX]+)\b/ or ALL-CAPS standalone line;
   numbering-scheme inference (decimal "3.2" vs "Chapter 3" vs unnumbered).
6. LLM ARBITRATION (only when 2–5 disagree or coverage <80% of expected chapters):
   send candidate-heading list (≤200 short lines) + TOC text to an LLM with a
   JSON-schema-constrained prompt → canonical chapter tree. Cheap: ~1 call/thesis.
7. MERGE & SCORE: reconcile S_b/S_t/layout headings; emit per-boundary confidence
   (bookmarks+TOC+layout agree = 1.0 … font-rule-only = 0.4). Route <0.6 to human QA.
```

**Expected accuracy:** chapter-boundary detection ≥0.95 F1 on born-digital ETDs (bookmarks or TOC alignment usually suffices), ~0.80–0.90 on scanned/OCR-degraded (ETD-ODv2 scanned AP numbers bound this [^10^]); heading-*level* assignment (tree nesting) is the weak spot per READoc (~22-point gap [^11^]) — expect ~0.85 tree-TEDS before LLM arbitration [MED, extrapolation]. **Failure modes:** TOC lists "Chapter 1" but body uses "1."; published-article chapters (stapled papers with their own internal IMRaD); appendices as chapters (ETD-OD explicitly treats appendices as chapters distinguishable by title [^10^]); two-column proceedings-style reprints; OCR noise breaking title matching.

---

## 2. Two-engine parsing architecture (verified state, 2026-07)

| Engine | Version/state | License (verbatim/verified) | Role in Calyx | Throughput | Long-doc handling |
|---|---|---|---|---|---|
| **GROBID** | 0.8.2 (2025-05-11; changelog verified: model "flavors" for non-standard article segmentation, header start/end page now customizable #282, improved non-standard font handling) [^20^] | Apache-2.0; docs CC-0; training data CC-BY [^20^] | References segmentation+parsing (~0.87–0.90 F1), citation contexts (0.76–0.91 F1), consolidation (biblio-glutton / Crossref; +0.12–0.13 F1 header fields), TEI coords [^2^][^3^][^5^] | 10.6 PDF/s fulltext, 36 PDF/s header [^2^] | Article-oriented; struggles with thesis front/back matter and chapters — use per-segmented-chapter or accept noise on front matter [HIGH, wide05] |
| **Docling** | IBM/LF AI&Data, active 2.x line; DocLayNet RT-DETR layout + TableFormer; per-item `prov` = page_no+bbox+charspan (verified in emitted JSON [^22^]) | **MIT** (verbatim in tech report [^9^]) | **Default structure engine**: layout, reading order, tables, section hierarchy, provenance; air-gapped OK | ~0.5 s/page GPU, ~3 s/page CPU (indep. benchmark [^23^]) | Linear pipeline, streaming-friendly; no thesis semantics |
| **MinerU** | 3.3–3.4 (2026-06; v3.1 2026-04-18 relicensed) | **MinerU Open Source License** = Apache-2.0 + clauses: commercial use allowed; separate license only if >100M MAU or >$20M monthly revenue; attribution required for online services (LICENSE text verified [^24^]) | **Accuracy-first engine** for scanned/CJK/complex theses; OmniDocBench v1.6 pipeline 86.2 / hybrid 95.39; PP-OCRv6, 109 langs; cross-page table merge [^7^] | ~0.2 s/page GPU (indep. [^23^]); READoc 214.9 s/doc [^12^] | **Sliding-window long-doc mode** — "tens of thousands of pages no longer need to be split manually" [^7^] [HIGH] |
| **Marker** | v1.10.x; sibling model Chandra 2 (4B, 85.9% olmOCR-bench) now carries Datalab's OCR frontier [^21^][^25^] | **GPL-3.0 code + OpenRAIL-M-derived weights** free for research/personal/startups <$2M funding/revenue — commercial deployment of Orchid Continuum as a product requires Datalab license [^6^] | Optional fast layout parser; best speed/quality on born-digital (LLM-judge 4.24; FinTabNet 0.816→0.907 w/ LLM); TOC metadata [^6^] | 0.18 s/page single; "projected 122 pages/s H100" [^6^]; READoc 27.7 s/doc [^12^] | Docs still advise manual splitting on OOM for very long PDFs [^6^] |
| **pymupdf4llm** | maintained 2026 | **AGPL-3.0** (verbatim [^13^]) | Preflight only (TOC/text/fonts). AGPL acceptable for internal service use; keep out of distributed artifacts | ~real-time | n/a |

**Architecture decision:** Engine A = GROBID (references/citations, run on full PDF + per-reference consolidation against biblio-glutton/OpenAlex [^5^][^27^]); Engine B = Docling (default) with MinerU as fallback by preflight class (scanned → MinerU; born-digital → Docling first, MinerU if Docling table/heading quality below threshold on the gold set). Marker only in a research branch. Docling's "metadata/reference extraction coming soon" gap [^9^] is covered by GROBID. Long documents: MinerU sliding-window handles >10k-page docs [^7^]; Docling is linear and memory-bounded; Marker needs splitting — split at *chapter boundaries found by §1.2*, never mid-chapter.

---

## 3. Non-IMRaD mapping → the 15-element schema

Theses deviate from IMRaD in three common ways: (i) chapter-based STEM theses whose chapters are Introduction/LitReview/Methods-per-study/Results-per-study/General Discussion; (ii) **monograph chapters** (taxonomy theses: each chapter a taxonomic treatment or a published paper); (iii) humanities-style titled chapters with no rhetorical labels. Mapping method, in order of cost:

1. **Heading lexicon + regex** (highest precision, ~covers 60–80% of STEM theses): canonical maps — "Literature Review|Related Work|Background"→LitReview; "Materials and Methods|Methodology|Experimental Setup"→Methods; "Results|Findings"→Results; "Discussion"→Discussion; "Conclusions?|Summary"→Conclusions; "Limitations|Threats to Validity"→Limitations; "Future Work|Directions for Future Research"→FutureResearch; "References|Bibliography|Works Cited"→References; "Appendix|Annex"→Appendices; "Abstract|Résumé|Zusammenfassung"→Abstract [MED, standard practice].
2. **Few-shot LLM heading classification**: for unmatched chapter titles ("Taxonomic revision of *Pleurothallis* sect. …"), classify the whole chapter (title + first 500 tokens) into {one of 15 elements | RESEARCH-CHAPTER | FRONT-MATTER | NONE}, JSON-constrained. Research chapters then get **internal** section detection (a stapled-paper chapter has its own mini-IMRaD) [MED].
3. **Sentence-level discourse classifiers** for fine-grained assignment when sections are unlabeled: CoreSC (11 classes incl. Hypothesis, Motivation, Goal, Method, Result, Conclusion; SVM/CRF on 265-article corpus: Experiment F1 0.76, Background 0.62, Model 0.53; section-heading features matter) [^14^] and Argumentative Zoning lineage (Teufel & Moens AIM/CONTRAST/BASIS/OTHER; MuLMS-AZ CODI 2023 [^15^]). Modern recipe: SciBERT/DeBERTa fine-tune; CONSORT-style study shows **prepending nested section headers + neighboring sentences** lifts sentence classification to 0.71 micro-F1 vs 0.65 sentence-only, and beats GPT-4 few-shot (0.46–0.51) [^19^] [HIGH] — direct evidence for "classifier-with-context beats LLM few-shot" on sentence-level rhetorical labeling.
4. **Position priors**: Abstract always in first ~5 pages; References after last content chapter (or per-chapter in stapled theses — detect by GROBID reference-model hit density); Appendices after References; Limitations/Future Research overwhelmingly inside the final 15% of the discussion/conclusion chapter (BioScope: Conclusions sections significantly more speculative [^26^]).

---

## 4. The 15-element method map

Format: **Method (tool+technique) · expected accuracy · failure modes · confidence.**

1. **Abstract** — TOC/bookmark "Abstract" anchor; else layout heading `Abstract` in first 5 pages + ETD-OD `Abstract Heading`/`Abstract Text` classes (169/183 instances in ETD-OD [^10^]). GROBID header model as cross-check. · ≥0.97 boundary F1 born-digital; ~0.90 scanned. · Multiple abstracts (technical + general-audience + translated — ETD-OD taxonomy explicitly notes multi-abstract ETDs [^10^]); scanned front matter. [HIGH]
2. **Research Question** — Heading cue ("Research Questions", "Objectives and Questions") + sentence classifier: interrogative sentences in Introduction + "this (thesis|study|work) (asks|investigates|addresses)" cue patterns + CoreSC Goal/Motivation classes [^14^]; LLM fallback with span anchoring. · Heading-cued: ~0.95 P; implicit RQs: 0.6–0.75 F1 [MED]. · RQs scattered across intro + repeated per chapter; RQ vs objective vs aim confusion. Datasets: CoreSC corpus (Goal/Motivation/Hypothesis) [^14^]; AZ corpora (AIM) [^15^]; no thesis-native RQ corpus — annotate in gold set (§6). [MED]
3. **Literature Review** — Heading lexicon (strong: "Literature Review", "Related Work", "State of the Art", "Background") + position (early chapters) + citation-density heuristic (lit-review chapters have ~2–5× reference-mention density; GROBID citation contexts quantify this [^3^]). · 0.90–0.95. · Lit review fused into Introduction; per-chapter "related work" sections in stapled theses. [HIGH on method, MED on accuracy]
4. **Hypotheses** — Heading cue ("Hypotheses", numbered "H1/H2" patterns — regex gold) + CoreSC Hypothesis sentence class [^14^] + hedging-cue overlap control (BioScope [^26^]); LLM extraction of hypothesis statements with evidence links. · Cued/numbered: ~0.95; free-text hypotheses: 0.6–0.7 [MED]. · Hypotheses embedded in RQ prose; prediction-vs-hypothesis conflation. [MED]
5. **Materials & Methods** — Heading lexicon (very strong across STEM: "Materials and Methods", "Methodology", "Methods", "Experimental Design") + chapter-position prior + verb-density/passive-voice features if needed. · 0.95+ heading-cued. · Monograph theses: "Materials examined" specimen lists inside treatment chapters (route to Plazi-style material-citation extraction, wide05); methods split per study chapter. [HIGH]
6. **Results** — Heading cue + table/figure-reference density ("Table 3 shows…") + CoreSC Result/Observation sentence classes [^14^]. · 0.90–0.95. · Combined "Results and Discussion" sections (emit *both* labels with sub-spans; sentence classifier splits at ~0.7 F1 [^14^][^19^]). [HIGH/MED]
7. **Discussion** — Heading cue + discourse markers ("These results suggest", "In contrast to", hedging density — BioScope: discussion/conclusion more speculative [^26^]). · 0.90 cued; 0.7 uncued. · "General Discussion" final chapter vs per-chapter discussions; merged Results-Discussion. [MED]
8. **Conclusions** — Heading cue ("Conclusion(s)", "Summary and Conclusions", "Concluding Remarks") + final-chapter position + CoreSC Conclusion class [^14^]. · 0.95. · "Summary of the thesis" front sections; conclusion absorbed into Discussion. [HIGH]
9. **Limitations** — Heading cue (often *subsection* inside Discussion/Conclusion: "Limitations", "Caveats", "Threats to Validity") + sentence classifier on cue lexicon ("limitation", "shortcoming", "caveat", "we acknowledge") + hedging/uncertainty machinery (BioScope/CoNLL-2010 cue+scope [^26^][^28^]) + LLM fallback with span anchors. · Heading-cued ~0.95; uncued sentence-level 0.55–0.70 [MED/LOW — thin dedicated corpora; best adjacent evidence: BioScope + CONSORT-style contextual classification [^19^][^26^]]. · Limitations dispersed; limitation-vs-future-work boundary. [MED]
10. **Future Research** — Heading cue ("Future Work", "Future Directions", "Perspectives") + deontic/future-tense sentence classifier ("future work should", "it remains to", "further research is needed") + LLM. · Cued ~0.95; uncued 0.6–0.75. · Fused "Limitations and Future Research" sections. [MED]
11. **References** — GROBID reference model: segmentation+parse 0.87–0.90 F1, >0.90 instance-level parsing, consolidation to DOI/PMID >0.95 [^3^]; per-chapter bibliographies in stapled theses handled by running GROBID per chapter segment; anystyle (BSD, user-trainable) as fallback for idiosyncratic styles [^29^]. · 0.87–0.95. · Non-DOI long tail (floras, herbaria, 19th-c. works — Crossref: 71% of refs lack DOIs; SBMV matching F1 0.966 [^30^]); OCR-degraded bibliographies. [HIGH]
12. **Appendices** — TOC/bookmark anchor + pattern /^appendix\s+[A-Z]/i + position (post-References); ETD-OD treats appendices as chapters distinguishable by title [^10^]. · 0.90–0.95. · Appendices inside chapters; "Supplementary Appendix" naming; appendix content misrouted as main-chapter results. [HIGH/MED]
13. **Figures** — Layout model figure regions (Docling/MinerU/ETD-ODv2 `Figure`+`Figure Caption` classes: 6,359/5,722 instances, among the strongest AP classes [^10^]) → crop to PNG with page/bbox + nearest-caption association (ETD-OD used Euclidean caption proximity [^10^]; modern parsers do it natively) + List-of-Figures cross-validation. · Detection ~0.90–0.95; caption-linking ~0.85–0.90 [MED]. · Multi-panel figures; figures-as-scans in old theses; captions split across pages. [HIGH]
14. **Tables** — Layout detection + structure recognition: TableFormer (Docling) / surya (Marker) / MinerU table models. **Accuracy ceiling from benchmarks**: PubTabNet TEDS 96.5–96.9 (SOTA ensembles), FinTabNet ~98.9 structure-only; TableFormer 93.6 PubTabNet-all / 96.8 FinTabNet-struct [^31^][^32^]; OmniDocBench in-the-wild: MinerU table TEDS ~0.78 vs Marker ~0.57 heuristic mode [^33^]; Marker FinTabNet 0.816→0.907 with `--use_llm` [^6^]; complex/spanning/multi-page tables remain the hard tail (PubTables-v2 cross-page continuation ~99.5% recall claimed in vendor eval [^34^]) [HIGH]. Export HTML+Markdown+CSV with bbox; flag TEDS-risky tables (spanning cells, borderless) for QA. · In-the-wild TEDS 0.75–0.85 on thesis tables [MED extrapolation]. · Borderless botanical character tables; rotated landscape tables; multi-page species lists. [HIGH on ceiling numbers]
15. **Supplementary Material** — Two kinds: **(a) in-PDF** → treat as Appendices (#12). **(b) separate files in the ETD submission**: institutions accept/require separate multimedia/data files ([^35^]: "Multimedia content… must be submitted separately from the PDF of the written work within the ETD system"); repository metadata carries them — ETD-MS records support multiple files per thesis with direct file links in identifier fields (Theses Canada harvest spec: "We can download multiple files per thesis" [^36^]); ETD-MS v2.0 adds explicit `ETD_File` and `Object_metadata` entities [^37^]; external data deposits linked via **DataCite relatedIdentifiers `IsSupplementTo`** (query pattern: `relatedIdentifiers.relatedIdentifier:<DOI> AND relationType:IsSupplementTo` [^38^]) or Crossref `is-supplemented-by` [^38^]. · Detection of separate files: ~1.0 when harvesting via OAI-PMH ETD-MS (metadata-declared); ~0.5–0.7 when inferring from PDF text mentions ("data available at…" — route via datastet/GROBID data-availability model, 0.8.2 extended DAS training data [^20^]). · Embargoed files; broken links; supplements only on ProQuest behind paywall. [HIGH on mechanism, MED on coverage]

---

## 5. Research-question / hypothesis / limitations / future-work: datasets with labels

- **CoreSC corpus** (265 biochemistry/chemistry full papers; sentence-level Hypothesis, Motivation, Goal, Conclusion; SVM/CRF baselines F1 0.53–0.76; annotation guidelines + corpus public) [^14^] — closest labeled resource for Hypothesis/RQ-adjacent classes.
- **Argumentative Zoning**: Teufel & Moens AZ (AIM class ≈ research goal); MuLMS-AZ (CODI 2023, materials-science AZ) [^15^].
- **BioScope** (hedge/negation cue+scope; Conclusions more speculative) [^26^] + **CoNLL-2010 shared task** [^28^] — the Limitations/uncertainty signal substrate.
- **CONSORT sentence-classification corpus** (biomedical reporting items incl. limitations-relevant items; demonstrated recipe: PubMedBERT + section-header prepending + neighbor context, 0.71 micro-F1, beats GPT-4 few-shot 0.46–0.51) [^19^].
- **No thesis-native corpus** exists for RQ/Limitations/FutureWork — gap to close with the §6 gold set (annotate these four at sentence level). [HIGH confidence in the gap after targeted searching]

---

## 6. Gold benchmark design (20–30 theses)

**Corpus:** 24 theses stratified: {born-digital, scanned} × {STEM-IMRaD-chapter, monograph/taxonomic (≥4 orchid/botany), humanities-style} × {PhD, MSc}; 100–400 pp; ≥6 with separate supplementary files. Source: institutional repositories via OAI-PMH (ETD-MS) [^36^][^37^] + READoc-Zenodo thesis subset [^12^] for cross-check.

**Annotation (INCEpTION):** INCEpTION (UKP Darmstadt) supports span/relation layers, curation/adjudication workflow, and built-in agreement (Cohen's/Fleiss' κ, Krippendorff α coding **and unitizing** — needed for boundary/segment agreement) [^39^] [HIGH]. Layers: (1) document-level chapter boundaries + 15-element labels (unitizing α); (2) sentence-level {RQ, Hypothesis, Limitation, FutureWork} (coding κ); (3) table regions w/ HTML gold for TEDS on a 30-table subsample. Pre-annotate with the §1.2 pipeline + LLM (AI-aided annotation cut per-page time ~2–3× in ETD-ODv2's study [^10^]).

**Effort/cost estimate:** ~1.5–3 h/thesis for structure+sentences with pre-annotation → 24 theses × 2 annotators × ~2.25 h ≈ 108 annotator-hours + ~20 h curation; at $25–40/h (trained graduate annotators) ≈ **$2,700–$4,300 + ~$800 tooling/PM ≈ $3.5–5k total** [MED/LOW — derived from ETD-ODv2 timing data and standard annotation rates, no direct citation].

**Metrics:** boundary F1 @±1 page; heading-text edit distance; **tree-TEDS on the chapter/section hierarchy** (READoc-style, since ToC-tree is the known weakness [^11^]); per-element span F1; table TEDS/TEDS-Struct [^31^]; reference segmentation F1 vs GROBID eval protocol [^3^]; supplementary-file detection precision/recall. Acceptance gates: chapter boundary F1 ≥0.95; tree-TEDS ≥0.90; table TEDS ≥0.80 on thesis tables; RQ/Hypothesis sentence F1 ≥0.70.

---

## 7. Output schema: recommendation

**Recommend: custom JSON with Docling-style provenance as the system-of-record; emit TEI/JATS as lossy interchange exports.**

Rationale: (1) Calyx's core need is **per-element, per-span provenance** (page, bbox, charspan, heading path) — Docling's `prov` (page_no + bbox + charspan + coord_origin, verified shape [^22^]) and GROBID TEI `coords` [^3^] show the pattern; JATS/TEI encode this only awkwardly (`<facsimile>`/surface zones). (2) The 15-element thesis schema is not JATS-native (JATS has no Limitations/FutureResearch/ResearchQuestion elements; TEI `<div type>` is freeform but then the "standard" buys nothing). (3) JSON + JSON Schema + Pydantic matches the constrained-decoding extraction layer and nanopub-style claim provenance (wide05 §13). (4) Interoperability is preserved by exporters: TEI for digital-library/text-analysis exchange, JATS for publisher-style deposits, ETD-MS v2.0 entities for repository ingestion [^37^].

```jsonc
// calyx-thesis-v1 (sketch)
{ "doc_id": "…", "source": {"pdf_sha256": "…", "oai_record": "…"},
  "parse": {"engines": ["docling@x","grobid@0.8.2"], "preflight": {"born_digital": true}},
  "structure": [ {"element": "materials_methods", "label_src": "heading_lexicon",
     "confidence": 0.97, "chapters": [3],
     "spans": [{"page_start": 45, "page_end": 61, "heading_bbox": [l,t,r,b],
                "prov_engine": "docling"}] } ],
  "items": [ {"type": "hypothesis", "text": "H1: …", "section_path": ["Ch1","1.4"],
     "prov": [{"page_no": 12, "bbox": {...}, "charspan": [0,143]}],
     "classifier": {"name": "coresc-scibert", "score": 0.88} } ],
  "tables": [ {"id":"t3.2", "html":"…", "teds_risk": false, "prov": […] } ],
  "supplementary_files": [ {"filename":"…", "relation":"IsSupplementTo", "source":"etd-ms"} ] }
```

---

## 8. Risks

1. **#1 structural risk — hierarchical nesting/tree construction** (READoc: ~22 TEDS-pt gap [^11^]): mitigation = fallback chain §1.2 + tree-TEDS gate in §6 + LLM arbitration on disagreement; budget ~1 LLM call/thesis.
2. Scanned-thesis layout degradation (ETD-ODv2 AP collapse on scanned classes [^10^]) → preflight routes to MinerU + OCR-quality gate.
3. Stapled-paper chapters break chapter↔element assumptions → per-chapter mini-IMRaD pass + GROBID per chapter.
4. License drift (MinerU custom license terms; Marker GPL/OpenRAIL) → Docling MIT as default keeps the commercial path clean.
5. Sentence-level RQ/Limitations/FutureWork has no thesis-native training data → gold set + fine-tune; LLM fallback only with span-anchored verification.

---

### Citations / URLs

[^2^] GROBID benchmarking & throughput — https://grobid.readthedocs.io/en/latest/Benchmarking/ ; https://grobid.readthedocs.io/en/latest/Introduction/
[^3^] GROBID reference/citation F1, consolidation gains, coordinates — https://grobid.readthedocs.io/en/latest/Benchmarking/
[^5^] GROBID consolidation (Crossref 25 q/s; biblio-glutton) — https://grobid.readthedocs.io/en/latest/Consolidation/
[^6^] Marker repo (GPL-3.0 + OpenRAIL-M weights verbatim; benchmarks; TOC metadata; long-doc OOM advice) — https://github.com/datalab-to/marker
[^7^] MinerU repo (v3.x changelog, sliding-window long-doc, OmniDocBench 95.39/86.2, license change 2026-04-18) — https://github.com/opendatalab/MinerU
[^9^] Docling tech report (MIT verbatim; "metadata… coming soon") — https://arxiv.org/abs/2501.17887 ; https://github.com/docling-project/docling
[^10^] Ahuja 2023 dissertation — ETD-OD & ETD-ODv2 (taxonomy, counts, AP tables, caption-proximity method, AI-aided annotation) — https://vtechworks.lib.vt.edu/bitstream/handle/10919/115817/Ahuja_A_D_2023.pdf
[^11^] READoc (ToC-tree weakness; 22.00 avg Tree-vs-Concat drop; Nougat 88.50→37.01; Tesseract KT 96.70/98.48) — https://arxiv.org/html/2409.05137v1
[^12^] READoc v2 (Zenodo subset w/ theses; Marker 27.7 vs MinerU 214.9 s/doc) — https://openreview.net/pdf?id=WbDouroc2O ; https://github.com/icip-cas/READoc
[^13^] pymupdf4llm (AGPL verbatim; TocHeaders) — https://github.com/pymupdf/pymupdf4llm
[^14^] CoreSC (11 classes; 265 articles; SVM/CRF F1 Experiment .76/Background .62/Model .53; corpus+guidelines) — https://pubmed.ncbi.nlm.nih.gov/22321698/
[^15^] MuLMS-AZ (CODI 2023) — https://aclanthology.org/2023.codi-1.1/
[^16^] Example institutional ETD formatting rules (TOC must list chapters+appendices; separate supplementary content) — https://gentext.ai/guides/en/stanford-university-thesis-format/
[^17^] WCAG 2.1 AA ETD accessibility mandate incl. bookmarks by 2026-04 — https://www.vims.edu/academics/graduate/student_handbook/handbook_milestones/ms_phd_milestones/thesis_dissertation/physical_standards/
[^18^] Bookmark creation is optional/tooling-dependent in Word→PDF workflows — https://www.utsouthwestern.edu/edumedia/edufiles/medical_school/academics/research/etd-thesis-template.doc
[^19^] CONSORT sentence classification (section-header prepending + context; 0.71 micro-F1; GPT-4 few-shot 0.46–0.51) — https://pmc.ncbi.nlm.nih.gov/articles/PMC11408668/
[^20^] GROBID 0.8.2 changelog (2025-05-11; flavors; header start/end pages; DAS training data) — https://github.com/grobidOrg/grobid/blob/master/CHANGELOG.md ; Apache-2.0 statement: https://github.com/grobidOrg/grobid
[^21^] Datalab changelog (section-hierarchy improvements; Chandra 1.5) — https://documentation.datalab.to/platform/changelog
[^22^] Docling prov JSON shape (page_no/bbox/charspan, verified example) — https://docs.langchain.com/oss/python/integrations/document_loaders/docling
[^23^] Independent parser benchmark (Docling 0.882 overall/0.887 tables; MinerU 0.21 s/page GPU; license summary) — https://yage.ai/share/markitdown-survey-en-20260412.html
[^24^] MinerU Open Source License full text (commercial thresholds 100M MAU / $20M monthly revenue; attribution) — https://github.com/opendatalab/MinerU (LICENSE.md; mirror text retrieved)
[^25^] Chandra 2 (4B, 85.9% olmOCR-bench) — https://blog.themenonlab.com/blog/chandra-2-ocr-model-structured-document-extraction
[^26^] BioScope (>10% hedged/negated; Conclusions more speculative) — https://pmc.ncbi.nlm.nih.gov/articles/PMC2586758/
[^27^] OpenAlex-as-consolidator validation — https://pmc.ncbi.nlm.nih.gov/articles/PMC12963361/
[^28^] CoNLL-2010 hedge cue+scope shared task — https://aclanthology.org/W10-3113/
[^29^] anystyle (BSD; user-trainable) — https://github.com/inukshuk/anystyle
[^30^] Crossref reference matching (71% refs w/o DOI; SBMV F1 0.966) — https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/
[^31^] TEDS definition (Zhong et al. 2020; structure+content; TEDS-Struct variant) — https://ar5iv.labs.arxiv.org/html/2208.04921 ; https://arxiv.org/html/2501.11800v1
[^32^] PubTabNet/FinTabNet SOTA TEDS (MuTabNet 96.87/98.87; TableFormer 93.6/96.8) — https://arxiv.org/pdf/2404.13268v2 ; https://www.scitepress.org/PublishedPapers/2023/116850/116850.pdf
[^33^] OmniDocBench (MinerU table TEDS ~0.78 vs Marker ~0.57; pipeline leads EN text) — https://arxiv.org/html/2412.07626v2
[^34^] PubTables-v2 cross-page table continuation claim — https://imagetotable.ai/blog/can-ai-extract-tables-from-images (vendor blog [LOW]); dataset: Smock et al. via https://www.emergentmind.com/topics/visual-table-extraction
[^35^] ETD supplementary multimedia as separate files (institutional guidance) — https://www.utsouthwestern.edu/edumedia/edufiles/medical_school/academics/research/etd-thesis-template.doc
[^36^] ETD-MS harvest: multiple files per thesis via direct links (Theses Canada) — https://library-archives.canada.ca/eng/services/services-libraries/theses/Pages/information-universities.aspx
[^37^] ETD-MS v2.0 (ETD_File/Object_metadata entities; 1,000-ETD implementation; ETDMiner prompts) — https://etd2024.unza.zm/proceedings/full-papers/papers/docs-paper-etd24-45.pdf ; https://planet.code4lib.org/
[^38^] DataCite IsSupplementTo linking + discovery query pattern; Crossref is-supplemented-by — https://arxiv.org/html/2405.13129v1
[^39^] INCEpTION (curation workflow; Cohen/Fleiss κ; Krippendorff α coding & unitizing) — https://inception-project.github.io/documentation/latest/user-guide

*End of report.*
