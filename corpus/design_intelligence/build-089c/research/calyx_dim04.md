# Calyx Dimension-04 Research Report

## Facet: Metadata aggregation spine — dissertation-slice precision & dedupe architecture

Date: 2026-07-21. Extends/verifies wide03. All API counts below are LIVE queries executed today (method noted per count). Confidence: [HIGH]=official docs or live query today; [MED]=credible secondary; [LOW]=unverified.

---

## 1. OpenAlex — dissertation slice (live counts, 2026-07-21)

| Query | Count | Live URL |
|---|---|---|
| `type:dissertation` (core corpus, XPAC excluded) | **11,023,419** | https://api.openalex.org/works?filter=type:dissertation&per-page=1 [^1^] |
| `type:dissertation` with `include_xpac=true` (all corpora) | **20,257,594** | https://api.openalex.org/works?filter=type:dissertation&include_xpac=true&per-page=1 [^2^] |
| `type:dissertation,is_xpac:true` (XPAC-only) | **9,234,175** | https://api.openalex.org/works?filter=type:dissertation,is_xpac:true&include_xpac=true [^3^] |
| `type:dissertation,concepts.id:C2781370656` (Orchidaceae) | **497** | https://api.openalex.org/works?filter=type:dissertation,concepts.id:C2781370656 [^4^] |
| same + `include_xpac=true` | **667** (+170 XPAC) | https://api.openalex.org/works?filter=type:dissertation,concepts.id:C2781370656&include_xpac=true [^5^] |
| `type:dissertation` + full-text `search=orchid` | **5,767** | https://api.openalex.org/works?filter=type:dissertation&search=orchid [^6^] |

- Orchidaceae concept id = **C2781370656** (level 2, 18,728 works total). [HIGH] [^7^]
- **Typing precision sample (n=10, `type:dissertation`&search=orchid, core corpus): 10/10 genuine theses** (Kyoto U 1964, U Oregon 2014, U Hawaii 1960, UWA ×3, Murdoch ×2, U Alberta 1994, Iowa State 1975). Raw types observed: "Thesis", "Electronic Thesis or Dissertation", "info:eu-repo/semantics/doctoralThesis", "info:eu-repo/semantics/masterThesis", "Dissertation". Note: OpenAlex `type:dissertation` is a *rollup* — masters theses are included. [HIGH] [^6^]
- **Provenance insight (dedupe-relevant):** records carry `indexed_in: ["datacite"|"crossref"]`, `ids.mag`, `primary_location.id` like `pmh:oai:depositonce.tu-berlin.de:11303/1931` (OAI identifier!), `locations[].landing_page_url` with Handles, and `landing_page_url` with URN:NBN (e.g. `https://nbn-resolving.org/urn:nbn:de:kobv:83-opus-16117`). A single thesis record aggregated 8 locations spanning repository OAI, CiteSeerX, BVB union catalog, DOI, MAG. This is a free pre-built crosswalk. [HIGH] [^1^]
- XPAC nearly doubles the dissertation pool (+9.23M, 84% more). XPAC dissertations skew DataCite/repository-sourced; quality lower but typed. [HIGH]

### 2026 freemium / keyed-credit change (verified live + docs)
- **API keys are now REQUIRED for all requests** (announced Jan 2026, in force Feb 2026). Free key from openalex.org/settings/api. [HIGH] [^8^]
- **Credit model:** anonymous = $0.10/day; free key = $1/day; prepaid beyond. Singleton lookups (work by DOI/ID) are FREE/unlimited; list+filter $0.10/1k calls; search $1/1k; PDF/TEI content $0.01/file. Rate: 100 req/s cap; 429 on breach. Verified live: anonymous requests from this IP returned HTTP 429 `Insufficient budget ... Resets at midnight UTC` with `dailyRemainingUsd: 0` — the credit system is live and enforced. [HIGH] [^8^][^9^]
- Cost exposed per response in `meta.cost_usd` + `X-RateLimit-*` headers; `/rate-limit` endpoint. [HIGH] [^9^]
- **Snapshot mechanics:** public S3 bucket `s3://openalex` (us-east-1, anonymous `--no-sign-request`, AWS Open Data covers transfer). 2026 layout: `data/jsonl/{entity}/updated_date=YYYY-MM-DD/part_*.gz` (≤400k records/part) and, since June 2026, `data/parquet/...`; per-entity + combined `manifest.json` (written last = completeness signal); pre-2026 flat layout + `merged_ids/` preserved under `legacy-data/`. JSONL ~330 GB compressed (~1.6 TB decompressed). Free snapshot refresh: **quarterly** (older help-center copy said monthly; current developer docs say quarterly — conflict flagged). Paid plans: daily snapshot in `s3://openalex-snapshots/full/<date>/` (key-derived credentials) + daily changefiles API (last 60 days; JSONL+Parquet; upsert by entity `id`). `merged_ids` directory supports deleted/merged work-ID redirects. [HIGH] [^10^][^11^][^12^]

---

## 2. DataCite (live + docs)

- **Dissertation count (live):** `query=types.resourceTypeGeneral:Dissertation` → **818,074** (wide03: 818,069; +5 in same day — active registration). https://api.datacite.org/dois?query=types.resourceTypeGeneral:Dissertation [^13^]
- **Free-text `types.resourceType:Thesis`** → **740,202** (overlap with above; combined thesis-like ~1.0–1.3M). [^13^]
- Subject-scoped probes (live): Dissertation AND `subjects.subject:"botany"` = **416**; Dissertation AND `botany` (full metadata) = **727**; Dissertation AND `orchid*` = **127**. Conclusion: DataCite subject metadata is sparse for theses — botany-relevant recall via DataCite alone is poor vs OpenAlex full-text search (5,767). Use DataCite for identifiers, not topical recall. [HIGH] [^13^]
- **Rate tiers (official, carried from wide03, re-confirmed page exists):** authenticated 3000 req/5min; identified UA 1000/5min; anonymous 500/5min; 429 on breach. [HIGH] [^14^]
- **OAI-PMH:** base `https://oai.datacite.org/oai`; sets = member / data-center symbols; **custom query setspecs**: base64url-encode an API query after `~` (e.g. `TIB~dHlwZXMucmVzb3VyY2VUeXBlR2VuZXJhbCUzQURhdGFzZXQ=`). So Calyx can OAI-harvest exactly `types.resourceTypeGeneral:Dissertation` per member with datestamp incrementals and persistent deleted-record policy. [HIGH] [^15^]
- **GraphQL: RETIREMENT CONFIRMED — deprecated 1 July 2027** (wide03 flagged "possible"; official deprecation notice, updated ~June 2026). DataCite Commons already migrated to REST. Also: REST v1 legacy endpoints (`/works`, `/members`, `/data-centers`) deprecated July 2026 → use v2 (`/dois`, `/providers`, `/clients`). [HIGH] [^16^][^17^]
- License CC0. Cross-reference fields useful for dedupe: `relatedIdentifiers` (IsVersionOf, IsIdenticalTo, IsSupplementTo), `alternateIdentifiers`, `identifiers`, `url`, `contentUrl`, `rightsList`. [HIGH] [^13^]

---

## 3. Crossref (live + docs)

- **Dissertation count (live, polite pool):** `GET /types/dissertation/works?rows=0` → **1,062,500** (unchanged vs wide03's 2026-07-21 count; same day). [HIGH] [^18^]
- **Top thesis registrants (live facet `publisher-name:*` on filter=type:dissertation):** ABES (Agence Bibliographique de l'Enseignement Supérieur, FR theses.fr) **192,563**; USP Agência de Bibliotecas (BR) **125,090**; Chulalongkorn (TH) **77,609**; UNICAMP **67,237**; National Documentation Centre/EKT (GR) **57,946**; Iowa State **29,267**; Faculdades Católicas **27,814**; HKU Libraries **27,722**; USP AGUIA **25,600**; U Queensland **24,990**; LSU **20,602**; Carleton **16,901**; Drexel **15,750**; HKUST **15,374**; WVU **11,282**; Göttingen **11,184**... Pattern: national thesis agencies (ABES/STAR, EKT) + Brazilian university consortia dominate; Anglo university libraries long-tail. [HIGH] [^18^]
- **Filter/update mechanics:** `/works?filter=type:dissertation,from-pub-date:...,until-pub-date:...`; cursor paging for deep harvest; facets incl. `update-type` (retraction, correction, new_edition, withdrawal, etc.); `update-to`/`relation` fields express version links (`is-version-of`, `has-preprint`) and Crossmark updates; `filter=from-update-date`/`from-index-date` for deltas; mailto → polite pool. [HIGH] [^19^][^20^]
- Crossref thesis DOIs and DataCite thesis DOIs are **disjoint namespaces keyed by RA prefix**: the same DOI string is globally unique, so DOI is a safe global merge key across both.

---

## 4. CORE

- **API v3** (api.core.ac.uk/docs/v3): endpoints `/search/works` (deduplicated+enriched) and `/search/outputs` (raw, per-provider, **not deduplicated**); entity CRUD endpoints (`/works/{id}`, `/outputs/{id}`); `documentType` values include `thesis`, `doctoral thesis`, `master thesis`, `bachelor thesis` (ML-classified from full text or dc.type). `identifiers` object carries `doi` + `oai` — built-in DOI↔OAI crosswalk per record. [HIGH] [^21^]
- **Tiers:** unregistered ~5 single / 1 batch per 10s; registered (free API key) higher; free for personal work + public research orgs' unfunded research; commercial licences for companies. [HIGH] [^22^]
- **Dataset:** latest dump 2024-07-12 (749 GB compressed / ~2.7 TB), registration-gated (credentials by email); ResourceSync **Resource Dump** structure: per-provider archives, `manifest.xml` with md5 + path per resource; per-line JSON (`[repositoryID].json.xz` legacy). Dumps licensed **ODC-BY** — attribution required, commercial reuse allowed. [HIGH] [^23^][^24^]
- **FastSync:** ResourceSync (ANSI/NISO Z39.99)-based incremental sync keeping an always-current local copy; "fast, incremental, enterprise" — enterprise-tier. [HIGH] [^24^]
- **ODC-BY scope for Calyx:** a local synced copy can be used for TDM freely (TDM is explicitly CORE's flagship use case; >7,000 TDM users). Redistribution of the database or substantial extracts requires ODC-BY attribution (produced-by notice); derived works OK commercially; note ODC-BY covers the *database right*, not the underlying full-text copyrights — redistributing thesis full texts still bounded by per-document licenses/embargoes. [MED — license text standard; document-level constraint is inference] [^24^]
- **Thesis coverage:** ~57M full texts / ~452M metadata records; documentType thesis present at scale (wide03). Exact live thesis count not obtainable without API key this session. [MED]

---

## 5. Unpaywall

- **Keys on Crossref DOIs only — verified live today:** DataCite thesis DOI `10.7939/r3c24qv9q` (U Alberta thesis) → **HTTP 404**; Crossref thesis DOI `10.31274/rtd-180813-580` → 200 with `genre:"dissertation"`, OA status gold. DataCite-registered theses are systematically invisible to Unpaywall. [HIGH] [^25^]
- API v2 only; `?email=` required; **100k calls/day** guidance. [HIGH] [^26^]
- **Snapshots: DISCONTINUED.** Unpaywall no longer produces semi-annual snapshots — directs bulk users to the OpenAlex snapshot (updated quarterly free / daily paid). Paid **Data Feed** (daily/weekly changefiles, daily snapshot) persists; changefiles apply-by-DOI overwrite semantics. [HIGH] [^27^]
- Role for Calyx: OA-status/license resolver for Crossref-DOI theses only; for DataCite/OAI theses use OpenAlex `best_oa_location` + repository records instead.

---

## 6. OpenAIRE Graph

- **Auth tiers (confirmed):** 60 req/h anonymous vs **7,200 req/h authenticated** (GÉANT/OpenAIRE Graph API slides) + concurrency caps (30/IP; 15 r/s). [HIGH] [^28^][^29^]
- **Dump:** Zenodo community "OpenAIRE Research Graph Dump", ~6-month cadence, tar/gz JSONL per entity (publication, dataset, software, otherresearchproduct, organization, datasource, project, relation), schema versioned; **CC-BY 4.0** — attribution obligation: cite the dump (Zenodo DOI) + acknowledge OpenAIRE; redistribute-derived allowed. Latest citation-graph derivatives on Zenodo confirm 2025-12-01 dump generation. [HIGH] [^30^][^31^]
- **ETD coverage:** aggregates 70k+ sources incl. national European thesis aggregators and institutional repositories; `resulttype` includes thesis; dedup uses DOI + fuzzy title matching internally. PDF access restricted/on-request; metadata CC-BY. [HIGH] [^29^][^32^]

---

## 7. Dedupe / crosswalk specification (design, grounded in observed mechanics)

### Identifier precedence (merge key ranking)
1. **DOI (case-normalized, doi.org form).** Globally unique across Crossref+DataCite; both OpenAlex and CORE expose it; Unpaywall/OpenAlex enrich keyed by it. Crossref/DataCite namespace disjoint by RA. [Grounding: OpenAlex `ids.doi`; DataCite `id`; Crossref `DOI`; CORE `identifiers.doi`] [^1^][^13^][^18^][^21^]
2. **Handle (hdl.handle.net).** DSpace default; appears as `landing_page_url` in OpenAlex locations and DataCite `url`. Extract via regex `hdl.handle.net/(\S+)` from any URL field. [^1^]
3. **URN:NBN.** National-library theses (DE/NL/FI/SE/NO); appears in OpenAlex `landing_page_url` (nbn-resolving.org) and repository `dc.identifier`. [^1^]
4. **OAI identifier.** Format `oai:{repo-domain}:{local-id}` — present verbatim in OpenAlex `primary_location.id` as `pmh:oai:...`, CORE `oai` field, and native OAI-PMH headers. Composite key = (repository base URL, local id). [^1^][^21^]
5. **Repository URL canonicalization** (DSpace `/handle/`, EPrints `/id/eprint/`, Digital Commons `cgi/viewcontent`) → same Handle/local-id space as #2/#4.
6. **Fuzzy fallback: normalized title + first-author surname + year.** Title normalization: lowercase, strip diacritics/punctuation, collapse whitespace; block on (author-surname, year); score with token-set ratio ≥0.92 (theses are long-titled → high separability). CORE/OpenAIRE both demonstrate this works at scale (CORE's own LSH+embeddings dedup paper; OpenAIRE DOI-then-title dedup). [^24^][^32^]

### Cross-source link exploitation (free pre-joins)
- **DataCite `relatedIdentifiers`** (IsVersionOf/IsIdenticalTo/IsSupplementTo) + `alternateIdentifiers` (often the OAI id or Handle — e.g. TUWien record carries `alternateIdentifier alternateIdentifierType="oai"`). [^13^][^15^]
- **OpenAlex `locations[]` + `indexed_in` + `ids.mag`:** one OpenAlex work already merges repository OAI id, DOI, union-catalog ids, URN:NBN — treat OpenAlex work-id clusters as candidate merge groups, validated by our own keys (OpenAlex mis-merges occur; keep XPAC records quarantined until key-matched). [^1^][^6^]
- **CORE `identifiers {doi, oai}` + `pdfHashValue`** (dedupe/changes at file level). [^21^][^23^]
- **Crossref `relation`/`update-to`** for version chains (thesis → published book/articles). [^20^]
- **OpenAlex `merged_ids`** snapshot directory: honors OpenAlex-side merges — apply as redirects, never as hard deletes. [^10^]

### Merge rules
- **Master record = repository-native record** (richest provenance, license, embargo state) enriched by registry records. Field-level precedence: license/embargo ← repository OAI; citation counts/topics ← OpenAlex; subject schemes ← DataCite + national aggregator; relation graph ← Crossref+OpenAIRE.
- **Never auto-merge on fuzzy match alone below threshold;** route 0.85–0.92 band to conflict queue.
- **Embargo/takedown wins:** OAI `deleted` status (persistent/transient) and DataCite state changes override all other copies — honor within one sync cycle. [^15^][^33^]
- **Provenance retention:** every merged record keeps an `id_set` (all source ids) + `source_records` pointers; merged record id = DOI if present else `calyx:{uuid}`.
- **Conflict logging schema:** `{ts, key_type, key_value, sources[], field, values[], rule_applied, resolution, confidence}`; conflicts bucketed as (a) identifier collision (same DOI, different title — log, keep separate, alert), (b) year drift ±1 (accept, prefer repository), (c) author-name variant (ORCID reconcile), (d) type disagreement (thesis vs article — repository/OAI etdms wins).

### Pipeline order (cost-optimal)
1. OpenAlex snapshot (CC0, quarterly) → seed universe; filter `type:dissertation` incl. XPAC (~20.3M), then intersect Orchidaceae concept/keywords (~667+) and full-text search slice.
2. OAI-PMH direct harvest of priority repositories (etdms/jpcoar formats) for ground truth + embargo status.
3. DataCite REST/OAI delta harvest (Dissertation type; query-set harvesting) for DOI+relatedIdentifier crosswalk.
4. Crossref `type:dissertation` cursor harvest for the 1.06M Crossref-registered theses.
5. CORE Works/Outputs for full-text links + documentType validation.
6. Unpaywall only for Crossref-DOI OA resolution.
7. OpenAIRE dump for European national-aggregator gap-fill + relation graph (CC-BY attribution tracked).

---

## 8. Conflicts vs wide03 (resolved)

| wide03 claim | Status now |
|---|---|
| DataCite GraphQL "possible retirement — verify" | **CONFIRMED retiring 1 July 2027**; REST v1 legacy endpoints retired July 2026 [^16^][^17^] |
| OpenAlex "freemium transition in progress; ~$1/day w/ key" | **In force:** keys required; $1/day key, $0.10/day anon; credits enforced with live 429s; per-endpoint pricing [^8^][^9^] |
| OpenAlex snapshot "quarterly" vs help-center "monthly" | Developer docs: **quarterly free, daily paid**; help-center pricing page still says monthly — use developer docs [^10^][^34^] |
| Unpaywall "snapshot ~2×/year free" | **OUTDATED:** snapshots discontinued → use OpenAlex snapshot; Data Feed paid continues [^27^] |
| OpenAlex dissertation count "unverified, likely several M" | **Verified: 11.02M core / 20.26M with XPAC (9.23M XPAC-only)** [^1^][^2^][^3^] |
| Unpaywall "Crossref DOIs only" | **Verified live:** 404 on DataCite thesis DOI [^25^] |
| OpenAIRE "~60/h anon, 7,200/h auth [MED]" | Confirmed [HIGH] [^28^] |

## 9. Unknowns / blockers

- CORE live thesis-type counts (needs API key; unregistered tier too slow to census).
- OpenAlex XPAC dissertation *precision* (sampled core only; XPAC sample not yet judged — recommend n=100 stratified check).
- Whether OpenAlex Orchidaceae concept coverage is complete vs keyword union (concept 667 vs full-text 5,767 orchid theses — the union set is the realistic acquisition target).
- DataCite `resourceType` free-text normalization table by client (wide03 deep-dive #2) still unbuilt.
- OpenAlex snapshot parquet availability for XPAC entities (docs promise June 2026 rollout — verify in next quarterly release).

---

## References

[^1^]: https://api.openalex.org/works?filter=type:dissertation&per-page=1 (live 2026-07-21; count 11,023,419; sample record w/ locations, indexed_in, pmh:oai ids, URN:NBN)
[^2^]: https://api.openalex.org/works?filter=type:dissertation&include_xpac=true&per-page=1 (live; 20,257,594)
[^3^]: https://api.openalex.org/works?filter=type:dissertation,is_xpac:true&include_xpac=true&per-page=1 (live; 9,234,175)
[^4^]: https://api.openalex.org/works?filter=type:dissertation,concepts.id:C2781370656&per-page=1 (live; 497)
[^5^]: https://api.openalex.org/works?filter=type:dissertation,concepts.id:C2781370656&include_xpac=true&per-page=1 (live; 667)
[^6^]: https://api.openalex.org/works?filter=type:dissertation&search=orchid&per-page=10 (live; 5,767; 10/10 precision sample)
[^7^]: https://api.openalex.org/concepts?search=Orchidaceae (live; C2781370656, 18,728 works)
[^8^]: https://blog.openalex.org/category/openalex/ (Feb 2026: API keys required; usage-based pricing; $1/day free)
[^9^]: https://developers.openalex.org/api-reference/authentication (endpoint costs, credit headers, /rate-limit; live 429 observed 2026-07-21)
[^10^]: https://developers.openalex.org/download/snapshot-format (S3 layout, manifests, partitions, legacy-data/merged_ids)
[^11^]: https://developers.openalex.org/download/download-to-machine (aws s3 sync --no-sign-request; >660 GB; enterprise daily bucket)
[^12^]: https://developers.openalex.org/download/changefiles (daily changefiles, paid plans; upsert semantics)
[^13^]: https://api.datacite.org/dois (live queries 2026-07-21: Dissertation 818,074; Thesis 740,202; botany 416/727; orchid* 127)
[^14^]: https://support.datacite.org/docs/rest-api-rate-limits (tiers 500/1000/3000 per 5 min)
[^15^]: https://support.datacite.org/docs/datacite-oai-pmh (oai.datacite.org/oai; member/data-center sets; base64url query-setspecs; formats)
[^16^]: https://support.datacite.org/docs/datacite-graphql-api-deprecation (GraphQL deprecated 1 July 2027)
[^17^]: https://support.datacite.org/docs/datacite-rest-api-legacy-endpoints-deprecation (v1 endpoints retired July 2026)
[^18^]: https://api.crossref.org/types/dissertation/works (live 2026-07-21: 1,062,500; publisher-name facet top-200)
[^19^]: https://github.com/CrossRef/rest-api-doc (filters, cursor, etiquette)
[^20^]: https://www.crossref.org/blog/retraction-watch-retractions-now-in-the-crossref-api/ (update-type filter/facet; update-to semantics)
[^21^]: https://api.core.ac.uk/docs/v3 (Outputs vs Works; documentType values; identifiers{doi,oai})
[^22^]: https://core.ac.uk/services/api (tiers; free personal/research use)
[^23^]: https://core.ac.uk/documentation/dataset (2024-07-12 dump 749 GB; ResourceSync Resource Dump; manifest.xml; register access)
[^24^]: https://www.nature.com/articles/s41597-023-02208-w (CORE paper: FastSync; ODC-BY dumps; 7,000+ TDM users)
[^25^]: https://api.unpaywall.org/v2/10.7939/r3c24qv9q (live 404) vs https://api.unpaywall.org/v2/10.31274/rtd-180813-580 (live 200, genre dissertation)
[^26^]: https://unpaywall.org/products/api (v2 only; 100k/day; email param)
[^27^]: https://unpaywall.org/products/snapshot + https://unpaywall.org/products/data-feed (snapshots discontinued → OpenAlex; Data Feed changefiles)
[^28^]: https://events.geant.org/event/1938/attachments/1235/1875/OpenAIRE%20Graph%20API%20-%20GeantInfoshare.pdf (60/h anon, 7200/h auth; Scholix links)
[^29^]: https://www.openaire.eu/infrastructure-acceptable-use-policy (concurrency caps; CC-BY metadata; PDF on-request)
[^30^]: https://zenodo.org/records/7488618 (OpenAIRE Graph Dump structure, 6-month cadence)
[^31^]: https://malta.imsi.athenarc.gr/docs/5.0.0/downloads/full-graph/ (CC-BY 4.0; citation requirement)
[^32^]: https://arxiv.org/html/2602.12206v3 (OpenAIRE dedup caveat; 2025-12-01 dump derivative)
[^33^]: https://www.openarchives.org/OAI/openarchivesprotocol.html (deleted-record policy; datestamp granularity)
[^34^]: https://help.openalex.org/hc/en-us/articles/24397762024087-Pricing (older "monthly snapshot" copy — superseded)
[^35^]: https://registry.opendata.aws/openalex/ (s3://openalex, us-east-1, CC0, no-sign-request)
