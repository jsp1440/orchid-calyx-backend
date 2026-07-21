# Calyx Deep-Dive: Idea-Evolution Engine — Link-Type Specifications

**Dimension:** dissertation→article→citation→replication→retraction→taxonomic revision→consensus.
**Researched:** 2026-07-21. 27 targeted searches + live API verification (curl) against Crossref, GitLab (RW repo), GBIF, ChecklistBank, POWO, IPNI beta, S2AG datasets endpoint.
**Builds on:** `calyx_wide06.md` (facts carried forward are re-cited, not re-verified, unless marked live-verified today).
**Confidence tags:** **[HIGH]** = verified via official docs/live API; **[MED]** = multiple agreeing sources; **[LOW]** = single source/inference.

---

## 1. Thesis → Article Lineage (record-linkage spec)

**Data sources.** OpenAlex works `type=dissertation` (~6.1M as of the 2022 arXiv audit; now larger after the Walden DataCite/repository ingest)[^1^][^2^]; DataCite `resourceTypeGeneral=Dissertation` records; institutional-repository OAI-PMH (DSpace/EPrints `dc.type=Thesis`); ProQuest PQDT (commercial, 6M+) only if licensed; NDLTD (6.5M) / OATD (7M+) as free discovery layers.[^2^][^3^] **[HIGH]**

**Method (no turnkey API exists — genuine gap = Calyx opportunity).** Standard entity-resolution pipeline:
1. **Blocking:** (author surname + forename initial, thesis year ∈ [article year − 6, article year + 1]) ∪ (ORCID exact) ∪ (institution ROR + year window). Reference benchmarks: Splink-style probabilistic blocking achieves ~99.9% reduction ratio; TF-IDF string blocking with tuned thresholds reaches P≈0.92/R≈0.86 on bibliographic-style records.[^4^]
2. **Scoring:** RapidFuzz token-set ratio on titles + cosine on SPECTER2 embeddings of thesis abstract vs article abstract (SPECTER2 dataset, Apache-2.0)[^5^] + article→thesis back-citation + advisor-name co-occurrence in acknowledgment text.
3. **Declared-link mining (highest precision, low recall):** acknowledgment/footnote regexes ("this chapter appeared as", "is based on chapter N of the author's dissertation"); DataCite `relationType = IsDerivedFrom / IsSourceOf` and `IsVariantFormOf / IsOriginalFormOf` where repositories deposit them — but deposit practice is sparse (Zenodo analysis: IsDerivedFrom = 19 of ~7k project relations; treat as P≈1.0 bonus signal, not backbone).[^6^] Crossref `relation` field similarly.
4. **LLM adjudication** of top-k ambiguous pairs (the w33944 pattern).[^7^]

**Gold set & evaluation.** Hand-build 300–500 verified pairs from cumulative ("sandwich") theses whose front matter lists constituent papers verbatim — trivially mined from institutional repos; stratify by field/decade/language. Report precision/recall/F1 per signal and combined; expected **P 0.92–0.97, R 0.75–0.88** with author+year blocking + embeddings (benchmarks in [^4^]); declared-link signals P≈1.0 but R<0.2. **[MED]**

**The NBER 2025 method (identified).** NBER Working Paper **w33944**, *"Funding the US Scientific Training Ecosystem: New Data, Methods, and Evidence"* (Shvadron, Zhang, Fleming, Gross; June 2025): 1.2M STEM PhD dissertations 1950–2022 from ProQuest + OpenAlex + institutional repositories; unsupervised LLM classifier (summarize → classify → subfield filter); funding-sponsor extraction from acknowledgment text for ~870k dissertations; validation via quantum-science case study against OpenAlex topic × institution publication counts.[^7^][^8^] Directly portable: their acknowledge-text and LLM screening at million-thesis scale proves feasibility; they note the **absence of ground truth** as the core validation problem — Calyx's gold set fixes this. **[HIGH]**

**Botany adaptation.** Cumulative theses are common in European/Latin-American botany; thesis chapters often become monograph sections rather than papers — add blocking on taxon-name sets (gnfinder-extracted name lists shared between thesis chapter and article = strong signal). Theses that are *effectively published* under the ICN (printed + ISBN/ISSN) may themselves contain valid nomenclatural acts (Melbourne Code worked examples: Rexer's *Mycena* dissertation, Rietema's thesis)[^9^] — flag such theses for the §5 pipeline.

---

## 2. Citation-Context Classification (build-vs-buy)

**Verified infrastructure (live 2026-07-21).**
- **S2AG datasets**: release cadence roughly weekly–biweekly in 2026 (release list live-verified: …2026-06-24, 2026-07-07, 2026-07-14); `citations` dataset = **2.4B records, 30 × 8.5GB**, schema verbatim: `isinfluential`, `contexts`, `intents`; license verbatim **"This collection is licensed under ODC-BY"**; full downloads need free partner key; SPECTER v1/v2 embedding datasets Apache-2.0.[^5^] **[HIGH — live]**
- **OpenCitations**: Index >1.4B DOI→DOI links CC0, REST v2 free token (180 req/min); **CCC (Citations in Context Corpus)** = open citation contexts from Europe PMC XML; CEX trained GROBID citation-context models available.[^10^] **[HIGH]**
- **scite** (buy option): 1.2–1.6B Smart Citations (supporting/contrasting/mentioning); pricing (official, verified June 2026 secondary): **Basic $20/mo (250 MCP credits), Pro $50/mo (2,500 credits), Team $50/user/mo, Enterprise/API = custom quote only**; MCP server `api.scite.ai/mcp`; accuracy independently questioned (supporting/contrasting-vs-mentioning confusion vs expert coding in systematic-review settings).[^11^][^12^] **[HIGH]**

**Cost math (build).** Corpus-wide polarity on Calyx theses: S2AG contexts are free (ODC-BY); downloading citations+papers+s2orc_v2 ≈ 330GB ≈ trivial; a fine-tuned classifier (SciFact/SciCit-style, distill from LLM labels on ~5k contexts) ≈ $200–500 LLM labeling + 1 GPU-week. scite Enterprise for programmatic bulk = five-figure annual quote at minimum and excludes theses. **Recommendation: BUILD for corpus-wide classification; BUY nothing — optionally use scite MCP Pro ($50/mo) for spot-auditing high-value claims in the UI.** Treat scite labels as signals, never ground truth.[^11^][^12^] **[HIGH]**

**Botany adaptation.** Citation contexts in biodiversity papers are overwhelmingly *mentioning* (floristic citations, basionym references); the useful Calyx classes are: nomenclatural citation (protologue/basionym/synonymy), taxonomic-opinion citation (agree/disagree with circumscription), and distributional citation. Train a small custom classifier on ~2k hand-labeled botany contexts (Label Studio); expect macro-F1 0.75–0.85 given the shallow taxonomy. **[MED/LOW]**

---

## 3. Retraction / Correction Graph

**Live-verified counts (Crossref REST, 2026-07-21):** `filter=update-type:` **retraction = 73,700; correction = 209,348; expression_of_concern = 4,094; withdrawal = 3,375; removal = 697.** (Note: the underscore form `expression_of_concern` is the valid filter value; the hyphenated form silently returns 6.)[^13^] **[HIGH — live]**

**Sources & mechanics.**
- **RW CSV** at `gitlab.com/crossref/retraction-watch-data`: README live-verified — dataset generated **2026-07-20**, updated **every working day**, git-clone/pull workflow (no versioned prior releases — clone daily for history); schema: RecordID, Title, Subject, Institution, Journal, Publisher, Country, Author, URLS, ArticleType, RetractionDate, RetractionDOI, RetractionPubMedID, OriginalPaperDate/DOI/PMID, **RetractionNature ∈ {Retraction, Correction, Expression of concern, Reinstatement}**, **Reason (controlled vocabulary)**, Paywalled, Notes. Free/public post-acquisition (Crossref paid $175k + $120k/yr).[^14^][^15^] **[HIGH — live]**
- **Crossref `update-to`/`updated-by`** blocks: dual `source: publisher | retraction-watch` entries with RW `record-id` join key — Crossmark deposit types: 12 (addendum, clarification, correction, corrigendum, erratum, expression_of_concern, new_edition, new_version, partial_retraction, removal, retraction, withdrawal); in-situ corrections flagged as bad practice.[^16^] **[HIGH]**
- **OpenAlex `is_retracted` error rate (the study):** Hauschke & Nazarovets, *"(Non-)retracted academic papers in OpenAlex"*, arXiv:2403.13339 — **~2,300 incorrectly flagged records** (institutional-repository records misclassified as retracted), affecting API 2023-12-22 → 2024-03-19 and snapshots 2024-01-24/2024-02-27; corrected after author report; repo github.com/hauschke/openalex_retractions. NISTEP's combined RW+OpenAlex ID mapping (Zenodo 14921712) operationalizes the merge-both practice; **retraction reasons exist only in RW data**.[^17^][^18^] **[HIGH]**

**Propagation design.** Edges: `Work —RETRACTED_BY→ UpdateNotice`, `—CORRECTED_BY→`, `—EXPRESSION_OF_CONCERN→`, each carrying `{valid_time: notice date, tx_time: ingest date, source: publisher|RW|openalex}`. Recompute nightly from the RW git pull + Crossref filtered harvest; **union sources, never intersect** (RW ⊄ Crossmark and vice versa — Crossref itself warns both directions of divergence exist).[^14^] Claim-level propagation: retracted Work downweights supporting polarity edges that cite it (post-retraction citations are documented to remain positive — Serra-Garcia & Gneezy: nonreplicable papers cited *more*), so consensus scores must reweight by retraction state, not just count.[^19^] **[HIGH]**

**Botany adaptation.** Formal retractions are rare in taxonomy; the analog is **nomenclatural invalidation** (nom. inval., nom. illeg., nom. superfl.) and **taxonomic recircumscription** — ingest IPNI nomenclatural status + WCVP status changes as the domain's "correction" edge (see §5). **[MED]**

---

## 4. Replication Layer

**Sources, schemas, licenses (verified).**
- **FReD (FORRT Replication Database):** 1,239 original→replication pairs from 336 originals/468 replications (Oct-2023 snapshot; living since); multilevel per-effect rows: original & replication references, study numbers, standardized effect sizes, N, CIs, power, outcome ∈ {success, informative failure, inconclusive, practical failure}, differences metadata; OSF DOI 10.17605/OSF.IO/9R62X, csv+xlsx, **CC BY 4.0**; merged with **FORRT Replications & Reversals** (600+ effects, 22 disciplines) by late 2024; Shiny explorer + reference-list annotator; changelog from Jan 2024.[^20^] **[HIGH]**
- **Curate Science:** 1,127 curated replications (Aug 2018), LeBel et al. framework; **entries folded into FReD**; site archived/unreachable — treat as historical source inside FReD, not a live feed.[^21^] **[MED]**
- **ReplicationWiki:** 4,484 studies / 652 classified replications (2020), economics, Semantic MediaWiki.[^22^] **[MED]**
- **COS Predicting Replicability Challenge:** trains on FORRT's 3,000+ effects; supplies calibrated replicability priors (Brier-scored).[^23^] **[HIGH]**

**Harmonization.** FReD already absorbed OSF-registries, CORE, RPP, Curate Science lists — adopt FReD's per-effect schema as the Calyx `ReplicationPair` edge template: `{original: Work, replication: Work, outcome, effect_sizes, independence}`; dedupe via DOI pairs. **[HIGH]**

**Botany replication — field-specific proxies (no formal replication culture).** Map each FReD slot to a botanical analog: (a) *repeated floristic surveys / resampling plots* (permanent-plot resurvey literature, e.g., forestREplot) = direct/close replication; (b) *re-sequencing of DNA barcodes / phylogenetic re-estimation with expanded sampling* = analytic replication (robustness); (c) *taxonomic re-circumscription* (monograph vs earlier treatment; WCVP status flips v→v+1) = the dominant "original claim vs later test" pair, which Calyx can enumerate *mechanically* from backbone diffs (§5); (d) herbarium re-determination events on specimens. Outcome vocabulary: confirmed / narrowed / expanded / synonymized / rejected. **[MED — design inference]**

---

## 5. Taxonomic Revision Tracking

**Identifier pinning (all verified in wide06 + today).** Per extracted name-string store: `{name, IPNI LSID (urn:lsid:ipni.org:names:…), WFO-ID, GBIF usageKey, POWO fqId, WCVP version + taxonID, matchType, confidence}`. GBIF match API live-verified today (Quercus robur → 2878688, ACCEPTED, EXACT, conf 97; backbone CC BY 4.0, DOI 10.15468/39omei).[^24^] POWO `/api/2/` confirmed still Cloudflare-challenged for non-browser clients → **bulk matching must go through WCVP/GBIF downloads, not the POWO API.**[^25^] IPNI has **no public API** (beta exists; empty/unreachable from sandbox today). **[HIGH — live]**

**Version ledger.** WCVP annual DOI'd releases: v12 (2023, 10.34885/jdh2-dr22), v13 (2024, 10.34885/0yex-xv26), v14 (2025, 10.34885/b8fr-km05), and **v15 (Govaerts ed. 2026, DOI 10.34885/rvc3-4d77; extracted 06 Jan 2026 — discovered in ppendemic R-package citation)** — v15 is the current release, newer than wide06 assumed.[^26^] License CC BY 3.0 (Kew IR) / CC BY 4.0 (GBIF copy). **[HIGH]**

**Synonym-drift quantification (method + expected magnitude).** Method: download v12…v15 zips (~100MB each, sftp.kew.org); inner-join on `taxonID`; compute per-name status transitions (synonym→accepted, accepted→synonym, family reassignment, unplaced→placed) and accepted-name remapping for a sample of thesis-era name strings. Magnitude priors: WCVP 2021 paper — 1,383,297 names, 342,953 accepted species, **925,561 synonyms (67% of all names)**, ~500,000 edits in 2019 alone, edited daily/updated weekly → expect **order 1–5% of accepted-concept assignments to change per annual version** (v12→v15 cumulative likely 3–8%); publish the measured number as Calyx's "taxonomic volatility index." **[MED]** (No official per-version release notes with transition counts were found — the diff itself is Calyx's contribution. **[HIGH]** for absence.)

**ChecklistBank diff (live-verified).** `api.checklistbank.org` serving: COL latest release = **COL26.7 (key 315777, DOI 10.48580/dgyhw, 5,413,595 usages, imported 2026-07-14)**; 27 releases from COL project key 3 (`origin=release&released_from=3`); documented dataset-compare/**"Show diff"** tool (WCVP-Fabaceae vs COL21 example, CSV export, name+authorship+synonym toggles); dataset aliases `3LR` (latest release), `COLyy` annual; colrapi Ruby wrapper for the API.[^27^] **[HIGH — live]**

**Nomenclatural acts in theses.** gnfinder detects scientific names **plus nomenclatural annotations** — verbatim: "Detection of nomenclatural annotations like `sp. nov.`, `comb. nov.`, `ssp. nov.`, `nom. nov.` and their variants" (incl. no-space variants `sp.nov.`); ~15MB binary + REST API; 50M pages in ~3h on 40 threads.[^28^] Cross-check flagged acts against IPNI records: for **plants, IPNI registration is NOT mandatory** (post-publication indexing; pre-publication registration only piloted with PhytoKeys/PLoS ONE/Kew Bulletin; fungi require MycoBank/Index Fungorum IDs since 2013) — so a thesis `sp. nov.` missing from IPNI is either (a) not effectively published (the usual case — theses need printed+ISBN status, cf. Melbourne Code worked examples) or (b) a genuine indexing gap → route to human review, it's a nomenclatural event worth recording.[^9^][^29^] **[HIGH]**

**Versioned edge representation.** `NameUsage —CURRENTLY_ACCEPTED_AS→ NameUsage` with `{backbone: "WCVP", version: "v14", valid_time: [v14 release, v15 release), tx_time: ingest}`; the 1998-thesis name keeps its verbatim string + matched ID, and the accepted target is resolved per version — a query "accepted name at time T" = edge whose valid_time contains T. **[HIGH — design]**

---

## 6. Consensus Reconstruction

- **ORKG:** comparisons receive **DataCite DOIs**; publishing creates **immutable snapshots with PROV-O provenance chains** linking successive versions; SHACL-validated templates; REST + SPARQL; backend MIT. This is the reference implementation of "versioned claim synthesis."[^30^] **[HIGH]**
- **Claim clustering (Calyx design):** SciFact-style pipeline — extract atomic claims from abstracts/conclusions → embed (SPECTER2) + cluster → attach citation-context polarity (§2 classifier on S2AG/CCC contexts) → weight each polarity vote by citing-work retraction/correction state (§3) and recency → output consensus state ∈ {supported, contested, refuted, unresolved} per claim-cluster, versioned as an ORKG-comparison-like DOI'd snapshot. SciFact's `claims_with_citances.jsonl` (claims ↔ generating citances) is the direct training-format template; note SciFact corpus license CC BY-NC 2.0 (training-data caveat).[^31^] **[MED]**
- **Botany consensus proxies:** POWO/WCVP acceptance state per WCVP version (accepted/synonym/unplaced + recorded *references supporting and disagreeing* with each decision — WCVP already stores pro/con taxonomic references per record, making it a native claim-polarity store);[^32^] Flora treatment agreement across WFO's 30+ digitized floras; IUCN Red List assessment history per taxon. **[HIGH]**

---

## 7. Temporal Knowledge-Graph Model — Recommendation

**Model.** Bitemporal edges: every edge carries `valid_time` (when the fact held in the world — publication date, backbone version interval, retraction notice date) and `transaction_time` (when Calyx learned it — ingest timestamp). Formal basis: TPGM bitemporal property graph (Rost et al.); BiTRDF (Tansel et al. 2025) if RDF-native.[^33^] Non-negotiable for Calyx: it is the only way to answer "what did the graph claim about X as of 2015?" after later corrections — corrections overwrite *asserted* truth without destroying *recorded* truth.

**Store choice — recommend ORKG-style snapshot chains on Apache Jena/qlever (RDF, named graphs per snapshot + PROV-O provenance), NOT TerminusDB as primary store.** Rationale: (1) Calyx's temporality is dominated by *externally versioned snapshots* (WCVP v12–v15, GBIF backbones, S2AG releases, OpenAlex monthly dumps, RW daily CSVs) — snapshot-diff + provenance is the natural model; (2) SPARQL over named graphs gives point-in-time queries without proprietary tooling; (3) ORKG proves the pattern in production for exactly this "research-contribution evolution" use case; (4) TerminusDB's git-for-data is attractive for the *curated* layer (gold sets, hand-verified lineage edges) — use it there, secondarily; its license history (Apache-2.0 now, AGPL-era confusion) and 2024 ownership transition add verification burden.[^30^][^34^] **[MED]**

---

## Build Order

1. **M0 — Ingest + pinning:** OpenAlex snapshot + Crossref harvest; RW CSV git-clone (daily); gnfinder name extraction; GBIF/WCVP v15 match table. *(Feeds everything else.)*
2. **M1 — Retraction/correction graph:** update-type harvest, union-source merge, `updated-by` chains, flag propagation. *(Cheapest high-value; all infra verified live.)*
3. **M2 — Citation contexts:** S2AG citations dataset + intents/influential joins; polarity classifier v1.
4. **M3 — Thesis→article linker v1:** blocking + RapidFuzz + SPECTER2 + gold-set eval (300–500 pairs); declared-link mining as P≈1 bonus.
5. **M4 — Taxonomic ledger:** WCVP v12–v15 diff pipeline, versioned accepted-as edges, nomenclatural-act detection + IPNI reconciliation.
6. **M5 — Replication proxies + claim clusters:** FReD schema adoption; botanical proxy edges; consensus snapshots w/ DOIs.
7. **M6 — Bitemporal serving layer:** named-graph snapshots + PROV-O; ORKG-style comparison publishing.

## Top Risks
1. **OpenAlex freemium shift (2026):** API key required since Feb 2026, credit pricing — snapshot-first is mandatory; live API calls from this sandbox were already blocked without a key. **[HIGH — live]**
2. **POWO Cloudflare guard / no IPNI API:** bulk taxonomy resolution must use downloads (WCVP zips, GBIF backbone) + IPNI reconciliation service; API scraping will fail. **[HIGH — live]**
3. **Gold-set absence for thesis→article links** (w33944 hit the same wall) — front-load gold-set construction before tuning claims. **[HIGH]**
4. **No official WCVP per-version release notes:** synonym drift must be computed, not looked up. **[HIGH]**
5. **SciFact CC BY-NC + S2AG ODC-BY attribution/share-alike obligations** in any redistributed derived data. **[HIGH]**

---

## URL List

1. https://arxiv.org/pdf/2206.14168v1.pdf (OpenAlex 2022 audit: 6,126,640 dissertations)
2. https://developers.openalex.org/api-reference/authentication (2026 key/credit model; snapshot CC0)
3. https://eca.libguides.com/az/databases (NDLTD 6.5M); https://rua.ua.es/dspace/bitstream/10045/141258/25/ (OATD >7M)
4. https://repositorio-aberto.up.pt/bitstream/10216/161726/2/689506.pdf (string-blocking P0.92/R0.86 benchmarks); https://sal.aalto.fi/publications/pdf-files//theses/mas/tseg23_public.pdf (Splink/TF-IDF blocking, 99.93% reduction)
5. https://api.semanticscholar.org/datasets/v1/release/latest (ODC-BY verbatim; citations 2.4B/30×8.5GB; contexts/intents/isinfluential schema) ; https://api.semanticscholar.org/datasets/v1/release/ (live 2026-07-21: latest 2026-07-14)
6. https://metadatagamechangers.com/blog/2023/5/2/project-metadata-in-datacite (relationType sparsity in the wild); https://datacite-metadata-schema.readthedocs.io/en/4.6/appendices/appendix-1/relationType/
7. https://www.nber.org/system/files/working_papers/w33944/revisions/w33944.rev0.pdf (NBER w33944 — Funding the US Scientific Training Ecosystem; ProQuest+OpenAlex+LLM, 1.2M dissertations, quantum validation)
8. https://www.purdue.edu/newsroom/in-the-news/which-universities-mint-the-most-phds-in-key-technology-areas/ (w33944 press summary; authors; 870k sponsor extractions)
9. https://www.iapt-taxon.org/historic/2012.htm (Melbourne Code worked examples: effectively-published theses; Rexer Mycena; Brandenburg; Rietema)
10. https://zenodo.org/records/8302170 (OpenCitations Index >1.4B CC0); https://api.opencitations.net/index ; https://digibug.ugr.es/bitstream/handle/10481/109407 (CCC)
11. https://www.rfp.wiki/artificial-intelligence/ai-agents-research-automation/scite/consensus (scite official pricing verified Jun 2026: Basic $20, Pro $50, Team $50/user, Enterprise/API custom; MCP credits; accuracy caveats)
12. https://pmc.ncbi.nlm.nih.gov/articles/PMC8608186/ (scite review; Smart Citation mechanics); https://theaiagentindex.com/agents/scite-ai (MCP endpoint)
13. https://api.crossref.org/v1/works?filter=update-type:retraction&rows=0 (live 2026-07-21: retraction 73,700; correction 209,348; expression_of_concern 4,094; withdrawal 3,375; removal 697)
14. https://gitlab.com/crossref/retraction-watch-data (README live: generated 2026-07-20; daily working-day updates; full column schema; RetractionNature values); https://community.crossref.org/t/ticket-of-the-month-december-2024-retraction-watch-tips/12991 (Crossmark≠RW divergence warning)
15. https://www.crossref.org/blog/retraction-watch-retractions-now-in-the-crossref-api/ (update-to JSON example; source: publisher|retraction-watch; record-id join)
16. https://www.crossref.org/documentation/crossmark/participating-in-crossmark/ (12 update types; in-situ correction caveat)
17. https://arxiv.org/pdf/2403.13339 (Hauschke & Nazarovets: ~2,300 false is_retracted records; affected windows); https://github.com/hauschke/openalex_retractions/
18. https://zenodo.org/records/14921712 (NISTEP combined RW+OpenAlex IDs; reasons only in RW)
19. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9382220/ (Serra-Garcia & Gneezy: nonreplicable cited more; post-retraction positive citations)
20. https://pmc.ncbi.nlm.nih.gov/articles/PMC12270267/ (FReD schema, 1,239 pairs, outcomes, CC BY 4.0, OSF 9R62X, FORRT merger)
21. https://open.lnu.se/index.php/metapsychology/article/view/843/1835 (Curate Science 1,127 replications, 2018); https://web.archive.org/web/20220128104303mp_/https://curatescience.org/app/replications
22. https://blog.repec.org/2020/08/04/a-replication-database-for-economics-and-social-sciences-the-replicationwiki/ (ReplicationWiki 4,484/652)
23. https://www.cos.io/predicting-replicability-challenge (FORRT 3,000+ effects; Brier)
24. https://api.gbif.org/v1/species/match (live-verified 2026-07-21); https://api.gbif.org/v1/dataset/d7dddbf4-2cf0-4f39-9b2a-bb099caae36c (backbone CC BY 4.0, DOI 10.15468/39omei)
25. https://powo.science.kew.org/api/2/ (live 2026-07-21: Cloudflare "Just a moment" challenge confirmed)
26. https://cran.rstudio.org/web/packages/ppendemic/refman/ppendemic.html (WCVP v15: Govaerts ed. 2026, DOI 10.34885/rvc3-4d77, extracted 06 Jan 2026); https://kew.iro.bl.uk/concern/datasets/042a9f96-41a9-4896-9e80-c89586e68363 (v14 DOI 10.34885/b8fr-km05, CC BY 3.0)
27. https://api.checklistbank.org/dataset/3LR (live: COL26.7, key 315777, DOI 10.48580/dgyhw, 5.41M usages, 2026-07-14); https://docs.gbif.org/course-checklistbank-tutorial/ (Show-diff tool, CSV); https://github.com/SpeciesFileGroup/colrapi
28. https://github.com/gnames/gnfinder (verbatim: sp. nov./comb. nov./ssp. nov./nom. nov. detection; throughput; REST API); CHANGELOG v1.1.3–1.1.4 (nom. nov., sp.nov. no-space)
29. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4741224/ (IPNI = post-publication indexing; plants registration NOT mandatory; fungi MycoBank mandatory 2013); https://www.apsnet.org/edcenter/apsnetfeatures/Pages/Melbourne.aspx
30. https://www.emergentmind.com/topics/open-research-knowledge-graph-orkg (ORKG: DataCite DOIs, immutable snapshots, PROV-O chains, SHACL); https://api.github.com/repos/TIBHannover/orkg-backend (MIT)
31. https://github.com/allenai/scifact (claims_with_citances.jsonl); https://arxiv.org/pdf/2104.08663 (CC BY-NC 2.0)
32. https://pmc.ncbi.nlm.nih.gov/articles/PMC8363670/ (WCVP 2021: 1,383,297 names / 342,953 accepted / 925,561 synonyms; pro/con references recorded per decision; ~500k edits 2019)
33. https://vbn.aau.dk/files/645431833/TGDK.1.1.11.pdf (TPGM bitemporal property graph survey); https://www.mdpi.com/2227-7390/13/13/2109 (BiTRDF)
34. https://terminusdb.org/ (Apache-2.0 verbatim; git-for-data); https://gdb-engines.com/db/terminusdb/ (license-history conflict)
