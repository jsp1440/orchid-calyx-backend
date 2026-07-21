# Calyx: Automated Discovery, Acquisition, and Analysis of Graduate Botanical Research — An Implementation Research Report

## Executive Summary (~900 words)
### Key Findings
#### The discovery layer is solved (OpenAlex XPAC 20.26M dissertation-typed records; DataCite 818k thesis DOIs; NDLTD union 7.9M records); the defensible asset is a rights-verified document store, not an index
#### Phase 1 = six acquisition channels, not 600 endpoints: OpenAlex snapshot + Content API, CORE dump, NDLTD union OAI, theses.fr, EThOS CSV, plus ~10 verified Tier-1 botanical OAI endpoints
#### Orchid research geography inverts harvesting priority: botanical value and acquisition difficulty are anti-correlated (Latin America / S/SE Asia / South Africa vs. easy US/EU sources)
#### Reasoning-extraction quality is gated by a gold annotation set (~12 chapters, $8–15k), not by model choice; LLMs scoped to pre-filtered spans only
#### Compute is trivial (<$5k at 100k-thesis scale); the true costs are dedupe (30–50% raw duplication), rights adjudication, and 0.5–1 FTE endpoint gardening
#### Legal posture: 5 hard rules fully automatable as a policy engine (lawful access, no non-CC redistribution, machine-readable opt-outs, license-gated default, locality fuzzing)

## 1. Global Repository Survey (~3,500 words, 3 tables, 1 chart)
### 1.1 The Global ETD Landscape in 2026
#### 1.1.1 Market structure: three tiers — commercial silos (ProQuest PQDT ~5.5M citations, licensed, no API), open aggregators (OpenAlex, CORE, NDLTD, OATD 7.46M), national/institutional repositories
#### 1.1.2 Consolidation and churn: DART-Europe closed Feb 2025; CiNii Dissertations ended 2025-05-12; NARCIS dead 2023; OpenAlex freemium shift 2026; 44% of OAI-PMH endpoints dead (Macgregor 2026)
### 1.2 Americas and Global Aggregators
#### 1.2.1 NDLTD union archive live at ndltdunion.cs.uct.ac.za/OAI-PMH: 7.9M records, 212 sets, 6 metadata prefixes — primary global harvest channel
#### 1.2.2 OATD (7.46M OA-ETD index) unscrapable but its 1,100+ source list recoverable via Wayback; EBSCO Open Dissertations 1.4M as discovery layer
#### 1.2.3 ProQuest PQDT: licensed-only; TDM Studio permits metadata export (10 datasets × 2M docs, 15 MB/week cap) but never full text
#### 1.2.4 HathiTrust: HathiFiles monthly dumps + Extracted Features; no thesis genre field — MARC 502 heuristics required; Theses Canada via NDLTD LACETR set (199,832 records)
### 1.3 Europe
#### 1.3.1 theses.fr: best-in-class — OAI (staroai.theses.fr), ddc:580 botany set + diffusable full-text set, Etalab Open Licence 2.0, REST API, stale-2024 data.gouv.fr dump
#### 1.3.2 EThOS post-relaunch: 650k+ records, CC0 CSV (v9, 610,535 records), ~65% institutional full-text links, no central PDFs
#### 1.3.3 DNB: dnb:reiheH Hochschulschriften set tree incl. sg580 Botanik, OAI+SRU, CC0 GND; plus TDR, NVA (DegreePhd 36,162), RCAAP, EADD, WUR
### 1.4 Asia, Latin America, Africa, Oceania
#### 1.4.1 Shodhganga (600k+ theses) geo-blocked — fallback via OpenAlex source records with direct bitstream URLs; KrishiKosh DSpace 7
#### 1.4.2 CNKI international access restored April 2024 but licensed-only; Japan IRDB OAI live (4.6M records also in OpenAlex); RISS OpenAPI application-based; Trove API v3 bulkHarvest
#### 1.4.3 LA Referencia OAI live (1.48M records) but portal Anubis-blocked; BDTD ~779k behind Oasisbr interstitial; national nodes (UNAM, UChile) harvestable
### 1.5 Ingestion Suitability Ranking
#### 1.5.1 Master ranking table: all surveyed repositories scored on access protocol, bulk capability, license clarity, full-text resolvability, botanical relevance
#### 1.5.2 Tier assignment: Tier-A direct harvest (7 sources), Tier-B aggregator-mediated, Tier-C partnership/licensed, Tier-D excluded (with rationale)

## 2. Botanical Priority Sources (~2,500 words, 2 tables, 1 chart)
### 2.1 Where Orchid Dissertations Live
#### 2.1.1 OpenAlex orchid census: 5,767 dissertations mention "orchid"; 2,296 Orchidaceae; 527 orchid-in-title; 497 Orchidaceae-concept — and why keyword/concept counts diverge
#### 2.1.2 Regional concentration: Latin America (388/2,296), S/SE Asia (UPM 21 orchid-title; Shodhganga 42), South Africa (UCT 36, UKZN 24), Europe (Kew/Leiden/Czech NUŠL), Oceania (ANU/UWA terrestrial + OMF)
### 2.2 Tier-1 Botanical Harvest List
#### 2.2.1 Verified endpoints with measured yields: Leiden OpenDissertations 7,764 records; Kew Research Repository 9,361 (highest orchid precision per record); OpenUCT; UH ScholarSpace; Bayreuth; Imperial Spiral; KU Leuven
#### 2.2.2 The mycoheterotrophy triangle (Bayreuth/Leuven/Imperial) and pollination school (UKZN) — small counts, unique value
#### 2.2.3 Blocked-but-valuable: UKZN (firewall), Shodhganga (geo), UCL/QMUL/RHUL (WAF) — workaround protocols per source
### 2.3 Botanical Institution Libraries and Coverage Gaps
#### 2.3.1 Kew, MOBOT, NYBG, Smithsonian: which host theses directly vs. via partner universities (CUNY Academic Works dataPolicy restricts robot harvest — permission required)
#### 2.3.2 Topic→lab map: mycorrhiza (Bayreuth/Imperial/Leiden/Leuven/UWA/ANU), pollination (UKZN/Brazil), taxonomy (Kew/Leiden/JBRJ/UNAM/UPM)
#### 2.3.3 The anti-correlation problem: orchid value concentrates where infrastructure is weakest — hard-region strategy required

## 3. Technical Access Mechanisms (~2,500 words, 2 tables)
### 3.1 Protocol Landscape
#### 3.1.1 OAI-PMH 2.0 as the dominant channel: verbs, resumptionToken, sets, deletedRecord policies, granularity; oai_dc vs oai_etdms/TEF/XOAI metadata richness
#### 3.1.2 REST APIs: OpenAlex ($1/day free credits), DataCite, NVA, theses.fr, Trove v3, RISS OpenAPI; GraphQL (DataCite retiring 2027); SRU (DNB, Swepub)
#### 3.1.3 Bulk channels: OpenAlex quarterly snapshot (~330 GB JSONL + Parquet), CORE dump + FastSync, data.gouv.fr, HathiFiles, WCVP annual snapshots
### 3.2 Connection Matrix
#### 3.2.1 Per-channel matrix: endpoint, method, auth, rate limits/etiquette, license metadata availability, full-text resolution pattern, documentation URL — for all Tier-A/B sources
#### 3.2.2 OpenAlex Content API as full-text channel: 60M+ OA PDFs + GROBID TEI at content.openalex.org, $0.01/file, 62M-row Parquet manifest
### 3.3 Identifier and Resolution Infrastructure
#### 3.3.1 PID stack: DOI (Crossref 1.06M dissertations vs DataCite 818k), Handle, URN:NBN, OAI IDs; Unpaywall keys on Crossref only (misses DataCite theses)
#### 3.3.2 Dedupe crosswalk precedence: DOI > Handle > URN:NBN > OAI ID > canonical URL > title+author+year fuzzy (≥0.92 auto-merge, 0.85–0.92 review)

## 4. Automated Ingestion Workflow (~2,800 words, 2 tables, 1 mermaid diagram)
### 4.1 Reference Pipeline
#### 4.1.1 Improved 14-stage pipeline: registry census → Identify-probe → incremental harvest (scythe, from = last_run − 2d) → tombstone processing → rights engine → decision matrix → registration (InvenioRDM) → polite download → dedupe → structure parse → entity/reasoning extraction → cross-reference → review queue → publication
#### 4.1.2 Queue architecture: Celery + RabbitMQ replicating CORE's CHARS pattern; Prefect orchestration; persistent resumptionToken checkpoints
### 4.2 Rights Verification as a Machine
#### 4.2.1 License extraction cascade: DataCite rightsURI → dc:rights/oai_etdms rights → CC REL (RDFa/XMP) → repo-default policy → human review
#### 4.2.2 Decision matrix: auto-allow (CC + open) / metadata-only / human-review lanes; embargo tracking via OAI deleted records (72h SLA)
### 4.3 Acquisition, Dedupe, and Provenance
#### 4.3.1 Polite full-text acquisition: per-host token bucket (1 req/2s), aggregator-first fallback (OpenAlex Content API, CORE, HTRC), ClamAV quarantine, SHA-256 content-addressed store
#### 4.3.2 Provenance: W3C PROV-O per activity; raw XML WORM retention; license snapshot at acquisition time; nanopublication-compatible registration
#### 4.3.3 Registry: InvenioRDM v13 with calx: UUIDv7 IDs, alternateIdentifiers crosswalk, OAI provider for re-exposure, annual snapshot DOIs (WCVP model)

## 5. Document Structure Recognition (~2,500 words, 2 tables)
### 5.1 Parsing Architecture
#### 5.1.1 Two-engine design: GROBID 0.8.2+ (references/sections/citations, ~0.87–0.90 F1 refs, 10.6 PDF/s) + Docling (MIT, page/bbox provenance) default layout; MinerU for scanned tier; Marker branch pending weight-license review
#### 5.1.2 The thesis-scale problem: no tool natively segments chapters; READoc v2 shows ~22 TEDS drop heading→tree across all systems; ETD bookmarks unreliable pre-2026
### 5.2 The Fifteen-Element Recognition Map
#### 5.2.1 Structural elements (Abstract, M&M, Results, References, Figures, Tables, Appendices, Supplementary): method per element with expected accuracy
#### 5.2.2 Semantic elements (Research Question, Hypotheses, Limitations, Future Research): heading lexicon + position priors + fine-tuned classifiers (0.71 micro-F1 beating GPT-4 few-shot) + LLM arbitration
#### 5.2.3 Five-level chapter segmentation fallback chain: bookmarks → TOC alignment → layout headings → font/pattern rules → LLM arbitration (~1 constrained call/thesis); tree-TEDS ≥0.90 gate on 24-thesis gold benchmark
### 5.3 Output Schema and Quality Gates
#### 5.3.1 Custom JSON with Docling-style page/bbox/charspan provenance as system-of-record; TEI/JATS/ETD-MS as exports only
#### 5.3.2 Gold benchmark: 24 theses, INCEpTION annotation, ~$3.5–5k, Krippendorff unitizing-α for boundary agreement; ETD-ODv2 for scanned-thesis evaluation

## 6. Scientific Reasoning Extraction (~3,000 words, 2 tables)
### 6.1 Method Landscape per Reasoning Category
#### 6.1.1 Classical-first categories: measurements (grobid-quantities micro-F1 85.2), uncertainty/speculation (BioScope/CoNLL-2010 + SciBERT), discourse roles (ART/AZ/DRI/PubMed200k)
#### 6.1.2 Hybrid categories: evidence, inferences, predictions, hypotheses, opinion — classical high-recall pre-filter → LLM normalization of filtered spans
#### 6.1.3 LLM-first categories: assumptions and alternative explanations — no training corpora exist; ARCHE (2026) shows frontier LLMs fail at latent reasoning chains; self-consistency ×3 + mandatory human review
### 6.2 Corpora Inventory
#### 6.2.1 Verified corpora table: AZ, ART (225 papers/35k sentences), DRI (10,784 sentences), PubMed 200k RCT, AbstRCT, BioScope, CoNLL-2010, Certainty (Rubin), SciFact (1,409 claims), Evidence Inference, ARCHE — sizes, labels, licenses
### 6.3 LLM Extraction Pipeline Design
#### 6.3.1 JSON-schema constrained decoding (SLOT 99.5% schema accuracy) — syntax guaranteed, truth not; verbatim-span hallucination gate (exact match + page/bbox) with quarantine
#### 6.3.2 Cost envelope at 10k theses: $50–150 blended (budget $7–9; frontier-only $450–480); ×10 at 100k; annotation $8–15k one-time
### 6.4 Output Model
#### 6.4.1 Nanopublication-per-claim (assertion/provenance/pubinfo, trusty URIs); ORKG-compatible edges: supports/contradicts/extends/assumes/alternative_to/limited_by
#### 6.4.2 Fine-tuning flywheel: gold chapters (κ≥0.70 target, 220–260 person-hours) → per-category small models replace LLM passes (15–40 F1 gain, ~20× throughput)

## 7. Tracing the Evolution of Scientific Ideas (~2,500 words, 2 tables)
### 7.1 Feasible Now
#### 7.1.1 Retraction/correction graph: Crossref update-types (73,700 retractions; 209,348 corrections; 4,094 EoC) + Retraction Watch CSV daily; OpenAlex is_retracted noisy (~2,300 false flags) — merge strategy
#### 7.1.2 Citation-context traversal: S2AG 2.4B contexts with intents (ODC-BY, current releases); OpenCitations Index 1.4B+ links (CC0); scite Enterprise-gated → build-own classifier
### 7.2 Requires Building
#### 7.2.1 Thesis→article lineage: no turnkey API exists; record-linkage design (author/ORCID blocking + fuzzy title + acknowledgments mining + DataCite IsDerivedFrom); NBER w33944 as method template; gold-set evaluation
#### 7.2.2 Replication layer: FReD (1,239 pairs), FORRT Reversals, ReplicationWiki; botany-specific proxies — re-circumscription, re-sequencing, Flora treatment updates
### 7.3 Botany-Native Idea Evolution
#### 7.3.1 Taxonomic revision ledger: name pinning (IPNI LSID, WFO-ID, GBIF key, POWO ID, WCVP version); WCVP v15 (Jan 2026); ChecklistBank diffs; 67% of names are synonyms → 1–5% accepted-concept churn per version as measurable drift
#### 7.3.2 Nomenclatural acts in theses: gnfinder sp. nov./comb. nov. detection → IPNI linkage; thesis acts missing from IPNI flagged for review
#### 7.3.3 Bitemporal knowledge graph: valid-time vs transaction-time edges; ORKG-style snapshot chains on qlever; consensus reconstruction deferred with botany-specific proxies (POWO acceptance, IUCN)

## 8. Existing Software Landscape (~2,500 words, 2 tables)
### 8.1 Component Catalog
#### 8.1.1 Harvest/registry: oaipmh-scythe 0.14.2 (BSD-3), InvenioRDM v13 (MIT), DSpace 7/8, Sickle (stalled — avoid); strengths/weaknesses/license/reuse/integration per project
#### 8.1.2 Parse/extract: GROBID (Apache-2.0), Docling (MIT), MinerU (custom — container-isolate), Marker (Apache code 2026-07-20 / weights unverified), Nougat (avoid — long-doc hallucination), Camelot (archived)
#### 8.1.3 Names/taxonomy: gnfinder/gnverifier (MIT, 15M pages/h), GBIF/POWO/WCVP APIs, Plazi GoldenGATE→TreatmentBank→DwC-A→GBIF pipeline for monograph chapters, CharaParser for character matrices
### 8.2 Platform Components
#### 8.2.1 Index/KG: OpenSearch 3.7 (lexical+k-NN), qlever SPARQL (Apache-2.0), SeaweedFS (MinIO CE archived 2026-04-25 — avoid), Vespa/Neo4j/TerminusDB deferred
#### 8.2.2 Review/annotation: INCEpTION (Apache-2.0, KB linking + external recommenders = built-in active learning) over Label Studio for scholarly spans
### 8.3 Build-vs-Reuse Decisions
#### 8.2.3 Copyleft contamination audit: license-safe paths for every pipeline stage; single-maintainer risks (scythe, gnames) → vendor/fork strategy
#### 8.2.4 Team-capacity evidence: CORE runs 290M records with 12 people → 1–3 engineers suffice for orchid-scoped Calyx if defer list holds

## 9. Legal and Compliance Architecture (~2,500 words, 3 tables)
### 9.1 Activity-by-Jurisdiction Matrix
#### 9.1.1 US: fair use for TDM (Authors Guild v. HathiTrust 2014 / v. Google 2015); Bartz v. Anthropic 2025 — pirated corpora "irredeemably infringing"; district-level uncertainty remains
#### 9.1.2 EU: DSM Art. 3 (research TDM, mandatory) vs Art. 4 (opt-out); OLG Hamburg Dec 2025 — only machine-readable opt-outs count; lawful-access precondition CJEU-untested
#### 9.1.3 Japan Art. 30-4 (broad), UK s.29A (reform dropped 2026-03-18), India (ANI v. OpenAI judgment reserved Apr 2026), Brazil (PL 2338 pending), China (data-security constraints)
### 9.2 License and Contract Layers
#### 9.2.1 CC license × activity matrix: BY/SA/NC/ND implications for mining, excerpt display, derived data, commercial tiers; Shodhganga repo-wide CC BY-NC-SA
#### 9.2.2 ToS enforceability: Ryanair v. PR Aviation, hiQ v. LinkedIn, Van Buren CFAA narrowing; EU database right; robots.txt RFC 9309 + TDMRep as reservation evidence
### 9.3 The Five Hard Rules (Automatable)
#### 9.3.1 Rule set: lawful access only; never redistribute non-CC full text; honor machine-readable signals + embargoes (72h SLA); license-gate default-ARR; fuzz sensitive locality data (CITES App. I, Paphiopedilum, 0.1° minimum per GBIF/Chapman 2020; Local Contexts TK labels; CARE principles)
#### 9.3.2 Compliance-as-code: policy engine with quarterly legal-watch; provenance logging of license snapshots; GDPR legitimate-interest documentation for author data

## 10. Implementation Roadmap (~2,800 words, 2 tables, 1 chart)
### 10.1 Phase 1 (Months 1–6): Working Automated Ingestion
#### 10.1.1 Six channels: OpenAlex snapshot + Content API, CORE dump, NDLTD union OAI, theses.fr OAI+API, EThOS CSV, ~10 Tier-1 botanical OAI endpoints; zero long-tail harvesting
#### 10.1.2 Deliverables: rights-verified store, dedupe pipeline, GROBID+Docling parse, gnfinder names, scoped LLM pass (abstract/intro/conclusion), InvenioRDM registry; go/no-go gates (≥30k orchid-relevant parsed theses, ≥85% dedupe precision, complete license register, <$5k compute)
### 10.2 Phase 2 (Months 7–15): Structure and Reasoning
#### 10.2.1 Gold annotation program starts month 1 of Phase 2 (parallel, not after); chapter segmentation benchmark; 14-category extraction with hallucination gates; nanopub emission
### 10.3 Phase 3 (Months 16–30): Memory and Evolution
#### 10.3.1 Retraction graph, citation contexts, WCVP drift ledger, thesis→article linker; hard-region partnerships (Shodhganga, UKZN, LA nodes); bitemporal serving
### 10.4 Resourcing Reality
#### 10.4.1 Team: ~1 FTE engineer + 0.25 curator Phase 1; cost tables at 10k/100k/1M-thesis scales; storage ~10 MB/thesis (0.3/3/30 TB); defer list (Kubernetes, Kafka, Neo4j, GraphQL)

## 11. Critical Review (~2,800 words, 1 table)
### 11.1 Technical Obstacles
#### 11.1.1 Endpoint mortality (44% OAI dead), anti-bot escalation (Anubis/Cloudflare default AI-blocking from Sept 2026), scanned-thesis OCR collapse, license-field sparsity, 30–50% raw duplication
### 11.2 Legal and Scientific Limitations
#### 11.2.1 Only ~32% of world theses OA; 10–26% embargoed; appellate legal uncertainty; NC/ND license traps
#### 11.2.2 Scientific: theses are grey literature (uneven peer review); ~41% never publish; negative-results and advisor-prestige biases; English/Global-North repository bias quantified
### 11.3 Sustainability and Maintenance Burden
#### 11.3.1 Free-tier erosion (OpenAlex freemium, CORE paid recency, BASE gated); funding-model fragility; 0.5–1 FTE endpoint gardening forever if long-tail harvesting is attempted
### 11.4 Simpler Alternatives Honestly Evaluated
#### 11.4.1 Five alternatives: metadata-only corpus; license ProQuest + TDM Studio; partner with CORE/OpenAIRE; curated 5–10k orchid-only corpus; OpenAlex+CORE dumps only — gain/loss, cost, time-to-value per option
#### 11.4.2 Verdict: if the near-term goal is serving orchid researchers, the curated orchid-only corpus delivers more value per dollar than any scale play; the full build is justified only if the reasoning-corpus vision is the true objective

## 12. Strategic Synthesis: Cross-Cutting Insights (~1,800 words)
### 12.1 Architectural Insights
#### 12.1.1 Discovery is solved — the asset is the rights-verified store; OpenAlex Content API as both best channel and biggest dependency risk (mirror-on-first-touch doctrine)
### 12.2 Strategic Insights
#### 12.2.1 Value/difficulty anti-correlation demands a hard-region strategy; annotation program is the critical path; botany-native idea evolution (WCVP drift, nomenclatural acts) as Calyx's distinctive contribution
### 12.3 Operational Insights
#### 12.3.1 Compliance-as-code converts the biggest risk into routine; Calyx-as-repository (InvenioRDM + annual snapshot DOIs) turns compliance into discoverability and feeds Orchid Continuum visibility

# References
## calyx_wide01.md – calyx_wide06.md
- **Type**: Wide-exploration research briefs
- **Description**: Six facet scans (Americas/global aggregators; Europe/Asia/Global South; metadata aggregators & protocols; botanical sources; document AI & reasoning tech; idea evolution & software)
- **Path**: /mnt/agents/output/research/

## calyx_dim01.md – calyx_dim12.md
- **Type**: Deep-dive research briefs
- **Description**: Twelve verified dimension reports with live endpoint probes and citations
- **Path**: /mnt/agents/output/research/

## calyx_cross_verification.md
- **Type**: Confidence-tier classification + conflict-zone register
- **Path**: /mnt/agents/output/research/calyx_cross_verification.md

## calyx_insight.md
- **Type**: Cross-dimension insights (8 insights)
- **Path**: /mnt/agents/output/research/calyx_insight.md

## User mission brief
- **Type**: Uploaded task specification (10 parts)
- **Path**: /mnt/agents/upload/user_pasted_clipboard_long_content_as_file_You_are_acting_as_the_Chief_Research_Lib1.txt
