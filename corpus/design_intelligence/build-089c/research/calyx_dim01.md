# Calyx Deep-Dive dim01 — Americas ETD Aggregators: Endpoint Verification & Acquisition Spec

**Agent:** calyx_dim01 | **Date:** 2026-07-21 | **Method:** live OAI-PMH probes (curl, `?verb=Identify/ListMetadataFormats/ListSets/ListIdentifiers/GetRecord`), browser rendering, targeted web searches (17 search calls / ~25 queries; 20+ live endpoint probes). All "live" claims verified today unless marked otherwise.

---

## Executive summary

- **NDLTD Union Archive OAI-PMH is LIVE and fully harvestable today** (contradicting the impression that NDLTD is down): `https://ndltdunion.cs.uct.ac.za/OAI-PMH/` returns valid Identify/ListMetadataFormats/ListSets/ListIdentifiers/GetRecord; **completeListSize = 7,908,563 records** (larger than wide01's 6.54M portal-stats figure); portal shows submissions dated **2026-07-20** (yesterday). `union.ndltd.org` and `search.ndltd.org` remain 503 "under redevelopment".
- **LA Referencia's re-exposure OAI endpoint is LIVE and NOT behind the Anubis screen**: `http://oai.lareferencia.info/request` — 1,480,679 records exposed, per-country and per-node sets. The *portal* (www.lareferencia.info) and RENATI (renati.sunedu.gob.pe) are Anubis-blocked; Alicia (Perú) is not.
- **OhioLINK OAI base URL confirmed live**: `https://etd.ohiolink.edu/acprod/odb_etd/ws/oai/oai` (self-identifies as `https://etd.ohiolink.edu/oai`), oai_dc/oai_etdms/marc21, per-institution sets, oai_etdms carries license text.
- **eScholarship OAI live**: `https://escholarship.org/oai`, 558,807 items (one "everything" set — must filter theses by dc:type), PDF pattern verified `https://escholarship.org/content/{id}/{id}.pdf` (HTTP 200, application/pdf).
- **OATD Cloudflare screen confirmed for curl AND full browser**; but the entire 1,100+ source-repository list with OAI baseURLs/sets/prefixes is recoverable from the Wayback snapshot of `https://oatd.org/oatd-repositories.html` (2024-07-08) [^16^].
- **Digital Commons `/do/oai/` pattern verified live** on two repos; set pattern `publication:{series}`; official Elsevier doc lists prefixes oai_dc, simple-dublin-core, qualified-dublin-core, oai_etdms, oai_openaire [^19^].
- **TDM Studio**: 10 datasets × 2M docs; **15 MB/week export cap**; **Citation + Extended Metadata export IS allowed** (CSV) — metadata enrichment feasible, raw-corpus building contractually excluded; new GPT-4o integration (June 2025). PQDT Open still degraded (521 on search page).

---

## 1. NDLTD Union Archive (UCT) — VERIFIED LIVE [HIGH]

**Identify (live 2026-07-21T04:57Z):**
```
GET https://ndltdunion.cs.uct.ac.za/OAI-PMH/?verb=Identify
repositoryName: NDLTD Union Archive of ETD Metadata
baseURL: http://ndltdunion.cs.uct.ac.za:8080/union.OAI-PMH/
protocolVersion: 2.0 | adminEmail: hussein@cs.uct.ac.za
earliestDatestamp: 2011-09-07T02:15:34Z | deletedRecord: persistent
granularity: YYYY-MM-DDThh:mm:ssZ
```
[^1^]

**ListMetadataFormats (live):** `oai_dc`, `oai_etdms`, `etdms`, `etdms11`, `etd-ms`, `mods`. Caveat: formats are **record-dependent** — `GetRecord&metadataPrefix=oai_etdms` on an ADTP record returned `<error code="cannotDisseminateFormat"/>` (source repo only exposed oai_dc). Harvest oai_dc as baseline; attempt oai_etdms opportunistically. [HIGH]

**Set structure (live):** 212 sets, `setSpec` = short collection codes with human-readable names (BOSTON=Boston College, IBICT=IBICT Brazilian ETDs, ADTP=Australasian Digital Theses Program, **LACETR=Library and Archives Canada ETDs Repository**). [HIGH] [^2^]

**Record count (live):** `ListIdentifiers&metadataPrefix=oai_dc` resumptionToken reports **completeListSize="7,908,563"**. First identifiers `oai:union.ndltd.org:ADTP/100073…`. Resumption-token flow control works; page size ~1,000 identifiers (432 KB first page). [HIGH] [^3^]

**Freshness:** portal "Recent Submissions" shows 5 records timestamped 2026-07-20 — the harvester is actively ingesting despite the search UI being down. [HIGH] [^4^]

**Sample record (oai_dc, ADTP/100073):** dc:title/creator/subject/description/date/language + dc:identifier = direct source URL (`http://web4.library.adelaide.edu.au/theses/09DM/09dma831.pdf` — a PDF link) + OAI-PMH `<about><provenance>` block preserving source baseURL/datestamp. [HIGH] [^5^]

**Acquisition spec:** OAI-PMH ListRecords, metadataPrefix=oai_dc, per-set harvest (212 sets) or full harvest with resumption tokens; no auth; standard etiquette (1 req/2–5 s, honor retry-after); full text resolved from dc:identifier links (often direct PDF, sometimes landing page); license capture from dc:rights when present + source-repo page otherwise. **Risk:** single-host UCT infrastructure, no published ToU/rate policy; mirror everything; dedupe vs OATD/CORE.

**Conflict vs wide01:** wide01 said union OAI re-exposure was plausible-but-unverified and gave record total 6,536,154; live OAI shows 7.91M records and full harvestability. Also, the canonical OAI path is `/OAI-PMH/` (not previously documented anywhere; found via portal footer "Feeds: OAI-PMH" link). union.ndltd.org (incl. its `/portal/` and `/OAIHandLer`) = 503 confirmed. [HIGH]

## 2. OATD — Cloudflare confirmed; source list recovered via Wayback [HIGH]

- **Bot screening:** `curl https://oatd.org/` and `/sitemap.xml` → HTTP 403 Cloudflare "Just a moment" challenge; automated headless browser likewise stuck on the challenge page. No sitemap access. [HIGH] [^6^]
- **Source-repository list:** canonical page `https://oatd.org/oatd-repositories.html` ("This is a list of OAI-PMH repositories that provide records to OATD"), with per-entry: institution name, **OAI baseURL (?verb=Identify link), and the exact thesis set(s) + metadataPrefix harvested**. Direct fetch blocked, but the **Wayback snapshot 2024-07-08 renders fully** (~300+ entries enumerated in one view; Americas-relevant examples extracted live): [HIGH] [^16^]
  - bepress/DC repos: Andrews (`digitalcommons.andrews.edu/do/oai/`, sets `publication:dissertations`, `publication:theses`, prefix qualified-dublin-core), BYU (`publication:etd`), UMass (`publication:open_access_dissertations` + 4 more), Kentucky (`publication:gradschool_diss/_theses`), Tennessee (`utk_graddiss/utk_gradthes`), LSU, Emory (oai_etdms), MIT (DSpace `hdl_1721.1_7582` mets), McGill (digitool OAI-PUB, `eTheses` oai_etdms), UBC-adjacent Canadian repos (Guelph mets, Waterloo uketd_dc, Manitoba dim, Saskatchewan, UVic dim), USP (custom `teses.usp.br/cgi-bin/oai.pl`, sets theses/dissertations, etdms), Brazilian TEDE network (`tde_oai/oai3.php`, oai_etdms), IBICT BDTD union (`oai.bdtd.ibict.br/request`, per-campus sets), Colombia (Uniandes mets, Rosario), Perú (UP).
  - **Derivation of "top 30 by record count":** not derivable from OATD without querying its search per repository (`repository:xxx` facet) — blocked by Cloudflare. Proxy: NDLTD union portal per-collection stats (live) rank the shared sources: DiVA Uppsala 386,560; EThOS UK 517,854; DiVA Archive 553,21; Taiwan ~1.17M (wide01); IBICT 632k; OCLC 1.2M; Czech ETDs 155,686; CCSD theses.fr 100,238; LAC 199,832; OhioLINK ~120k. [MED]
- **Acquisition spec:** do NOT scrape OATD. Use Wayback snapshot of oatd-repositories.html as the seed target list; verify each baseURL live (`?verb=Identify`), then harvest the documented set/prefix directly. Also cross-dedupe against the NDLTD union (many sources appear in both). **Risk:** snapshot is 2 years stale — some baseURLs dead/migrated (e.g., `digitool.library.mcgill.ca:8881`, `simba.cs.uct.ac.za/~ethos/...` EThOS static XML file); validate all before scheduling.

## 3. HathiTrust / HTRC [HIGH for docs; HathiFiles host unreachable from probe network — LOW-MED for live reachability]

- **HathiFiles:** monthly full dump `hathi_full_YYYYMMDD.txt.gz` + daily incrementals, distributed from `https://www.hathitrust.org/hathifiles` (redirects to member-libraries data-resources page). Tab-delimited, 26+ fields; field list in header file `hathi_field_list.txt`. Full file ~4+ GB compressed. [HIGH docs] [^7^][^8^][^9^]
- **Thesis identification fields:** there is **no explicit "thesis" genre flag in HathiFiles**. Column 20 `bib_fmt` (BK/SE/MP/… — bibliographic format from MARC Leader) distinguishes books/serials but not dissertations. Practical thesis filter: description/imprint patterns ("Thesis (Ph. D.)"), collection_code/content_provider clusters (e.g., UC thesis digitization programs), and MARC 502 via the **Bibliographic API** (`babel.hathitrust.org/cgi/ls`, JSON/MARC-XML, up to 20 IDs/call, no auth for PD; terms: non-commercial research, no bulk re-hosting). [MED — this refines wide01's vague "genre fields" claim]
- **Extracted Features:** HTRC EF dataset (~18.7M vols) via **rsync, no auth, PD + in-copyright feature files** (features are non-consumptive for all volumes; full OCR only PD). Steps: (1) pull HathiFiles, filter PD (`rights` = pd/pdus) + thesis heuristics → htid list; (2) rsync EF JSON per htid (`rsync -av data.analytics.hathitrust.org::features/…`); or (3) TORCHLITE EF API for small batches; (4) Data Capsule (HTRC Analytics account, member-affiliate approval) only if OCR for in-copyright theses is needed. [HIGH docs] [^10^][^11^]
- **Probe note:** hathitrust.org was unreachable (timeout) from this probe network today; all Hathi statements rest on official docs + GitHub `hathitrust/hathifiles` repo (field definitions) rather than live fetches. [transparency note]

## 4. OhioLINK ETD Center + eScholarship — BOTH VERIFIED LIVE [HIGH]

**OhioLINK:**
- OAI base URL: `https://etd.ohiolink.edu/acprod/odb_etd/ws/oai/oai` (from OhioLINK's official OAI-PMH MARC manual PDF [^12^]; live Identify self-reports `baseURL https://etd.ohiolink.edu/oai`, adminEmail etd-admin@ohiolink.edu, earliestDatestamp 1995-01-01, deletedRecord persistent). Note: `rave.ohiolink.edu/etdc/oai` and `etd.ohiolink.edu/oai2` are 404 — the manual's path is the correct one. [HIGH] [^13^]
- Formats: `oai_dc`, `oai_etdms`, `marc21`. Sets: per-institution (`akron`, `osu`, `ohiou`, plus undergrad honor-program sets like `ma`=Malone). [HIGH]
- oai_etdms record content (verified, `akron1340049818`): full ETD-MS thesis element incl. `<degree><name>Doctor of Philosophy</name><level>doctoral</level>`, identifier = landing page `http://rave.ohiolink.edu/etdc/view?acc_num={acc}`, and **two `<rights>` elements — access class ("unrestricted") + license text** ("all rights reserved" in this sample; CC BY-NC-ND 3.0 / CC BY-NC-SA 3.0 common per item pages). **License variety confirmed: CC vs ARR, machine-capturable via oai_etdms rights.** [HIGH]
- Full-text resolution: landing page → PDF via rave.ohiolink.edu/etdc/view?acc_num= (page embeds PDF link); no OAI-completeListSize reported (token without size attr — page-and-count locally). [HIGH/MED]

**eScholarship (UC):**
- OAI: `https://escholarship.org/oai` — live Identify; formats `oai_dc`, `oclc_dc`, `marc21`; **only one set ("everything")**; completeListSize=**558,807** (all content types, not just theses). [HIGH] [^14^]
- Identifiers are ARKs (`oai:escholarship.org:ark:/13030/qtXXXXXXXX`); records fresh (datestamp 2026-07-20 seen).
- Thesis filtering: harvest oai_dc + filter `dc:type`/publisher (graduate division) — no dedicated ETD set; alternatively use per-campus ETD "series" pages to seed IDs. [HIGH]
- Full text: `https://escholarship.org/content/{itemid}/{itemid}.pdf` — **verified HTTP 200 application/pdf**. Landing page `https://escholarship.org/uc/item/{itemid}`. [HIGH] [^15^]
- License: default © author all-rights-reserved; optional CC (record-level, check landing page; oai_dc rights field sparse). [MED]

## 5. Theses Canada (LAC) [HIGH]

- **LAC is a harvestER, not a provider**: official "Information for universities" page — LAC harvests university repos via OAI-PMH 2.0, requires **ETD-MS 1.0/1.1**, one non-embargoed graduate set per university, and **identifier fields must be direct file links ending in .pdf/.mp3 etc.** No LAC-side OAI endpoint or API documented or found. [HIGH] [^17^]
- **Bulk path for Calyx = NDLTD union set `LACETR`** — live completeListSize **199,832** (unchanged vs wide01). Sample record (`LACETR/oai:collectionscanada.gc.ca:BVIV.1828/1007`): dc:type "Thesis", dc:rights "Available to the World Wide Web", and dc:identifier pointing to the **source-university handle** (hdl.handle.net/1828/1007, UVic) — i.e., many LACETR records link to university full text rather than LAC-hosted PDF. [HIGH] [^18^]
- **PDF availability:** harvested e-theses (1998+) free; ProQuest-digitized retrospective theses carry the ~4-year contractual lag (wide01, not re-falsifiable today; consistent with LAC-university agreement terms). LAC-hosted PDFs served from theses portal record pages; no bulk API. [MED]

## 6. ProQuest TDM Studio + PQDT Open [HIGH]

- **Workbench limits (multi-institution libguides, current):** up to **10 simultaneous datasets × 2,000,000 documents each**; dataset build ~100k docs/hour; VM 4 vCPU/16 GB/100 GB; **export cap 15 MB per rolling week** (larger on request to technical support); **full text never exportable** — "cannot export the full text or any consumptive information that would allow the researcher to reconstruct the full text" (CMU). [HIGH] [^20^][^21^]
- **Metadata export IS allowed and is the Calyx-relevant finding:** two export types — **Citation Metadata** (title/date/author) and **Extended Metadata** (subject fields + extra publication info, "valuable metadata for text and data mining purposes") — exportable per dataset. So: dissertation **metadata/enrichment for corpus-building is contractually feasible** (within 15 MB/week pacing — at ~1–2 KB/record that's roughly 7.5k–15k enriched records/week unless ProQuest raises the cap on request); **full-text corpus-building is not**. [HIGH] [^20^]
- **Pricing model:** no public price list; institution-wide subscription add-on (negotiated with PQ subscription; free at point of use for affiliated researchers, e.g., Columbia "available at no cost to researchers"). Team workbenches 2–5 members, institutional email auth. June 2025: GPT integration beta (gpt-4o etc., 10 req/s, $5/day compute). [HIGH] [^22^][^23^]
- **PQDT Open:** homepage 302→Cloudflare; `pqdtopen.proquest.com/search.html` = **HTTP 521 (origin down)** today — still unstable as wide01 flagged; not an acquisition channel. [HIGH] [^24^]

## 7. LA Referencia — LRProvider VERIFIED LIVE; portal & RENATI Anubis-blocked [HIGH]

- **OAI endpoint:** `http://oai.lareferencia.info/request` — live Identify ("LA Referencia OAI-PMH Provider", adminEmail lautaro.matas@lareferecia.redclara.net, deletedRecord persistent; earliestDatestamp field is dynamic/broken — shows request timestamp). Formats: `oai_dc`, `xoai`. Open-source stack: github.com/lareferencia/lareferencia-oai-pmh. [HIGH] [^25^][^26^]
- **Sets:** two families — per-country (`AR BR CL CO CR …` incl. PE) and per-node-community (`com_MINCYT, com_IBICT, com_CONICYT, com_MINCIENCIAS, com_CONARE, com_CEDIA, com_CONCYTEC, com_REMERI, com_SENACYT, com_ANII`). [HIGH]
- **Counts (live):** full ListIdentifiers completeListSize=**1,480,679**; set PE = **306,520**. Note: portal claims ~4.65M documents — the OAI provider exposes a subset (~1.5M); thesis-specific sets do NOT exist at the union level (filter by dc:type "TESIS DE DOCTORADO"/"MAESTRÍA" or degree fields). [HIGH]
- **License:** portal footer CC BY 4.0 for portal materials (wide01; portal unreachable today behind Anubis — [MED]); underlying theses retain source-repo licenses; xoai format may carry license bundles per DSpace convention.
- **Anubis blocking:** `www.lareferencia.info` (all paths incl. OAI-looking URLs) and `renati.sunedu.gob.pe/oai/request` return Anubis PoW challenge pages (HTTP 200, "Making sure you're not a bot!"). **The dedicated host oai.lareferencia.info is NOT Anubis-screened** — use it. Alicia (alicia.concytec.gob.pe, VuFind 6.1.1) reachable without challenge. `remeri.conacyt.mx` timed out (000) — domain/endpoint appears defunct or moved; Mexico reachable via `com_REMERI` set instead. [HIGH] [^27^]
- **Acquisition spec:** harvest `oai.lareferencia.info/request` per-country sets (CR, CO, EC, PE, MX-com_REMERI) with oai_dc (baseline) + xoai (bitstream/license); resolve full text from dc:identifier to national repos (Alicia/CONCYTEC, SIC Chile, institutional DSpace); polite pacing; CC BY 4.0 attribution for portal-derived metadata. **Risk:** LR metadata quality varies; xoai needed for direct bitstream URLs; earliestDatestamp bug breaks date-based incremental harvesting — use set snapshots + local diffing.

## 8. Digital Commons (bepress) — pattern verified [HIGH]

- **OAI path:** `https://{repo-host}/do/oai/` — verified live on digitalcommons.unl.edu and digitalcommons.usu.edu (valid Identify, adminEmail dc-support@elsevier.com). [HIGH] [^28^]
- **Prefixes (official Elsevier doc):** `oai_dc`, `simple-dublin-core` (dcs), `qualified-dublin-core` (dcq/qdc — richest), **`oai_etdms`** ("Generally used by Library and Archives of Canada"), `oai_openaire`. [HIGH] [^19^]
- **Set structure:** `publication:{series-handle}` per community/collection (verified ListSets on UNL: `publication:accountancyschool` etc.). ETD series handles seen across OATD list: `etd`, `theses`, `dissertations`, `gradschool_diss`, `gradschool_theses`, `open_access_dissertations`, `utk_graddiss`, `oa_etd`, `dissertation_and_theses`… → **enumeration method: per repo, ListSets → filter setSpec/setName for /etd|thes|diss|gradschool/ → harvest with qualified-dublin-core or oai_etdms.** [HIGH]
- **Network-wide repo enumeration:** no public API; seed from OATD Wayback list (dozens of `*.digitalcommons.* / *.bepress.com / scholarworks.*` hosts already enumerated with their ETD sets) + Digital Commons Network browse pages + OpenDOAR. [MED]
- **Risk:** bepress throttles aggressive bots; robots.txt/ToU restrict scraping of HTML — stay on OAI-PMH; PDFs via `https://{host}/cgi/viewcontent.cgi?article=NNNN&context={series}`.

---

## Conflicts vs wide01 — consolidated

| wide01 claim | dim01 finding | Status |
|---|---|---|
| NDLTD union "re-exposes merged metadata via OAI" (unverified); 6,536,154 records | OAI base `https://ndltdunion.cs.uct.ac.za/OAI-PMH/` live; **7,908,563** records; 212 sets; 6 prefixes; actively harvesting (submissions 2026-07-20) | **Upgraded to verified; count revised up** |
| wide01 unaware of exact union OAI path | Path `/OAI-PMH/` (advertised in portal footer "Feeds") | New fact |
| "Union archive submission dates to Feb 2025" | Fresh July 2026 submissions — stale | Corrected |
| OhioLINK "OAI feed" (no URL) | base URL + formats + sets + oai_etdms license fields verified; rave/oai paths 404 | Filled |
| eScholarship "OAI supported" (no URL) | `https://escholarship.org/oai` live; 558,807 items; no ETD set (filter dc:type); PDF pattern verified | Filled |
| LA Referencia "LRProvider OAI — verify" | `http://oai.lareferencia.info/request` live, 1.48M records, country+node sets; portal/RENATI Anubis-blocked; REMERI domain dead | Filled + new blockers |
| OATD list "1,100+ sources" obtainable? | Yes via Wayback 2024-07-08 snapshot incl. exact sets/prefixes; live site Cloudflare-walled for curl and browser | Solved with staleness caveat |
| TDM Studio "2M docs (UChicago)" | Confirmed network-wide; **15 MB/week export cap**; metadata export sanctioned (Citation + Extended) | Deepened |
| HathiFiles "genre fields identify theses" | No thesis genre flag; bib_fmt (col 20) only BK/SE/MP — thesis ID needs 502/imprint heuristics | **Corrected** |
| LAC "metadata harvested into NDLTD" | Confirmed LACETR=199,832 live; records link to university handles; LAC harvest spec requires ETD-MS + direct-file identifiers | Verified + mechanism |
| PQDT Open 521 | Still 521 on search page; homepage behind CF | Confirmed |

## Remaining unknowns / blockers

1. NDLTD union OAI throughput & rate policy unpublished — pilot harvest needed to time a full 7.9M-record pull (est. weeks at polite rates).
2. NDLTD per-record format availability is source-dependent — fraction of records with oai_etdms unknown (needs sampling).
3. OATD source list is a July-2024 snapshot; unknown how many baseURLs have since died/migrated (EThOS entry already points to a dead UCT static file).
4. OhioLINK OAI does not report completeListSize; total harvest size must be counted during pull (portal claim 100k+).
5. LA Referencia OAI exposes ~1.48M of the ~4.65M portal corpus — gap unexplained (validation status? incremental sync?); thesis-type filtering must be client-side.
6. HathiFiles/Bib API hosts unreachable from probe network — live download test still owed (docs are solid).
7. LA Referencia license CC BY 4.0 observed previously on portal but not re-confirmable today (Anubis).
8. REMERI standalone endpoint status (domain timeout) — rely on LA Referencia `com_REMERI` set meanwhile.

---

## References

[^1^]: NDLTD Union Archive OAI-PMH Identify (live 2026-07-21) — https://ndltdunion.cs.uct.ac.za/OAI-PMH/?verb=Identify
[^2^]: NDLTD Union Archive ListSets (212 sets) — https://ndltdunion.cs.uct.ac.za/OAI-PMH/?verb=ListSets
[^3^]: NDLTD Union Archive ListIdentifiers (completeListSize=7,908,563) — https://ndltdunion.cs.uct.ac.za/OAI-PMH/?verb=ListIdentifiers&metadataPrefix=oai_dc
[^4^]: NDLTD Union Archive portal (Recent Submissions 2026-07-20; collection stats) — https://ndltdunion.cs.uct.ac.za/portal/
[^5^]: NDLTD Union Archive GetRecord sample — https://ndltdunion.cs.uct.ac.za/OAI-PMH/?verb=GetRecord&metadataPrefix=oai_dc&identifier=oai:union.ndltd.org:ADTP/100073
[^6^]: OATD homepage (HTTP 403 Cloudflare challenge, curl+browser) — https://oatd.org/ ; FAQ — https://oatd.org/faq.html
[^7^]: HathiTrust HathiFiles landing (redirect target) — https://www.hathitrust.org/member-libraries/resources-for-librarians/data-resources/hathifiles/
[^8^]: hathitrust/hathifiles GitHub (26-field definitions incl. bib_fmt col 20, collection codes) — https://github.com/hathitrust/hathifiles
[^9^]: HathiFiles usage example (hathi_full_YYYYMMDD.txt.gz pattern; pd/pdus rights filter) — https://francescagiannetti.com/librarianship/using-dh-skills-to-do-collections-work/
[^10^]: HTRC data access (EF dataset, rsync, Data Capsule) — https://htrc.atlassian.net/wiki/spaces/COM/pages/43293057/HTRC+data+access
[^11^]: Walsh et al. 2023, TORCHLITE EF API — https://jawalsh.github.io/assets/pdf/walsh2023.pdf
[^12^]: OhioLINK ETD Center OAI-PMH MARC Cataloging Records Manual v1.1 (base URL https://etd.ohiolink.edu/acprod/odb_etd/ws/oai/oai) — https://www.ohiolink.edu/sites/default/files/uploads/OhioLINK-ETD-Center-OAI-PMH-MARC-Cataloging-Records-Manual_0.pdf
[^13^]: OhioLINK OAI Identify (live) — https://etd.ohiolink.edu/acprod/odb_etd/ws/oai/oai?verb=Identify
[^14^]: eScholarship OAI (Identify/ListMetadataFormats/ListSets live) — https://escholarship.org/oai?verb=Identify
[^15^]: eScholarship PDF pattern (HTTP 200 application/pdf) — https://escholarship.org/content/qt39018317/qt39018317.pdf
[^16^]: OATD "Repositories Providing Records to OATD" (Wayback 2024-07-08 snapshot; full baseURL/set/prefix list) — https://web.archive.org/web/20240708000300/https://oatd.org/oatd-repositories.html ; live (CF-blocked) — https://oatd.org/oatd-repositories.html
[^17^]: LAC, "Information for universities — Harvesting requirements" (OAI-PMH v2, ETD-MS 1.0/1.1, direct-file identifier rule) — https://library-archives.canada.ca/eng/services/services-libraries/theses/Pages/information-universities.aspx
[^18^]: NDLTD LACETR set ListIdentifiers (completeListSize=199,832) — https://ndltdunion.cs.uct.ac.za/OAI-PMH/?verb=ListIdentifiers&metadataPrefix=oai_dc&set=LACETR
[^19^]: Elsevier Digital Commons docs, "Digital Commons and OAI-PMH" (prefixes oai_dc/simple/qualified/oai_etdms/oai_openaire) — https://digitalcommons.elsevier.com/integration-preservation/digital-commons-and-oai-pmh
[^20^]: CMU LibGuides, TDM Studio FAQ (15 MB/week export; Citation vs Extended Metadata exports; no full text) — https://guides.library.cmu.edu/TDMStudio
[^21^]: UW LibGuides, TDM Studio Workbench (10 datasets × 2M docs; export rules) — https://guides.lib.uw.edu/tdmstudio/workbench ; UPenn — https://guides.library.upenn.edu/penntdm/tdm-studio
[^22^]: Columbia DSSC blog (2025-06-16), TDM Studio GPT beta; "no cost to researchers" — https://blogs.library.columbia.edu/dssc/2025/06/16/text-mine-proquest-with-chatgpt/
[^23^]: ProQuest TDM Studio Workbench Quick Start Guide (VM specs; sales contact; export terms) — https://pq-static-content.proquest.com/collateral/media2/documents/tdmstudio-qsg.pdf
[^24^]: PQDT Open (521 origin-down on search page, 2026-07-21) — https://pqdtopen.proquest.com/search.html
[^25^]: LA Referencia OAI-PMH Provider Identify (live, no Anubis) — http://oai.lareferencia.info/request?verb=Identify
[^26^]: lareferencia/lareferencia-oai-pmh (open-source provider) — https://github.com/lareferencia/lareferencia-oai-pmh
[^27^]: LA Referencia portal (Anubis PoW challenge, 2026-07-21) — https://www.lareferencia.info/vufind/ ; RENATI (Anubis) — https://renati.sunedu.gob.pe/oai/request?verb=Identify ; Alicia portal (reachable, VuFind 6.1.1) — https://alicia.concytec.gob.pe/vufind/
[^28^]: Digital Commons OAI Identify (live) — https://digitalcommons.unl.edu/do/oai/?verb=Identify ; second repo — https://digitalcommons.usu.edu/do/oai/?verb=Identify

*Probe log: 20+ live HTTP probes (NDLTD×6, OhioLINK×5, eScholarship×4, LA Referencia×5, Digital Commons×3, OATD×3, PQDT Open×2, LAC×1, RENATI/Alicia/REMERI×3, HathiTrust×3) + 17 web-search calls (~25 queries) + 2 browser renders. Unreachable from probe network: hathitrust.org (timeout), web.archive.org via curl (browser OK), remeri.conacyt.mx (timeout).*
