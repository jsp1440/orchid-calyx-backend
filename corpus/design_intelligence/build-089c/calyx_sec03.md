## 3. Technical Access Mechanisms

Chapters 1 and 2 established which repositories and aggregators hold orchid-relevant theses; this chapter specifies, at engineering level, how the Calyx acquisition layer connects to each: endpoint, protocol, authentication, rate policy, license signal, and full-text resolution pattern, verified in live probes on 21 July 2026. Access mechanisms stratify into three families — Open Archives Initiative Protocol for Metadata Harvesting (OAI-PMH) 2.0, REST-style application programming interfaces (APIs), and bulk file channels — and Calyx connects automatically to every Tier-A channel today, while a growing minority of Tier-B endpoints require anti-bot negotiation. The chapter closes with the identifier infrastructure that Chapter 4 assembles into the deduplicating pipeline.

### 3.1 Protocol Landscape

#### 3.1.1 OAI-PMH 2.0 as the dominant channel

OAI-PMH 2.0 remains the ground-truth acquisition protocol for electronic theses and dissertations (ETDs): every major repository platform — DSpace, EPrints, Digital Commons (bepress), Hyku, WEKO3, VuFind-based national aggregators — exposes its six verbs (`Identify`, `ListMetadataFormats`, `ListSets`, `ListIdentifiers`, `ListRecords`, `GetRecord`) over HTTP with XML responses.[^1^] Five mechanics matter for the acquisition layer:

1. **Verbs and paging.** `ListIdentifiers` and `ListRecords` return incomplete lists continued via an opaque `resumptionToken`; an empty token element signals list end, and optional attributes (`completeListSize`, `cursor`, `expirationDate`) support progress tracking. The maintained Python client is oaipmh-scythe (BSD-3-Clause), a fork of the stalled Sickle library built on httpx and lxml, which follows tokens automatically; Calyx must persist the last token itself to resume after a crash, since OAI idempotency guarantees a repository accepts re-issued tokens.[^2^]
2. **Sets.** Selective harvesting via `setSpec` is the primary precision instrument: the NDLTD union archive exposes 212 collection sets, theses.fr STAR exposes Dewey discipline sets (`ddc:580` = "Plantes. Botanique") plus a `diffusable` full-text-dissemination set, and the German National Library (Deutsche Nationalbibliothek, DNB) mirrors the DDC hierarchy under `dnb:reiheH:sg5*` for Hochschulschriften.[^3^][^4^][^5^]
3. **Incremental harvesting.** `from`/`until` datestamps are inclusive at both ends; granularity (day vs. second) is declared in `Identify`, which Calyx queries first per endpoint, caching granularity, earliestDatestamp, deletedRecord policy, and adminEmail. A 2-day overlap on `from` compensates for day-granularity and timezone drift.
4. **deletedRecord policies.** `Identify.deletedRecord` ∈ {no, transient, persistent}. Persistent repositories (NDLTD union, OhioLINK, LA Referencia) advertise deletions indefinitely; transient ones (DNB, Wageningen) only within a window. Deleted headers carry no metadata and are Calyx's embargo/takedown compliance path: they are processed into tombstone events that quarantine the corresponding full text within one sync cycle. Repositories with `deletedRecord=no` require periodic full `ListIdentifiers` diffing.[^1^][^2^]
5. **Metadata richness.** `oai_dc` (simple Dublin Core) is mandatory but thin. The thesis-specific ETD-MS vocabulary (`oai_etdms`/`etdms11`) carries degree name/level/discipline/grantor and, on OhioLINK, machine-capturable license text distinguishing Creative Commons (CC) from all-rights-reserved deposits.[^6^] Theses.fr STAR serves native AFNOR TEF 2.0 XML embedding full-text access URLs; DSpace-derived endpoints (LA Referencia, TDR, most Tier-1 botanical repositories) serve `xoai`/`dim` with bitstream and license bundles. Format availability is record-dependent — the NDLTD union returns `cannotDisseminateFormat` for `oai_etdms` where the source exposed only `oai_dc` — so Calyx harvests `oai_dc` as baseline and attempts richer prefixes opportunistically.[^3^]

The countervailing evidence is fragility: a 2026 peer-reviewed infrastructure study found approximately 44% of OAI-PMH endpoints dead and roughly one in five repositories offline.[^7^] OAI-PMH is therefore Calyx's precision instrument for Tier-1 botanical sources and national aggregators — not a strategy for endpoint-gardening the long tail.

#### 3.1.2 REST APIs, GraphQL, and SRU

The second family, JSON REST APIs, now carries most of the discovery load. OpenAlex (`api.openalex.org`) has required an API key since February 2026: free keys carry a $1/day credit (anonymous $0.10/day), singleton lookups are free, list/filter calls cost $0.10 per 1,000, search $1 per 1,000, and a 100 requests/second cap is enforced by live 429 responses observed on 21 July 2026.[^8^] DataCite (`api.datacite.org/dois`, JSON:API v2) is unauthenticated with tiered limits — 500 requests/5 min anonymous, 1,000/5 min identified, 3,000/5 min authenticated; its GraphQL endpoint retires 1 July 2027 and legacy REST v1 endpoints were retired in July 2026, so integration targets REST v2 or the DataCite OAI-PMH service, which accepts base64url-encoded query setspecs (e.g., harvest exactly `types.resourceTypeGeneral:Dissertation` per member).[^9^] Crossref remains keyless with a mailto-identified polite pool (~50 requests/second guidance). National-node APIs complete the picture: theses.fr REST (100,000-result cap), Norway's NVA (36,162 DegreePhd records live), Trove API v3 (thesis metadata at Level-1 approval with a purpose-built `bulkHarvest=true` paging mode; artificial-intelligence training use triggers Level 3–4 review and possibly a data-sharing agreement), and Korea's RISS OpenAPI (application-based via KERIS).[^10^][^11^][^12^] Search/Retrieval via URL (SRU) persists at DNB (verified live) and Swepub — whose SRU returned an Anubis proof-of-work anti-bot challenge on probe day, a new friction for a formally free-reuse service.[^5^][^13^]

#### 3.1.3 Bulk channels

Bulk files are the cost-optimal seed for every large channel, consistent with the snapshot-first posture. The OpenAlex snapshot (CC0) distributes from the public S3 bucket `s3://openalex` (us-east-1, anonymous access): approximately 330 GB compressed JSONL (~1.6 TB decompressed) partitioned by entity and update date, with Parquet mirrors since June 2026 and per-entity `manifest.json` completeness signals; free-tier refresh is **quarterly** (the older help-center "monthly" copy is superseded by June 2026 developer documentation), with daily snapshots and 60-day changefiles on paid plans.[^14^] The CORE Dataset dump (latest: 12 July 2024, 749 GB compressed, registration-gated) is licensed Open Data Commons Attribution (ODC-BY) and structured as a ResourceSync Resource Dump with per-resource MD5 fixity; CORE FastSync applies the same standard (ANSI/NISO Z39.99-2017) for incremental, always-current local copies at enterprise tier.[^15^] theses.fr publishes a full CSV/JSON/NDJSON dump on data.gouv.fr under Etalab Open Licence 2.0 — stale since 8 January 2024, so OAI/API incrementals gap-fill.[^16^] EThOS distributes a versioned CC0 CSV (v9, 2022, 610,535 records).[^17^] HathiTrust HathiFiles provide monthly full plus daily incremental bibliographic dumps. The World Checklist of Vascular Plants (WCVP) issues annual DOI'd snapshots (v15, January 2026, DOI 10.34885/rvc3-4d77) — the model Calyx adopts for its own releases.[^18^]

### 3.2 Connection Matrix

#### 3.2.1 Per-channel matrix for Tier-A/B sources

Table 3.1 consolidates verified connection parameters for every Tier-A and Tier-B channel. "License metadata" indicates whether a machine-readable license is available in the channel itself; "full-text resolution" gives the pattern by which a record yields a PDF.

**Table 3.1. Connection matrix, Tier-A and Tier-B acquisition channels (verified 21 July 2026).**

| Channel | Endpoint/URL | Protocol | Auth | Rate limit/etiquette | License metadata | Full-text resolution | Docs link |
|---|---|---|---|---|---|---|---|
| NDLTD union archive | `https://ndltdunion.cs.uct.ac.za/OAI-PMH/` | OAI-PMH 2.0 | None | No published policy; 1 req/2–5 s; pilot required | dc:rights sparse; oai_etdms where source permits | dc:identifier → source URL (often direct PDF) | openarchives.org spec; portal footer feeds[^3^] |
| OpenAlex API | `https://api.openalex.org/works` | REST/JSON | API key (free) | $1/day credit; 100 req/s; 429 enforced | `best_oa_location.license` per location | `best_oa_location.pdf_url`; Content API (§3.2.2) | docs.openalex.org[^8^] |
| OpenAlex snapshot | `s3://openalex` (us-east-1) | S3 bulk (JSONL+Parquet) | None (`--no-sign-request`) | AWS Open Data; quarterly free refresh | CC0 dataset; per-location license fields | URLs in records; manifest completeness | developers.openalex.org[^14^] |
| OpenAlex Content API | `https://content.openalex.org` | REST file delivery | Key | $0.01/file | License per manifest row | 60M+ OA PDFs + GROBID TEI direct | developers.openalex.org[^19^] |
| DataCite | `https://api.datacite.org/dois`; OAI `https://oai.datacite.org/oai` | REST JSON:API v2; OAI-PMH | Optional | 500/1000/3000 req per 5 min tiers | CC0 metadata; `rightsList` (SPDX IDs) | `url`/`contentUrl` fields, inconsistent | support.datacite.org[^9^] |
| Crossref | `https://api.crossref.org/works` | REST/JSON | None | mailto polite pool; ~50 req/s | CC0-ish metadata; license arrays sporadic | link[] full-text URLs where members deposit | github.com/CrossRef/rest-api-doc[^20^] |
| CORE | `https://api.core.ac.uk/v3`; dump 749 GB | REST; ResourceSync dump/FastSync | Free key | Unregistered ~5 req/10 s | ODC-BY dump; per-record licenses | ~57M hosted full texts; downloadUrl | api.core.ac.uk/docs/v3[^15^] |
| theses.fr (STAR) | `http://staroai.theses.fr/OAIHandler`; `https://theses.fr/api/v1/theses/recherche/` | OAI-PMH; REST | None | 100k result cap; no published limit | Etalab OL 2.0 metadata; TEF access flags | TEF access URL → STAR/CINES/HAL PDF; `diffusable` set | documentation.abes.fr[^4^] |
| EThOS | `bl.iro.bl.uk` dataset collection | CSV dump (CC0) | None | Versioned DOI chain | CC0 metadata; per-university full-text terms | Institutional-link field → university IR PDF (~65%) | bl.uk/collection/ethos[^17^] |
| DNB | `https://services.dnb.de/oai/repository`; SRU `services.dnb.de/sru/dnb` | OAI-PMH; SRU/CQL | None | Fair use; `from`/`until` incrementals | Catalogue data free; GND CC0 | URN:NBN/d-nb.info → DissOnline/university PDF | services.dnb.de[^5^] |
| NVA (Norway) | `https://api.nva.unit.no/search/resources` | REST/JSON | None (read) | Undocumented; polite paging | Per-artifact license names | `associatedArtifacts` file identifiers | GitHub Unit-no/nva[^11^] |
| TDR (Catalonia) | `https://www.tdx.cat/oai/request` | OAI-PMH (XOAI, DSpace 7) | None | Standard etiquette | CC0 catalogue claim; per-record CC | Bitstream PDFs on tdx.cat | tdx.cat[^21^] |
| EADD (Greece) | `https://www.didaktorika.gr/eadd-oai/request` | OAI-PMH | None | Standard etiquette | Open-data page; OA set `hdl_10442_2` | Handles 10442/* → OA collection PDFs | didaktorika.gr/eadd/opendata[^22^] |
| WUR eDepot | `https://library.wur.nl/oai` | OAI-PMH | None | Day granularity; transient deletions | Per-record rights | WUR DOI resolution → eDepot PDF | library.wur.nl[^23^] |
| IRDB (Japan) | `https://irdb.nii.ac.jp/oai` | OAI-PMH | None | Standard etiquette | junii2/oai_dc rights fields | Source WEKO3 IR bitstreams | irdb.nii.ac.jp[^24^] |
| Trove (NLA) | `https://api.trove.nla.gov.au/v3/result` | REST | API key, tiered approval | ~200 calls/min baseline tier; `bulkHarvest=true` | Rights fields per record | Source-university repositories | trove.nla.gov.au v3 guide[^12^] |
| LA Referencia | `http://oai.lareferencia.info/request` | OAI-PMH | None | earliestDatestamp buggy → set-diff incrementals | CC BY 4.0 portal; xoai license bundles | dc:identifier → national-node repos | github.com/lareferencia[^25^] |
| BDTD (Brazil) | `https://bdtd.ibict.br/vufind/OAI/Server` | OAI-PMH (VuFind) | None | **Oasisbr anti-bot interstitial on probe day** | DRIVER types; member-repo licenses | Full text at member institutions (USP TEDE, Lume, UNESP) | bdtd.ibict.br[^26^] |
| OhioLINK ETD | `https://etd.ohiolink.edu/acprod/odb_etd/ws/oai/oai` | OAI-PMH | None | No completeListSize; count during pull | oai_etdms rights: CC vs ARR machine-capturable | rave.ohiolink.edu landing → PDF | OhioLINK OAI manual[^6^] |
| Leiden (Naturalis) | `https://scholarlypublications.universiteitleiden.nl/oai2` | OAI-PMH | None | Standard | `open_access` set flag | handle 1887/* → access/item PDF | —[^27^] |
| Kew Research Repository | `https://kew.iro.bl.uk/catalog/oai` | OAI-PMH (Hyku) | None | OAI passes; HTML UI Cloudflare-blocked | Per-record license field; Plan S green OA | `concern/thesis_or_dissertations/<uuid>` | —[^27^] |
| OpenUCT | `https://open.uct.ac.za/server/oai/request` | OAI-PMH (DSpace 7) | None | Standard | CC per record; UCT OA policy | `/server/api/core/items/<uuid>/bundles` bitstreams | —[^27^] |
| UH ScholarSpace | `https://scholarspace.manoa.hawaii.edu/server/oai/request` | OAI-PMH (DSpace 7) | None | Standard | OA; watch campus-only rights field | items/<uuid> bitstreams | —[^27^] |
| EPub Bayreuth | `https://epub.uni-bayreuth.de/cgi/oai2` | OAI-PMH (EPrints 3.4.3) | None | Standard | Non-profit metadata reuse policy in Identify | `/id/eprint/<n>/1/<file>.pdf` | —[^27^] |
| KU Leuven Lirias | `https://lirias.kuleuven.be/oai` | OAI-PMH | None | gzip/deflate supported | License per record; OA mandate | Bitstream links in record | —[^27^] |
| UPM PSASIR | `http://psasir.upm.edu.my/cgi/oai2` | OAI-PMH (EPrints) | None | Standard | OA EPrints | `/id/eprint/<n>/` | —[^27^] |
| RISS (Korea) | KERIS application | OpenAPI (XML) | Application-based key | Quota per approval | Licensed | dCollection university instances | librarian.riss.kr[^28^] |
| Swepub (SRU) | `https://swepub.kb.se/sru` | SRU | None | **Anubis challenge on probe day** | MODS free-reuse | National-linkage records | kb.se Swepub data access[^13^] |

The matrix exposes three structural regularities. First, authentication is nearly free: only OpenAlex (keyed credits), Trove (tiered approval), CORE (free key), and RISS (application) gate access at all, and every gate is surmountable without payment for Calyx's use class — the constraint is budgeted throughput, not permission. Second, license metadata is the weakest column: only DataCite (`rightsList` with SPDX identifiers), OhioLINK (oai_etdms rights), the Nordic/EPrints repositories, and OpenAlex location records carry machine-readable licenses reliably; the rest require the rights-verification fallback chain (dc:rights parsing → CC REL/RDFa on landing pages → repository-default policy).[^2^] Third, full-text resolution bifurcates into hosted-PDF channels (CORE, TDR, DSpace bitstream repositories, OpenAlex Content API) and link-out channels (EThOS, BDTD, LA Referencia, DataCite), where Calyx inherits per-host politeness obligations and anti-bot exposure — BDTD, Swepub, RENATI, Shodhganga, and YÖK were all blocked or geo-restricted on probe day, and the correct response is aggregator fallback plus administrator contact, never challenge-solving.[^26^] The implication for Chapter 4 is a scheduler-driven downloader with per-host token buckets, treating blocked hosts as routine with a defined fallback order (CORE → OpenAlex Content API → Unpaywall for Crossref-keyed records → admin contact → manual queue).

#### 3.2.2 OpenAlex Content API as full-text channel

The most consequential 2026 addition is the OpenAlex Content API at `content.openalex.org`, serving more than 60 million open-access PDFs and their GROBID-generated Text Encoding Initiative (TEI) XML at predictable URLs for $0.01 per file, indexed by a 62-million-row Parquet manifest.[^19^] For the OA subset of the dissertation corpus this collapses the polite per-host download problem: one keyed endpoint delivers both file and pre-parsed structure (GROBID achieves F1 ≈ 0.87–0.90 on reference extraction), replacing thousands of heterogeneous bitstream negotiations. Two disciplines follow: Calyx mirrors every consumed file into its own content-addressed store on first touch, and no live-query dependency is designed into serving paths — the same entity is both the best full-text pathway and the canonical freemium-drift risk.

### 3.3 Identifier and Resolution Infrastructure

#### 3.3.1 The PID stack

Theses arrive under four persistent identifier (PID) families with asymmetric registry coverage. Live counts on 21 July 2026: Crossref holds 1,062,500 works typed `dissertation` (dominated by national agencies — ABES 192,563; USP consortia 125,090 — and Brazilian universities); DataCite holds 818,074 DOIs typed `resourceTypeGeneral:Dissertation` plus approximately 740,202 free-text `resourceType:Thesis` records.[^20^][^9^] The namespaces are disjoint by registration-agency prefix, so a case-normalized DOI is a safe global merge key across both. Handles (hdl.handle.net) are the DSpace default, appearing as landing-page URLs in OpenAlex locations and DataCite `url` fields; URN:NBN serves national-library theses in Germany, the Netherlands, Finland, Norway, and Sweden via nbn-resolving.org; OAI identifiers (`oai:{repo}:{local-id}`) survive verbatim inside OpenAlex `primary_location.id` as `pmh:oai:…` strings and in CORE's `identifiers.oai` field — a free pre-built crosswalk.[^20^]

One resolution gap is structural: Unpaywall keys exclusively on Crossref DOIs — verified live, a DataCite thesis DOI returns HTTP 404 — so DataCite-registered theses are systematically invisible to it; Calyx resolves OA status for non-Crossref theses via OpenAlex `best_oa_location` and repository records instead.[^29^] Unpaywall's free snapshots are discontinued, with bulk users directed to the OpenAlex snapshot.

**Table 3.2. Identifier schemes: resolution and metadata payload comparison.**

| Identifier | Example form | Resolver | Metadata payload on resolution | Registry scale (theses) | Role in Calyx |
|---|---|---|---|---|---|
| DOI (Crossref) | `10.31274/rtd-180813-580` | doi.org content negotiation | Citeproc JSON, relations, Crossmark updates | 1,062,500 typed dissertation | Primary merge key; Unpaywall/Crossref enrichment |
| DOI (DataCite) | `10.7939/r3c24qv9q` | doi.org | Schema 4.4 JSON incl. `rightsList`, `relatedIdentifiers` | 818,074 Dissertation + ~740k Thesis | Primary merge key; license + crosswalk fields |
| Handle | `hdl.handle.net/1887/NNNNNN` | hdl.handle.net | None native; scrape/OAI companion record | Ubiquitous in DSpace ETDs | Secondary key, extracted by URL regex |
| URN:NBN | `urn:nbn:de:kobv:83-opus-16117` | nbn-resolving.org | None native; catalogue record | National-library ETD corpora | Secondary key for DE/NL/FI/NO/SE theses |
| OAI identifier | `oai:union.ndltd.org:ADTP/100073` | Originating repository only | Full OAI-PMH GetRecord payload | All OAI-harvested records | Composite key (baseURL, local id); tombstone tracking |
| OpenAlex WID | `W2789295406` | api.openalex.org | Richest aggregate: locations, indexed_in, ids.mag | 11.02M core / 20.26M XPAC dissertations | Cluster seed; never sole merge authority |

Table 3.2's key asymmetry is payload: only DOI and OpenAlex identifiers resolve to structured metadata; Handle and URN:NBN resolve to landing pages, and OAI identifiers resolve nowhere outside their originating repository — which is why the composite (repository base URL, local id) must be stored at harvest time rather than reconstructed. The OpenAlex work-ID cluster is the strongest free pre-join available (one observed thesis aggregated eight locations spanning repository OAI, CiteSeerX, a union catalog, a DOI, and MAG), but OpenAlex mis-merges occur, so clusters are candidate merge groups validated against Calyx's own keys, with XPAC records quarantined until key-matched.[^20^]

#### 3.3.2 Dedupe crosswalk precedence

The merge-key ranking applied at ingest is: **DOI** (case-normalized, doi.org form) > **Handle** (regex-extracted from any URL field) > **URN:NBN** > **OAI identifier** (composite) > **canonicalized repository URL** (DSpace `/handle/`, EPrints `/id/eprint/`, Digital Commons `cgi/viewcontent` patterns collapse into the Handle/local-id space) > **fuzzy fallback** on normalized title + first-author surname + year. Title normalization lowercases, strips diacritics and punctuation, and collapses whitespace; scoring uses a token-set ratio with blocking on (surname, year). Theses are long-titled, giving high separability: scores ≥ 0.95 auto-merge (with author-surname and year ±1 corroboration), 0.85–0.95 routes to a human conflict queue, and below 0.85 records stay separate — thresholds consistent with published repository-dedupe practice (CORE's LSH-plus-embeddings; OpenAIRE's DOI-then-title) and tunable against a gold set.[^2^][^15^] Master records are repository-native (richest license, embargo, provenance state) enriched by registry records; OAI deleted-record events and DataCite state changes override all other copies within one sync cycle; no merged record is ever deleted — it is tombstoned-as-duplicate with a PROV link. Chapter 4 assembles these channels and keys into the scheduled harvest, rights-verification, and registration pipeline.

<!-- SOURCES
[^1^] OAI-PMH 2.0 specification | https://www.openarchives.org/OAI/openarchivesprotocol.html
[^2^] Calyx dim06 ingestion engineering (oaipmh-scythe, etiquette, dedupe) | https://pypi.org/project/oaipmh-scythe/
[^3^] NDLTD Union Archive OAI-PMH (live Identify/ListSets, 7,908,563 records) | https://ndltdunion.cs.uct.ac.za/OAI-PMH/?verb=Identify
[^4^] ABES documentation — Moissonnage des métadonnées (STAR OAI) | https://documentation.abes.fr/aidethesespro/co/moissonnage_metadonnes.html
[^5^] DNB OAI-PMH and SRU (live probes) | https://services.dnb.de/oai/repository?verb=Identify
[^6^] OhioLINK ETD Center OAI-PMH manual | https://www.ohiolink.edu/sites/default/files/uploads/OhioLINK-ETD-Center-OAI-PMH-MARC-Cataloging-Records-Manual_0.pdf
[^7^] Macgregor 2026 repository-infrastructure study (via calyx_dim12) | https://journals.library.ualberta.ca/jchla/index.php/jchla
[^8^] OpenAlex API authentication and credit model | https://developers.openalex.org/api-reference/authentication
[^9^] DataCite REST API rate limits and OAI-PMH service | https://support.datacite.org/docs/rest-api-rate-limits
[^10^] theses.fr REST search API (live probe) | https://theses.fr/api/v1/theses/recherche/?q=botanique&nombre=1
[^11^] NVA API (live probe, DegreePhd=36,162) | https://api.nva.unit.no/search/resources?category=DegreePhd&size=0
[^12^] Trove API v3 technical guide | https://trove.nla.gov.au/about/create-something/using-api/v3/api-technical-guide
[^13^] Kungliga biblioteket — Swepub data access | https://www.kb.se/for-bibliotekssektorn/eng/services/swepub-data-access.html
[^14^] OpenAlex snapshot format documentation | https://developers.openalex.org/download/snapshot-format
[^15^] CORE paper: FastSync, ODC-BY dumps | https://www.nature.com/articles/s41597-023-02208-w
[^16^] data.gouv.fr — Thèses soutenues en France depuis 1985 | https://www.data.gouv.fr/datasets/theses-soutenues-en-france-depuis-1985
[^17^] British Library — EThOS collection page | https://www.bl.uk/collection/ethos
[^18^] WCVP v15 snapshot DOI | https://doi.org/10.34885/rvc3-4d77
[^19^] OpenAlex Content API (developers portal) | https://developers.openalex.org/
[^20^] Crossref REST API documentation and live dissertation counts | https://api.crossref.org/types/dissertation/works
[^21^] TDR OAI-PMH (live probe) | http://www.tdx.cat/oai/request?verb=Identify
[^22^] EADD open data page | https://www.didaktorika.gr/eadd/opendata
[^23^] Wageningen University & Research Publications OAI (live probe) | https://library.wur.nl/oai?verb=Identify
[^24^] IRDB OAI-PMH (live probe) | https://irdb.nii.ac.jp/oai?verb=Identify
[^25^] LA Referencia OAI-PMH provider (live probe) | http://oai.lareferencia.info/request?verb=Identify
[^26^] BDTD VuFind OAI endpoint (anti-bot probe 2026-07-21) | https://bdtd.ibict.br/vufind/OAI/Server?verb=Identify
[^27^] Calyx dim05 botanical endpoint verification log | https://kew.iro.bl.uk/catalog/oai?verb=Identify
[^28^] KERIS — RISS Open API application notice | http://librarian.riss.kr/boardArticle/boardArticleView.do?boardArticleBean.articleId=000000016237
[^29^] Unpaywall API v2 (Crossref-keyed, live 404 on DataCite DOI) | https://unpaywall.org/products/api
-->
