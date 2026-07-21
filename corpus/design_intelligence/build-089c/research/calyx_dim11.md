# Calyx Deep-Dive — Dimension 11: Software Stack Selection & Integration Architecture (Build vs Reuse)

**Agent date:** 2026-07-21 · **Method:** ~15 search batches (~45 queries) + live verification via GitHub REST API (24 repos), PyPI JSON API (7 packages), official docs/release notes. Context: wide05 (Document AI landscape), wide06 (existing software catalog).
**Confidence tags:** [HIGH] = verified this session via repo/PyPI/official doc; [MED] = strong secondary evidence; [LOW] = inference.

---

## 1. Executive Summary — The Recommended Stack

1. **Registry/repository:** InvenioRDM v13 (MIT) — reuse, don't build.
2. **Harvest:** oaipmh-scythe 0.14.2 (BSD-3) + custom rights-check service — build thin layer.
3. **Queue/orchestration:** RabbitMQ 4.x (MPL-2.0) for event queueing + **Prefect 3** (Apache-2.0) for orchestration — NOT Airflow (0.5–1 FTE ops burden).
4. **Parse:** GROBID 0.9.0 (Apache-2.0, refs/sections, CPU) + **Marker 2.0.0 — relicensed GPL→Apache-2.0 on 2026-07-20** (layout, GPU) + MinerU 3.4.4 only for scanned/CJK tier (custom license — isolate).
5. **Entity/name layer:** gnfinder + gnverifier/gnames (MIT) — reuse.
6. **Storage:** **NOT MinIO** (CE archived 2026-04-25) → SeaweedFS (Apache-2.0) or managed S3.
7. **Search:** OpenSearch 3.7 (Apache-2.0) lexical+vector; defer Vespa.
8. **Knowledge layer:** qlever (Apache-2.0) as public SPARQL endpoint; Neo4j deferred; nanopub-model RDF emission via nanopub-py (Apache-2.0).
9. **Review queue:** INCEpTION 41.x (Apache-2.0) with external-recommender HTTP loop; Label Studio only if multimodal needed.
10. **API:** REST (FastAPI) primary + versioned snapshot releases with DataCite DOIs (WCVP model); SPARQL public read-only with WDQS-style limits; GraphQL deferred.
11. **ETL/reconciliation:** OpenRefine 3.9.5 (BSD-3) interactive only, not in pipeline.
12. **Team reality:** CORE runs a 200M-record aggregator with **12 people**; a 1–3-engineer team must defer Neo4j, Vespa, Kafka, TerminusDB, self-hosted Kubernetes.

---

## 2. Component-by-Component Decision Table (verified 2026-07-21)

| # | Component | Choice / Version (verified) | License (verified) | Role in Calyx | Integration notes | Risk |
|---|---|---|---|---|---|---|
| 1 | **InvenioRDM** | v13.0 (2025-07); repo pushed 2026-07-16 [HIGH] | MIT (GitHub API) [HIGH] | Thesis registry + Calyx release repository (DOIs, versioning, OAI-PMH provider) | Docker-compose deploy; custom metadata schema for reasoning objects; OAI-PMH sets re-expose Calyx content; DataCite DOI versioning built-in | Ops complexity (Flask+React+OpenSearch+Postgres+RabbitMQ+Redis ~7 services); needs ~0.25 FTE [MED] |
| 2 | **DSpace 7/8/9/10** | dspace-10.0 released 2026-05-28 [HIGH] | BSD-3-Clause [HIGH] | **Harvest target only**, not Calyx infra | Most institutional ETD repos run DSpace — oaipmh-scythe harvests its OAI-PMH; REST API for PDF bitstream URLs | None as target; do not adopt as own registry (Java heaviness) [HIGH] |
| 3 | **oaipmh-scythe** | 0.14.2 (2026-04-10), pushed 2026-07-05 [HIGH] | BSD-3-Clause (PyPI) [HIGH] | OAI-PMH harvesting (all 6 verbs, httpx+lxml) | Python lib inside harvest workers; resumption-token handling; emits `HarvestEvent` to queue | Small project (16 stars) — single-maintainer risk; fork-and-vendor acceptable [MED] |
| 4 | **GROBID** | 0.9.0 (2025-05-11; repo moved kermitt2→grobidOrg) [HIGH] | Apache-2.0 [HIGH] | Citation/reference + section extraction, consolidation | Stateless REST service in Docker (official multi-arch images, JDK 21); scale horizontally behind queue consumers; 10.6 PDF/s full-text on 16-CPU server (articles) [HIGH]; header 36 PDF/s | Thesis front-matter/chapter layout weaker; needs thesis fine-tune later [HIGH] |
| 5 | **biblio-glutton** | 0.3 (GROBID 0.8.1+ support) [HIGH] | Apache-2.0 [HIGH] | Local high-throughput biblio consolidation (Crossref+PubMed+Unpaywall) | Elasticsearch-backed service; deploy only when Crossref API rate (25 q/s) becomes bottleneck — defer to 100k+ corpus | Extra ES cluster to operate [MED] |
| 6 | **Docling** | 2.114.0 (2026-07-20) [HIGH] | MIT (PyPI) [HIGH] | Fallback parser; structure+provenance (page+bbox) layer; non-PDF formats | Python lib in parse workers; CPU-capable (~1–4 s/page); air-gapped | Slower than Marker on GPU; no reference extraction ("coming soon") [HIGH] |
| 7 | **Marker** | **2.0.0 released 2026-07-20 — code relicensed GPL-3.0→Apache-2.0 (PyPI metadata + LICENSE file both confirm; 1.9.3 was GPL-3.0-or-later); surya also Apache-2.0 now** [HIGH] | Apache-2.0 code; **model weights license still to re-verify** (historically modified OpenRAIL-M, free <$2M revenue/funding) [MED] | Primary layout parser for born-digital theses (MD/JSON + section_hierarchy + TOC metadata) | GPU worker pool: 3.17 GB VRAM/doc, ~5 GB peak/worker; 0.18 s/page single, projected 25–122 pp/s H100 [HIGH]; `marker_server` FastAPI for service mode | Weight-license for commercial redistribution; OOM on very long PDFs (split chapters) [MED] |
| 8 | **MinerU** | 3.4.4 (2026-07-10) [HIGH] | MinerU Open Source License (custom, Apache-2.0-based; AGPLv3 before 2026-04-18) [HIGH] | Accuracy tier for scanned/CJK/complex-layout theses only | Run as isolated service (separate container) to contain custom-license surface; sliding-window long-doc mode handles 200+ pp theses [HIGH] | Custom license needs legal read before redistribution; slower (READoc: ~215 s/doc vs Marker 28 s) [HIGH] |
| 9 | **gnfinder / gnverifier / gnames** | gnfinder pushed 2026-05; gnames MIT (repo verbatim) [HIGH] | MIT [HIGH] | Taxon-name detection (15M pp/h) + verification vs 100+ backbones | Go binaries as REST sidecars; self-host gnames (32 GB RAM, 50 GB disk, Postgres) when API rate becomes issue; feeds OpenRefine recon API too | Single-author ecosystem (Mozzherin) — bus factor [MED] |
| 10 | **OpenRefine** | 3.9.5 stable; 3.10-beta2 (2026-02-10) [HIGH] | BSD-3-Clause [HIGH] | Interactive metadata cleanup + entity reconciliation (IPNI/Wikidata recon services) | Analyst tool, NOT pipeline component; gnames exposes a recon-API endpoint compatible with it [HIGH] | None — keep out of automated path [HIGH] |
| 11 | **INCEpTION** | 41.1 (2026-07-07) [HIGH] | Apache-2.0 [HIGH] | Human adjudication of extracted reasoning spans; KB linking; curation | **External-recommender HTTP protocol**: Calyx classifiers expose predict/train endpoints (documented protocol; spaCy reference impl in Flask) → active-learning loop: recommender pre-labels → humans correct → retrain [HIGH] | Java webapp, single-host; annotation-project admin is manual [MED] |
| 12 | **Label Studio CE** | pushed 2026-07-21 (28k stars) [HIGH] | Apache-2.0 (CE) [HIGH] | Backup/alternative review queue; multimodal (PDF page images) tasks | Webhooks → retraining jobs; ML-backend pre-annotation | Overlaps INCEpTION — pick ONE; INCEpTION wins for span+KB-linking fit [MED] |
| 13 | **OpenSearch** | 3.7.0 (2026-06-09) [HIGH] | Apache-2.0 (Linux Foundation) [HIGH] | Lexical + k-NN vector search over thesis full text & extracted claims | Also embedded in InvenioRDM — share the cluster to save ops; HNSW vector indexes for claim embeddings | 5.5× vector gains in 3.7 need reindex; JVM heap sizing [MED] |
| 14 | **qlever** | v0.5.50 (pushed 2026-07-17) [HIGH] | Apache-2.0 [HIGH] | Public SPARQL endpoint for the reasoning ledger (RDF) | Single-binary, low RAM, SPARQL+text; load nanopub-style named graphs; front with rate-limit proxy (WDQS policy as model: 60 s timeout, 5 concurrent/IP) [HIGH] | v0.x versioning; no built-in authz — put behind proxy [MED] |
| 15 | **Neo4j** | 5.26.x CE (pushed 2026-07-08) [HIGH] | GPL-3.0 (community) [HIGH] | ~~App-side reasoning graph~~ → **DEFER** | Property graph attractive for traversal UX, but: second graph stack to maintain + GPL-3.0; qlever/RDF covers the ledger, OpenSearch covers retrieval | Defer until a consumer actually needs Cypher/GQL [MED] |
| 16 | **TerminusDB** | v12.0.6 (2026-06-24, DFRNT-maintained) [HIGH] | Apache-2.0 (site; older sources said GPL/AGPL — conflict noted in wide06) [MED] | ~~Temporal versioned KG~~ → **DEFER** | Git-style branch/merge is intellectually right for a "reasoning ledger," but small community + license-history confusion | Substitute: named-graph snapshots in qlever + WCVP-style annual DOI'd dumps [MED] |
| 17 | **Vespa** | 8.x, pushed 2026-07-21 [HIGH] | Apache-2.0 [HIGH] | ~~Hybrid lexical+vector+tensor ranking~~ → **DEFER** | Best-in-class hybrid ranking but a second search engine; OpenSearch k-NN + RRF hybrid (3.7) is sufficient at ≤1M docs [HIGH] | Revisit if relevance quality plateaus [MED] |
| 18 | **Workflow orchestration** | **Prefect 3.7.8 (2026-07-09)** chosen over Airflow 3.3.0 (2026-07-06) and Dagster 1.13.14 [HIGH] | All Apache-2.0 [HIGH] | Pipeline DAG: harvest→rights→download→parse→extract→KG-emit; retries, dynamic mapping, event-driven triggers | Python-native @flow/@task; self-hosted server + workers on 1 VM + Postgres; 2026 comparisons: Airflow self-host ≈ 0.5–1 FTE ops, Prefect lightest; Dagster best lineage but steeper model [HIGH] | OSS server lacks RBAC/SSO (fine for 1–3-person team) [HIGH] |
| 19 | **Object storage** | **NOT MinIO**: CE entered maintenance mode 2025-12, repo **archived read-only 2026-04-25**, AGPLv3, no more binaries [HIGH] → **SeaweedFS (Apache-2.0)** or managed S3 | SeaweedFS Apache-2.0; Garage AGPLv3; RustFS Apache-2.0 (young) [HIGH] | PDF blobs, TEI/JSON derivatives, page images | S3 API either way — code against `boto3`, backend swappable; start single-node SeaweedFS, ~512 MB RAM | SeaweedFS smaller ops community than MinIO had [MED] |
| 20 | **Message queue** | **RabbitMQ 4.3.3** (pushed 2026-07-21) [HIGH] over Kafka 4.0 (2025-03, ZooKeeper removed) | RabbitMQ MPL-2.0 [MED]; Kafka Apache-2.0 [HIGH] | Event bus: `harvest.discovered`, `rights.cleared`, `pdf.downloaded`, `parse.done`, `extract.done` | Task-queue semantics, per-stage consumer scaling, dead-letter queues for rights-rejected; Kafka is overkill (log replay, 1.9M partitions) until multi-team event streaming [HIGH] | RabbitMQ also embedded in InvenioRDM — share the broker [HIGH] |

**Build (thin, Calyx-specific) vs Reuse summary:** BUILD = rights-check service, thesis→article linker, reasoning-span classifiers, chapter/TOC segmentation layer, nanopub emitter, API gateway. REUSE = everything in the table above.

---

## 3. Architecture Blueprint (event-driven)

```
OAI-PMH sources (DSpace/EPrints/OJS repos)
   │  oaipmh-scythe pollers (Prefect scheduled flows)
   ▼
[RabbitMQ exchange: calyx.events]
   │ harvest.discovered ─► Rights-check service (BUILD: license/embargo/robots logic
   │                        + OpenAlex OA status + Unpaywall) ─► rights.cleared
   ▼
Download workers ─► SeaweedFS (raw PDF) ─► pdf.downloaded
   ▼
Parse tier (two lanes, content-routed):
   ├─ born-digital ─► Marker GPU workers (marker_server, 4–6 workers/GPU)
   ├─ scanned/CJK/complex ─► MinerU service (isolated container)
   └─ always ─► GROBID CPU service (Docker, N replicas behind consumers;
                references + consolidation via biblio-glutton or Crossref)
   ▼ parse.done (TEI + Marker JSON in object store, URIs in event)
Entity/extract tier:
   ├─ gnfinder/gnverifier sidecars (taxon names → GBIF/POWO/WCVP backbone pinning)
   ├─ section/discourse classifiers (BUILD: SciBERT/DeBERTa)
   └─ scoped LLM passes (constrained JSON + span anchors; GPU or API budget)
   ▼ extract.done
KG emission (BUILD): nanopub-per-claim (assertion+provenance+pubinfo, trusty URI)
   ├─► qlever (RDF reasoning ledger, SPARQL)  ──► public read-only endpoint w/ limits
   └─► OpenSearch (lexical + vector, per-chunk provenance)
Review loop: low-confidence spans ─► INCEpTION (external recommender = Calyx
   classifier over HTTP) ─► corrected annotations ─► Prefect retrain flow ─► new model version
Registry & releases: InvenioRDM (metadata+DOIs); annual snapshot dumps
   (RDF + JSONL + OpenAlex-style flat files) → DataCite DOI per version (WCVP model)
```

**GROBID placement:** official Docker images, stateless, CPU-only (CRF+DeLFT); run 2–4 replicas behind RabbitMQ consumers; 8–16 threads each. GPU only for DeLFT DL models — optional.
**GPU needs:** 1× 24 GB GPU (RTX 4090/L4) handles Marker 4–6 workers + a 7–9B LLM for scoped passes at 10k-thesis scale; 100k+ wants 1× H100-class or 2× 4090; MinerU VLM mode needs its own GPU share [HIGH, from wide05 throughput figures].

## 4. Storage & Throughput Sizing Math

**Average thesis size evidence:** NDLTD digitization study: ~70 KB/page × ~186 pages ≈ **13 MB per scanned thesis** [^s4^]; Old Dominion/Virginia Tech ETD corpus: **3.4 TB / 451,358 ETDs ≈ 7.9 MB average** (mixed born-digital+scanned) [^s5^]. Planning figure: **10 MB/thesis PDF** [HIGH for order of magnitude].

| Corpus | Raw PDFs | +Derivatives (TEI/JSON/MD ~15% of PDF) + page-image cache (optional 1×) | OpenSearch index (~0.3×) | qlever RDF (~50 claims/thesis ≈ 0.1×) | Total (planning) |
|---|---|---|---|---|---|
| 10k theses | 100 GB | ~120–220 GB | 30 GB | 10 GB | **~0.3 TB** |
| 100k | 1 TB | 1.2–2.2 TB | 300 GB | 100 GB | **~3 TB** |
| 1M | 10 TB | 12–22 TB | 3 TB | 1 TB | **~30 TB** |

**Parse time (250 pp avg):** 10k theses = 2.5M pages → Marker @25 pp/s single GPU ≈ **1.2 days**; GROBID parallel ≈ 1–2 days. 1M theses = 250M pages → 1 H100 @25–122 pp/s ≈ **24–116 days** (batch project, not ops load) [HIGH arithmetic on wide05 figures]. LLM scoped passes are the cost driver: budget per-section, not per-document (wide05 §12).

## 5. Knowledge Layer Decisions

- **Triplestore (qlever) vs property graph (Neo4j):** choose **qlever-only initially**. Rationale: RDF/nanopub model is the natural ledger; qlever Apache-2.0, single binary, SPARQL 1.1 + full-text; Neo4j CE is GPL-3.0 and doubles the graph-ops surface. Property-graph UX can later be served by an RDF→LPG export job. [MED]
- **Nanopublication store options:** (a) emit trusty-URI nanopubs into qlever as named graphs (full control); (b) publish to the public nanopub server network (decentralized, grlc/QPF query layer on top; nanopub-py Apache-2.0 client) [HIGH]; (c) hybrid: internal qlever master + selective publication to nanopub network for citable claims. Recommend (c). [MED]
- **ORKG import/export:** ORKG offers REST API, Python package, **SPARQL endpoint (Virtuoso)** and **full RDF dump (N-Triples)** [HIGH, orkg.org/data]. Calyx↔ORKG: align contribution schema; export Calyx comparisons to ORKG via its REST API; import ORKG dump into qlever for cross-claims. ORKG's immutable-snapshot+provenance-chain versioning = the model for Calyx annual releases [HIGH].

## 6. Review Queue & Active Learning

- **INCEpTION** is the domain-fit choice (span annotation + KB linking + curation/adjudication + recommenders). Integration: implement INCEpTION's **external-recommender HTTP protocol** in a small FastAPI service wrapping Calyx's span classifiers — recommenders both *predict* (pre-annotation) and *train* (INCEpTION pushes corrected docs back) [HIGH, official docs]. This closes the active-learning loop: classifier pre-labels → human adjudicates → retrain flow (Prefect) → new model deployed to recommender and pipeline.
- Label Studio CE kept as alternative only for PDF-page-image tasks INCEpTION handles poorly (figure/table region adjudication) [MED].

## 7. API Layer for Calyx Consumers

- **REST (FastAPI) primary**, OpenAPI-documented: `/theses/{id}`, `/claims/{id}`, `/taxa/{name}`, `/lineage/{thesis}`. REST wins over GraphQL for a 1–3-engineer team: caching, rate-limiting, and versioning are simpler; scholarly-infrastructure consumers (CORE, OpenAlex, ORKG) all ship REST [MED].
- **GraphQL deferred** — adds a second schema to maintain; revisit if UI complexity demands it. (ORKG added GraphQL federation only at maturity [wide06].)
- **SPARQL exposure policy:** public **read-only** qlever endpoint behind a proxy enforcing WDQS-style rules: 60 s query timeout, ~5 concurrent per IP, descriptive User-Agent required, no federation whitelist exceptions [HIGH, WDQS policy]. Heavy consumers get the **annual dump** instead.
- **Versioning:** WCVP-style annual snapshot releases (per wide06 §5): full RDF dump + JSONL claims export + OpenSearch snapshot, each minted a DataCite DOI via InvenioRDM; `calyx/v2026`, `v2027`…; SPARQL named graph per snapshot so queries can pin a version. [HIGH as pattern]

## 8. Team-Effort Reality Check (1–3 engineers)

| Reference | Scale | Team | Lesson |
|---|---|---|---|
| **CORE** (Open Univ.) | 218M→291M metadata records, 10k+ providers, 30M MAU | **"a team of 12 people actively maintaining it"** (SIGIR 2023 lecture by founder Knoth) [^s6^] [HIGH] | A 6-stage OAI-PMH pipeline at global scale needs ~10 FTE. Calyx at ≤100k theses is ~1/1000th the provider count — 1–3 engineers feasible **if** scope is orchid-domain only |
| **Semantic Scholar** (AI2) | 200M+ papers | Open Data Platform paper (2025) lists ~45 team members; AI2 overall ~75–200 staff [^s7^] [MED] | Full-text + citations + APIs at 200M scale = tens of FTE. Do not emulate scope |
| **OpenAIRE** | EU-wide graph | Multi-institution consortium (CNR, UoA, ICM, Bielefeld…) [^s8^] [HIGH] | Consortium infrastructure — not a small-team model |
| **GROBID** | Used by OpenAlex/S2/HAL | ~1–2 core maintainers + community [HIGH] | Single-purpose OSS services can be run tiny — the model for Calyx's own services |

**Implication:** 1–3 engineers can operate: 1 search engine + 1 triplestore + 1 queue + 1 orchestrator + 1 object store + registry + ~6 GPU/CPU worker services. **Cannot** additionally operate: Kafka, Neo4j, Vespa, TerminusDB, Kubernetes.

**Defer list:** Neo4j · Vespa · TerminusDB · Kafka · biblio-glutton (until Crossref rate hurts) · self-hosted gnames (until API limits) · GraphQL · Label Studio · multi-node SeaweedFS replication · Kubernetes (use docker-compose/systemd).

## 9. License Compatibility Audit

| Component | License | Pipeline-safe? | Notes |
|---|---|---|---|
| InvenioRDM, GROBID, biblio-glutton, Docling, qlever, OpenSearch, Prefect/Airflow/Dagster, INCEpTION, Label Studio CE, Vespa, Kafka, TerminusDB, SeaweedFS | MIT / Apache-2.0 | ✅ safe core | Apache/MIT/BSD path is fully achievable [HIGH] |
| oaipmh-scythe, OpenRefine, DSpace (target) | BSD-3 | ✅ | [HIGH] |
| gnfinder/gnverifier/gnames | MIT | ✅ | [HIGH] |
| **Marker 2.0** | **Apache-2.0 code (new, 2026-07-20)**; weights historically OpenRAIL-M/cc-by-nc-sa variant with <$2–5M waiver | ✅ code; ⚠️ **re-verify weight license before commercial redistribution** | The single biggest stack change this week [HIGH for code relicense; MED for weights] |
| **MinerU 3.x** | Custom "MinerU Open Source License" (Apache-2.0-based, from AGPLv3 2026-04) | ⚠️ isolate as service; legal read before redistribution | Keep behind container boundary; parsed *output* (text/JSON) is data, not derivative code [MED] |
| RabbitMQ | MPL-2.0 | ✅ (file-level copyleft, service use fine) | [MED] |
| Neo4j CE, Garage | GPL-3.0 / AGPLv3 | ⚠️ deferred anyway | [HIGH] |
| **MinIO** | AGPLv3 + upstream archived | ❌ do not adopt | Vendor asserted AGPL reaches *connecting software* (GH issue #13308) [HIGH] |
| pymupdf4llm, CERMINE, DocLayout-YOLO, EPrints, OJS | AGPL/GPL | ❌ pipeline exclusion or target-only | (wide05/wide06) [HIGH] |

**Copyleft-contamination policy:** all ⚠️/❌ components run as **network services in separate containers**, never as linked libraries; pipeline code stays Apache-2.0; parsed outputs are data and not license-contaminated. Service-boundary isolation is the standard industry pattern for GPL tooling (FOSSA guidance) [^s9^] [MED].

---

## URL List

[^s1^] GitHub REST API verifications (2026-07-21): invenio-app-rdm (MIT, pushed 2026-07-16); DSpace/DSpace dspace-10.0 (2026-05-28); afuetterer/oaipmh-scythe 0.14.2 (2026-04-10); docling 2.114.0 (2026-07-20); opendatalab/MinerU 3.4.4 (2026-07-10); inception 41.1 (2026-07-07); qlever v0.5.50 (Apache-2.0, pushed 2026-07-17); terminusdb v12.0.6 (2026-06-24); apache/airflow 3.3.0 (2026-07-06); PrefectHQ/prefect 3.7.8; dagster 1.13.14; neo4j (GPL-3.0, pushed 2026-07-08); label-studio (Apache-2.0); kafka (Apache-2.0); rabbitmq-server v4.3.3; vespa (Apache-2.0); gnames/gnfinder (MIT) — https://api.github.com/repos/…
[^s2^] PyPI JSON API (2026-07-21): marker-pdf 2.0.0 license "Apache-2.0" (vs 1.9.3 "GPL-3.0-or-later"), uploaded 2026-07-20; docling 2.114.0 MIT; prefect 3.7.8 Apache-2.0; dagster 1.13.14 Apache-2.0; oaipmh-scythe 0.14.2 BSD-3-Clause — https://pypi.org/pypi/{pkg}/json
[^s3^] Marker LICENSE file now Apache-2.0 (master); surya LICENSE Apache-2.0; README (older snapshot): "code is GPL… weights modified AI Pubs Open Rail-M… free for research, personal use, and startups under $2M"; throughput "122 pages per second on an H100", "5GB of VRAM per worker at the peak" — https://github.com/datalab-to/marker ; https://raw.githubusercontent.com/datalab-to/marker/master/LICENSE
[^s4^] NDLTD ETD digitization study: "~70 Kb per page… 13 Mb per document… 186 pages average" — https://docs.ndltd.org/collection/etd2007/paper-11.pdf
[^s5^] ODU/VT ETD corpus paper: "The total size of the repository is 3.4 terabytes… 451,358 records" — https://vtechworks.lib.vt.edu/server/api/core/bitstreams/09d1d81d-5301-44d5-b5df-ed4e93f74b56/content
[^s6^] CORE team of 12 (SIGIR Forum lecture, Knoth) — http://sigir.org/wp-content/uploads/2023/01/p16.pdf ; CORE Sci Data paper — https://www.nature.com/articles/s41597-023-02208-w
[^s7^] Semantic Scholar Open Data Platform author list (~45 names, 2025) — https://sciarena.allen.ai/SciArena_An_Open_Evaluation_Platform_for_Foundation_Models_in_Scientific_Literature_Tasks.pdf (ref 30)
[^s8^] OpenAIRE technical infrastructure (D-Net + Invenio; multi-institute) — https://www.cnr.it/en/focus/074-17/
[^s9^] GPL/Apache service-boundary isolation guidance — https://fossa.com/resources/devops-tools/license-compatibility-checker/gpl-3-0-vs-apache-2-0/
[^s10^] MinIO CE maintenance mode/archival: bizety 2025-12, glukhov.org 2026-05 (timeline: UI removal 2025-05, binaries stopped 2025-10, maintenance mode 2025-12, archived 2026-02/2026-04-25), stormdevelopments 2026-06; alternatives SeaweedFS/Garage/RustFS/Ceph — https://www.glukhov.org/data-infrastructure/object-storage/minio-dead/ ; https://stormdevelopments.ca/blog/minio-s-community-edition-is-archived-what-still-runs-in-2026/ ; https://rilavek.com/resources/self-hosted-s3-compatible-object-storage-2026
[^s11^] GROBID 0.9.0 release notes (2025-05-11, grobidOrg) — https://github.com/grobidOrg/grobid/releases/
[^s12^] InvenioRDM v13.0 release notes (2025-07) — https://inveniordm.docs.cern.ch/releases/v13/version-v13.0.0/
[^s13^] OpenSearch version history (3.7.0, 2026-06-09) — https://docs.opensearch.org/latest/version-history/
[^s14^] Kafka 4.0 release (2025-03-18; ZooKeeper removed, KRaft) — https://kafka.apache.org/blog/2025/03/18/apache-kafka-4.0.0-release-announcement/
[^s15^] Airflow/Dagster/Prefect 2026 comparisons (Airflow self-host 0.5–1 FTE; Prefect for ≤3 engineers; Dagster asset model) — https://getbruin.com/blog/best-data-pipeline-tools-2026/ ; https://www.getorchestra.io/blog/dagster-vs-prefect-vs-airflow-complete-data-orchestration-comparison-2026 ; https://www.birjob.com/blog/data-pipelines-airflow-dagster-prefect-2026
[^s16^] INCEpTION external recommender protocol — https://inception-project.github.io/example-projects/external-recommender/
[^s17^] ORKG data access (REST, SPARQL/Virtuoso, RDF dump N-Triples) — https://orkg.org/data
[^s18^] Nanopublication service layer (server network; grlc + QPF; no open SPARQL) — https://pmc.ncbi.nlm.nih.gov/articles/PMC7959648/ ; nanopub-py Apache-2.0 — https://research-software-directory.org/software/nanopub
[^s19^] WDQS policy (60 s timeout, 5 concurrent/IP, UA policy) — https://apis.io/apis/wikipedia/wikidata-query-service-sparql/
[^s20^] gnames MIT license verbatim + self-host reqs (32 GB RAM, Postgres) — https://github.com/gnames/gnames ; gnverifier — https://github.com/gnames/gnverifier
[^s21^] OpenRefine 3.10-beta2 / latest stable 3.9.5 — https://zenodo.org/records/18602789
[^s22^] Marker ecosystem 2026 (Chandra Apache-2.0; olmOCR 2 Apache-2.0; license comparison table) — https://www.marktechpost.com/2026/07/04/structured-pdf-to-json-a-guide-to-open-source-extraction-models-in-2026/

*End of report.*
