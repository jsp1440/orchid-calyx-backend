# Calyx Deep-Dive — Dimension dim02
## European ETD Repositories — Verified Acquisition Specs
*Research date: 2026-07-21. Prior file verified/deepened: `calyx_wide02.md`. "Probe" = live check by this agent on 2026-07-21 (curl/web_open_url). Claims inline-cited `[^n^]`; URL list at end. Confidence tags: **[H]** verified live; **[M]** documented but not probe-confirmed; **[L]** inference/stale.*

---

## Executive summary

- **Newly probe-verified live (not fully confirmed in wide02):** STAR OAI-PMH (theses.fr) including `ddc:580` botany set + `diffusable` full-text set; DNB OAI + SRU; EADD OAI incl. `hdl_10442_2` OA set; TDR OAI-PMH (DSpace-7 XOAI); Wageningen `library.wur.nl/oai`; RCAAP mirror OAI at INESC-ID; NVA API with degree-category counts; theses.fr REST search API.
- **New conflicts vs wide02:** (1) Swepub `swepub.kb.se` is now behind **Anubis anti-bot** (SRU probe 2026-07-21) — "freely harvestable" needs re-testing; (2) theses.fr OAI base URL is `staroai.theses.fr/OAIHandler`, **not** a path under theses.fr (the `theses.fr/OAIHandler` path 404s); (3) RCAAP main portal `www.rcaap.pt` unreachable from probe environment — the live OAI endpoint is `rcaap.inesc-id.pt/oai-pmh`; (4) `*.diva-portal.org` and several Italian IRIS hosts are unreachable/403 from this environment (DiVA OAI unverifiable here); (5) NUŠL Invenio OAI unreachable (HTTP 000).
- **Best botany entry points:** STAR `ddc:580`/`ddc:570`/`ddc:630` + `diffusable`; DNB `dnb:reiheH:sg5*`; EADD `hdl_10442_2`; EThOS CC0 CSV (DDC field) → institutional links; TDR XOAI per-university sets; NVA `instanceType=DegreePhd` (36k hits) + subject filters.

---

## 1. theses.fr (ABES) — France **[H]**

| Field | Spec |
|---|---|
| REST API | `https://theses.fr/api/v1/theses/recherche/?q=<query>&nombre=<n>` — **probe-verified live** (q=botanique → 1,042 totalHits, JSON). Open-source with OpenAPI spec: GitHub `abes-esr/theses-api-recherche`. Query DSL documented on data.gouv.fr dataservice page: filters `status:(soutenue|enCours)`, `accessible:oui`, `discipline:(...)`, `sujetsLibelle:(...)`, `dateSoutenance:([AAAA-MM-JJ TO ...])`, IdRef PPN filters; result cap **100,000** theses; availability 99.99%.[^5^] |
| OAI-PMH | Base URL **`http(s)://staroai.theses.fr/OAIHandler`** — **probe-verified live** (Identify: "STAR : dépôt national des thèses électroniques françaises", protocol 2.0, admin thelec@abes.fr, earliestDatestamp 2008-11-25, compression deflate).[^1^][^2^] NB: `theses.fr/OAIHandler` 404s — use the `staroai` host (correction to wide02's vague "STAR warehouse"). |
| OAI formats | `tef` (native TEF XML) + `oai_dc` — probe via ListMetadataFormats.[^2^] |
| OAI sets | 289 sets (ListSets paginated via resumptionToken): ~100 **Dewey discipline sets** (`ddc:570` Sciences de la vie/biologie; **`ddc:580` Plantes. Botanique**; `ddc:590` Zoologie; `ddc:630` Agronomie/agriculture/vétérinaire); per-institution sets by ABES code (`BOR1`, `METZ`, `NICE`, …); plus the full-text-dissemination flag set **`diffusable`** — observed as setSpec on headers in a live `ListIdentifiers&set=ddc:580` probe (e.g. `2008BOR13624` carries `setSpec: ddc:580 + BOR1 + diffusable`). Sets cannot be cross-filtered server-side (documented limitation) — harvest `ddc:580` and intersect locally with `diffusable` membership, or harvest institution sets for MNHN/INRAE partners.[^2^][^3^] |
| Bulk dump | data.gouv.fr dataset **"Thèses soutenues en France depuis 1985"** (ABES publisher page) — CSV + JSON + NDJSON, licence Etalab **Licence Ouverte / Open Licence 2.0**. Caveat: last full refresh 2024-01-08 (update frequency "not respected" per data.gouv.fr scorecard); gap-fill via API/OAI incrementals.[^4^][^6^] |
| License obligations | Etalab OL 2.0: free reuse incl. commercial, **obligations: attribute source (ABES/theses.fr) + state date of retrieval**; personal data exposure framed by CRPA D.312-1-3 / GDPR Art. 17(3) — names of authors/jury are public administrative data; right of rectification via ABES helpdesk.[^4^][^8^] |
| TEF format | AFNOR/CG46 TEF 2.0 XML schema for French e-theses; contains full-text access URL (harvest TEF → extract URL → HTTP GET PDF, per ABES' own recipe).[^3^] |
| Full-text resolution | TEF `dcterms:hasPart`/access URL → STAR/CINES-hosted copy or HAL/institutional copy; `accessible:oui` API filter pre-selects downloadable theses. |
| Rate etiquette | No published rate limit; API documented with 100k-record cap and 99.99% availability metric; use annual dump for bulk, OAI for deltas. |
| Botany sets | `ddc:580`, `ddc:570`, `ddc:630`; institutions: MNHN (MUSN), INRAE-partner schools, Montpellier, IRD. **Probe sample:** ddc:580 live and populated (2008–2009 Bordeaux records returned 2026-03 datestamps). |
| Risk | **Low.** Gold standard. |

## 2. EThOS / British Library — UK **[H/M]**

| Field | Spec |
|---|---|
| Post-relaunch state | New platform live by 2026-07-08 (BL news + collection page): 650k+ records (incl. +14k added since the 2023 cyber-attack); **no central full text, no login**; ~65% of records carry an "Access thesis from university" link; **400,000+ theses openly downloadable from university repositories**. Digitisation now by-request *via the university* (BL returns files to the university repo; EThOS link added at next harvest).[^9^][^10^] |
| CSV dataset | "UK Doctoral Thesis Metadata from EThOS", BL Research Repository (Hyku, `bl.iro.bl.uk`). Versioned DOI chain; latest pre-attack versions: v9 (2022) `10.23636/kvwc-ty06` (CC0 per reusers); suspension-era spreadsheet `10.23636/rcm4-zk44` (linked from bl.iro.bl.uk homepage); collection record `collections/e492dc4b-82d9-4f8c-bb0a-2cdd8a62105d`. BL states the full CSV remains downloadable post-relaunch; **whether a refreshed post-2026 snapshot has been published is unknown — check collection page at harvest time.** Fields (from published reuses): author, title, awarding institution, year, abstract (truncated), DDC discipline, supervisors (sparse), EThOS ID/institutional link. Licence **CC0** (confirmed for v9 by Transactions IBG data statement; verify on current version record).[^9^][^11^][^12^][^13^] |
| API | None documented on new platform; CSV + institutional-repo crawling is the route. **[M]** |
| Full-text resolution | CSV institutional-link field → university repository record (DSpace/EPrints/Pure/Figshare; many expose OAI-PMH themselves) → OA PDF. ~65% of records link out; 400k+ downloadable. |
| Botany identification | Filter DDC 570/580/630 + keywords (Orchidaceae) in CSV; Kew-linked PhDs (QMUL, Reading), Oxford/Cambridge/Edinburgh/Nottingham/Bangor plant science. |
| Risk | **Low** for metadata (CC0). Full text: per-university licences; respect robots/rate limits per repo. |

## 3. DNB — Germany **[H]**

| Field | Spec |
|---|---|
| OAI-PMH | `https://services.dnb.de/oai/repository` — **probe-verified live** (Identify: "OAI-Repository of the German National Library V2.0.11", earliest 1945-01-01, deletedRecord transient, second granularity).[^14^] |
| Sets | Full ListSets probed: `dnb:*` (all of DNB) + **`dnb:reiheH` = "Hochschulschriften"** with DDC-hierarchy subsets — botany-relevant: `dnb:reiheH:sg5*` (Naturwissenschaften incl. 570 Biowissenschaften, **580 Botanik**, 590 Zoologie, 630 Landwirtschaft), `dnb:reiheH:sg333.7` (Natürliche Ressourcen/Umwelt). Set tree mirrors DDC Sachgruppen.[^14^] |
| SRU | `https://services.dnb.de/sru/dnb` — **probe-verified live** (ExplainResponse v1.1). CQL queries, MARCXML record schema; no key.[^15^] |
| Metadata licence | Catalogue data free without registration (DNB free-interfaces policy); **GND authority data CC0** (lobid-GND CC0 confirmed widely).[^16^] |
| Full-text resolution | Records carry d-nb.info persistent URLs + URN:NBN:de; DissOnline online dissertations link to DNB-hosted or university publication-server PDFs (OPUS/DSpace/eprints hosts). Rights vary; OA subset crawlable. |
| Rate etiquette | No registration; fair-use; use `from/until` incremental harvesting; resumptionTokens supported. |
| Risk | **Low** metadata; medium for full text (German dissertation copyright strict — capture per-record rights/oa status). |

## 4. RCAAP — Portugal **[M/H]**

| Field | Spec |
|---|---|
| REST API | Public REST API, JSON (XML/JSONP on request), **OpenAPI (OAS) compliant** per official RCAAP blog (2019 restructure post); v1 maintained, richer v2 in development. **Docs URL not re-confirmed in 2026** — historically linked from rcaap.pt; main portal unreachable from probe environment (HTTP 000), so treat docs URL as **unknown**; contact FCCN. No published rate limits; no auth for metadata.[^17^] |
| OAI-PMH | Portal OAI rebuilt on XOAI with an extended full-text-link context set. **Probe:** main `www.rcaap.pt` and `comum.rcaap.pt` unreachable from this environment (HTTP 000); however **mirror `https://rcaap.inesc-id.pt/oai-pmh` probe-verified live** (Identify: "INESC-ID RCAAP Portal", protocol 2.0; earliestDatestamp 2025-11-23 → recent re-platform, verify completeness vs. portal before production use). Member-repository OAI pattern: `https://<repo>/oai/request` (e.g. comum.rcaap.pt), directory at rcaap.pt/directory.jsp.[^18^][^19^][^20^] |
| Thesis filtering | COAR document types (OpenAIRE 4) — filter `doctoral thesis`/`master thesis`; CC licence links extracted into dedicated field (blog). |
| Scale | 1M+ documents (Dec 2023 milestone; ~1.1M by 2026 per sector guides).[^21^] |
| Risk | **Low-Medium.** Open aggregator; portal reachability from foreign egress to be confirmed. |

## 5. Sweden — Swepub / DiVA **[M, conflict flagged]**

| Field | Spec |
|---|---|
| Swepub | KB-run national aggregate (~40 HEIs). KB page documents: OAI-PMH + SRU + open JSON APIs + Xsearch + **data dumps**, "freely available for reuse" (Swepub MODS; BIBFRAME JSON-LD). **CONFLICT / new finding: `swepub.kb.se/sru` probe 2026-07-21 returned an Anubis anti-bot challenge** (anubis v1.25.0, fast/difficulty-2) — automated harvest currently gated; KB dumps/API on other hosts may still be open; verify each path and/or request whitelisting from KB.[^22^][^23^] |
| DiVA per-institution | Pattern `<org>.diva-portal.org/dice/oai` (oai_dc, MODS, ETDMS, MARC21). **All diva-portal.org probes returned HTTP 000 from this environment** (su., uu., slu., www.) — likely IP/geo blocking; endpoints are well-documented (apis.io entries for Stockholm, Uppsala). Mark **unreachable from probe environment, not down**.[^24^] |
| SLU | SLU now on DiVA (`slu.diva-portal.org`); legacy `pub.epsilon.slu.se` OAI paths 404. SLU coverage flows into Swepub. **[M]** |
| Licence | Swepub metadata explicitly free for reuse; full text © authors (many CC); Swedish TDM exception (DSM). |
| Risk | **Medium** (Anubis on Swepub is new friction; DiVA reachable from SE-friendly egress expected). |

## 6. NVA — Norway **[H]**

| Field | Spec |
|---|---|
| API | `https://api.nva.unit.no/search/resources` — **probe-verified live**; category param maps to `instanceType=`. Degree-thesis counts probed 2026-07-21: **DegreePhd 36,162; DegreeMaster 225,445; DegreeBachelor 35,712; DegreeLicentiate 53**. JSON; UUID-keyed; `associatedArtifacts` carry file identifiers + license names; paged via `nextResults`.[^25^] |
| Docs | GitHub `Unit-no/nva-*` repos / Sikt developer pages; OpenAPI specs in repos. **[M]** |
| Licence | Metadata open (Norwegian OA policy); per-artifact licence names in records (probe saw "COPYRIGHT-AC…" value — parse per record). |
| Auth/limits | Read access none; undocumented rate limits — polite paging. |
| Botany | Filter by subject/keywords + institution (NMBU owner org `194.0.0.0` seen in probe = NMBU). |
| Risk | **Low.** System young (full production 2025-10); schema versions drift (modelVersion 0.23.3 observed). |

## 7. Southern/Eastern Europe + Netherlands

### TDR Catalonia (tdx.cat) **[H]**
- OAI-PMH **`https://www.tdx.cat/oai/request`** — **probe-verified live** (Identify "TDX (Tesis Doctorals en Xarxa)"; note: respond reliably via http→https; earlier wide02 path doubt resolved — it is classic DSpace `/oai/request`, now **XOAI (DSpace 7)**).
- Formats: didl, mods, ore, **oaire**, mets, xoai, dim, **uketd_dc**, qdc. Sets: `com_10803_*` per university (UB, UAB, Girona, Lleida, Illes Balears, València, Jaume I, Cantabria, Murcia, Oviedo, …). CC0 claimed for the catalogue per library guides; per-record CC for texts. Handles 10803/*.[^26^]
- Full text: OA PDFs on tdx.cat (bitstreams). Risk **Low**.

### TESEO Spain **[M]** (carried from wide02, no new contradictions)
- Ministry bibliographic DB since 1976; **no full text, no API/OAI, no official bulk export**; unauthorized scraped dumps exist with dubious legality — do not ingest scraped dumps; use TESEO for discovery validation only, RECOLECTA OAI for full text.[^27^]

### Italy IRIS / tesidottorato **[M/H]**
- IRIS per-ateneo OAI pattern `https://<repo>/oai` (e.g. `air.unimi.it/oai` → **403 to curl; host live** — bot protection; use documented OAI path with proper harvester UA or OpenAIRE). National legal-deposit platform `tesidottorato.depositolegale.it` (BNCF/BNCR + Cineca) assigns **NBN URN**; CC licence selection in deposit workflow since Oct 2025; 36-month max embargo. No national OAI documented yet.[^28^][^29^]
- Risk **Medium** (endpoint-by-endpoint). Botany: Padova, Florence, Sapienza, Bologna IRIS endpoints.

### Czech NUŠL **[L — unreachable]**
- Grey-literature national repository (NTK Prague; 600k+ records by 2020; Invenio). Documented OAI base `http://invenio.nusl.cz/oai2d` (set `global`, prefix `marcxml`; confirmed in metha site lists + OARepo harvester examples). **Probe 2026-07-21: HTTP 000 (unreachable from this environment)** — possibly http-only/host down/migrated to new OARepo platform. Orchid relevance: grey lit + ČZU/Mendel theses. Czech legal regime: theses public for study, republication restricted — **metadata-only ingestion; negotiate full text.**[^30^][^31^]

### EADD Greece **[H]**
- OAI **`https://www.didaktorika.gr/eadd-oai/request`** — **probe-verified live** ("National Archive of PhD theses", EKT). Sets probed: `dart`, `voa3r`, `triple`, `hdl_10442_1` (ΕΑΔΔ), **`hdl_10442_2` (Συλλογή ΕΑΔΔ = full-text-OA collection)**. Formats oai_dc/hedi/unimarc/mods (opendata page). 43k+ theses. Handles 10442/*. Licence: open-data page; OA set intended for reuse. Risk **Low**.[^32^][^33^]

### Wageningen eDepot (post-NARCIS) **[H]**
- NARCIS dead (confirmed wide02). Direct harvest: **`https://library.wur.nl/oai`** — **probe-verified live** ("Wageningen University & Research Publications", OAI 2.0, earliest 2013-01-02, deletedRecord transient, granularity day). `edepot.wur.nl` itself is now a JS app (WURLIB6) — use library.wur.nl/oai + WUR DOI resolution. WUR = world #1 plant/agriculture; orchid-systematics via Naturalis/Leiden partners. Risk **Low**.[^34^]

## 8. DART-Europe closure & succession **[H/M]**
- **Confirmed closed 3 Feb 2025** (multiple sources; infotoday.eu landscape review 2025-10). Nothing replaced it institutionally — LIBER partnership dissolved. De-facto successors: **OpenAIRE Explore** (~2.6M doctoral theses), **BASE** (~3.75M theses), CORE (type:"thesis"); OATD recommended by NDLTD while Global ETD Search itself is down/migrating (new finding: G-ETD-S has been inaccessible for months — flag for other dimensions). Strategy: harvest national nodes directly (this file) + OpenAIRE/BASE as discovery overlays.[^35^][^36^]

---

## Conflicts / corrections vs wide02
1. **theses.fr OAI URL:** wide02 gave no concrete base URL; live path is `staroai.theses.fr/OAIHandler` (theses.fr/OAIHandler 404). Full-text set observed as setSpec **`diffusable`**, not an English-named set.
2. **Swepub "explicitly for free reuse":** still true legally, but **Anubis anti-bot observed on swepub.kb.se** (2026-07-21) — harvesting needs whitelist/dump route. New risk, analogous to LA Referencia finding in wide02.
3. **RCAAP OAI endpoint:** wide02 said XOAI at rcaap.pt; main portal unreachable from environment; live mirror at `rcaap.inesc-id.pt/oai-pmh` (earliestDatestamp 2025-11-23 — recently re-platformed; completeness vs portal unverified).
4. **TDR OAI path doubt resolved:** `https://www.tdx.cat/oai/request` works (XOAI) — wide02's "did not respond" superseded.
5. **DiVA/Italian IRIS reachability:** wide02 assumed standard endpoints; from this environment diva-portal.org = 000, air.unimi.it/oai = 403. Environment-specific blocking likely; flag for egress planning.
6. **EThOS CSV licence:** wide02 said "license verify" — CC0 confirmed for v9 (2022) by independent reuse statements; current-version record should be re-checked at download.

## Unknowns / blockers
- RCAAP REST API OpenAPI docs URL (portal unreachable); INESC-ID mirror coverage vs. portal.
- Whether a refreshed post-relaunch EThOS CSV snapshot (2026) has been published; DOI chain resolution of `10.23636/j278-4b96`/`rcm4-zk44` failed from probe environment.
- Swepub: which of OAI/SRU/API/dump paths are Anubis-exempt; KB whitelisting process.
- DiVA per-institution OAI from non-EU egress; SLU coverage check pending.
- NUŠL OAI status (host unreachable; possible OARepo migration).
- IRIS OAI correct per-ateneo paths + bot-protection policy; national tesidottorato platform API.
- TEF parsing test not performed (schema documented); botany-set record counts not enumerated (STAR resumptionToken paging works, probe only sampled).
- DNB full-text URL coverage fraction inside reiheH records — not quantified.

## References
[^1^]: ABES documentation — Moissonnage des métadonnées (STAR OAI-PMH at staroai.theses.fr/OAIHandler; sets; TEF recipe): https://documentation.abes.fr/aidethesespro/co/moissonnage_metadonnes.html
[^2^]: STAR OAI-PMH (probe-verified Identify/ListSets/ListMetadataFormats/ListIdentifiers 2026-07-21): http://staroai.theses.fr/OAIHandler?verb=Identify
[^3^]: ABES — Réutiliser les données (Etalab OL 2.0, OAI sets/formats): https://abes.fr/reseau-theses/reutiliser-les-donnees/
[^4^]: data.gouv.fr — Thèses soutenues en France depuis 1985 (CSV/JSON/NDJSON, OL 2.0, updated 2024-01-08): https://www.data.gouv.fr/datasets/theses-soutenues-en-france-depuis-1985
[^5^]: data.gouv.fr — API Interroger les Données de theses.fr (query fields, 100k cap, 99.99% availability): https://www.data.gouv.fr/fr/dataservices/api-interroger-les-donnees-de-theses-fr/
[^6^]: GitHub — abes-esr/theses-api-recherche (OpenAPI): https://github.com/abes-esr/theses-api-recherche
[^7^]: theses.fr REST search (probe 2026-07-21, q=botanique → 1,042 hits): https://theses.fr/api/v1/theses/recherche/?q=botanique&nombre=1
[^8^]: ABES — Guide de réutilisation des données theses.fr (PDF): https://abes.fr/wp-content/uploads/2022/03/guide-reutilisation-donnees-theses-fr.pdf
[^9^]: British Library — EThOS collection page (post-relaunch facts; CSV availability): https://www.bl.uk/collection/ethos
[^10^]: British Library — EThOS records restored (2026-07-08; 650k records, 65% IR links): https://www.bl.uk/stories/news/ethos-records-restored
[^11^]: BL Research Repository — EThOS dataset collection (versioned snapshots): https://bl.iro.bl.uk/collections/e492dc4b-82d9-4f8c-bb0a-2cdd8a62105d
[^12^]: BL Research Repository homepage (suspension-era CSV pointer doi 10.23636/rcm4-zk44): https://bl.iro.bl.uk/
[^13^]: Reades & Sheppard (Trans. IBG 2025) — EThOS metadata "freely available… under a CC0 licence"; Oct-2022 release 610,535 records: https://discovery.ucl.ac.uk/10203004/7/
[^14^]: DNB OAI-PMH (probe-verified Identify + full ListSets incl. dnb:reiheH:* 2026-07-21): https://services.dnb.de/oai/repository?verb=Identify
[^15^]: DNB SRU (probe-verified explain 2026-07-21): https://services.dnb.de/sru/dnb?version=1.1&operation=explain
[^16^]: DNB/ZDB — OAI-PMH interface description (free, no registration): https://zeitschriftendatenbank.de/services/schnittstellen/oai
[^17^]: RCAAP blog — Novo Portal RCAAP (public REST API, OpenAPI/OAS, JSON/XML/JSONP; XOAI full-text-link set): https://blog.rcaap.pt/2019/01/11/novo-portal-rcaap-disponibiliza-novas-funcionalidades/
[^18^]: RCAAP OAI-PMH mirror (probe-verified Identify 2026-07-21): https://rcaap.inesc-id.pt/oai-pmh?verb=Identify
[^19^]: RCAAP blog — member-repo OAI pattern /oai/request + directory: https://blog.rcaap.pt/2018/01/22/boas-praticas-inserir-tid-nas-teses-e-dissertacoes-como-fazer/
[^20^]: OpenAIRE — RCAAP API integration (aggregator architecture): https://www.openaire.eu/rcaap-api-integration
[^21^]: Tesify.pt — RCAAP 2026 guide (1.1M documents; FCT management; deposit mandate): https://tesify.pt/rcaap-repositorios-cientificos-guia/
[^22^]: Kungliga biblioteket — Swepub data access (OAI-PMH, SRU, APIs, dumps, free reuse): https://www.kb.se/for-bibliotekssektorn/eng/services/swepub-data-access.html
[^23^]: Swepub SRU (probe 2026-07-21: Anubis anti-bot challenge returned): https://swepub.kb.se/sru?version=1.1&operation=explain
[^24^]: apis.io — DiVA OAI-PMH entries (Stockholm etc.; dice/oai pattern): https://apis.io/tags/oai-pmh/
[^25^]: NVA API (probe-verified 2026-07-21; DegreePhd=36,162 etc.): https://api.nva.unit.no/search/resources?category=DegreePhd&size=0
[^26^]: TDR OAI-PMH (probe-verified Identify/ListSets/ListMetadataFormats 2026-07-21): http://www.tdx.cat/oai/request?verb=Identify
[^27^]: M. Blázquez — TESEO scraped catalogue (legal ambiguity noted): https://mblazquez.es/catalogo-de-tesis-doctorales-espanolas-teseo-disponible-para-su-descarga/
[^28^]: Tesify.it — IRIS/BOA/OAR OAI-PMH guide 2026 (per-ateneo endpoints, OpenAIRE integration): https://tesify.it/blog/repository-iris-boa-oar-2026-oai-pmh/
[^29^]: EPO academic research — Italian doctoral theses legal-deposit platform report (NBN URN, embargo, CC from Oct 2025): https://link.epo.org/web/academic-research-programme/completed-research-projects/en-doc-track-2022-2025-final-technical-report.pdf
[^30^]: GL2020 proceedings — NUSL service (600k records, Invenio, OAI): http://greyguide.isti.cnr.it/attachments/article/51/GL2020%20Conference%20Proceedings.pdf
[^31^]: OARepo OAI harvester docs — NUSL harvester example (invenio.nusl.cz/oai2d, set global, marcxml): https://pypi.org/project/oarepo-oai-pmh-harvester/
[^32^]: EADD OAI-PMH (probe-verified Identify + ListSets 2026-07-21): https://www.didaktorika.gr/eadd-oai/request?verb=Identify
[^33^]: EADD — Open data page (sets incl. dart, hdl_10442_2; formats): https://www.didaktorika.gr/eadd/opendata
[^34^]: Wageningen University & Research Publications OAI (probe-verified Identify 2026-07-21): https://library.wur.nl/oai?verb=Identify
[^35^]: Information Today Europe — "European theses: new landscape, new challenges" (2025-10-07; DART closed 3 Feb 2025; G-ETD-S inaccessible; BASE/OpenAIRE/CORE successors): https://www.infotoday.eu/Articles/Editorial/Featured-Articles/European-theses-new-landscape-new-challenges-171757.aspx
[^36^]: arXiv 2604.08619 — French theses linked-dataset paper (DART-Europe closure note; theses.fr dump/API gap-filling practice): https://arxiv.org/html/2604.08619v1

*Probe log 2026-07-21: LIVE ✓ — STAR OAI, theses.fr API, DNB OAI, DNB SRU, EADD OAI, TDR OAI (XOAI), WUR library OAI, RCAAP INESC-ID mirror OAI, NVA API. BLOCKED/UNREACHABLE ✗ — swepub.kb.se (Anubis), www.rcaap.pt + comum.rcaap.pt (000), *.diva-portal.org (000), pub.epsilon.slu.se OAI paths (404), air.unimi.it/oai (403), invenio.nusl.cz/oai2d (000), doi.org resolution of BL DOIs via fetcher.*
