# Calyx Deep-Dive dim08 — Scientific Reasoning Extraction: Per-Category Method Specification

**Agent date:** 2026-07-21 · **Searches:** 4 batches / 20 targeted queries (ACL Anthology-lineage papers, GitHub repos, official dataset pages, grobid docs) + full reuse of verified context from calyx_wide05.md
**Confidence tags:** [HIGH] verified this session via official/primary source; [MED] consistent secondary evidence; [LOW] single weak source / inference.

---

## 1. Corpora Inventory (verified)

| Corpus | Size | Labels | License / access | URL | Conf. |
|---|---|---|---|---|---|
| **AZ corpus (AZ I, Teufel & Moens)** | 80 CL conference articles (from Cmplg arXiv); sentence-level | 7 zones: Aim, Background, Basis, Contrast, Other, Own, Text; IAA κ=0.71 | **CC BY-NC 2.0 UK**; download from Cambridge; mirror at WING-NUS/RAZ | https://www.cl.cam.ac.uk/~sht25/AZ_corpus.html ; https://github.com/WING-NUS/RAZ | [HIGH] |
| **AZ-II (Liakata et al. 2012)** | Chemistry papers; sentence-level, fine-grained | 15 zones (extends AZ); jointly annotated w/ CoreSC on subset | Research access via authors (no open license found) | ACL Anthology 2012 paper (Liakata et al., "Automatic recognition of conceptualization zones in scientific articles") | [MED] |
| **ART corpus (Liakata & Soldatova)** | 265 chemistry papers total; distributable core = **225 papers, >1M words, 35,040 sentences** (2.2 MB tar.gz → 12 MB); phase II = 41 papers / 5,000 sentences | CoreSC L1: Hypothesis, Motivation, Goal, Background, Object, Method, Model, Experiment, Observation, Result, Conclusion (+ properties, concept IDs); preliminary κ=0.55 (16 experts, groups of 3); phase III restricted to 9 highest-agreement annotators | Free for research, contact m.liakata@warwick.ac.uk; no explicit OSS license | http://www.sapientaproject.com/links ; https://www.aber.ac.uk/en/media/departmental/impacs/computerscience/pdfs/Description_ART_Corpus.pdf | [HIGH] |
| **Sci-Arg (Lauscher et al. 2018)** | 40 CL papers; ~1.2–1.3k argumentative components, ~900+ relations [component/relation counts MED] | Components: own claim, background claim, data; Relations: support / contradict / non-argumentative | Public download, research use | https://data.informatik.uni-mannheim.de/sci-arg/ ; paper https://aclanthology.org/W18-5206 | [HIGH] exists; [MED] counts |
| **Dr. Inventor (DRI) multi-layer corpus** | 40 computer-graphics papers; **10,784 sentences**, ~12,000 argumentative component labels | Rhetorical: Challenge, Background, Approach, Outcome, FutureWork (+ combined labels e.g. Challenge_Hypothesis); κ=0.66 | Public via project site + OpenDataLab mirror | http://sempub.taln.upf.edu/dricorpus ; https://opendatalab.com/OpenDataLab/DRI_Corpus/download | [HIGH] |
| **PubMed 200k RCT (Dernoncourt & Lee 2017)** | **195,654 RCT abstracts, 2.3M sentences** (train 190,654 / val 2,500 / test 2,500); 20k subset | Sequential 5-class: BACKGROUND, OBJECTIVE, METHOD, RESULT, CONCLUSION | Free (GitHub); derived from PubMed | https://github.com/Franck-Dernoncourt/pubmed-rct ; https://arxiv.org/abs/1710.06071 | [HIGH] |
| **AbstRCT (Mayer et al. 2020/2021)** | 659 RCT abstracts (500 neoplasm / 100 glaucoma / 59-mixed); **4,198 components + 2,601 relations**; v1: 169 abstracts, 919 components | Components: claim, premise/evidence; Relations: support, attack, **partial attack**; Fleiss κ 0.72 (components), 0.62 (relations) | Public (GitLab/GitHub); research | via https://arxiv.org/html/2301.10527 ; thesis https://theses.hal.science/tel-03209489/document | [HIGH] |
| **BioScope (Vincze et al. 2008)** | ~20,000 sentences: 1,954 abstracts + 9 full papers + 1,273 clinical radiology reports [MED on exact split]; >10% of sentences negated or hedged | Negation + speculation cues **and linguistic scope**; Conclusions sections significantly more speculative | Free after registration, academic use | https://rgai.inf.u-szeged.hu/project/bioscope ; paper https://pmc.ncbi.nlm.nih.gov/articles/PMC2586758/ | [HIGH] corpus facts; [MED] exact counts |
| **CoNLL-2010 shared task (Farkas et al.)** | BioScope (abstracts+full) train; new bio sentences eval; Wikipedia set: 11,110 train / 9,634 eval sentences; 77.26% of Wiki sentences certain | Task1B: uncertain-sentence detection (bio); Task1W: Wikipedia; Task2: cue detection + scope resolution | Free download | https://aclanthology.org/W10-3113/ | [HIGH] |
| **Certainty corpus (Rubin)** | News + narrative text (~300+ documents), sentence-level [MED] | **4 graded certainty levels** (absolute / high / moderate / low) + certainty dimensions (level, perspective, focus, time) | Research access via author (Syracuse); no open redistribution located | Rubin 2006/2010; discussion https://www.researchgate.net/publication/260178341 | [MED] |
| **SciFact (Wadden et al. 2020)** | **1,409 claims vs 5,183 abstracts** (train 809 / dev 600 claims) | Claim-level SUPPORTS / REFUTES / NOINFO + rationale sentences; test labels withheld | CC-BY-NC [MED]; public leaderboard | https://github.com/allenai/scifact ; usage per https://pmc.ncbi.nlm.nih.gov/articles/PMC10919922/ | [HIGH] |
| **Evidence Inference (Lehman et al. 2019; v2.0 DeYoung et al. 2020)** | **10,000+ prompts** (ICO triplets) over full-text PMC RCT reports; v2.0 +25% annotations; abstract-only subset (~1,964 abstracts train) | Ternary directionality: significantly increased / decreased / no significant effect + **evidence snippets (rationales)** | Public, code+data on GitHub | https://github.com/bwallace/evidence-inference-1 ; https://aclanthology.org/N19-1371 | [HIGH] |
| **ARCHE / ARCHE-Bench (AAAI 2026)** | **70 peer-reviewed Nature Communications articles**; reasoning steps extracted from introduction paragraphs | Steps typed **deductive / inductive / abductive** (Peircean); assembled into Reasoning Logic Trees (RLT) with premise→conclusion edges; two-stage generation+evaluation | Benchmark paper public | https://ojs.aaai.org/index.php/AAAI/article/view/37170/41132 | [HIGH] |
| **MuLMS-AZ (CODI 2023)** | Materials-science articles | AZ-adapted zones; includes label-count comparison table of AZ/ART/DRI corpora | Public | https://aclanthology.org/2023.codi-1.1/ | [HIGH] |

**Baseline performance anchors:** PubMed 200k RCT bi-ANN F1 83.1–91.6 (modern: 0.95 macro-F1, Hu et al. 2023) [^10^][^11^]. CoNLL-2010 Task1B best F1 **86.4** (Tang, cascade CRF+large-margin); biological cue-level best ~81.3 F1; Task2 scope best **57.3 F1** (Morante, memory-based + dependency syntax) — scope remains the hard subtask [^12^][^13^]. grobid-quantities: quantities model micro-F1 **76.5 CRF / 85.2 BERT_CRF(SciBERT)**; values 99.4; units 80.8 CRF [^17^][^18^].

---

## 2. The 14-Category Method Map

Routing key: **C** = classical/fine-tuned small model first; **L** = LLM-first; **H** = hybrid (classical detector + LLM normalizer). Expected performance is thesis-domain-transfer-adjusted (orchid/botany prose), not the source-domain ceiling.

| # | Category | Routing | Method spec | Training corpora | Expected perf (thesis domain) | Cost @ 10k theses* | Conf. |
|---|---|---|---|---|---|---|---|
| 1 | **Observations** | **H (C-first)** | Sentence-level discourse classifier: fine-tune SciBERT/DeBERTa on CoreSC `Observation`+`Result` (ART), PubMed 200k RESULT, DRI `Outcome`; Plazi material-citation extractor for specimen observations | ART, DRI, PubMed 200k, MuLMS-AZ | F1 0.75–0.85 sentence classification | GPU hours only (~$0 API) | [HIGH] method / [MED] transfer |
| 2 | **Measurements** | **C** | **grobid-quantities** (verified: 3-stage CRF cascade quantities→units→values, SI normalization via Unit Lexicon, REST/batch; BERT_CRF variant micro-F1 85.2 quantities / 99.4 values / 80.8 units) + CharaParser for morphological character measurements; LLM cross-check only on parse failures | grobid-quantities corpus (32 OA papers + UNISCOR ~1,600 unit examples + 950 value examples, public) | Field-level F1 0.75–0.85; unit normalization near-deterministic | CPU; negligible | [HIGH] |
| 3 | **Experimental evidence** | **H** | Argument mining: BIO sequence tagger (SciBERT) for evidence/premise spans (AbstRCT-style) + support/attack/partial-attack relation classifier; LLM synthesizes extra training data per AM survey finding | AbstRCT, Sci-Arg, Evidence Inference (evidence snippets), SciFact rationales | Component F1 0.65–0.75; relation F1 0.45–0.60 | Fine-tune once; inference GPU | [HIGH] |
| 4 | **Author interpretations** | **H** | Discourse-role split RESULT vs INTERPRETATION (CoreSC Result vs Conclusion; AZ Own vs Contrast; DRI Outcome vs Challenge/FutureWork) then LLM span extraction w/ section context | ART (Result/Conclusion), AZ, DRI | Class F1 0.70–0.80; boundary accuracy lower | Cheap | [MED] |
| 5 | **Assumptions** | **L + human review** | Few-shot frontier LLM, per-section scoped, JSON-schema output, span anchor required; no mature corpus exists; ARCHE (2026) shows latent reasoning-step extraction "revealing the limitations of current LLMs" — expect partial recall only | None dedicated; ARCHE-Bench (70 papers) as eval probe | Recall 0.3–0.6 est.; human-in-loop mandatory | LLM-heavy: see §5 | [LOW–MED] — **risk tier 1** |
| 6 | **Hypotheses** | **H** | AZ `Aim` + CoreSC `Hypothesis` classifiers; cue patterns ("we hypothesize", "if…then", "predicts that"); LLM extraction linking hypothesis→evidence; DRI `Challenge_Hypothesis` combined labels as extra signal | ART (`Hypothesis` class), AZ, DRI | Detection F1 0.70–0.80 (explicit hypotheses); implicit hypotheses → risk tier | Moderate | [MED] |
| 7 | **Inferences** | **H** | Relation classification (support/attack between claims, AbstRCT/Sci-Arg machinery) + LLM rationale extraction for implicit steps; ARCHE deductive/inductive/abductive typing as schema | AbstRCT, Sci-Arg, ARCHE-Bench | Explicit relations F1 0.50–0.65; implicit chains much lower (ARCHE gap) | Moderate | [MED] |
| 8 | **Alternative explanations** | **L** | LLM extraction keyed on contrast markers + AZ `Contrast` class as classical pre-filter ("alternatively", "however, X could also", "cannot exclude"); epistemic-stance models for commitment strength | AZ Contrast; stance corpora | F1 0.4–0.6 est.; sparse phenomenon, high inter-annotator disagreement | LLM on Contrast-filtered subset only | [LOW–MED] — **risk tier 1** |
| 9 | **Predictions** | **H** | Modal/future-tense + cue detection ("we predict/expect", "will", "should") + hedge classifier for strength; LLM structures (prediction, condition, falsifiability) | BioScope cues, Rubin certainty levels | Detection F1 0.75–0.85; structured fields F1 0.6–0.7 | Cheap (classical) + scoped LLM | [MED] |
| 10 | **Recommendations** | **H** | Sentence classifier on conclusion sections ("should", "we recommend", "implications", "future work" — DRI FutureWork class directly transferable); LLM normalizes (action, target, strength) | DRI FutureWork, PubMed CONCLUSION, CoreSC Conclusion | F1 0.75–0.85 (explicit recommendations) | Cheap | [MED] |
| 11 | **Limitations** | **H** | Limitation-section detection (heading heuristics) + sentence classifier ("limitation", "caveat", "shortcoming", "caution is warranted"); overlap with hedging stack; AZ Contrast as auxiliary | DRI Challenge, AZ Contrast, BioScope | F1 0.70–0.80 | Cheap | [MED] |
| 12 | **Uncertainty / hedging** | **C (most mature)** | Fine-tuned SciBERT/DeBERTa on BioScope + CoNLL-2010 bio train (~1k domain sentences added); cue detection **and** scope resolution; **graded** output (Rubin 4-level: absolute/high/moderate/low) preferred over binary — re-label binary corpora via cue-strength lexicon; calibrate vs Pei & Jurgens sentence+aspect certainty | BioScope, CoNLL-2010 (bio+wikipedia), Rubin corpus, Pei & Jurgens | Cue F1 0.80–0.86 (bio best 86.4); scope F1 0.55–0.65 (SOTA 57.3); graded certainty κ 0.5–0.6 | GPU; fine-tune once | [HIGH] |
| 13 | **Speculation** | **C** | Same machinery as #12 but treat as **scope problem**: cue presence ≠ speculative proposition; scope resolution identifies which span is speculative. Distinct from hypothesis (forward-looking, testable) and opinion (attitudinal stance) via context classifier | BioScope speculation cues+scopes, CoNLL-2010 Task2 | Sentence-level speculative F1 ~0.85; scope ~0.6 | GPU | [HIGH] detection / [MED] scope |
| 14 | **Opinion** | **C/H** | Epistemic-stance / subjectivity classifier (RoBERTa multi-source stance model outperformed complex SOTA, Blodgett et al. 2022); author-vs-attributed-source attribution ("Smith argues" vs "we argue") — attribution is the thesis-relevant discriminator | Stance corpora, subjectivity corpora, AZ Own-vs-Other distinction | F1 0.65–0.75; attribution F1 0.6–0.7 | Cheap | [MED] |

\* Cost column assumes fine-tuned open models on-prem; LLM costs itemized in §5.

**Domain-transfer risk note [HIGH]:** hedge/uncertainty cues are "high-precision markers… though highly domain-dependent" [^14^]. Botany/taxonomy prose hedges differently than biomedical abstracts ("possibly conspecific", "provisionally placed", "aff.", "cf.", "?"-annotations, "sensu lato/stricto" carry graded epistemic weight unique to taxonomy). Mitigation: augment BioScope-style training with ~1k gold orchid-thesis sentences before fine-tuning; treat taxonomic qualifier vocabulary as a domain-cue lexicon layer on top of the learned model.

---

## 3. Hedging/Uncertainty Deep Spec

- **Cue-based (BioScope cue lexicon + rules):** precision-oriented, transparent, zero training; F1 cue detection ~0.80 with syntactic features [^13^]. Use as (a) high-precision pre-filter to scope LLM passes, (b) feature input to classifiers, (c) fallback for OCR-degraded text where transformers degrade.
- **Fine-tuned SciBERT/DeBERTa:** best documented bio results (CoNLL-2010 best 86.4 F1 pre-transformer; fine-tuned BERT beats Tree-LSTM/CNN on BioScope) [^12^][^15^]. SciBERT > BioBERT on the biological subcorpus (BERTUncertaintyDetection) [^15^]. **Recommended primary.**
- **LLM zero/few-shot:** competitive on binary uncertain-sentence classification but worse on **scope** (needs exact span discipline) and 20–50× cost; use for **graded certainty calibration** (Rubin 1–5-style scale) where training data is thin, via ensemble-of-3 self-consistency votes.
- **Graded vs binary:** Rubin's 4-level framework (absolute/high/moderate/low certainty, plus perspective/focus/time dimensions) is the target output schema [^16^]. Practical path: binary detector → cue-strength mapping → LLM 5-point rating on detected-certain-vs-hedged subset only; report quadratic-weighted κ against gold.
- **Domain transfer to botany:** [MED] expect 5–15 F1 drop from bio to taxonomic prose without adaptation; 1k domain sentences historically recovers most of it (standard domain-adaptation finding across AZ/BioScope transfer studies) [LOW on exact figure].

---

## 4. Measurements / Quantitative Claims Deep Spec

- **grobid-quantities — verified this session [HIGH]:** open-source (Apache-2.0 line, GROBID org); three CRF models in cascade (Quantities → Units → Values); SI normalization; unit lexicon EN/FR/DE (JSR-385 units library); REST API + batch; training corpus public (32 OA papers + 3 patents; UNISCOR ~1,600 unit examples; 950 value examples). Reported eval: quantities micro-F1 76.5 (CRF) / **85.2 (SciBERT BERT_CRF)**; values 99.4; units 80.8 [^17^][^18^]. Weak labels: `<unitRight>` (sparse, F1 ~33), `<valueList>` (F1 16 CRF / 47.8 BERT_CRF) — lists like "sepals 2, 3 and 10 mm" are exactly orchid-description style, so **fine-tune the BERT_CRF variant and add ~200 orchid-description annotations for `<valueList>`** [^18^].
- **Numeric-claim datasets:** Evidence Inference (directional effects + snippets); the 699-abstract numerical-extraction extension (ICO + numeric results for meta-analysis, PMC) [^19^]; AbstRCT numeric evidence spans.
- **Unit normalization:** grobid-quantities SI output + UCUM codes; log (not silently fix) imperial/non-SI and dimensionless botanical counts ("3-flowered", "2-nerved" — these need a botanical-quantity grammar extension, CharaParser-style) [MED].

---

## 5. LLM Pipeline Design + Cost Envelope

**Architecture (evidence-backed, per wide05 §11–12):**
1. Deterministic parse (GROBID + Marker/Docling) → sections with page/bbox.
2. Classical pre-filters per §2 route the corpus: hedge cues, discourse classes, section types.
3. **Per-section scoped LLM passes** (never whole-thesis): prompt = section text + category-specific JSON schema. Constrained decoding (GBNF/JSON-schema via vLLM/SGLang on-prem, or provider structured outputs) — "de facto standard"; naive prompting can yield 0% schema accuracy on 7–9B models; constrained decoding guarantees validity but can reduce task accuracy and adds latency [^20^][^21^]. SLOT (fine-tuned Mistral-7B): 99.5% schema accuracy, 94.0% content similarity — viable on-prem structured extractor [^22^].
4. **Span-anchored verification:** every extracted item must carry a verbatim quote that exact-matches (normalized) the parser text, plus page + bbox. Items failing match are quarantined, not repaired silently — syntax validity ≠ truth [^20^][^21^].
5. **Self-consistency:** 3 samples @ T=0.3 for risk-tier categories (assumptions, alternatives, speculation boundaries); majority-agree → accept, else → human queue.
6. Pydantic validation + 1 retry w/ error feedback (>95% first-attempt pass achievable with tuned prompts [^23^] [LOW exact figure]).

**Token budget model:** 10k theses × ~120 pages ≈ 1.2M pages ≈ 600M source tokens; after classical pre-filtering, ~8–12% of sentences enter LLM passes → ~60M input + 6M output tokens per full-corpus pass (per category bundle).

| Tier (2026-07 prices) | $/1M in/out | 10k-thesis corpus (60M in / 6M out) | 100k theses (×10) |
|---|---|---|---|
| Budget: Gemini 3 Flash / GPT-4.1-nano class | $0.075–0.10 / $0.30–0.40 | **~$7–9** | ~$70–90 |
| Mid: Gemini 3 Pro / GPT-5.4 / GLM-5.1 | $1.25–2.50 / $5–15 | ~$105–200 | ~$1,050–2,000 |
| Frontier: GPT-5.5 / Claude Opus 4.8 | $5 / $25–30 | **~$450–480** | ~$4,500–4,800 |
| On-prem (Llama/Qwen 70B, 2×H100) | infra only | ~$500–1,500 amortized GPU-time est. [LOW] | dominant fixed cost; wins >100k scale |

Batch APIs (−50%) and prompt caching (−75–90% on repeated instructions) roughly halve the mid/frontier numbers [^24^]. **Recommended split:** budget/mid model for categories 1–4, 9–14 after classical pre-filter; frontier only for risk-tier (assumptions, alternatives, inference chains) ≈ 10–15% of LLM volume → **blended envelope ≈ $50–150 @ 10k theses; $0.5–1.5k @ 100k theses**, plus one-time annotation + fine-tuning (§7).

**Hallucination controls [HIGH]:** (a) verbatim-span exact-match gate; (b) page/bbox provenance mandatory; (c) constrained decoding for syntax only; (d) self-consistency on risky categories; (e) spot-audit 1% random + 100% of low-confidence items; (f) never let the LLM emit numeric values not exact-matched to source (route numbers through grobid-quantities instead).

---

## 6. Hybrid Routing Rule (justified)

**Classical-first when:** labeled corpora ≥ tens of thousands exist in-domain or adjacent-domain, task is span/sequence-precise, and throughput matters — evidence: fine-tuned encoders beat zero-shot LLMs by 15–40 F1 on NER/span tasks (HingBERT 79.7 vs Gemini 62.2; BioGottBERT 0.84 vs GLiNER 0.45–0.66) and run ~20× faster (277 vs 12 samples/s); fine-tuned BERT/RoBERTa beat GPT-4 on short-answer scoring [^25^][^26^][^27^][^28^]. → Categories 2, 12, 13 (+1, 3, 11, 14 classifier layer).

**LLM-first when:** no training corpus exists, schema is evolving, or task requires implicit/cross-sentence reasoning — ARCHE shows even frontier LLMs struggle at latent reasoning chains, so pair LLM-first with human review [^29^]. → Categories 5, 8 (+ implicit part of 6, 7).

**Hybrid default:** classical detector scopes text (cheap, high-recall) → LLM structures/normalizes only the filtered subset (span-anchored). This is the documented cost/accuracy sweet spot (fine-tuned wins on localization, LLM on schema fluidity) [^25^][^30^].

---

## 7. Output Schema

**Nanopublication-per-claim [HIGH]:** four named graphs in TriG — Head, Assertion (one atomic claim), Provenance (`prov:wasDerivedFrom` → thesis URN + page/bbox span selector; extraction-method + model-version + confidence), PublicationInfo (agent ORCID/software, timestamp); **trusty URI** = content hash embedded in identifier (immutable; any edit mints a new nanopub) [^31^][^32^]. Map hedging strength to ECO-style evidence/certainty classes in provenance.

**ORKG compatibility [HIGH]:** assertions serialized as ORKG statements (subject = thesis/contribution, predicate = ORKG research-contribution predicates where mappable, e.g. `hasObservation`, `hasMethod`, `reportsResult`); enables ORKG comparisons and leaderboards tooling (>90% F1 task-dataset-metric extraction precedent) [^33^].

**Reasoning-graph edge types:** `supports` / `contradicts` (incl. partial-attack as `weakly_contradicts`, per AbstRCT) / `extends` / `assumes` / `predicts_from` / `alternative_to` / `limited_by` / `measured_by`. Node types = the 14 categories. Edges carry provenance (span pair) + relation confidence + hedging grade.

---

## 8. Annotation Program

- **Platform:** INCEpTION (Apache-2.0; web-based multi-user; built-in IAA agreement tools; recommender API — attach SciBERT/grobid-quantities/hedge-cue pre-annotation as external recommenders via `inception-external-recommender`/ariadne; inceptalytics for κ computation) [^34^][^35^][^36^].
- **Corpus:** 12 gold chapters (≈ 3 theses: 1 monograph/taxonomic, 1 ecological/experimental, 1 review) × full 14-category schema; double-annotate 100%; hedging/speculation/opinion boundary chapters triple-annotate.
- **Pre-annotation:** classical detectors + LLM draft labels; annotators correct (2–4× speedup typical for pre-annotation [LOW]).
- **IAA targets [MED]:** span-level categories κ ≥ 0.70 (AZ got 0.71; DRI 0.66; AbstRCT 0.72 components / 0.62 relations — match these); hedging grade quadratic-weighted κ ≥ 0.65; scope-boundary F1 agreement ≥ 0.65. Below target → guideline revision round, re-annotate 1 chapter.
- **Adjudication:** weekly; senior adjudicator resolves disagreements; all adjudications logged as guideline deltas; gold = adjudicated version, silver = single-annotator remainder.
- **Cost/time [MED]:** 12 chapters × ~2,500 sentences ≈ 30k sentence-labels + ~8k span labels; 2 annotators × ~60–90 h + adjudication ~20 h + guidelines ~30 h ≈ **220–260 person-hours ≈ $8–15k** (trained annotators) or 2–3 months part-time.

---

## 9. Top-3 Risk Categories — Specific Actions

1. **Assumptions.** Problem: no corpus; ARCHE shows LLMs fail at latent steps; worst recall category. Actions: (a) narrow schema to *stated* assumptions ("we assume", "given that", "taking X as") for v1 — cue-findable, classical-assist; (b) implicit assumptions → frontier-LLM-only, self-consistency ×3, mandatory human review, precision-optimized (false positives cheap, missing not claimed); (c) report as `confidence: low` tier in KG; (d) seed a 500-sentence gold set from annotation program before any scale-up; (e) use ARCHE-Bench (70 papers) as regression probe each model upgrade [^29^].
2. **Alternative explanations.** Problem: sparse, discourse-dependent, high IAA failure risk. Actions: (a) AZ `Contrast` classifier + cue lexicon ("alternatively", "cannot rule out", "equally consistent with") as high-recall pre-filter; (b) LLM structured extraction only on pre-filtered sentences with `alternative_to` edges mandatory; (c) annotation guidelines with ≥10 worked examples incl. near-misses (contrast that is NOT alternative hypothesis); (d) accept κ ~0.5–0.6 and triage disagreements to adjudicator; (e) cluster extracted alternatives per claim to catch multiplicity.
3. **Speculation / hypothesis / opinion boundaries.** Problem: three categories share cue vocabulary ("may", "suggest"); annotators conflate. Actions: (a) define decision tree in guidelines — *testable forward claim? → hypothesis; attitudinal/evaluative + attributed? → opinion; else hedged present claim → speculation*; (b) annotate jointly (same span, 3 label slots + certainty grade) to force explicit boundary decisions; (c) scope resolution (CoNLL-2010 Task2 machinery) mandatory so the speculative proposition is explicit; (d) boundary-sentence triple-annotation with κ tracked per boundary pair; (e) classifier = single multi-label model (shared encoder, 3 heads) trained on joint annotations rather than 3 independent models.

---

### Citations / URLs

[^10^] PubMed 200k RCT paper + repo — https://arxiv.org/abs/1710.06071 ; https://github.com/Franck-Dernoncourt/pubmed-rct
[^11^] Modern sequential-classification result on PubMed 200k (F1 0.9508) — https://pmc.ncbi.nlm.nih.gov/articles/PMC10620359/
[^12^] CoNLL-2010 shared task paper (Task1B best 86.36 Tang; Task2 best 57.32 Morante; cue-level tables) — https://aclanthology.org/W10-3113/ ; proceedings PDF http://www.cs.columbia.edu/~prokofieva/CandidacyPapers/Farkas_Hedging.pdf
[^13^] CoNLL-2010 results recap (bio cue/scope F1s; syntactic features) — https://people.dbmi.columbia.edu/~szhang/conll2010.pdf
[^14^] Epistemic-rhetorical miscalibration (hedge cues "high-precision… highly domain-dependent") — https://arxiv.org/html/2604.19768
[^15^] SciBERT-vs-BioBERT uncertainty detection (BioScope) — https://github.com/PeterZhizhin/BERTUncertaintyDetection
[^16^] Rubin certainty framework (4 levels, dimensions) — discussion https://www.researchgate.net/publication/260178341 ; wide05 [^40^]
[^17^] grobid-quantities DocEng'19 paper (cascade, SI normalization, eval tables, public corpus) — https://inria.hal.science/hal-02294424/file/Automatic_Identification_and_Normalisation_of_Physical_Measurements_in_Scientific_Literature(1).pdf
[^18^] grobid-quantities official evaluation scores (CRF vs BERT_CRF; UNISCOR; weak labels) — https://grobid-quantities.readthedocs.io/en/stable/evaluation-scores/ ; repo https://github.com/grobidOrg/grobid-quantities
[^19^] Evidence Inference + numeric-extraction extension (699 abstracts, ICO triplets) — https://github.com/bwallace/evidence-inference-1 ; https://aclanthology.org/N19-1371 ; https://pmc.ncbi.nlm.nih.gov/articles/PMC12448672/
[^20^] Constrained-decoding survey ("de facto standard"; JSONSchemaBench) — https://arxiv.org/html/2601.17717v3
[^21^] Small-LM structured reliability (0% naive output accuracy; latency/quality costs) — https://arxiv.org/html/2605.02363v1
[^22^] SLOT (Mistral-7B 99.5% schema accuracy, 94.0% content similarity) — https://arxiv.org/abs/2505.04016
[^23^] Structured-output engineering heuristics (Pydantic + retry) — https://alex-jacobs.com/posts/ [LOW]
[^24^] 2026 LLM pricing (GPT-5.5 $5/$30; Claude Opus 4.8 $5/$25; Gemini 3 Flash $0.075/$0.30; batch −50%; cache −75–90%) — https://toolsignal.site/articles/llm-api-pricing-comparison-2026 ; https://www.clawrouters.com/blog/llm-api-pricing-guide-2026
[^25^] Hinglish NER controlled comparison (79.7 vs 62.2) — https://arxiv.org/pdf/2509.02514
[^26^] On-prem clinical NER (0.84 vs 0.45–0.66) — https://www.frontiersin.org/journals/digital-health/articles/10.3389/fdgth.2025.1623922/full
[^27^] Beating BERT (277 vs 12 samples/s) — https://alex-jacobs.com/posts/beatingbert/
[^28^] ASAS comparison studies (fine-tuned BERT/RoBERTa > GPT-4) — https://arxiv.org/html/2605.07647v1
[^29^] ARCHE / ARCHE-Bench (AAAI-26; 70 Nature Communications papers; deductive/inductive/abductive RLTs; LLM limitations) — https://ojs.aaai.org/index.php/AAAI/article/view/37170/41132
[^30^] LLM argument-mining survey — https://arxiv.org/html/2506.16383v3
[^31^] Nanopublication model (assertion/provenance/pubinfo; trusty URI; ECO) — https://link.springer.com/article/10.1007/s00799-025-00431-x
[^32^] Nanopub structure/trusty-URI practice — https://digitalrelics.uk/posts/linked-open-data/nanopublications-heritage
[^33^] ORKG approach + ORKG-Leaderboards — https://arxiv.org/pdf/2308.12981 ; https://arxiv.org/abs/2305.11068
[^34^] INCEpTION platform (Apache-2.0, COLING 2018 demo) — https://github.com/inception-project/inception ; https://aclanthology.org/C18-2002
[^35^] INCEpTION external recommenders (ariadne; spaCy/S-BERT/sklearn) — https://github.com/inception-project/inception-external-recommender
[^36^] inceptalytics (IAA/κ from XMI exports) — https://github.com/catalpa-cl/inceptalytics
[^37^] AZ corpus distribution page (80 papers, 7 zones, κ=0.71, CC BY-NC 2.0 UK) — https://www.cl.cam.ac.uk/~sht25/AZ_corpus.html
[^38^] ART corpus metadata (265 papers; 225 distributable, 35,040 sentences; κ=0.55 phase II; CoreSC labels) — https://www.aber.ac.uk/en/media/departmental/impacs/computerscience/pdfs/Description_ART_Corpus.pdf ; http://www.sapientaproject.com/links
[^39^] DRI corpus (40 papers, 10,784 sentences, 5 rhetorical classes, κ=0.66) — via MuLMS-AZ Appendix E https://arxiv.org/html/2307.02340 ; http://sempub.taln.upf.edu/dricorpus
[^40^] AbstRCT (4,198 components, 2,601 relations; κ 0.72/0.62; partial attack) — https://theses.hal.science/tel-03209489/document ; https://arxiv.org/html/2301.10527
[^41^] SciFact (1,409 claims / 5,183 abstracts; SUPPORTS/REFUTES/NOINFO + rationales) — https://pmc.ncbi.nlm.nih.gov/articles/PMC10919922/
[^42^] BioScope corpus paper — https://pmc.ncbi.nlm.nih.gov/articles/PMC2586758/
[^43^] Sci-Arg corpus + guidelines — https://data.informatik.uni-mannheim.de/sci-arg/ ; https://aclanthology.org/W18-5206

*End of report.*
