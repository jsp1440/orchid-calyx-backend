# Calyx — Dim 12: Cost/Throughput Benchmarks, Failure Modes, Critical Review, Simpler Alternatives

**Role:** adversarial stress-test of the whole proposal. Date: 2026-07-21.
Confidence tags: **[H]** verified primary source; **[M]** credible secondary/extrapolation; **[L]** estimate/analogy.

---

## 1. Verified throughput & cost primitives

| Primitive | Number | Confidence | Source |
|---|---|---|---|
| GROBID throughput | ~10.6 PDF/s on 16-CPU server (short papers; theses at 150+ pp are 10–20× slower per doc, i.e. ~0.5–1 thesis/s) | [H] for headline figure, [M] for thesis derating | wide05 / GROBID docs |
| Marker | ~122 pp/s H100 (~0.6 pp/s L40S consumer GPU per wide05 benchmark) | [H] | wide05 / Marker benchmark |
| gnfinder | ~15M pages/h (taxonomic name-finding, CPU) | [H] | wide05 |
| olmOCR | <$176 per 1M pages (self-hosted pipeline incl. infra) | [H] | wide05 / Ai2 olmOCR report |
| GPT-4o vision OCR | >$6,200 per 1M pages (~35× olmOCR) | [H] | wide05 / olmOCR comparison |
| OpenAlex snapshot | ~330 GB gzip JSONL, ~1.6 TB decompressed; works entity alone ~384 GB; free on S3 (AWS Open Data covers ~$70/download transfer) | [H] | [^1^][^2^] |
| OpenAlex full-text PDFs | ~60M works; **$0.01 per file** content download (paid API) | [H] | [^1^] |
| CORE dataset | 291M metadata records (Feb 2023), ~34–40M full texts; ~100 TB uncompressed incl. PDFs; **393 GB compressed plaintext-only / 3.5 TB uncompressed** | [H] | [^3^] |
| CORE pricing shift | Older dumps free (ODC-BY); **recent dumps now require paid licence or Sustaining Membership** | [H] | [^4^] |
| Avg thesis length | Dissertation-length studies (Beck/Brailsford-type analyses): median ~150–200 pp humanities→STEM; use **170 pp, ~10 MB PDF** as planning figure | [M] | [^5^] |
| PDF storage per 100k theses | 100k × ~10 MB ≈ **1 TB**; 1M theses ≈ 10 TB; S3 standard ≈ $23/TB/mo | [M] | AWS pricing [L] |
| OpenAlex memberships (freemium precedent) | Premium $5k/yr, Premium+ $20k/yr institutions; free snapshot retained but quarterly vs daily refresh | [H] | [^6^] |

### Cost model (one-time build + annual run; excludes free tiers of OpenAlex/CORE dumps)

Assumptions: 170 pp/thesis, 10 MB PDF; H100 rental $2.50/h; 16-CPU VM $0.65/h; LLM scoped pass (dim08) = ~6k input + 2k output tokens/thesis on a Gemini-Flash-class batch model (~$0.10/M in, $0.40/M out) → **≈$1.4 per 1k theses**; GPT-4o-class = ~50× that.

| Item | 10k pilot | 100k | 1M |
|---|---|---|---|
| PDF download bandwidth/storage (in) | 100 GB / ~$2 | 1 TB / ~$25 | 10 TB / ~$250 (one-time egress to ingest ~$90–900 if cloud-to-cloud) |
| Storage $/yr (S3) | ~$28 | ~$280 | ~$2,800 |
| OCR/parse compute (Marker 122 pp/s on H100) | 14 GPU-h ≈ **$35** | 140 GPU-h ≈ **$350** | 1,400 GPU-h ≈ **$3,500** |
| (alternative) olmOCR pipeline | ~$0.30 | ~$3 | ~$30 [H pricing, L applicability] |
| GROBID structuring (1 thesis/s, 16-CPU) | 3 h ≈ $2 | 28 h ≈ $18 | 280 h ≈ $180 |
| gnfinder nomenclature pass | minutes, <$1 | ~$1 | ~$10 |
| LLM scoped passes (Flash-class batch) | ~$15 | ~$150 | ~$1,500 |
| LLM scoped passes (GPT-4o-class) | ~$750 | ~$7,500 | ~$75,000 |
| **Compute+storage subtotal (Flash-class)** | **< $100** | **< $1,000** | **< $9,000** |
| Staff (dominant cost): pipeline eng @ $90k/yr loaded | 0.25 FTE ≈ $22k | 0.5 FTE ≈ $45k | 1.0 FTE ≈ $90k + ~0.25 FTE/yr maintenance |

**Verdict on costs:** compute and storage are rounding errors (even 1M theses < $10k with olmOCR/Flash-class models). **The proposal's real cost is staff time for harvesting plumbing, QA, dedupe, and churn management.** Any budget slide that leads with GPU/LLM cost is misrepresenting the risk profile. Using GPT-4o-class vision/extraction at 1M scale ($75k+) is the only way to make LLMs the dominant line item — avoid it.

---

## 2. Failure-mode catalog (documented)

| # | Failure mode | Evidence | Impact on Calyx |
|---|---|---|---|
| F1 | **Scanned/image-only theses break GROBID** — GROBID assumes born-digital PDFs with text layers; digitized legacy theses (EThOS, ProQuest scans, HathiTrust) need OCR first | GROBID docs/issues [H]; HathiTrust OCR of older digitized texts is noisy, esp. title pages, formulae, non-Latin scripts [H] | Two-track pipeline (born-digital vs scanned) mandatory; scanned fraction in old theses can exceed 30–50% pre-2005 [M] |
| F2 | **Non-English coverage**: GROBID models trained predominantly on English/Western layouts; performance degrades on CJK, RTL, Cyrillic without retraining; Marker multilingual-capable but weaker; abstracts often only in local language | wide05; metadata-quality study: non-English records have worse affiliation/metadata completeness (74.3% of records missing affiliation data entirely) [H] | Brazilian, French, German, Indian, Japanese, Chinese theses (a large share of global ETD output) will yield thinner extracted data [M] |
| F3 | **License-field sparsity**: dc:rights / licence URIs are absent in a large fraction of OAI-PMH records; "OA" in a directory ≠ explicit reuse licence. CORE itself: only ~13% of records have full text and ~48% have any full-text link [H] | CORE Sci Data 2023 [^3^]; OpenAIRE guidelines exist precisely because rights metadata is inconsistently provided [M] | Cannot rely on licence fields for the redistribution/AI-training legal posture; per-source ToS review unavoidable (dim07) |
| F4 | **Repository/OAI endpoint decay**: large-scale crawl of registries found **>1/5 of repositories offline and ~44% of OAI-PMH endpoints dead** (Macgregor 2026, arXiv:2601.04015) [H]; ~25% of HTTP requests to repository URLs fail [H]; reference link rot 13–22% within years, rising to 40–80% for older links [H] | [^7^][^8^][^9^] | A self-harvested source list of hundreds of endpoints decays ~continuously; budget a recurring "endpoint gardener" task |
| F5 | **"Orchid" keyword false positives**: bare keyword "orchid" hits ORCHID acronyms in engineering/medicine (e.g., "ORCHID" trial/project names) and non-botanical uses; wide04's own OpenAlex probes showed title.search "orchid" (527 thesis works) vs Orchidaceae concept (497) diverge → keyword-only recall/precision both poor | wide04 data [H as observed]; inference on precision [M] | Relevance filter must be multi-signal (taxon names via gnfinder + concept + venue), not keyword |
| F6 | **Cross-aggregator duplicates**: OpenAIRE dedupe studies report ~52% duplication for publications across sources [H]; CORE describes multi-version same-paper problem requiring locality-sensitive hashing [H]; NDLTD union catalog double-lists institutions (e.g., "Texas A and M" twice, "Robert Gordon University" 0 and 518) [H] | [^3^][^10^] | Expect 30–50% raw duplication when combining OATD + CORE + OpenAlex + direct OAI; dedupe is a first-class pipeline stage, not an afterthought |
| F7 | **Metadata thinness in theses vs articles**: type field inconsistent ("thesis"/"dissertation"/genre tags), advisor rarely in OAI-DC, no DOI for most ETDs (NDLTD union: OCLC collection 1.2M records, ProQuest only 18.7k with DOI-able presence) | NDLTD stats [^11^] [H] | Citation-graph/impact features will be sparse for most of the corpus |
| F8 | **OCR quality of digitized legacy theses**: HathiTrust-era scans: skew, show-through, degraded type → OCR WER materially higher; marker/olmOCR handle born-digital well but handwritten annotations/typewriter text fail | HathiTrust OCR quality literature [H/M] | Legacy backfile (pre-1990 digitized) should be explicitly out of Phase-1 scope |

---

## 3. Critical-review evidence pack (for Part 10)

**Technical obstacles.**
- Endpoint decay (F4): 44% dead OAI-PMH endpoints; one-quarter of repository HTTP requests fail [^7^][^8^]. Harvesting is a maintenance treadmill, not a one-shot crawl.
- Format heterogeneity: OAI-DC vs ETD-MS vs QDC/MODS (OpenEdition supports 5 formats) — normalisation effort per source [^12^].
- Scanned-PDF two-track problem (F1/F8).

**Legal obstacles.**
- Licence sparsity (F3): most OAI records carry no machine-readable licence; only ~13% of CORE records have full text at all [^3^]. Redistribution and LLM-training rights must be established per repository ToS; EU TDM exception helps for research mining but not for redisplay.
- Embargo culture: ~10% of ETDs not freely available (up to 26%+ excl. ProQuest figures; France 17% embargoed + 9% campus-only; Amherst 52% restricted; Maryland 32%) [^13^][^14^]. Embargo lifts require re-harvest logic.

**Scaling challenges.**
- Dedupe at 30–50% raw duplication (F6); multi-version linking [^3^].
- OpenAlex snapshot at 330 GB/1.6 TB is a real data-engineering barrier (Leiden Madtrics: "fundamental barrier for many users") [^15^].
- LLM cost cliff if using frontier models for full-text (GPT-4o $6,200/M pages vs olmOCR $176/M pages) — a 35× discipline test [H].

**Scientific limitations.**
- Theses ≠ peer-reviewed: defence-committee review only; ~41% of traditional-format nursing PhD dissertations **never** produced a peer-reviewed publication (retrospective cohort, n=113) [^16^] → corpus mixes validated and unvalidated claims.
- Negative-results bias cuts both ways: meta-analyses include theses *precisely because* they reduce publication bias (Rothstein; PRISMA grey-lit guidance) [^17^] — a genuine scientific *asset* of a thesis corpus, but it means effect sizes differ systematically from journal literature [M].
- Advisor-prestige / institutional bias: bibliometric studies of thesis corpora show heavy concentration (e.g., 86 professors supervising 304 theses; 91% male PhD holders in one Bangladeshi faculty sample) [^18^] — corpus inherits supervision-network inequities.

**Bias risks.**
- OA-bias: French-German survey (16,508 theses): only **38% disseminated digitally, 84% of those OA → ~32% of all theses OA**; France 12–24%, Germany 41–47% (2009–2012, improving since) [^13^]. A harvest-only corpus systematically misses ProQuest-locked North-American backfile and print-only Global-South output (India: >1M theses in universities, ~65k in Shodhganga at survey time) [^19^].
- English/Global-North bias: non-English records have measurably worse metadata completeness [^20^]; repository infrastructure (and surviving endpoints, F4) concentrates in EU/North America → coverage skew is structural, quantifiable, and must be reported per-source.

**Maintenance burden.**
- Repository churn (F4) + format migrations + dedupe rule tuning ⇒ budget ≥0.25 FTE/yr indefinitely, or the corpus silently rots (same mechanism documented for link rot: availability drops ~17% per 3 years in LIS-journal URL cohorts) [^9^].

**Long-term sustainability.**
- OpenAlex has already moved to freemium: free quarterly snapshot vs paid daily; full-text PDFs $0.01/file; institutional memberships $5k–$20k/yr [^1^][^6^]. "Free forever API" is not a safe planning assumption.
- CORE: older dumps free ODC-BY, **recent dumps behind paid licence/Sustaining Membership**; 15-year survival depended on Jisc grants, OU hosting, Microsoft multi-year funding [^4^][^21^]. Precedent: free tiers shrink.
- Calyx itself needs a funding model line item; "volunteer + grants" is the failure mode CORE/OpenAlex explicitly engineered away from.

---

## 4. Simpler alternatives — comparison matrix

| Option | You gain | You lose | Cost | Time-to-value |
|---|---|---|---|---|
| **(a) Metadata-only corpus + link-out** (OATD-style: 5M+ records, no full text) | Zero OCR/parse/storage burden; no licence risk for full text; index live in weeks | No nomenclature mining (gnfinder needs text); no trait/distribution extraction — the core scientific value of Calyx; link-out suffers rot (F4: ~44% endpoints dead) | <$5k/yr + 0.2 FTE | 4–8 weeks |
| **(b) License ProQuest PQDT + TDM Studio** | 2M+ theses incl. backfile and embargoed corpus; legal TDM clarity; no harvesting | $$$ subscription (TDM Studio licences typically five figures/yr/institution [M]); vendor lock-in; redistribution/derived-data restrictions; misses non-ProQuest world (Europe/LatAm/Asia OA theses) | $20k–60k/yr [M] | 1–3 months (contracting is the bottleneck) |
| **(c) Partner with CORE/OpenAIRE** | Their dedupe, endpoint-gardening, and enrichment already exist; CORE openly wants partners (SHARE/LLM projects) | Roadmap dependency; CORE recent dumps now paid/licensed [^4^]; thesis-specific enrichment (advisor, taxa) still yours to build | Membership/licence $5k–25k/yr [M] | 2–4 months |
| **(d) Narrow orchid-only curated corpus (~5–10k docs), semi-manual** | Directly serves the actual user need (Orchid Continuum); QA-able by domain experts; high precision | Not "automated ingestion at scale"; recall limited; doesn't prove the pipeline | 0.5 FTE × 3–4 months | ~3 months |
| **(e) OpenAlex snapshot + free CORE dump only, zero direct harvesting** | Two downloads replace 1,000 fragile endpoints; OpenAlex has `type: dissertation` works + OA URLs; dedupe largely pre-done; full-text via OpenAlex OA links / CORE plaintext (393 GB) | Inherits upstream lag and gaps (theses under-typed in OpenAlex [M]); CORE full text only ~13% of records; no control over refresh | ~$70 transfer + <$2k compute [H] | 2–6 weeks |

**Honest assessment:** (e) dominates (a)–(d) as the *first* move — it is strictly cheaper, faster, and deletes the highest-risk component (direct OAI harvesting of decaying endpoints). (d) is the best *product* move if the goal is serving orchid researchers this year. (b) is only worth it if the North-American embargoed backfile is scientifically essential. (a) alone is a catalogue, not a corpus.

---

## 5. Phase-1 recommendation (evidence-based)

**Smallest pipeline that works, 6 months, ~1 FTE + 0.25 domain curator:**

1. **Sources (6, no direct long-tail OAI):** OpenAlex snapshot filter `type=dissertation` + OA locations [^1^]; CORE free older dump (plaintext) [^3^][^4^]; OATD metadata (5.0M records) [^22^]; DART-Europe OAI-PMH (single national-aggregator endpoint, not per-university); NDLTD union catalog [^11^]; BDTD/IBICT Brazil (631k records — biggest single non-English ETD source) [^11^].
2. **Dedupe first** (OpenAlex ID > DOI > title+year fuzzy; expect 30–50% dupes, F6).
3. **Download only OA-flagged PDFs** for the orchid-relevant subset after multi-signal relevance filter (gnfinder taxon hit OR Orchidaceae concept OR venue), not keyword "orchid" alone (F5).
4. **Born-digital → GROBID; scanned → olmOCR** ($176/M pages) — never GPT-4o-vision at scale.
5. **gnfinder + scoped LLM pass (Flash-class batch)** on abstract/introduction/conclusion only (~8k tokens/doc ⇒ ~$150 per 100k docs).
6. **Skip:** legacy pre-1990 scanned backfile, embargo chasing, >100-endpoint direct OAI harvesting.

**Effort comparables:** CORE started as a Jisc grant for "6 person-months to aggregate 20 UK repositories" [^21^]; NDLTD union harvest of ~6.5M records is a standing small-team service [^11^]. A 6-source, dump-first pipeline at 1 FTE/6 months is consistent with these; a 500-endpoint self-harvest is not.

**Go/no-go metrics for Phase-1:** ≥30k orchid-relevant theses with parsed full text; ≥85% dedupe precision on a 500-doc audit; ≤$5k total compute; per-source licence register completed for every redistributed item.

---

## Sources
[^1^] OpenAlex Developers — Download overview (snapshot 330 GB/1.6 TB; PDFs $0.01/file): https://developers.openalex.org/download/overview
[^2^] OpenAlex — Download to your machine (AWS covers ~$70 transfer): https://developers.openalex.org/download/download-to-machine
[^3^] Knoth et al., "CORE: A Global Aggregation Service for Open Access Papers", Scientific Data 2023 (291M records; 13% full text; 100 TB; 393 GB plaintext; dedupe via LSH): https://www.nature.com/articles/s41597-023-02208-w.pdf
[^4^] CORE Dataset service page (older dumps free ODC-BY; recent dumps paid/Sustaining Members): https://core.ac.uk/services/dataset
[^5^] Dissertation length data/discussions: e.g., Beck, "Dissertation by the numbers" (flowingdata.com/2016/05/12/length-of-the-average-dissertation/); thesis length norms 50–300 pp.
[^6^] OpenAlex pricing/membership: https://openalex.org/pricing (Premium $5k/yr; Premium+ $20k/yr)
[^7^] Macgregor, G. (2026), repository/OAI-PMH persistence study (>1/5 repos offline; ~44% OAI endpoints dead): https://arxiv.org/abs/2601.04015
[^8^] Chen et al. 2025 JCDL (citing: ~25% of repository HTTP requests fail; Hiberlink 13–22% link rot): https://www.cs.odu.edu/~jwu/downloads/pubs/chen-2025-jcdl/chen-2025-jcdl.pdf
[^9^] Reference-rot literature survey (67% URI loss over 4 yrs; LIS URLs −17.4%/3yrs; ETD URL references 23%→80% 1999–2012): https://ceur-ws.org/Vol-3246/10_Paper3.pdf
[^10^] OpenAIRE deduplication (~52% publication duplication across sources): OpenAIRE dedupe documentation, https://graph.openaire.eu/develop/ + wide02.
[^11^] NDLTD Union Archive collection statistics (6.58M records; per-source counts; OCLC 1.2M, IBICT 631k, ProQuest 18.7k): https://ndltdunion.cs.uct.ac.za/
[^12^] OpenEdition OAI-PMH docs (oai_dc / qdc / oai_openaire / mods / mets formats): https://oai-openedition.readthedocs.io/
[^13^] Schöpfel & Prost, French-German ETD survey (38% digital; 84% of those OA; 32% of all theses OA; France/Germany trends): https://hal.univ-lille.fr/hal-01398949v1/document
[^14^] Greynet GL15 empirical panel (~10% of 550k ETDs not free; Amherst/Maryland/Liège/Brazil rates; ProQuest 5% embargoed): https://greynet.org/images/Conference_Proceedings_15,_2014.pdf
[^15^] Leiden Madtrics, Campinas experience (OpenAlex 470 GB+ as barrier): https://www.leidenmadtrics.nl/articles/towards-the-democratisation-of-open-research-information-for-scientometrics-and-science-policy-the-campinas-experience
[^16^] Journal of Nursing Scholarship 2019, dissertation dissemination cohort (41.3% of traditional-format grads never published): summarized at https://www.academia.edu/21700248/Publish_Your_Dissertation_Research
[^17^] Meta-analysis including theses to reduce publication bias (Rothstein; PRISMA 2020): https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2026.1817200/full
[^18^] Bibliometric thesis-corpus studies (advisor concentration; 91.1% male): https://www.researchgate.net/publication/382895047
[^19^] NDLTD ETD2016, Indian ETD survey (>1M theses in Indian universities; ~65k in Shodhganga): https://docs.ndltd.org/metadata/etd2016/37/index.html
[^20^] Metadata-quality study by language (74.3% records missing affiliations; non-English worse): https://microblogging.infodocs.eu/wp-content/uploads/2026/03/document.pdf
[^21^] CORE About/15-year timeline (Jisc 6-person-month origin; Microsoft funding; POSI): https://core.ac.uk/about
[^22^] OATD (5.03M theses indexed from 1,100+ institutions): via https://www.library.ucsb.edu/scholarly-communication/open-access-dissertations
