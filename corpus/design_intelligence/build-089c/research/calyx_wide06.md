# Facet: Idea Evolution & Existing Software

**Scope:** (A) infrastructure for tracing the evolution of scientific ideas (dissertation→article lineage, citation-context traversal, citation-statement classification, replication/contradiction detection, corrections/retractions, plant taxonomic revision tracking, consensus reconstruction); (B) existing software for acquisition→processing pipeline segments. Researched 2026-07-21; ~14 search batches + live API verifications (curl) against GBIF, Crossref, OpenAlex, OpenCitations, POWO, IPNI, COL, and GitHub license metadata.

Confidence tags: **[HIGH]** = verified via official docs/API response/license file; **[MED]** = multiple secondary sources agree; **[LOW]** = single source or inference.

---

## Key Findings

1. **Retraction/correction infrastructure crossed a threshold in 2023–2025 and is now fully open.** Crossref acquired the Retraction Watch (RW) database in Sept 2023; RW data shipped in the Crossref REST API from Jan 2025 (`filter=update-type:retraction`) and as a full CSV on Crossref's GitLab; OpenAlex also exposes `is_retracted` (verified live: Wakefield 1998 DOI returns `is_retracted: True`); ~73,700 retraction-flagged records in Crossref as of today; RW itself ~55,000 entries end-2024.[^3^][^4^][^5^][^6^][^7^] Caveat: OpenAlex retraction flags contain errors; RW reasons only exist in RW data — merging both is recommended.[^8^] **[HIGH]**
2. **Citation-context data at scale is available open (S2AG, ODC-BY) or commercial (scite).** Semantic Scholar's monthly datasets include a 2.4B-record `citations` dataset with verbatim `contexts`, `intents` (methodology/background/result), and `isInfluential`; the Graph API exposes the same per-paper.[^9^][^10^] Scite classifies 1.2–1.6B citation statements as supporting/contrasting/mentioning; individual ~$12–20/mo; programmatic access is Enterprise-tier or via its MCP server.[^11^][^12^] **[HIGH]**
3. **OpenAlex is no longer unlimited-free at the API layer (2026 change).** API key required since 2026-02-13; credit-based pricing ($1/day free with key; singleton lookups free; list/filter $0.10/1k calls; search $1/1k); bulk snapshot remains free/CC0 ("We sell services, not data"). Corpus: ~477M works after Q4-2025 "Walden" rewrite (+192M works from DataCite/repositories).[^13^][^14^][^15^] **[HIGH]** This argues for snapshot-first, API-second architecture for Calyx.
4. **Dissertation→article lineage has no turnkey API; it is a record-linkage problem with good raw material.** OpenAlex holds ~6.1M `dissertation`-type works (2022 count) plus new DataCite/repository theses; ProQuest PQDT (6M+ records) is commercial, now also a WoS citation index; NDLTD Global ETD Search (6.5M) and OATD (7M+, 1,100 institutions) are free metadata sources.[^16^][^17^][^18^][^19^] Practical recipe: author (ORCID) + fuzzy title/abstract matching (RapidFuzz), acknowledgments mining, DataCite `relationType` (IsDerivedFrom/IsPartOf where deposited), repository `dc.relation` links, and citation-graph proximity (thesis cited by the article). An NBER 2025 study demonstrates the pattern at 1.2M-dissertation scale using ProQuest+OpenAlex+LLM text mining.[^20^] **[MED]**
5. **The plant-taxonomy stack is more API-complete than expected, with versioned, DOI'd backbone releases — exactly the revision-tracking model Calyx wants.** POWO public API (`/api/2/`, no key, Cloudflare-guarded); IPNI beta API (undocumented, via pykew/tskew) + LSID/RDF per record + reconciliation service; WCVP annual versioned releases with per-version DOIs (v14, May 2025, CC BY 3.0; GBIF copy CC BY 4.0); WFO-IDs (1.4M names) + API + Zenodo-archived backbone versions; GBIF species match API (live-verified) + backbone (CC BY 4.0, DOI 10.15468/39omei); Catalogue of Life ChecklistBank API (name-matching jobs, ColDP/DwC-A exports).[^21^][^22^][^23^][^24^][^25^][^26^][^27^] **[HIGH]**
6. **Replication/contradiction infrastructure is fragmented but consolidating.** FORRT Replication Database (FReD): 1,239+ original→replication pairs, CC BY 4.0, OSF-hosted with DOI, merged with FORRT Replications & Reversals (600+ effects/22 disciplines); Curate Science curates transparency/credibility links between papers and follow-up scrutiny; ReplicationWiki (economics, 4.5k studies); COS "Predicting Replicability" challenge trains on FORRT data.[^28^][^29^][^30^][^31^][^32^] **[HIGH]**
7. **Nearly every pipeline segment has a maintained open-source component** — harvesting (oaipmh-scythe, BSD-3, actively maintained Sickle fork), registry (InvenioRDM, MIT), ETL (OpenRefine BSD-3, Metafacture Apache-2.0, Catmandu), index (OpenSearch/Solr/Vespa Apache-2.0; Qdrant/Milvus Apache-2.0, Weaviate BSD-3), annotation (Label Studio Apache-2.0, INCEpTION Apache-2.0, Doccano MIT), KG (Apache Jena, qlever Apache-2.0, TerminusDB Apache-2.0 with git-style versioning), citation mining (GROBID Apache-2.0), bibliometrics (bibliometrix GPL, VOSviewer), knowledge-curation (ORKG, MIT backend, CC content).[^33^–^56^] **[HIGH]**

---

## Idea-Evolution Infrastructure (per capability)

### 1. Dissertation → journal-article lineage
- **OpenAlex theses** — provider: OurResearch; docs: https://docs.openalex.org; work `type: dissertation` (~6.1M in 2022 snapshot study[^16^]); fields: authors/ORCID, `referenced_works`, `related_works`, topics; access: snapshot CC0 free; API freemium credits (2026).[^13^][^14^] Fit: backbone for candidate-pair generation. **[HIGH]**
- **ProQuest Dissertations & Theses Global / PQDT Citation Index (WoS)** — commercial; 6M+ records; full-text PDFs post-1997; citation-index linking in WoS since 2023 (phase 2).[^17^][^18^] Fit: gold-standard coverage but license-bound; use only if institutional access exists. **[HIGH]**
- **NDLTD Global ETD Search** (6.5M ETDs) and **OATD** (7M+ theses, 1,100 institutions) — free metadata search; no bulk API of note; OAI-PMH harvest directly from contributing institutional repositories instead.[^19^] **[MED]**
- **Detection method (no dedicated API exists):** candidate blocking by author (ORCID/surname+year), fuzzy title similarity (RapidFuzz), abstract embedding similarity, acknowledgment/advisor mining, citation from article back to thesis, DataCite `relationType=IsDerivedFrom/IsPartOf` and Crossref `relation` where deposited, repository `dc.relation` fields. NBER 2025 shows LLM-based text mining of 1.2M ProQuest dissertations joined to OpenAlex is feasible.[^20^] **[MED]** (Direct "thesis→paper derived" queries returned essentially nothing — genuine infrastructure gap = opportunity for Calyx.)
- **Semantic Scholar** has no thesis-linkage feature; `related works` in OpenAlex is SPECTER-similarity, not provenance. **[HIGH]**

### 2. Citation-network traversal & context
- **OpenAlex**: `filter=cites:W…` / `cited_by:W…`, `related_to:W…`, `referenced_works` array; snapshot for offline graph; new daily sync service announced Q1-2026.[^15^][^57^] License CC0. **[HIGH]**
- **Semantic Scholar Graph API + S2AG datasets** (https://api.semanticscholar.org): citations endpoint fields `contexts,intents,isInfluential`; datasets monthly: papers (200M), citations (2.4B w/ contexts+intents), abstracts, SPECTER v1/v2 embeddings (Apache-2.0), TLDRs. License verbatim: *"This collection is licensed under ODC-BY"* (datasets); embeddings Apache-2.0. Free key; full datasets need (free) partner key.[^9^][^10^] **[HIGH]**
- **OpenCitations** (COCI + unified Index + Meta): 1.4B+ DOI→DOI citation links; REST API v2 (`/index/v2/references/{doi}`, `/citations/{doi}`), rate 180 req/min, free access token; dumps CC0 (verbatim: *"more than 445 million DOI-to-DOI citation links made available under a Creative Commons CC0 public domain waiver"*; current Index >1.4B links).[^58^][^59^] **CCC (Citations in Context Corpus)** provides citation contexts from Europe PMC XML — the open alternative to scite-style context.[^60^] **[HIGH]**
- **Crossref REST API**: references (`is-referenced-by-count`, `reference` arrays where open), `filter=update-type:*`, `relation` field; free, polite pool; metadata CC0.[^3^] **[HIGH]**
- **Co-citation/bibliographic coupling for idea clusters**: bibliometrix (R, GPL; coupling network, co-citation, thematic evolution), VOSviewer (free desktop; claimed MIT in secondary lit **[MED]**), CiteSpace (free). Connected Papers demonstrates "prior works / derivative works" views built purely on co-citation+coupling — a working commercial analog of lineage-by-coupling.[^61^][^62^] **[HIGH]**

### 3. scite.ai (citation-statement classification)
- Provider: scite (Research Solutions, acquired Nov 2023). Smart Citations: supporting/contrasting/mentioning with sentence-level context + section location; 1.2–1.6B statements; 280M+ articles; 30+ publisher agreements.[^11^][^12^]
- Access: 7-day trial; individual $12/mo (annual) – $20/mo (monthly); Pro $50/mo; **API access is Enterprise-tier / separate usage-based terms**; MCP server at `api.scite.ai/mcp` (requires subscription); Zotero plugin + browser extension.[^11^][^12^]
- Coverage: strongest biomedical; weaker humanities; classification accuracy criticized externally (supporting/contrasting vs mentioning confusions).[^12^] Fit: **aspirational for bulk corpus work** (cost/terms); fine for spot-checking high-value claims via MCP. **[HIGH]**

### 4. Replication / contradiction detection
- **FReD (FORRT Replication Database)**: 1,239+ finding pairs + meta-analytic fields; OSF DOI 10.17605/OSF.IO/9R62X; license CC BY 4.0; Shiny explorer/annotator; continuously updated changelog.[^28^][^29^] **[HIGH]**
- **Curate Science** (curatescience.org): unified curation linking papers to "critical commentaries, reproducibility/robustness re-analyses, and new sample replications"; transparency standards checks; social-science focus; entries folded into FReD.[^30^][^31^] **[MED]** (site unreachable from sandbox; status/maintenance uncertain.)
- **ReplicationWiki** (Univ. Göttingen): 4,484 studies, 652 replications classified by type/result (2020), economics; Semantic MediaWiki.[^32^] **[MED]**
- **COS Predicting Replicability Challenge** (2024–26): confidence scores (0–1) vs held-out claims; training data = FORRT 3,000+ replication effects; Brier scoring.[^63^] **[HIGH]**
- **Citation-polarity research base**: negative/post-retraction citation studies (Bar-Ilan & Halevi 2017; Schneider et al. 2020; Bordignon 2020); OpenCitations' Heibi & Peroni protocols to gather/characterize citations of retracted articles — methodological basis for automated contradiction signals.[^64^] **[HIGH]**

### 5. Corrections & retractions
- **Crossref × Retraction Watch** (primary): REST `filter=update-type:retraction|correction|expression-of-concern|withdrawal`; JSON `update-to`/`updated-by` blocks with `source: retraction-watch` and RW `record-id`; full CSV at https://gitlab.com/crossref/retraction-watch-data; ~73.7k retraction-flagged records (live today). Publishers register updates via Crossmark `<update type="retraction" …>` deposit.[^3^][^4^] **[HIGH — live-verified]**
- **OpenAlex** `is_retracted` field (live-verified on Wakefield DOI) — but documented error rate; merge with RW CSV via DOI/OpenAlex ID (NISTEP's Zenodo combined-ID dataset exists for Dec-2024 snapshot).[^6^][^8^] **[HIGH]**
- **PubMed**: NLM "Retracted Publication" publication type + retraction-of/in linking; free E-utilities API; biomedical only.[^65^] **[HIGH]**
- **Zotero** integrates RW data to flag retracted items (relevant precedent for Calyx UI warnings).[^5^] **COPE** retraction guidelines = policy vocabulary. **[HIGH]**

### 6. Scientific-consensus reconstruction
- **Claim-verification datasets**: SciFact (1,409 claims, 5,183-abstract corpus; CC BY-NC 2.0 per BEIR; GitHub allenai/scifact) and SciFact-Open (500k-doc corpus); claim-generation file `claims_with_citances.jsonl` pairs claims with the citation contexts that generated them — directly reusable for reasoning-lineage work.[^66^][^67^] **[HIGH]**
- **Living systematic reviews**: Epistemonikos **L·OVE** (living overview of evidence; maps/organizes health evidence, free access to systematic reviews); Cochrane living reviews model; FReD as social-science analog.[^68^] **[MED]**
- **ORKG (TIB/L3S)**: structured research-contribution graphs; comparisons get DataCite DOIs; **immutable snapshots + provenance chains link successive versions** (temporal versioning model to copy); REST+SPARQL; backend MIT; content openly readable, curation via free account.[^69^][^70^] **[HIGH]**
- **Temporal KG versioning**: TerminusDB (git-for-data branching/merging, Apache-2.0, v12 Dec 2025, now DFRNT-maintained); Wikidata point-in-time qualifiers as pattern.[^71^] **[HIGH]**

---

## Taxonomic Revision Stack (IPNI / POWO / WFO / GBIF / COL / WCVP)

How nomenclatural change is versioned in practice: **IPNI records nomenclatural acts continuously** (new names, new combinations — daily updates); **WCVP/POWO curate taxonomic opinion (accepted vs synonym) released as versioned snapshots with per-version DOIs**; **WFO versions its backbone via file-server + Zenodo DOIs**; **GBIF/COL rebuild backbones periodically and expose match APIs**; linking a thesis's names to current accepted names = name-matching service + accepted-usage resolution + backbone-version pinning.

| Resource | API / access | Versioning & identifiers | License/terms | Verified |
|---|---|---|---|---|
| **IPNI** (nomenclature) | No formal public API — verbatim: *"API - Currently there is no publicly available API. A beta version is being trialled right now and we are working towards providing this in the next 12 months."*; beta API used by pykew (`beta.ipni.org/api/1`) and tskew; **Names Reconciliation Service** (OpenRefine-style); LSIDs; **RDF per record** (`Accept: application/rdf+xml` or `/rdf` suffix) | LSID per name (`urn:lsid:ipni.org:names:…`); protologue links | Kew terms; nomenclatural data freely browsable | **[HIGH]** for absence of official API; beta reachable but empty from sandbox |
| **POWO** (taxonomy) | Public REST `https://powo.science.kew.org/api/2/` (search + taxon by fqId), no key, "fully public" but **Cloudflare bot-guarded** (verified: challenge page returned); pykew/tskew clients; underlying WCVP+IPNI | accepted/synonym status per name; TDWG WGSRPD distributions | Kew terms (research use; 800ms polite delay noted by third-party scraper) | **[HIGH]** |
| **WCVP** (checklist data) | Bulk: Kew IR (kew.iro.bl.uk) zips ~100MB; sftp.kew.org listing live-verified; GBIF checklist copy (DOI 10.15468/6h8ucr) | **Annual versions v12 (2023), v13 (2024), v14 (May 2025), each with own DOI** — the revision ledger | Verbatim: *"Licence CC BY Attribution 3.0 Unported"* (Kew IR); CC BY 4.0 via GBIF | **[HIGH]** |
| **WFO** | Portal API (HTML/JSON, RestDoc via OPTIONS); DwC-A / text downloads; static backbone on Zenodo (10.5281/zenodo.7460141); R pkg `WorldFlora` | **WFO-IDs for 1.4M names**, cross-ref to IPNI/WCVP; backbone versions on file server + periodic repository deposit; updated via Taxonomic Expert Networks | Provider-level licenses; FAIR principles | **[MED-HIGH]** (endpoints timed out from sandbox) |
| **GBIF backbone** | Species API `/v1/species/match` — **live-verified** (Quercus robur → usageKey 2878688, ACCEPTED, confidence 97, EXACT); `/species/search`, `/parser/name`; `backbone-current.zip` bulk; pygbif/rgbif clients; match against any checklist via `checklistKey` | periodic backbone rebuilds; dataset DOI 10.15468/39omei | Verbatim (API): license = *CC BY 4.0* | **[HIGH — live-verified]** |
| **Catalogue of Life / ChecklistBank** | `api.checklistbank.org` (dataset nameusage search; **cross-checklist match jobs** e.g. GBIF backbone vs other list); exports DwC-A, ColDP, ACEF, TextTree, Newick | monthly COL checklists + annual editions; COL backend Apache-2.0 | COL data CC BY; ChecklistBank code Apache-2.0 | **[HIGH]** (rate-limited live: 429 — exists) |
| **Plazi TreatmentBank** | TreatmentBank APIs + GoldenGate Imagine; treatments get DataCite DOIs via Biodiversity Literature Repository (Zenodo); DwC-A exports harvested daily by GBIF; names mapped via CoL/GBIF backbone | per-treatment DOIs; links treatments↔names↔materials citations | open access article data (CC BY typical); ideal for thesis treatments | **[HIGH]** |
| **TaxonWorks** (Species File Group) | Workbench + API (Ruby; MIT license — verified GitHub) | curates nomenclature with full history; feeds CoL; GlobalNames integration | MIT | **[HIGH]** |

**Fit for Calyx:** pin every extracted taxon name to (name-string, IPNI LSID, WFO-ID, GBIF usageKey, POWO accepted fqId, backbone-version). Name-resolution pipeline: GBIF match API (or POWO for plants-only precision) → synonym→accepted mapping → store backbone version + matchType/confidence verbatim. **[HIGH]**

---

## Existing Software Catalog

### Harvest targets & Calyx's own registry
| Project | Function | Strengths | Weaknesses | License (verified) | Reuse/integration for Calyx |
|---|---|---|---|---|---|
| **DSpace 7/8/9** (+DSpace-CRIS) | Institutional repository | ubiquitous, OAI-PMH provider, REST API, versioning | Java heaviness; UI customization cost | **BSD-3-Clause** (GitHub) | harvest target; candidate registry |
| **EPrints 3.4** | Publications/theses repository | simple, OAI-PMH, versioning, flavors/ingredients | Perl; aging; 3.4 "managed availability" licensing controversy (2017) | **GPLv3** (verbatim: *"EPrints is free software… under the terms of the GNU General Public License… version 3"*) | harvest target mainly |
| **InvenioRDM / Zenodo** | Research data repo | modern Python/Flask+React+OpenSearch+Postgres; DOI versioning; OAI-PMH, REST; powers Zenodo | ops complexity | **MIT** (invenio-app-rdm; verified) | **top candidate for Calyx registry** |
| **Dataverse** | Dataset repository | Harvard IQSS ecosystem, DOIs, guestbooks, API | dataset-centric, less narrative-doc oriented | **Apache-2.0** (verbatim LICENSE.md) | candidate registry for extracted reasoning datasets |
| **Fedora (fcrepo) / Samvera Hyrax / Hyku / Islandora** | Preservation repo + DAMS | Fedora = durable object store w/ versioning & OCFL; Hyrax/Hyku = turnkey IR/multi-tenant | heavy Ruby stack; dev capacity needed | **Apache-2.0** (fcrepo, hyrax, hyku); Islandora **GPL-2.0** | use only if preservation-grade storage needed |
| **VIVO** | Researcher networking/RIS | linked-open-data native (RDF/SPARQL) | ontology upkeep | **BSD-3-Clause** | model for entity pages |
| **OJS (PKP)** | Journal platform | includes OAI-PMH provider | publishing workflow focus | **GPLv3** (docs/COPYING) | harvest target (many thesis journals) |

### OAI-PMH harvesters
| Project | Notes | License | Status |
|---|---|---|---|
| **oaipmh-scythe** | modernized Sickle fork; all 6 verbs; httpx+lxml | **BSD-3-Clause** | **active (2026)** — recommended |
| sickle (mloesch) | the classic; last push 2023 | BSD (NOASSERTION on GH) | maintenance-stalled |
| pyoai / oai-harvest / pyoaiharvester | older/CLI options | various | legacy |
| Catmandu OAI importer | harvest→fix→load to MongoDB/Elasticsearch in one command (documented ETL pattern) | Perl (Artistic/GPL dual) **[MED]** | maintained |
| jOAI / PKP OAI / VuFind harvest | Java/PHP alternatives; VuFind (GPL-2.0) OAI ingestion module | mixed | situational |

### Metadata normalization / ETL
| Project | Notes | License | Fit |
|---|---|---|---|
| **OpenRefine** | interactive cleaning, reconciliation API (matches IPNI/Wikidata recon services); headless via `openrefine-client` | **BSD-3-Clause** | entity reconciliation step |
| **Metafacture** (hbz) | declarative Flux/Morph pipelines for library metadata; JVM | **Apache-2.0** | bulk metadata ETL |
| **Catmandu** (LibreCat) | Fix-language ETL; OAI/SRU importers; DSpace/Fedora loaders | Perl dual **[MED]** | OAI→index glue |
| Airbyte/Singer-style connectors | generic ELT; few scholarly sources out-of-box | ELv2/MIT connectors | low priority |

### Search / index / semantic layer
| Project | Notes | License | Fit |
|---|---|---|---|
| **OpenSearch** | Lucene; k-NN (FAISS/NMSLIB); Linux Foundation governance (2024) | **Apache-2.0** | default choice |
| **Elasticsearch** | triple-licensed **AGPLv3/SSPL/ELv2** since Aug 2024; ELSER; license vetting needed | mixed | viable if AGPL acceptable |
| **Apache Solr** | Lucene veteran; dense vectors added | **Apache-2.0** | solid |
| **Vespa** | hybrid lexical+vector+tensor ranking at scale | **Apache-2.0** | strong for hybrid retrieval |
| **Qdrant / Milvus / Weaviate / pgvector** | vector DBs | Apache-2.0 / Apache-2.0 / BSD-3 / PostgreSQL lic. | semantic layer |
| **Postgres tsvector/GIN** | fine <~10M docs; no extra infra | PostgreSQL | pragmatic start |

### Annotation / human-review queue
| Project | Notes | License | Fit |
|---|---|---|---|
| **Label Studio CE** | multimodal, ML-assisted pre-annotation, IAA, webhooks; Enterprise ~$950/mo | **Apache-2.0** (CE) | **primary review queue** |
| **INCEpTION** | scholarly text annotation: KB linking ( Wikidata), curation/adjudication, recommenders — best fit for reasoning-span + entity-link review | **Apache-2.0** | **domain-fitted** |
| **Doccano** | minimal text tasks; stalled cadence since ~2023 | **MIT** | quick pilots |
| **Prodigy** | active-learning with spaCy; commercial ~$490/dev one-time; weak multi-annotator | proprietary | optional |
| **Argilla** | LLM feedback/RLHF queues; HF integration | Apache-2.0 | LLM-output review |
| **Potato / brat** | research workflows (YAML, MACE); brat classic spans/relations | open (research/BSD) | niche |

### Knowledge-graph stores
| Project | Model | License | Fit for Calyx |
|---|---|---|---|
| **Apache Jena (Fuseki)** | RDF/SPARQL | **Apache-2.0** | default RDF endpoint |
| **qlever** (ad-freiburg) | RDF/SPARQL, very fast, low RAM, SPARQL+text | **Apache-2.0** | large-scale SPARQL serving |
| **Virtuoso OS** | RDF+SQL | GPLv2 (NOASSERTION) | proven (DBpedia) |
| **GraphDB** | RDF+reasoning | proprietary w/ free tier | if reasoning needed |
| **Blazegraph** | RDF | GPL-2.0; **last push 2023** | avoid for new builds |
| **Neo4j community** | property graph, Cypher/GQL | **GPL-3.0** (community) | app-side reasoning graph |
| **TerminusDB** | doc-graph, **immutable history + git-style branch/merge** | **Apache-2.0** (per terminusdb.org; older sources say GPL/AGPL — **conflict noted**) | temporal reasoning-ledger store |

### End-to-end scholarly-mining / discovery frameworks
- **GROBID** (Apache-2.0, verified LICENSE): PDF→TEI; `/api/processFulltextDocument` yields structured body + parsed references; sentence segmentation options; CEX project ships trained citation-context models; basis of S2ORC parsing. **[HIGH]**
- **OpenCitations tooling**: RAMOSE (REST-over-SPARQL), OSCAR, LUCINDA, BEE/SPACIN, CEC citation-context service — ISC license. **[HIGH]**
- **Literature-based discovery**: Arrowsmith re-implementation Valmont-F (Apache-2.0); SKiM/KinderMiner (PubMed-scale, validated by rediscovering Swanson's discoveries); BITOLA, RaJoLink, PKDE4J (relation extraction + Swanson ABC); reproducible pipelines repo akastrin/ida2025lbd. Mostly biomedical; none are turnkey — **aspirational** for reasoning-gap discovery. **[MED-HIGH]**
- **Commercial analogs (note only)**: Connected Papers (co-citation/coupling similarity, prior/derivative views, $3/mo), Litmaps ($12.50/mo timeline maps + alerts), ResearchRabbit (free collections + alerts), Inciteful (free; PageRank, literature-connector pathfinding, SQL transparency), Citation Gecko, Undermind, Consensus. Useful UX patterns; none expose lineage-aware APIs suitable as Calyx backbone. **[HIGH]**

---

## Trends & Signals

1. **Open-infrastructure consolidation (2023–2026):** Crossref absorbed Retraction Watch; OpenAlex added 192M DataCite/repository works and a first-class Awards entity; OpenCitations Index >1.4B links.[^3^][^15^][^58^]
2. **OpenAlex shifted to freemium credits (Feb 2026)** with paid membership tiers ($5k/$20k/yr) and an author-disambiguation rewrite — budget planning required; snapshot-first architectures now the norm.[^13^][^14^][^15^]
3. **Retraction/correction signals are becoming first-class metadata** everywhere (Crossref update-types, OpenAlex `is_retracted`, Zotero RW flagging, scite Reference Check).[^3^][^6^][^11^]
4. **Agent-native access is arriving:** scite MCP server (`api.scite.ai/mcp`), POWO MCP gateway experiments, Riksarkivet OAI-PMH MCP — MCP becoming the integration surface for scholarly tools.[^11^][^72^]
5. **Metascience industrialized:** FReD merged with FORRT Reversals into a Replication Hub; COS runs paid prediction challenges on FORRT data — replication data is becoming trainable ground truth.[^29^][^63^]
6. **Taxonomy infrastructure quietly versioning itself:** WCVP annual DOI'd releases; WFO-IDs + Zenodo-archived backbones; ChecklistBank cross-checklist diff/match jobs — a working model of "science evolving over versions" that Calyx can mirror.[^22^][^24^][^26^]
7. **Search licensing wars settled:** OpenSearch (LF, Apache-2.0) vs Elasticsearch (AGPLv3 option restored Aug 2024) — both safe now with different caveats.[^52^][^53^]

## Controversies & Conflicting Claims

1. **Nonreplicable work gets cited more.** Serra-Garcia & Gneezy (Sci. Adv. 2021): nonreplicable publications cited more than replicable ones; and retracted articles keep accumulating positive citations post-retraction (multiple Scientometrics studies) — means raw citation graphs systematically mislead "consensus" reconstruction; Calyx must weight by polarity/retraction state.[^64^][^73^]
2. **scite classification accuracy disputed:** external evaluations note weak distinguishing of supporting/contrasting vs mere mentions; treat Smart Citations as signals needing verification, not ground truth.[^12^]
3. **OpenAlex retraction flags vs Retraction Watch disagree**: documented error rate in OpenAlex flags (arXiv 2403.13339); community practice = merge RW CSV with OpenAlex IDs yourself.[^8^]
4. **TerminusDB license confusion:** current site says Apache-2.0; older comparisons say AGPL/GPL — verify before embedding (historical relicensing).[^71^]
5. **EPrints 3.4 "managed availability" episode (2017):** community feared non-GPL distribution of 3.4 additions; core remained GPLv3 but trust eroded — a cautionary tale for Calyx's own licensing clarity.[^46^]
6. **POWO "public API but bot-guarded":** documented as fully public/no key, yet Cloudflare challenges non-browser clients — bulk use should go through WCVP/GBIF downloads instead.[^21^][^22^]
7. **VOSviewer openness:** repeatedly called "open-source MIT" in secondary literature, but source availability has historically been restricted — verify before redistribution. **[LOW]**

## Recommended Deep-Dive Areas

1. **Thesis→article linker as a Calyx-built service**: blocking on OpenAlex `dissertation` works + ORCID + RapidFuzz/embeddings + acknowledgment mining; validate against a hand-built gold set (deep-dive: NBER 2025 methodology; ProQuest vs OpenAlex coverage deltas).[^20^]
2. **Crossref update-graph mining**: beyond retractions — `update-type:correction|expression-of-concern`, Crossmark `update-to/updated-by` chains as an explicit "idea correction" edge type.[^3^]
3. **Open citation-context corpora at scale**: S2AG citations dataset + OpenCitations CCC + SciFact `claims_with_citances.jsonl` to train Calyx's own support/contrast classifier without scite licensing.[^9^][^60^][^66^]
4. **Backbone-version pinning experiment**: run a sample of historical thesis taxon names through GBIF match + WCVP v12/v13/v14 snapshots to quantify synonym drift over versions (directly measures "idea evolution" in nomenclature).[^22^][^25^]
5. **FReD + Curate Science + ReplicationWiki harmonization**: schema alignment into one replication-claim graph; check FReD OSF API for bulk pull; assess Curate Science maintenance status.[^28^][^30^][^32^]
6. **Temporal KG bake-off**: TerminusDB (git-for-data) vs ORKG-style snapshot+provenance chains vs plain RDF + named-graph versioning for Calyx's reasoning ledger.[^69^][^71^]
7. **InvenioRDM as Calyx registry**: verify OAI-PMH sets, custom metadata schema for reasoning objects, DOI versioning semantics.[^39^]
8. **Scite enterprise/MCP cost-benefit** for targeted claim auditing vs building on open contexts.[^11^]

---

## URL List

1. https://api.crossref.org/v1/works?filter=update-type:retraction (live-verified 2026-07-21: 73,700 results)
2. https://gitlab.com/crossref/retraction-watch-data
3. https://www.getfulltextresearch.com/wp-content/uploads/2025/04/Retraction_watch_data_in_the_REST_API.pdf (Crossref webinar, Apr 2025; verbatim Crossmark XML example)
4. https://retractionwatch.com/2024/12/26/a-look-back-at-2024-at-retraction-watch-and-forward-to-2025/ (55k entries; "now part of Crossref")
5. https://www.ideals.illinois.edu/items/118036/bitstreams/386642/data.pdf (Zotero+RW integration; pre-2021 licensing constraints)
6. https://api.openalex.org/works/doi:10.1016/S0140-6736(97)11096-0 (live-verified is_retracted:true)
7. https://congresoeditores.com/wp-content/uploads/2025/09/memorias-cartagena.pdf (Sept 2023 Crossref acquisition; Jan 2025 API launch)
8. https://zenodo.org/records/14921712 (NISTEP combined RW+OpenAlex IDs; cites arXiv:2403.13339 on OpenAlex flag errors)
9. https://api.semanticscholar.org/datasets/v1/release/latest (live-fetched dataset READMEs: ODC-BY verbatim; citations 2.4B records w/ contexts+intents; SPECTER Apache-2.0)
10. https://api.semanticscholar.org/api-docs/ (Graph API contexts/intents fields)
11. https://theaiagentindex.com/agents/scite-ai (MCP api.scite.ai/mcp; Enterprise-gated API; Research Solutions acquisition)
12. https://monday.com/blog/ai-agents/best-ai-for-research/ + https://paperguide.ai/blog/elicit-alternatives/ + https://casrai.org/research-tools/productivity/scite/ (scite coverage 1.2–1.6B statements; pricing $12–20/mo; accuracy caveats; Zotero plugin)
13. https://developers.openalex.org/api-reference/authentication (verbatim: "We sell services, not data"; $0.10/day no key, $1/day with key)
14. https://blog.openalex.org/openalex-api-new-features-and-usage-based-pricing/ (Feb 2026 credit pricing)
15. https://blog.openalex.org/openalex-2026-roadmap/ (Walden; 477M works; sync service; membership tiers)
16. https://arxiv.org/pdf/2206.14168v1.pdf (OpenAlex document types: 6,126,640 dissertations, 2022)
17. https://webofscience.zendesk.com/hc/en-us/articles/25740294405905 (PQDT Citation Index; 5.5M+ records phase 1)
18. https://library.bogazici.edu.tr/en/databases (PQDT >6M dissertations & theses)
19. https://eca.libguides.com/az/databases (NDLTD Global ETD Search 6.5M); https://rua.ua.es/dspace/bitstream/10045/141258/25/ (OATD >7M)
20. https://www.purdue.edu/newsroom/in-the-news/which-universities-mint-the-most-phds-in-key-technology-areas/ (NBER 1.2M dissertations; ProQuest+OpenAlex+LLM method)
21. https://orbtop.com/actors/kew-powo-plants-of-the-world-online-scraper/ (POWO /api/2/ public, no key, 800ms politeness; live-observed Cloudflare guard)
22. https://kew.iro.bl.uk/concern/datasets/042a9f96-41a9-4896-9e80-c89586e68363 (WCVP v14, verbatim "Licence CC BY Attribution 3.0 Unported", DOI 10.34885/b8fr-km05) ; v13 DOI 10.34885/0yex-xv26; v12 DOI 10.34885/jdh2-dr22
23. https://www.ipni.org/about (verbatim "Currently there is no publicly available API… beta version"; reconciliation service; RDF/LSID)
24. https://www.researchgate.net/publication/346462089 (WFO FAIR paper: WFO-IDs 1.4M names; API HTML/JSON; DwC-A; backbone versions on file server)
25. https://api.gbif.org/v1/species/match (live-verified) ; https://api.gbif.org/v1/dataset/d7dddbf4-2cf0-4f39-9b2a-bb099caae36c (backbone license CC BY 4.0, DOI 10.15468/39omei)
26. https://docs.gbif.org/course-checklistbank-tutorial/ + https://discourse.gbif.org/t/download-checklist-with-mapping-to-gbif-backbone/4415 (ChecklistBank match jobs; api.checklistbank.org — live 429)
27. https://github.com/CatalogueOfLife/backend (Apache-2.0, Dropwizard/Postgres)
28. https://pmc.ncbi.nlm.nih.gov/articles/PMC12270267/ (FReD: 1,239 pairs; CC BY 4.0; OSF DOI 10.17605/OSF.IO/9R62X)
29. https://forrt.org/reversals/ (Reversals → FORRT Replication Hub; 600+ effects/22 disciplines)
30. https://forrt.org/curated_resources/curate-science/ (Curate Science description)
31. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9382220/ (Curate Science cited as replication curation source, LeBel)
32. https://blog.repec.org/2020/08/04/a-replication-database-for-economics-and-social-sciences-the-replicationwiki/ (4,484 studies; 652 replications)
33. https://github.com/afuetterer/oaipmh-scythe (BSD-3-Clause; active 2026)
34. https://sickle.readthedocs.io/ (Sickle; last push 2023)
35. https://librecatproject.wordpress.com/tag/catmandu/ (Catmandu OAI→fix→Elasticsearch ETL one-liner)
36. https://journal.code4lib.org/articles/11013 (Catmandu/Metafacture/Krikri ETL survey)
37. https://api.github.com/repos/OpenRefine/OpenRefine (BSD-3-Clause)
38. https://api.github.com/repos/metafacture/metafacture-core (Apache-2.0)
39. https://api.github.com/repos/inveniosoftware/invenio-app-rdm (MIT); https://raw.githubusercontent.com/inveniosoftware/invenio/HEAD/LICENSE (MIT verbatim)
40. https://raw.githubusercontent.com/IQSS/dataverse/HEAD/LICENSE.md (verbatim "The Dataverse software is licensed under the Apache License, Version 2.0")
41. https://api.github.com/repos/fcrepo/fcrepo (Apache-2.0); samvera/hyrax (Apache-2.0)
42. https://raw.githubusercontent.com/samvera-labs/hyku/HEAD/LICENSE (Apache-2.0 verbatim)
43. https://api.github.com/repos/Islandora/islandora (GPL-2.0)
44. https://api.github.com/repos/vivo-project/VIVO (BSD-3-Clause)
45. https://raw.githubusercontent.com/pkp/ojs/HEAD/docs/COPYING (GPLv3 verbatim)
46. https://www.eprints.org/eptech/msg06730.html (EPrints GPLv3 verbatim; "managed availability" controversy)
47. https://pulse.support/kb/opensearch-vs-elasticsearch (2021 SSPL fork; 2024 AGPLv3 addition; OpenSearch→Linux Foundation)
48. https://api.github.com/repos/vespa-engine/vespa ; qdrant/qdrant ; milvus-io/milvus ; weaviate/weaviate ; pgvector/pgvector (licenses verified)
49. https://api.github.com/repos/HumanSignal/label-studio (Apache-2.0); inception-project/inception (Apache-2.0); doccano/doccano (MIT)
50. https://aitaggers.com.au/blog/label-studio-vs-doccano-vs-prodigy-2026 (Prodigy ~$490/seat; Label Studio Enterprise ~$950/mo; comparison matrix)
51. https://api.github.com/repos/neo4j/neo4j (GPL-3.0); apache/jena (Apache-2.0); ad-freiburg/qlever (Apache-2.0); blazegraph/database (GPL-2.0, last push 2023); openlink/virtuoso-opensource (GPLv2)
52. https://gdb-engines.com/db/terminusdb/ + https://terminusdb.org/ (Apache-2.0 verbatim; git-for-data; v12 Dec 2025; DFRNT maintenance)
53. https://raw.githubusercontent.com/kermitt2/grobid/HEAD/LICENSE (Apache-2.0 verbatim); https://grobid.readthedocs.io/en/stable/Grobid-service/
54. https://zenodo.org/records/10529709 (CEX trained GROBID citation-context models; OUTCITE; opencitations/cec)
55. https://github.com/SpeciesFileGroup (TaxonWorks MIT; TaxonPages; Plazi wrapper)
56. https://api.github.com/repos/TIBHannover/orkg-backend (MIT)
57. https://lobehub.com/skills/kortix-ai-kortix-registry-openalex-paper-search (cites/cited_by/related_to traversal patterns)
58. https://api.opencitations.net/index (REST v2; 180 req/min; access token; RAMOSE ISC)
59. https://opencitations.wordpress.com/2019/04/15/coci-iswc2019/ (CC0 verbatim; citations as first-class entities w/ creation date + time span — useful for temporal edges); https://zenodo.org/records/8302170 (>1.4B links, CC0)
60. https://digibug.ugr.es/bitstream/handle/10481/109407 (OpenCitations CCC — citation contexts from Europe PMC)
61. http://eprints.rclis.org/46901/ (VOSviewer claimed MIT; bibliometrix GPL/AGPL note); https://pmc.ncbi.nlm.nih.gov/articles/PMC9782747/ (co-citation/coupling capabilities)
62. https://www.connectedpapers.com + https://libguides.hkust.edu.hk/citation-chaining/citation-mapping-tools-comparison (prior/derivative works; co-citation+coupling)
63. https://www.cos.io/predicting-replicability-challenge (FORRT 3,000+ effects; Brier scoring)
64. https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0285383&type=printable (negative-citation & post-retraction-citation literature list); https://publish.illinois.edu/yiyuncheng/files/2020/10/ReTracker-paper.pdf (ReTracker)
65. https://www.nlm.nih.gov/bsd/policy/retractions.html (NLM retraction publication types)
66. https://github.com/allenai/scifact (+ doc/data.md; claims_with_citances.jsonl)
67. https://arxiv.org/pdf/2104.08663 (BEIR: "SciFact: Provided under the CC BY-NC 2.0 license"); https://arxiv.org/pdf/2210.13777.pdf (SciFact-Open 500K corpus)
68. https://foundation.epistemonikos.org/en/posts/all-health-evidence-free-and-organized-in-one-place-epistemonikos-launched-the-new-l-ove (L·OVE living evidence)
69. https://www.emergentmind.com/topics/open-research-knowledge-graph-orkg (ORKG: DataCite DOIs, immutable snapshots, provenance chains; federated GraphQL); https://nfdi4ing.de/orkg/
70. https://arxiv.org/pdf/2206.01439 (ORKG system walkthrough)
71. https://terminusdb.org/ (Apache-2.0 verbatim "open source and free to use under the Apache 2.0 license"); https://stackshare.io/stackups/neo4j-vs-terminusdb (conflicting AGPL claim)
72. https://github.com/topics/oai-pmh (MCP for Riksarkivet OAI-PMH; harvester ecosystem census)
73. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9382220/ (Serra-Garcia & Gneezy 2021 ref: nonreplicable publications cited more)
74. https://arxiv.org/html/2505.14838v2 (fine-grained temporal citation analysis w/ S2AG contexts; confirmation/correction intents)
75. https://github.com/akastrin/ida2025lbd (reproducible LBD pipelines); https://www.biorxiv.org/content/10.1101/2020.10.16.343012v1 (SKiM); https://github.com/fogbeam/Valmont-F (Arrowsmith, Apache-2.0)
76. https://intuitionlabs.ai/pdfs/research-paper-apis-for-scientific-literature-in-2026.pdf (2026 scholarly-API comparison table)
77. https://www.zobodat.at/pdf/EJT_0782_0173-0196.pdf (Plazi workflow: treatments/figures/materials citations as FAIR data; DataCite DOIs; DwC-A→GBIF; CoL/backbone name attribution)
