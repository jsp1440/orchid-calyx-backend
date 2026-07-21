# Calyx Wide-03 Research Report

## Facet: Metadata Aggregators & Access Protocols

Date of research: 2026-07-21. Live API spot-checks performed against Crossref, DataCite, Semantic Scholar, and OpenAlex (OpenAlex was rate-limited from the research IP; counts for OpenAlex are from official pages/docs instead). Confidence tags: [HIGH] = official docs or live query; [MED] = credible secondary/derived; [LOW] = unverified or historically variable.

---

### Key Findings

1. **The single biggest 2025–26 change: OpenAlex "Walden" rewrite + XPAC.** On 2025-11-04 OpenAlex added >190M new works ("expansion pack", XPAC) drawn from *all of DataCite plus thousands of institutional and subject repositories*, taking the catalog to ~470M records (core ~278M; homepage now advertises 316M works). XPAC records are lower-quality and **excluded by default**; opt in via `include_xpac=true`, filter via `is_xpac`. This makes OpenAlex the de-facto largest dissertation-relevant metadata pool, since most ETDs live in repositories and many now have DataCite DOIs.[^2^][^3^][^4^][^5^][^1^] [HIGH]
2. **Thesis typing exists in three big registries, with three different counts.** Live queries (2026-07-21): Crossref type `dissertation` = **1,062,500 works**;[^18^] DataCite `types.resourceTypeGeneral:Dissertation` = **818,069 DOIs**, plus `types.resourceType:Thesis` (free-text) = **740,202** (overlapping; combined thesis-like DataCite records plausibly ~1–1.5M).[^17^] OpenAlex supports `type:dissertation` filter but a July 2026 type-classifier rebuild changed types of ~49.6M works (~10%), so counts are in flux.[^3^][^6^] [HIGH for counts; MED for stability]
3. **Everything important is free at metadata level; money appears at throughput and full text.** Crossref, DataCite, OpenAlex, Unpaywall, OpenAIRE, S2AG metadata, CORE (personal/research use) are free; paid tiers sell rate/volume/support (OpenAlex freemium ~$1/day free w/ key; Unpaywall Data Feed; CORE commercial licences; Crossref Metadata Plus).[^1^][^10^][^13^][^19^] [HIGH]
4. **Licensing for harvesting is cleanest at OpenAlex (CC0) and CORE dumps (ODC-BY); S2AG/S2ORC is ODC-BY (attribution, commercial OK); S2ORC's *original* release was CC BY-NC — do not mix old files.**[^8^][^9^][^15^] [HIGH]
5. **S2 is weak for dissertations.** S2ORC historically "does not include slides, dissertations, books" — Semantic Scholar's canonical paper notion excludes most theses; use S2 for citation enrichment, not discovery.[^9^] [HIGH]
6. **OAI-PMH remains the ground-truth acquisition layer for ETDs.** All major repository platforms (DSpace, EPrints, Digital Commons, OJS) expose OAI-PMH; registries/validators exist (openarchives.org Register/BrowseSites, ValidateSite, validator.oaipmh.com, BASE OVAL); ResourceSync (ANSI/NISO Z39.99-2017) is the modern bulk-sync successor and underpins CORE FastSync.[^22^][^23^][^24^][^15^] [HIGH]
7. **Legal posture for metadata harvesting is favorable; full-text TDM is jurisdiction-split.** EU DSM Directive 2019/790 Art. 3 (research TDM, no opt-out possible) / Art. 4 (general TDM, opt-out via machine-readable reservation) vs US fair use (Authors Guild v. HathiTrust 2014; Authors Guild v. Google 2015, cert. denied 2016) which blesses non-expressive copying for search/mining. CFAA risk for scraping public pages receded after Van Buren (2021) and hiQ v. LinkedIn (9th Cir. 2022), but contract/ToS and database-right theories (Ryanair v. PR Aviation, C-30/14) remain live.[^29^][^30^][^31^][^32^][^33^] [HIGH for case holdings; MED for application]
8. **ETD copyright almost always stays with the student author**; universities take non-exclusive repository licenses, often with embargo options; CC licenses on ETDs are optional, so *full-text reuse* of theses is not uniformly permitted even when metadata is open.[^36^] [MED]

---

### Service Profiles

#### OpenAlex (OurResearch, non-profit)
- **Coverage:** ~316M works advertised (July 2026), incl. "journal articles and dissertations to datasets and preprints"; 60M fulltext PDFs; 200k journals & repositories; 2B+ citations. XPAC adds ~190–192M repository/DataCite records (total ~464–470M).[^1^][^2^][^5^]
- **Thesis coverage:** `type:dissertation` filter; institution filters via ROR; `primary_location.source.type:repository`; abstract-inverted index where lawful. XPAC is *the* ETD growth area (DataCite + repositories). Type classifier rebuilt July 2026 → type assignments volatile short-term.[^3^][^6^]
- **API:** REST, JSON, cursor paging; docs docs.openalex.org. Currently ~100k calls/day free, no key; **freemium transition in progress (2026): free tier ~$1/day credit with API key, paid tiers for throughput**; polite pool via `mailto`.[^1^][^5^]
- **Bulk:** full snapshot (CC0) free quarterly via AWS/HuggingFace; paid sync option ("optional paid sync to stay current").[^1^]
- **License/sustainability:** CC0 data, open code; $800k ARR + $3.5M Wellcome grant; 1.5B monthly API calls (OpenAlex+Unpaywall) — surpassing Crossref for the first time.[^3^]
- **Caveats:** 40% of core records lack abstracts; 64% lack references; documented type misclassifications; XPAC metadata quality "lower... improving over time."[^6^]

#### Semantic Scholar (Allen Institute for AI)
- **Coverage:** ~200M+ papers, 2.4B citation links; weekly dataset releases (verified live: release `2026-07-14`).[^7^]
- **Thesis coverage:** weak — S2ORC explicitly excludes dissertations; treat as citation/abstract enrichment source.[^9^]
- **API:** Academic Graph REST + Recommendations + **Datasets API** (`/datasets/v1/release/...`); unauthenticated shared limit (~100 req/5 min), free API key raises limits; dataset *metadata/release info* is open, bulk files gated by key.[^7^] [MED on exact limits]
- **Bulk/licensing:** datasets (papers, abstracts, citations, paper-ids, s2orc full text, tldrs, embeddings) under **ODC-BY 1.0** per per-dataset README ("This collection is licensed under ODC-BY"); original 2020 S2ORC was CC BY-NC — version hygiene required.[^8^][^9^]

#### Crossref (Crossref, non-profit membership org)
- **Coverage:** ~180M+ registered records; ~1B API requests/month. **1,062,500 works typed `dissertation`** (live `api.crossref.org/types/dissertation/works`, 2026-07-21).[^18^][^19^]
- **Thesis DOIs:** registered by universities/national libraries/ProQuest-type members; far from complete vs actual ETD output — most thesis DOIs are in DataCite instead.
- **API:** REST (`/works`, filters incl. `type:dissertation`, `from-pub-date` cursor); etiquette = descriptive UA with `mailto`; polite pool; ~50 req/s guidance; **Metadata Plus** = paid guaranteed-service tier; **Event Data** tracks DOI mentions (deprecated/quiet — verify before relying).[^19^]
- **License:** metadata CC0-ish (reference metadata open); some abstracts/references restricted by member choice.[^19^]

#### DataCite (DataCite, non-profit)
- **Coverage:** ~131.6M DOIs all states (live); 15.6M typed `Text`; **818,069 `resourceTypeGeneral:Dissertation`** (schema 4.4+ value), ~740k free-text `resourceType:Thesis`. Key thesis registrants: national libraries, university repositories, DSpace/DataCite consortia.[^17^]
- **APIs:** REST (`api.datacite.org/dois`, JSON:API), OAI-PMH (`oai.datacite.org/oai`), GraphQL (note: GraphQL API announced for retirement — verify current status, MED).[^16^]
- **Rate limits (official):** authenticated **3000 req/5 min**; identified (UA w/ email or `mailto=`) **1000/5 min**; unidentified **500/5 min**; 429 on breach; content-negotiation via doi.org 1000/5 min.[^16^]
- **License:** metadata CC0. Strong registry for *identifying* theses; full-text URLs must be resolved downstream (media/relation metadata inconsistent).

#### CORE (The Open University, non-profit)
- **Coverage:** ~452M searchable papers, ~57M full texts, ~15k data providers — largest OA full-text aggregation; document types include doctoral/master theses.[^13^][^15^]
- **API v3:** api.core.ac.uk/docs/v3. Unregistered: ~5 single or 1 batch request/10 s; registered: better performance, **free for individuals' personal work and public research orgs' unfunded research; commercial licences for companies**.[^13^][^14^]
- **Bulk:** CORE Dataset dumps **ODC-BY**; **FastSync** = ResourceSync-based incremental sync service for keeping a local always-current copy.[^15^]
- **TDM stance:** explicitly TDM-friendly ("used by over 7,000 experts to analyse data, develop text-mining applications").[^15^]

#### Unpaywall (OurResearch)
- **Coverage:** >135M articles tracked, ~35M OA; >5,000 repositories; 88k journals/14k publishers.[^11^]
- **API v2 (only supported):** `api.unpaywall.org/v2/{doi}?email=YOU`; **100,000 calls/day** guidance; same schema as snapshot/Data Feed.[^10^]
- **Bulk:** free snapshot ~2×/year; paid **Data Feed** (daily changefiles).[^11^]
- **Caveat:** keyed on Crossref DOIs — simple query tool "only searches DOIs registered with Crossref," missing DataCite/Airiti/mEDRA (many theses!).[^12^]
- **Thesis relevance:** license/oa_status flags per location; best used as OA-URL resolver *after* discovery elsewhere, not as thesis discovery source.

#### BASE (Bielefeld University Library)
- **Coverage:** ~400M+ documents from ~11,000+ content providers (incl. most ETD repositories) — one of the deepest thesis indexes.[^21^] [MED on current count]
- **API:** exists but historically **restricted — requires registration/IP whitelisting; ToS limit automated use of the search UI**; OAI-PMH harvesting of BASE itself not openly offered. Treat as *negotiated* source. Also runs OVAL, the BASE OAI-PMH validator (oval.base-search.net).[^21^] [MED]
- **License:** metadata reuse restricted absent agreement; non-commercial stance historically. [MED]

#### OpenAIRE Graph (OpenAIRE, EU infrastructure)
- **Coverage:** research graph of publications/data/software/theses from 70k+ sources (incl. national ETD aggregators); periodic Zenodo dumps.[^20^]
- **API:** graph.openaire.eu/docs/apis/graph-api/; **~60 req/hour anonymous, ~7,200 req/hour authenticated** (per documented limits).[^20^] [MED on exact numbers]
- **License:** metadata CC-BY; PDF/full-text access restricted (on-request research pipelines).
- **Thesis relevance:** strong European ETD coverage via national aggregators (e.g., NARCIS/DANS, HAL, etc.); `resulttype` includes theses.

#### Registries (ROAR, OpenDOAR, re3data, OAI registry)
- **OpenDOAR** (Jisc/SHERPA, v2.sherpa.ac.uk/opendoar): curated directory, filter by content type "theses"; historically exposed API (`api13.php`).[^25^][^27^]
- **ROAR** (roar.eprints.org): machine-readable list (rawlist.xml) of OAI-PMH endpoints.[^26^][^27^]
- **OAI official registry:** openarchives.org/Register/BrowseSites (data providers), /service/listproviders.html (service providers), /Register/ValidateSite (validation); third-party validator validator.oaipmh.com.[^22^][^23^][^24^]
- **re3data:** research-data-repository registry w/ free API; more data-than-thesis oriented.[^35^]
- arXiv 1708.08669 documents scraping 6 meta-catalogs (OpenDOAR, ROAR, OpenArchives, Illinois, OAIster, OpenAIRE) to enumerate OAI-PMH endpoints — a ready-made enumeration recipe.[^27^]

---

### Protocol Notes

**OAI-PMH 2.0 mechanics** (spec: openarchives.org/OAI/openarchivesprotocol.html)[^22^]
- Six verbs over HTTP GET/POST, XML: `Identify`, `ListMetadataFormats`, `ListSets`, `ListIdentifiers`, `ListRecords`, `GetRecord`. `oai_dc` (simple Dublin Core) mandatory; repositories commonly also expose `xoai`/`dim` (DSpace), `mods`, `etdms` (theses!), `marc21`.
- **Incremental harvesting:** `from`/`until` datestamp params on ListIdentifiers/ListRecords; granularity (day vs second) declared in `Identify`.
- **resumptionToken:** stateless paging for incomplete lists; must be honored as opaque; empty token element signals end. Flow control possible via `expirationDate`.
- **Sets:** selective harvesting (e.g., a "theses" collection); membership via `setSpec`.
- **Deleted records:** `deleted="no|transient|persistent"` declared in Identify; deleted headers (no metadata) must be respected to keep local copies in sync — critical for embargo removals/takedowns.
- **Etiquette:** identify via User-Agent w/ contact; serial requests, back off on 503/`Retry-After`; harvest off-peak; prefer ListIdentifiers→selective GetRecord for large diffs. Tools: R `oai`, Python `sickle`/pyoai, OCLC OAIHarvester2.[^28^]
- **ResourceSync (ANSI/NISO Z39.99-2017)**: sitemap-based bulk/change-list sync; basis of CORE FastSync; better than OAI-PMH for file-level sync.[^15^]

**Persistent identifiers for theses**[^37^]
- **DOI** (Crossref/DataCite): growing for ETDs (DataCite Dissertation type); best metadata payload; resolvable via doi.org content negotiation (Citeproc JSON, BibTeX).
- **Handle** (DSpace default): ubiquitous in older ETD repos (hdl.handle.net); metadata must be scraped/OAI-harvested.
- **URN:NBN**: national-library theses (DE/NL/FI/NO/SE persistence services).
- **ARK**: some library platforms (arks.org); **PURLs** legacy.
- **ORCID** for authors (public API free; thesis linkage sparse), **ROR** for institutions (CC0 dump + API) — both integrate into OpenAlex/Crossref/DataCite records; use ROR to scope institutional ETD harvesting.[^37^]

---

### Legal/TDM Landscape Summary

- **EU:** Directive (EU) 2019/790 Art. 3 = mandatory TDM exception for research organisations & cultural-heritage institutions (lawful access required; copies retained with security; **rightholders cannot opt out**). Art. 4 = TDM by anyone, **unless rights "expressly reserved"** (machine-readable reservation for online content — robots.txt/HTTP headers/readable ToS). Practical rule: metadata harvesting fine; full-text mining of ETDs OK for research orgs (Art. 3), else check Art. 4 reservations.[^29^]
- **US:** *Authors Guild v. HathiTrust*, 755 F.3d 87 (2d Cir. 2014) — "the creation of a full-text searchable database is a quintessentially transformative use"; *Authors Guild v. Google*, 804 F.3d 202 (2d Cir. 2015), cert. denied 136 S. Ct. 1658 (2016) — whole-book copying for search/snippets = fair use; courts "impressive" security measures mattered; non-expressive computational reuse doctrine extends to TDM/AI pipelines (contested for generative-AI outputs).[^30^][^31^][^32^]
- **Access-law layer:** *Van Buren v. US* (2021) narrowed CFAA "exceeds authorized access"; *hiQ v. LinkedIn* (9th Cir. 2019/2022) — scraping *public* pages likely not CFAA "without authorization" — but breach of contract, trespass-to-chattels, copyright, and (EU) sui-generis database right survive (*Ryanair v. PR Aviation*, C-30/14). robots.txt = RFC 9309 (2022) informational standard; legally a unilateral signal, not a technical barrier — its weight is as evidence of reservation/notice (Art. 4) or contract breach.[^33^][^34^]
- **ETD-specific:** student authors hold copyright; repositories hold non-exclusive licenses; embargoes common (respect deleted records); CC-licensed ETDs reusable per terms; non-CC full text → rely on Art. 3/fair use for *internal* mining, but **do not redistribute full text**; metadata (titles/abstracts) is largely safe (facts/thin copyright; OpenAlex even redacts some abstracts for copyright).[^6^][^36^]

---

### Trends & Signals

- **OpenAlex ascendant:** 1.5B monthly API calls (OpenAlex 1B + Unpaywall 0.5B), "exceeding Crossref for the first time"; explicit positioning for agents/automation ("Our API is built for agents and automation"); freemium monetization arriving 2026 — budget for API keys.[^1^][^3^]
- **Repository-first ingestion is now mainstream:** Walden/XPAC means OpenAlex itself harvests repositories — a validation of the Calyx thesis that repository OAI-PMH is the canonical ETD source; also means OpenAlex XPAC can substitute for first-pass harvesting.[^2^][^3^]
- **Dataset dumps > APIs for scale:** every major provider steers bulk users to snapshots (OpenAlex, S2, Unpaywall, CORE, Crossref public data file) — design Calyx as dump-first, API-for-deltas.[^1^][^10^][^15^]
- **Rate-limit convergence on identity:** mailto/User-Agent identification (Crossref, DataCite tiers) or API keys (S2, CORE, OpenAlex-soon) — anonymous scraping is the slowest lane everywhere.[^16^][^19^]
- **Consolidation risk:** OpenDOAR moved under Jisc/SHERPA; ROAR aging; OAI registry UI dated but functional; DataCite GraphQL retirement signals API-surface pruning.[^25^][^26^] [MED]

---

### Controversies & Conflicting Claims

- **OpenAlex quality vs scale:** researchers document type misclassifications (>300k vs WoS), missing abstracts (40%) and references (64%), duplicate authors; OpenAlex counters with classifier rebuilds and XPAC quality roadmap. Treat type=dissertation as high-recall, verify precision.[^6^]
- **S2ORC licensing history:** original S2ORC CC BY-NC vs current ODC-BY — old mirrors (Kaggle/HF) may carry the NC license; use current Datasets API files.[^9^]
- **"Free" APIs drifting freemium:** OpenAlex community concern about key requirements/reduced free limits; CORE charging commercial users while marketing "free for >99.99% of users."[^5^][^15^]
- **BASE openness:** marketed as open search but API effectively gated (IP registration/agreements) — conflicts with "open" positioning; do not plan BASE into automated pipelines without a signed agreement.[^21^] [MED]
- **Thesis counts don't reconcile:** Crossref 1.06M dissertation-type vs DataCite ~0.8–1.5M thesis-like vs OpenAlex (unverified, likely several M incl. non-DOI ETDs via repositories) — definitional drift ("thesis" vs "dissertation" vs "ETD") plus registry overlap; any global ETD census must dedupe on multiple IDs.[^17^][^18^]

---

### Recommended Deep-Dive Areas

1. **OpenAlex XPAC thesis slice:** quantify `type:dissertation` within XPAC vs core; evaluate precision of the July 2026 classifier on ETDs; snapshot-based extraction cost.
2. **DataCite ETD schema conformance:** which repositories populate `resourceTypeGeneral:Dissertation` vs free-text "Thesis" vs nothing — build a normalization table by client/repository.
3. **CORE FastSync pilot:** full-text thesis availability rate by documentType; ODC-BY redistribution boundaries for derived data products.
4. **OAI-PMH endpoint enumeration:** refresh the 6-catalog endpoint census (OpenDOAR API, ROAR rawlist, OAI registry, OpenAIRE PROVIDE) → dedupe → probe `Identify` for deleted-record policy and `etdms` support.
5. **Art. 4 opt-out detection:** operational spec for parsing robots.txt/`tdm-reservation` HTTP header/ai.txt as DSM Art. 4 machine-readable reservations across target repositories.
6. **Embargo/takedown sync:** deleted-record handling + re-harvest cadence to honor ETD embargoes at scale.
7. **Identifier crosswalk service:** DOI↔Handle↔URN:NBN↔repository-ID mapping for ETD dedupe (DataCite + Crossref + OpenAlex + repository OAI IDs).

---

### References

[^1^]: https://openalex.org/ — homepage (316M works, CC0, 60M fulltext PDFs, "built for agents", paid sync)
[^2^]: https://docs.openalex.org/how-to-use-the-api/xpac — XPAC: >190M works from DataCite + repositories, excluded by default, `include_xpac=true`
[^3^]: https://blog.openalex.org/openalex-2025-in-review/ — Walden launch, 1.5B monthly API calls, $800k ARR, $3.5M Wellcome grant
[^4^]: https://developers.openalex.org/guides/key-concepts — XPAC details, `is_xpac` field/filter
[^5^]: https://library.smu.edu.sg/topics-insights/exploring-research-impact-beyond-traditional-metrics-iv-openalex-open-research-intelligence — 464M works w/ XPAC; ~100k calls/day free; key requirement anticipated
[^6^]: https://arxiv.org/html/2512.16434v1 — "OpenAlex: Features, Advantages and Limitations" (271.3M works Nov 2025; xpac 192M; abstracts/references gaps; misclassification studies)
[^7^]: https://api.semanticscholar.org/datasets/v1/release/ — live dataset release listing (checked 2026-07-21; latest 2026-07-14)
[^8^]: https://api.semanticscholar.org/datasets/v1/release/2023-08-15 — per-dataset READMEs incl. ODC-BY license text
[^9^]: https://github.com/allenai/s2orc — S2ORC: excludes dissertations; license history CC BY-NC → ODC-BY
[^10^]: https://unpaywall.org/products/api — REST API v2: email param, 100k calls/day, snapshot alternative
[^11^]: https://www.igroupjapan.com/wp-content/uploads/2022/04/Unpaywall-Data-Feed.pdf — 135M articles/35M OA; snapshot 2×/yr free; Data Feed daily changefiles paid
[^12^]: https://loc.gov/flicc/education/PDFs/2022SpringExpoMaterials.pdf — Unpaywall simple-query tool searches Crossref DOIs only
[^13^]: https://core.ac.uk/services/api — CORE API tiers (unregistered ~5 req/10 s; registered; free for personal/research use)
[^14^]: https://api.core.ac.uk/docs/v3 — CORE API v3 documentation
[^15^]: https://www.researchgate.net/publication/371375678 — "CORE: A Global Aggregation Service for Open Access Papers" (FastSync/ResourceSync; ODC-BY dumps; 7,000+ TDM users)
[^16^]: https://support.datacite.org/docs/rest-api-rate-limits + https://support.datacite.org/docs/rate-limit — DataCite tiers 500/1000/3000 req per 5 min; 429; backoff guidance
[^17^]: https://api.datacite.org/dois — live queries: total 131.6M; Text 15.6M; Dissertation 818,069; Thesis 740,202 (2026-07-21)
[^18^]: https://api.crossref.org/types/dissertation/works — live: 1,062,500 dissertation works (2026-07-21)
[^19^]: https://github.com/CrossRef/rest-api-doc — Crossref REST etiquette (mailto UA, backoff, caching), filters
[^20^]: https://graph.openaire.eu/docs/apis/graph-api/ — OpenAIRE Graph API docs (rate tiers ~60/h anon, 7,200/h auth)
[^21^]: https://www.base-search.net/ + https://oval.base-search.net/ — BASE search & OVAL OAI-PMH validator (API access restricted/registration)
[^22^]: https://www.openarchives.org/OAI/openarchivesprotocol.html + https://www.openarchives.org/Register/BrowseSites — OAI-PMH 2.0 spec; registered data providers
[^23^]: https://www.openarchives.org/Register/ValidateSite — OAI-PMH data provider validation/registration
[^24^]: https://validator.oaipmh.com/ — OAI-PMH validator & data extractor
[^25^]: https://v2.sherpa.ac.uk/opendoar/ — OpenDOAR directory (content-type filters incl. theses)
[^26^]: http://roar.eprints.org/ — ROAR registry of open access repositories
[^27^]: https://arxiv.org/pdf/1708.08669.pdf — "Global picture of OAI-PMH repositories... 6 key open archive meta-catalogs" (endpoint-enumeration URLs)
[^28^]: https://docs.ropensci.org/oai/reference/update_providers.html — R `oai` package; provider table from OAI registry
[^29^]: https://eur-lex.europa.eu/eli/dir/2019/790/oj/eng — DSM Directive 2019/790 (Art. 3/4 TDM)
[^30^]: https://www.copyright.gov/fair-use/summaries/authorsguild-google-2dcir2015.pdf — USCO fair-use summary, Authors Guild v. Google
[^31^]: https://www.law.berkeley.edu/wp-content/uploads/2016/05/Authors-Guild-v-Google-804_F.3d_202.pdf — full 2d Cir. opinion (quotes incl. "quintessentially transformative use")
[^32^]: https://www.gtlaw.com/-/media/files/events/2023/06/ballon01/copyright-fair-use.pdf — treatise excerpt: HathiTrust 755 F.3d 87 holding; cert. denied 136 S. Ct. 1658 (2016)
[^33^]: https://www.eff.org/cases/hiq-v-linkedin — hiQ v. LinkedIn case page (CFAA/public-data scraping)
[^34^]: https://www.rfc-editor.org/rfc/rfc9309 — Robots Exclusion Protocol RFC
[^35^]: https://www.re3data.org/ — registry of research data repositories (API)
[^36^]: https://www.ndltd.org/ — NDLTD (ETD community; copyright/embargo practice context) [general]
[^37^]: https://www.doi.org/ , https://www.handle.net/ , https://arks.org/ , https://ror.org/ , https://orcid.org/ — PID infrastructure roots
