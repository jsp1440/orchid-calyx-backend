# Calyx Wide-Exploration — Facet wide02
## Facet: Europe + Asia + Global South ETD Repositories
*Research date: 2026-07-21. Claims inline-cited `[^n^]`; numbered URL list at file end. "Probe" = live check performed by this agent on 2026-07-21.*

---

### Key Findings

1. **EThOS (British Library) is back online as of ~July 2026 — but changed.** After the October 2023 BL cyber-attack took it fully offline, a new EThOS platform launched (interim metadata-only service announced Jan 2026, full public platform live by 8 July 2026) holding 650,000+ UK doctoral-thesis metadata records; ~65% of records link to institutional repositories, and 400,000+ theses are openly downloadable *from the universities*, not from BL. No login required. Critically: **"the full bibliographic dataset in csv format is available for download from the British Library Research Repository"** — this is the single best UK bulk-ingestion path. Digitisation-on-demand is discontinued; unscanned theses must be requested from the awarding university.[^1^][^2^][^3^][^4^][^5^][^6^]
2. **DART-Europe is permanently closed** (3 February 2025) after 20 years — its partner-portal OAI role is gone; national nodes (theses.fr, DNB, EADD, etc.) must be harvested directly.[^7^]
3. **theses.fr (ABES, France) is the gold-standard ingestion target in Europe**: Etalab Open Licence 2.0 (free reuse with attribution + retrieval-date), documented REST API (`https://theses.fr/api/v1/recherche/`, OpenAPI on GitHub), OAI-PMH "STAR" warehouse (sets by institution / discipline / full-text availability; TEF + enriched Dublin Core), and annual full data dumps on data.gouv.fr (JSON/NDJSON/CSV).[^8^][^9^][^10^]
4. **Germany DNB OAI-PMH is live and free without registration**, with a dedicated **"Hochschulschriften" (academic theses) set hierarchy** — confirmed live by probe on 2026-07-21 (`https://services.dnb.de/oai/repository`). GND authority data is CC0.[^11^][^12^][^13^]
5. **LA Referencia's whole site — including its OAI-PMH endpoint — is currently behind "Anubis" anti-bot proof-of-work protection** (observed by probe 2026-07-21). The regional aggregator (10–12 Latin American national nodes) is therefore *not currently machine-harvestable* without whitelisting/arrangement; harvest the national nodes (Argentina SNRD, Brazil BDTD, Chile, Mexico) directly instead.[^14^][^15^][^16^]
6. **Shodhganga (INFLIBNET, India) passed 600,000 theses (May 2025)** and is DSpace-based with OAI-PMH; however the site was unreachable from this research environment (possible geo-blocking — INFLIBNET has previously restricted non-Indian access; ShodhShuddhi is a separate plagiarism-screening service, not a repository). India also has **KrishiKosh** (ICAR/NARES agricultural theses, DSpace, OA, ~180k theses incl. KrishiPrabha legacy) — high botanical value.[^17^][^18^][^19^][^20^][^21^]
7. **CNKI's China Doctoral/Master's Dissertation databases (CDMD/CDFD) suspended international/institutional access in April 2023** following Chinese cross-border data-security regulation — multiple universities (Kyoto, Korea) lost service; access is now largely China-domestic or via resellers such as East View. Treat China as a *restricted* jurisdiction for bulk acquisition.[^22^][^23^][^24^]
8. **Norway consolidated everything in 2025**: NVA (Nasjonalt vitenarkiv, run by Sikt) went into full production 1 October 2025, replacing Cristin and the Brage institutional repositories; it has a public REST API (`api.nva.unit.no`, probe-confirmed responding).[^25^][^26^][^27^][^28^]
9. **Sweden: harvest Swepub (Kungliga biblioteket), not 50 separate DiVA endpoints** — Swepub aggregates all Swedish HEI repositories (incl. DiVA schools) with OAI-PMH, SRU, open REST APIs and data dumps, explicitly for free reuse. DiVA per-institution OAI (e.g. `su.diva-portal.org/dice/oai`) remains the fallback.[^29^][^30^][^31^][^32^]
10. **Netherlands: NARCIS is dead** (portal offline 1 March 2023; service discontinued July 2023; CC0 data snapshot was published). Use university repositories directly (Wageningen — world #1 in plant sciences — plus Leiden, Utrecht, Amsterdam, NWO's new Netherlands Research Portal).[^33^][^34^][^35^]
11. **Italy launched a new national doctoral-thesis platform (tesidottorato.depositolegale.it) in 2024** under mandatory legal deposit (L.382/1980), fed automatically from universities' IRIS CRIS systems (per-ateneo OAI-PMH endpoints exist); NBN URN persistent identifiers; from Oct 2025 CC-licence options were added to the deposit workflow.[^36^][^37^][^38^][^39^]
12. **Greece EADD is a small but fully open, OAI-PMH-verified target** (43,000+ theses; `didaktorika.gr/eadd-oai/request` probe-verified live; open-data page documents sets incl. DART and full-text).[^40^][^41^][^42^]
13. **Spain: TDR (Catalonia) and TESEO (national, Ministry) are complementary** — TDR gives full text (OA, DSpace); TESEO is bibliographic-only since 1976 (no full text, no official bulk export; community scrapers exist). National aggregator RECOLECTA harvests Spanish repositories via OAI-PMH.[^43^][^44^][^45^]
14. **Portugal RCAAP has both OAI-PMH and a documented public REST API (OpenAPI, JSON/XML)**, 1M+ documents, no auth for metadata — a model Global-South-style aggregator in Europe.[^46^][^47^]
15. **Korea RISS (KERIS) holds ~2.29M theses with free full text for most**, DOIs assigned since 2021; no documented open bulk API — screen-scraping rate-limited; LOD pilot exists.[^48^][^49^][^50^]
16. **Trove (Australia) API v3 works with a free API key** (theses split between "Books & Libraries" and "Research & Reports" categories, `l-format=Thesis`), but NLA tightened API access in 2024–25 (GLAM Workbench keys were cancelled; new approval workflow) — obtain institutional buy-in before depending on it.[^51^][^52^][^53^]
17. **Brazil BDTD (IBICT) migrated to a VuFind platform (Jan 2024)** with ~900k records, OA full text where authors allow, OAI-PMH historically at `oai.ibict.br`; CAPES Catalogue is abstracts-only.[^54^][^55^][^56^]
18. **Iran GANJ (IranDoc) is the standout Middle-East mandate repository** (1.2M+ documents; deposit mandated; first ~20 pages + bibliography free immediately; full text free after 18 months (master's) / 30 months (doctoral) embargo).[^57^][^58^]

---

### Repository Profiles (21-field blocks)

---

#### 1. EThOS — e-Theses Online Service
- **Name:** EThOS (e-Theses Online Service)
- **Organization:** British Library (UK national library)
- **Geographic coverage:** United Kingdom (all HEIs, ~130 institutions)
- **Subject coverage:** All disciplines (doctoral theses only)
- **Approx. dissertation count:** 650,000+ metadata records; ~300,000 full-text theses previously hosted; 400,000+ now downloadable via institutional links [^1^][^3^][^5^]
- **Open access vs restricted:** Metadata fully open, no login; full text only where the awarding university repository hosts OA copies [^5^]
- **Metadata availability:** Full UK doctoral bibliographic dataset as **CSV download from the British Library Research Repository** ("UK Doctoral Thesis Metadata from EThOS"); searchable web platform (Hyku-based) [^5^]
- **Full-text availability:** Indirect — ~65% of records link out to institutional repositories; BL no longer serves central downloads [^1^][^5^]
- **API availability:** No documented public API on new platform as of 2026-07 (unknown); dataset CSV is the bulk route [^5^]
- **OAI-PMH support:** No (pre-2023 there was none; new platform not documented)
- **DOI/Handle support:** BL DOIs were minted for some theses; institutional handles/DOIs prevail for downloads
- **Bulk metadata harvesting:** Yes — official CSV dataset [^5^]
- **Bulk download capability:** No central bulk full text; must crawl institutional repositories using CSV links
- **Rate limits:** Unknown (new platform)
- **Authentication requirements:** None for search/metadata (previously required account + paid digitisation — discontinued) [^4^]
- **Licensing restrictions:** Metadata open; full texts under each university's licence (mixed; many CC)
- **Terms of use:** BL Research Repository dataset terms; verify at bl.uk [^2^]
- **TDM permissions:** Metadata clearly reusable; full-text TDM depends on source repository
- **Copyright concerns:** Theses remain © authors; pre-2023 digitised scans re-hosting restricted — source from universities
- **Preferred acquisition method:** Download CSV dataset → filter botanical subject/keywords → resolve institutional-repository URLs → harvest OA PDFs
- **Botanical/orchid relevance:** High — Kew-linked PhDs (QMUL, Reading, etc.), strong plant-science schools (Oxford, Cambridge, Edinburgh, Nottingham, Bangor)
- **Confidence:** High (multiple 2026 sources, incl. BL's own news) [^3^][^4^][^5^]

#### 2. theses.fr — French national theses portal
- **Name:** theses.fr
- **Organization:** ABES (Agence bibliographique de l'enseignement supérieur), France
- **Geographic coverage:** France (all doctoral-granting institutions)
- **Subject coverage:** All disciplines (doctoral; also some HDR)
- **Approx. dissertation count:** ~450,000 theses records (~380k defended + in-preparation); exact current count unknown
- **Open access vs restricted:** Metadata open data; full text where universities/authors permit (links to STAR/institutional/HAL copies) [^8^]
- **Metadata availability:** Rich (TEF format: French thesis XML); person/org IDs via IdRef [^8^][^9^]
- **Full-text availability:** Partial OA; confidentiality sets respected [^8^]
- **API availability:** Yes — REST API `https://theses.fr/api/v1/recherche/` with OpenAPI spec, open source on GitHub (abes-esr) [^10^]
- **OAI-PMH support:** Yes — "Entrepôt OAI-PMH STAR": sets by institution, by discipline, and "thèses accessibles en texte intégral"; formats TEF + Dublin Core enrichi [^8^]
- **DOI/Handle support:** IdRef ARKs for persons/orgs; theses have persistent theses.fr IDs
- **Bulk metadata harvesting:** Yes — OAI-PMH + **annual full dump on data.gouv.fr** (JSON/NDJSON/CSV) [^8^][^9^]
- **Bulk download capability:** Metadata yes; full text via linked repositories (HAL etc.)
- **Rate limits:** Not published (be polite; dumps exist to avoid hammering API)
- **Authentication requirements:** None
- **Licensing restrictions:** **Licence Ouverte / Open Licence Etalab 2.0** — "récupération et la réutilisation des données est libre et gratuite sous réserve de l'indication de leur date de récupération et de la mention de leur source"; retain dcterms:creator/created/modified in XML headers [^8^]
- **Terms of use:** Etalab licence per dataset
- **TDM permissions:** Explicitly open (metadata); full texts per source licence
- **Copyright concerns:** Low for metadata; author copyright on texts
- **Preferred acquisition method:** data.gouv.fr annual dump → OAI-PMH STAR incremental updates (discipline set ~"Sciences"/biology) → resolve full-text links
- **Botanical/orchid relevance:** High — INRAE, MNHN (Muséum), Montpellier (top-10 world plant science), IRD tropical botany
- **Confidence:** High [^8^][^9^][^10^]

#### 3. DNB — Deutsche Nationalbibliothek / DissOnline
- **Name:** DNB dissertation catalogue (Katalog der Deutschen Nationalbibliothek; "DissOnline" portal for online dissertations)
- **Organization:** Deutsche Nationalbibliothek
- **Geographic coverage:** Germany (all universities; mandatory deposit of e-dissertations)
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** Millions of records overall; online dissertations ~200k+ full texts (exact unknown)
- **Open access vs restricted:** Metadata free; full text OA where deposited electronically with OA consent
- **Metadata availability:** MARC21/MARCXML/RDF via interfaces; GND subject indexing (CC0) [^13^]
- **Full-text availability:** Yes for DissOnline deposits (PDF)
- **API availability:** SRU (`services.dnb.de/sru/`) + RDF/LOD; no key needed
- **OAI-PMH support:** **Yes — probe-verified live 2026-07-21** (`https://services.dnb.de/oai/repository?verb=Identify` → OAI-PMH v2.0.11, earliest datestamp 1945); dedicated **"Hochschulschriften" setSpec hierarchy** confirmed via ListSets [^11^]
- **DOI/Handle support:** URN (NBN) resolver urn:nbn:de; persistent d-nb.info IDs
- **Bulk metadata harvesting:** Yes — OAI-PMH sets, no registration, free [^12^]
- **Bulk download capability:** Metadata yes; full text per record rights (many OA PDFs crawlable)
- **Rate limits:** Not published for OAI; fair-use
- **Authentication requirements:** None for OAI/SRU
- **Licensing restrictions:** Catalogue metadata usable freely (DNB data services); GND CC0 [^13^]
- **Terms of use:** DNB free interfaces policy ("free without registration")
- **TDM permissions:** Metadata yes; full text case-by-case
- **Copyright concerns:** German dissertation copyright strict; many university-server PDFs OA
- **Preferred acquisition method:** OAI-PMH Hochschulschriften sets (incremental, dated) → d-nb.info links → university publication-server PDFs
- **Botanical/orchid relevance:** High — Bonn, Hohenheim, Kassel (organic ag), Munich, Göttingen, BGBM Freie Universität Berlin
- **Confidence:** High (live probe + official docs)

#### 4. DART-Europe (CLOSED)
- **Name:** DART-Europe E-theses Portal
- **Organization:** LIBER-hosted partnership of European libraries/consortia
- **Geographic coverage:** Europe (~28 countries, 600+ institutions at peak)
- **Subject coverage:** All disciplines (research theses)
- **Approx. dissertation count:** ~1.6M records at peak (estimate; portal described itself as largest European index)
- **Status:** **Permanently closed 3 February 2025** [^7^]
- All other fields: N/A — service terminated. Historical OAI-PMH aggregation role ends; DART metadata set survives inside partners (e.g., EADD exposes a `dart` set for backward compatibility) [^40^]
- **Preferred acquisition method:** Replace with direct national harvests (theses.fr, DNB, EADD, Swepub, RCAAP, institutional)
- **Botanical/orchid relevance:** Was high as aggregator; now none directly
- **Confidence:** High [^7^]

#### 5. Netherlands — NARCIS (CLOSED) → university repositories
- **Name:** NARCIS (National Academic Research and Collaborations Information System) — closed; successors: Netherlands Research Portal (NWO) + institutional repositories
- **Organization:** Was DANS/KNAW; now NWO + universities (e.g., Wageningen University & Research Library)
- **Geographic coverage:** Netherlands
- **Approx. dissertation count:** NARCIS held ~1.9M publications incl. 60k+ theses (historical); Dutch university repos individually indexed
- **Open access vs restricted:** Dutch theses overwhelmingly OA via university repositories (DARE tradition)
- **Metadata availability:** NARCIS snapshot published CC0 before closure; live metadata per repository (OAI-PMH: Wageningen `library.wur.nl/oai`, etc.) [^33^][^34^]
- **Full-text availability:** Yes, per repository
- **API availability:** Netherlands Research Portal based on CRIS data; institutional OAI-PMH
- **OAI-PMH support:** Yes at institutional level (all major Dutch repos)
- **DOI/Handle support:** Handles/DOIs per repository (WUR uses DOIs)
- **Bulk metadata harvesting:** Institutional OAI-PMH
- **Bulk download capability:** Yes for OA PDFs
- **Rate limits / Auth:** None standard
- **Licensing / ToU / TDM / Copyright:** Repository-specific; Dutch copyright TDM exception for research applies
- **Preferred acquisition method:** OAI-PMH from WUR + Leiden + Utrecht + UvA + VU + RUG; national portal for discovery
- **Botanical/orchid relevance:** **Very high — Wageningen is world #1 in plant/agricultural sciences**; Naturalis/Leiden orchid systematics
- **Confidence:** High on NARCIS closure; medium on current national-portal specifics [^33^][^34^][^35^]

#### 6. Sweden — DiVA + Swepub
- **Name:** DiVA portal (institutional) / Swepub (national aggregator)
- **Organization:** DiVA consortium (~50 HEIs, e.g. SLU, Uppsala, Stockholm); Swepub run by Kungliga biblioteket (National Library)
- **Geographic coverage:** Sweden
- **Subject coverage:** All disciplines (doctoral + licentiate + master's)
- **Approx. dissertation count:** DiVA union catalogue 460k+ records (30 institutions cited); Swepub ~1M+ records total
- **Open access vs restricted:** Mostly OA full text (strong Swedish OA norms)
- **Metadata availability:** MODS/ETDMS/oai_dc/MARC21 via OAI; Swepub normalized MODS [^29^][^30^]
- **Full-text availability:** Yes, majority
- **API availability:** Swepub open REST APIs (JSON) + SRU; DiVA per-institution search [^30^][^31^]
- **OAI-PMH support:** Yes — Swepub OAI-PMH (`swepub.kb.se`) + per-institution DiVA endpoints (pattern `*.diva-portal.org/dice/oai`) [^29^][^30^]
- **DOI/Handle support:** DiVA persistent URNs (URN:NBN:se); SLU and others mint DOIs
- **Bulk metadata harvesting:** Yes — Swepub OAI-PMH/dumps, explicitly for free reuse [^30^]
- **Bulk download capability:** OA PDFs crawlable
- **Rate limits:** Not published
- **Authentication requirements:** None
- **Licensing restrictions:** Swepub metadata open; full-text © authors (many CC)
- **Terms of use / TDM:** KB open-data policy; Swedish TDM exception
- **Copyright concerns:** Low for metadata; standard for texts
- **Preferred acquisition method:** Swepub OAI-PMH filtered by subject/classification → DiVA/SRep links for PDFs
- **Botanical/orchid relevance:** **Very high — SLU (Swedish University of Agricultural Sciences), Uppsala (Linnaeus), Gothenburg (Naturhistoriska), Stockholm**; strong orchid/flora tradition
- **Confidence:** High [^29^][^30^][^31^][^32^]

#### 7. Norway — NVA (Nasjonalt vitenarkiv)
- **Name:** NVA — Norwegian Research Information Archive (launched 2025)
- **Organization:** Sikt (Norwegian Agency for Shared Services in Education and Research)
- **Geographic coverage:** Norway (all HEIs + research institutes)
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** Unknown (absorbs Cristin + Brage content, incl. NTNU/UiO/UiB/NMBU theses)
- **Open access vs restricted:** Metadata open; full text where deposited OA
- **Metadata availability:** Public REST API + web search [^25^]
- **Full-text availability:** Partial OA
- **API availability:** **Yes — `https://api.nva.unit.no` probe-verified responding 2026-07-21** (JSON; UUID-keyed resources; documented on GitHub Sikt/no/Unit) [^28^]
- **OAI-PMH support:** Unknown/legacy (Brage endpoints being retired end-2025 as institutions migrate) [^26^][^27^]
- **DOI/Handle support:** Handles inherited from Brage; DOIs via Cristin era
- **Bulk metadata harvesting:** Via API (paged search); bulk dump availability unknown
- **Bulk download capability:** OA files linked in API records
- **Rate limits:** Undocumented
- **Authentication requirements:** Read access none
- **Licensing restrictions:** Norwegian open research-data policy; metadata free
- **Terms of use / TDM / Copyright:** Standard institutional; check NVA terms
- **Preferred acquisition method:** NVA REST API queries (category=Degree/Doctoral thesis + subject filter)
- **Botanical/orchid relevance:** High — NMBU (Norwegian University of Life Sciences, Ås), NTNU, UiO (Natural History Museum), UiT Arctic flora
- **Confidence:** Medium-High (very new system; 2025 sources) [^25^][^26^][^27^]

#### 8. Finland — Helda / Theseus / Finna
- **Name:** Helda (U. Helsinki, exemplar); Theseus (universities of applied sciences joint repo); Finna.fi national discovery API
- **Organization:** University of Helsinki; Arene ry (Theseus); National Library of Finland (Finna)
- **Geographic coverage:** Finland
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** Helda tens of thousands incl. ~1,500+ dissertations; Theseus 200k+ (mostly UAS bachelor's/master's)
- **Open access vs restricted:** Mostly OA
- **Metadata availability:** DSpace 7 metadata; Finna normalized [^73^][^74^]
- **Full-text availability:** Yes, majority
- **API availability:** DSpace 7 REST (helda.helsinki.fi/server/api); **Finna public REST API (api.finna.fi/v1)** across Finnish repos
- **OAI-PMH support:** Yes — Helda `helda.helsinki.fi/server/oai/request` (documented); Theseus DSpace OAI [^24^]
- **DOI/Handle support:** Handles + URN:NBN:fi; dissertations get ISBNs
- **Bulk metadata harvesting:** Yes (OAI-PMH / Finna API)
- **Bulk download capability:** OA PDFs
- **Rate limits / Auth:** None standard
- **Licensing / ToU / TDM / Copyright:** Per repository; many CC
- **Preferred acquisition method:** Helda + Aalto + Turku + Oulu + Jyväskylä + Luke (Natural Resources Institute) via OAI-PMH; Finna API for union discovery
- **Botanical/orchid relevance:** High — Helsinki (botanics, LUOMUS), Turku (biodiversity), Luke
- **Confidence:** Medium-High [^23^][^24^]

#### 9. Denmark — Forskningsportalen.dk / institutional repos
- **Name:** Danish National Research Database via forskningsportalen.dk; institutional repos (KU, AU, DTU, AAU)
- **Organization:** DEFF/Universities Denmark (DDFO pool)
- **Geographic coverage:** Denmark
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** Unknown (PhD theses registered in national CRIS pool; Aarhus/KU repos individually tens of thousands)
- **Open access vs restricted:** Mixed; PhD theses usually OA in institutional repos
- **Metadata availability:** National portal search; Pure (Elsevier CRIS) backends
- **Full-text availability:** Institutional repos
- **API availability:** Portal undocumented; Pure portals have no standard public API (OAI on some DSpace repos, e.g., DTU Orbit limited)
- **OAI-PMH support:** Partial (repository-dependent)
- **DOI/Handle support:** DOIs via DataCite for some
- **Bulk metadata harvesting:** Limited — mark unknown
- **Bulk download capability:** Per repository
- **Rate limits / Auth:** N/A
- **Licensing / ToU / TDM / Copyright:** Institutional
- **Preferred acquisition method:** Harvest KU/AU/DTU repositories directly; use OpenAlex as discovery overlay for Danish PhDs
- **Botanical/orchid relevance:** High — Copenhagen (Naturmuseet, plant sciences), Aarhus (agroecology, Flakkebjerg), DTU
- **Confidence:** Medium (fragmented landscape)

#### 10. Switzerland — institutional repositories + swissbib/swisscovery
- **Name:** No national ETD service; key repos: ZORA (Zurich), BORIS (Bern), Infoscience (EPFL), edoc (Basel), Archive ouverte UNIGE
- **Organization:** Universities; swissbib/swisscovery (SLSP) as union catalogue
- **Geographic coverage:** Switzerland
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** Unknown nationally; ZORA alone 100k+ items
- **Open access vs restricted:** Mostly OA (SNSF OA mandate)
- **Metadata availability:** Per repository; swissbib API (SRU/JSON-API)
- **Full-text availability:** Yes, majority
- **API availability:** swissbib linked-data API; DSpace/EPrints REST per repo [^85^]
- **OAI-PMH support:** Yes at major repos (ZORA, BORIS, Infoscience)
- **DOI/Handle support:** Yes (DataCite via ETH; handles)
- **Bulk metadata harvesting:** OAI-PMH per repo
- **Bulk download capability:** OA PDFs
- **Rate limits / Auth:** None standard
- **Licensing / ToU / TDM / Copyright:** Institutional; SNSF encourages CC-BY
- **Preferred acquisition method:** OAI-PMH from ZORA/BORIS/Infoscience/Basel/Geneva + ETH Research Collection (Zurich)
- **Botanical/orchid relevance:** High — ETH Zurich, Zürich Botanic Garden, Geneva (Conservatoire et Jardin botaniques — world-class herbarium), Bern
- **Confidence:** Medium [^85^][^86^]

#### 11. Spain — TDR, TESEO, RECOLECTA
- **Name:** TDR (Tesis Doctorals en Xarxa); TESEO (Ministry of Universities DB); RECOLECTA (national OAI aggregator, FECYT)
- **Organization:** CSUC (TDR, Catalonia); Ministerio de Ciencia, Innovación y Universidades (TESEO); FECYT (RECOLECTA)
- **Geographic coverage:** TDR = Catalonia (+Balearic); TESEO/RECOLECTA = Spain
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** TDR ~30k+ full texts; TESEO 300k+ bibliographic records since 1976 [^43^][^44^]
- **Open access vs restricted:** TDR mostly OA; TESEO metadata-only, free search; RECOLECTA open
- **Metadata availability:** TDR rich DSpace metadata; TESEO bibliographic (author, director, university, year, summary) [^44^][^45^]
- **Full-text availability:** TDR yes; TESEO none (by design); RECOLECTA links out
- **API availability:** TDR DSpace REST/OAI; TESEO none official (community scrapers/dumps exist) [^45^]
- **OAI-PMH support:** TDR yes (DSpace OAI; note: `tdx.cat` OAI path did not respond to probe — verify `/oai/request` vs DSpace-7 `/server/oai/request` at harvest time); RECOLECTA harvests national repos via OAI-PMH
- **DOI/Handle support:** TDR handles (hdl.handle.net/10803/…)
- **Bulk metadata harvesting:** TDR OAI; TESEO — no (scraping tolerated historically; a community full dump circulated) [^45^]
- **Bulk download capability:** TDR OA PDFs
- **Rate limits / Auth:** TDR none; TESEO free search UI only
- **Licensing / ToU / TDM / Copyright:** TDR per-record CC; TESEO records © Ministry
- **Preferred acquisition method:** TDR OAI-PMH (Catalonia) + RECOLECTA harvest of ~50 Spanish university repos (DIGIBIB) + TESEO for discovery/backfile
- **Botanical/orchid relevance:** High — U. Barcelona, UAB (CREAF), Real Jardín Botánico (CSIC, Madrid theses via e-prints Complutense/CSIC Digital), Córdoba (agronomy)
- **Confidence:** High for TDR/TESEO roles; Medium on TDR OAI path [^43^][^44^][^45^]

#### 12. Portugal — RCAAP
- **Name:** RCAAP — Repositório Científico de Acesso Aberto de Portugal
- **Organization:** FCCN/FCT (Fundação para a Ciência e a Tecnologia)
- **Geographic coverage:** Portugal (all universities + polytechnics)
- **Subject coverage:** All disciplines (strong ETD emphasis)
- **Approx. dissertation count:** 1M+ documents total; hundreds of thousands of theses/dissertations [^46^][^47^]
- **Open access vs restricted:** Open access aggregator
- **Metadata availability:** Yes — central, normalized
- **Full-text availability:** Links + many hosted copies
- **API availability:** **Yes — public REST API with OpenAPI documentation (JSON/XML)** [^46^]
- **OAI-PMH support:** Yes (XOAI; also exposes OpenAIRE 4 driver set) [^46^]
- **DOI/Handle support:** Handles per record; some DOIs
- **Bulk metadata harvesting:** Yes — OAI-PMH + API, no auth [^46^]
- **Bulk download capability:** OA PDFs via links
- **Rate limits:** Not published
- **Authentication requirements:** None for metadata
- **Licensing restrictions:** Open-access mandate (FCT policy); per-record licences
- **Terms of use / TDM / Copyright:** Open-data friendly; author copyright on texts
- **Preferred acquisition method:** OAI-PMH full harvest, filter type=doctoral/master's + subject
- **Botanical/orchid relevance:** Medium-High — U. Lisbon (FCUL, cE3c), U. Porto, U. Coimbra (historic botanic garden), UTAD, Azores/Madeira flora
- **Confidence:** High [^46^][^47^]

#### 13. Italy — tesidottorato.depositolegale.it + IRIS federated repos
- **Name:** National doctoral-thesis legal-deposit platform; IRIS/institutional repositories (e.g., AIR Milan, IRIS-Unimore, BOA)
- **Organization:** National Central Libraries of Florence & Rome (BNCF/BNCR) + Cineca (IRIS) + universities
- **Geographic coverage:** Italy
- **Subject coverage:** All disciplines (doctoral theses, post-1980s onward)
- **Approx. dissertation count:** 200k+ theses expected in legal-deposit corpus (exact unknown)
- **Open access vs restricted:** Metadata open; full text mirrors university-repository policy (OA majority; embargo max 36 months) [^36^][^37^]
- **Metadata availability:** Via university IRIS OAI-PMH; national catalogue
- **Full-text availability:** Where universities deposit OA
- **API availability:** Per-ateneo IRIS OAI-PMH endpoints documented; national platform API unknown [^38^][^83^][^84^]
- **OAI-PMH support:** Yes — IRIS instances expose OAI-PMH [^84^]
- **DOI/Handle support:** **NBN URN persistent identifiers (URN:NBN:it)** assigned at legal deposit [^36^][^37^]
- **Bulk metadata harvesting:** Per-university OAI-PMH
- **Bulk download capability:** OA subset
- **Rate limits / Auth:** None standard
- **Licensing restrictions:** From Oct 2025 CC-licence selection in deposit workflow [^36^]
- **Terms of use / TDM / Copyright:** Legal-deposit framework; author copyright
- **Preferred acquisition method:** Harvest top IRIS OAI endpoints (Sapienza, Bologna, Padova, Milan, Pisa, Florence) + monitor national platform API maturation
- **Botanical/orchid relevance:** High — Padova (oldest botanic garden, 1545), Florence (tropical herbarium), Sapienza, Bologna
- **Confidence:** High (2022–2025 technical report + official BNCF) [^36^][^37^][^38^]

#### 14. Poland — POL-on / CRPD + institutional repos
- **Name:** POL-on (Integrated System of Information on Science and Higher Education) incl. Central Repository for Diploma Theses (CRPD); Polish Science Database (archiwum.nauka-polska.pl) legacy
- **Organization:** OPI PIB (National Information Processing Institute), Ministry of Science
- **Geographic coverage:** Poland
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** Unknown publicly; thesis deposit mandated since Oct 2014 [^38^]
- **Open access vs restricted:** Registry/repository hybrid; OA practices vary by institution; many theses visible only as metadata [^39^]
- **Metadata availability:** National registry; API exists (polon.nauka.gov.pl, registration required)
- **Full-text availability:** Partial
- **API availability:** POL-on REST API (documented, requires institutional/registered access)
- **OAI-PMH support:** Institutional repos yes (many DSpace); national — no public OAI
- **DOI/Handle support:** Some DataCite DOIs
- **Bulk metadata harvesting:** Restricted via API registration
- **Bulk download capability:** Limited
- **Rate limits:** Undocumented
- **Authentication requirements:** Yes for API
- **Licensing / ToU / TDM / Copyright:** Government system; restrictive reuse
- **Preferred acquisition method:** Institutional OAI-PMH (Jagiellonian, Warsaw, UAM Poznań, Wrocław) + OpenAlex overlay; POL-on API if partnership obtained
- **Botanical/orchid relevance:** High — Warsaw (botanic garden), Jagiellonian, Wrocław (flora of Sudety), Poznań
- **Confidence:** Medium [^38^][^39^][^72^]

#### 15. Czech Republic — theses.cz / SKC
- **Name:** Theses.cz (national thesis register) + Souborný katalog ČR (SKC, union catalogue, National Library); university repos (e.g., MUNI, ČZU Prague)
- **Organization:** AURES Holdings (theses.cz, with universities) / Národní knihovna ČR (SKC)
- **Geographic coverage:** Czech Republic
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** Unknown (theses.cz covers defended theses nationally for plagiarism-check interop)
- **Open access vs restricted:** theses.cz is primarily a register/similarity system; full texts mostly in institutional repos (DSpace)
- **Metadata availability:** Register search; SKC catalogue records (dissertation format flag)
- **Full-text availability:** Institutional repos (OA where law permits — Czech theses are public by law but "consultation" not redistribution)
- **API availability:** None public documented
- **OAI-PMH support:** Institutional repos yes (DSpace: MUNI, ČZU, UK Prague)
- **DOI/Handle support:** Handles
- **Bulk metadata harvesting:** Institutional OAI only
- **Bulk download capability:** Restricted (Czech legal regime: on-site/consultation use)
- **Rate limits / Auth:** N/A
- **Licensing / ToU / TDM / Copyright:** **Notable copyright concern — Czech theses legally public for study but republication restricted**
- **Preferred acquisition method:** Institutional OAI-PMH metadata; negotiate full-text access for research TDM
- **Botanical/orchid relevance:** Medium-High — ČZU (Czech University of Life Sciences), Mendel University Brno, Charles University, Průhonice (IBOT CAS)
- **Confidence:** Low-Medium (sparse English documentation)

#### 16. Greece — EADD (National Archive of PhD Theses)
- **Name:** Εθνικό Αρχείο Διδακτορικών Διατριβών (EADD) — didaktorika.gr
- **Organization:** EKT/NHRF (National Documentation Centre, National Hellenic Research Foundation)
- **Geographic coverage:** Greece (all universities; deposit mandatory for public employment recognition)
- **Subject coverage:** All disciplines (doctoral only)
- **Approx. dissertation count:** 43,000+ theses (official) [^41^]
- **Open access vs restricted:** OA majority; some restricted full text
- **Metadata availability:** Full, Greek + English fields [^40^]
- **Full-text availability:** PDFs for OA subset
- **API availability:** No REST API documented
- **OAI-PMH support:** **Yes — probe-verified live 2026-07-21** (`https://www.didaktorika.gr/eadd-oai/request` → "National Archive of PhD theses", protocol 2.0); documented sets: `dart`, `hdl_10442_2` (full-text OA), voa3r; formats oai_dc, hedi, unimarc, mods [^40^][^42^]
- **DOI/Handle support:** EKT handles (hdl.handle.net/10442)
- **Bulk metadata harvesting:** Yes via OAI-PMH
- **Bulk download capability:** OA set PDFs
- **Rate limits:** None published
- **Authentication requirements:** None
- **Licensing restrictions:** Open-data page; metadata freely harvestable [^40^]
- **Terms of use / TDM / Copyright:** Author copyright; OA set intended for reuse
- **Preferred acquisition method:** OAI-PMH `hdl_10442_2` set (full-text OA) + complete metadata set
- **Botanical/orchid relevance:** Medium — U. Athens (botany), Agricultural University of Athens, AUTH; Greek flora endemic-rich
- **Confidence:** High (live probe + official open-data page)

#### 17. India — Shodhganga (INFLIBNET) + KrishiKosh (ICAR)
- **Name:** Shodhganga ("reservoir of Indian theses"); companion services ShodhShuddhi (plagiarism screening — NOT a repository), KrishiKosh/KrishiPrabha (agricultural theses)
- **Organization:** INFLIBNET Centre (UGC inter-university centre), Gandhinagar; KrishiKosh by ICAR-IARI (NARES system)
- **Geographic coverage:** India (universities mandated to deposit e-theses under UGC regulations)
- **Subject coverage:** All disciplines; KrishiKosh = agriculture/veterinary/fisheries/horticulture
- **Approx. dissertation count:** Shodhganga **600,000+ theses (May 2025)**, ~700 contributing universities [^17^][^18^]; KrishiKosh 270k+ items incl. ~180,000 theses [^20^][^21^]
- **Open access vs restricted:** Shodhganga — free web access to full-text PDFs; some theses restricted/embargoed by universities; site unreachable from this research environment (probe 2026-07-21: connection failure — INFLIBNET has previously geo-restricted traffic; verify from India-based egress) [^18^]
- **Metadata availability:** DSpace metadata (title, guide, university, year, subject, abstract) — English
- **Full-text availability:** Yes, majority of deposited records (chapter-wise PDFs in many)
- **API availability:** No official REST API (DSpace 5-era UI; DSpace 7 migration status unknown)
- **OAI-PMH support:** Yes — DSpace OAI historically at `shodhganga.inflibnet.ac.in/oai/request` (documented in registry literature; probe from this environment failed — needs re-verification) [^34^]
- **DOI/Handle support:** Handles (hdl.handle.net/10603/…)
- **Bulk metadata harvesting:** OAI-PMH (when reachable)
- **Bulk download capability:** Web PDF download; no official bulk policy — large-scale crawling likely throttled
- **Rate limits:** Undocumented; aggressive crawling discouraged
- **Authentication requirements:** None for reading
- **Licensing restrictions:** © authors/universities; INFLIBNET claims non-commercial research use
- **Terms of use:** Shodhganga ToU (verify current; "fair use for research" framing)
- **TDM permissions:** Not explicitly granted — legal grey zone; seek INFLIBNET partnership for TDM at scale
- **Copyright concerns:** High for redistribution; metadata harvesting low-risk
- **Preferred acquisition method:** OAI-PMH metadata harvest (from India-accessible IP) → selective PDF fetch of botany departments → KrishiKosh OAI-PMH for agricultural theses
- **Botanical/orchid relevance:** **Exceptional — India is an orchid megadiversity hotspot (NE Himalaya, Western Ghats); hundreds of orchid taxonomy/conservation/horticulture theses; IARI, TNAU, UAS Bangalore, NEHU, Punjab Agricultural U.**
- **Confidence:** High on counts/architecture; Medium on current access/terms (site unreachable from test environment) [^17^][^18^][^19^][^20^]

#### 18. China — CNKI CDMD / Wanfang / CALIS
- **Name:** CNKI China Doctoral Dissertations Full-text Database (CDMD) + China Master's Theses (CMFD); Wanfang Dissertations; CALIS ETD union catalogue
- **Organization:** CNKI (Tongfang Knowledge Network); Wanfang Data (Institute of Scientific & Technical Information of China); CALIS (academic library consortium)
- **Geographic coverage:** China (PRC), incl. top universities
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** CDMD 500k+ doctoral dissertations; CMFD 5M+ master's; Wanfang millions [^22^]
- **Open access vs restricted:** **Restricted/commercial** — subscription or pay-per-view
- **Metadata availability:** Via CNKI/Wanfang search UIs; East View resells Western-institutional access
- **Full-text availability:** Subscribers only
- **API availability:** No open API (CNKI has licensed data services for partners)
- **OAI-PMH support:** No
- **DOI/Handle support:** No DOIs historically (CNKI internal IDs)
- **Bulk metadata harvesting:** Not openly; licensed feeds only
- **Bulk download capability:** None legally without licence
- **Rate limits / Auth:** Account + licence; strict anti-crawl enforcement
- **Licensing restrictions:** Commercial database licence
- **Terms of use:** Subscription agreement; **cross-border data-security law impacts**
- **TDM permissions:** Only via negotiated licence (East View/CNKI agreements)
- **Copyright concerns:** **High — CNKI's cross-border institutional service suspended April 2023** after Chinese regulatory review of data exports; multiple foreign universities (e.g., Kyoto, Korea U) reported service suspension; restoration partial/opaque [^23^][^24^]
- **Preferred acquisition method:** Metadata discovery via OpenAlex (which indexes CNKI records) + licensed reseller route for priority full texts; institutional repos of top ag universities (CAU, Nanjing Ag, Zhejiang) as OA supplement
- **Botanical/orchid relevance:** **Very high — China has ~1,700 orchid species and massive horticulture/systematics output** (CAAS, Kunming Institute of Botany, South China Botanical Garden) — but access is the bottleneck
- **Confidence:** High on restrictions; Medium on current reseller terms [^22^][^23^][^24^]

#### 19. Taiwan — NDLTD Taiwan (National Central Library)
- **Name:** 臺灣博碩士論文知識加值系統 (National Digital Library of Theses and Dissertations in Taiwan) — ndltd.ncl.edu.tw
- **Organization:** National Central Library (NCL), Taiwan
- **Geographic coverage:** Taiwan (all universities; deposit mandated)
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** 1M+ records claimed by NCL (exact unknown)
- **Open access vs restricted:** Metadata free; full text only where author granted e-publication permission (large OA subset; others abstract-only or campus-restricted)
- **Metadata availability:** Bilingual (zh/en) rich metadata
- **Full-text availability:** OA subset (author-permission model)
- **API availability:** None documented publicly
- **OAI-PMH support:** Not documented (NCL has internal exchange systems)
- **DOI/Handle support:** NCL persistent IDs
- **Bulk metadata harvesting:** Not officially; discovery via web UI
- **Bulk download capability:** OA PDFs individually
- **Rate limits / Auth:** Reading free; downloads of OA files no login (some features require account)
- **Licensing / ToU / TDM / Copyright:** Author-permission framework; TDM not addressed
- **Preferred acquisition method:** Web discovery + OA PDF fetch; complement with OpenAlex/NDLTD Global ETD Search
- **Botanical/orchid relevance:** **High — Taiwan is a global orchid-breeding/research center (Tainan orchid industry, NCHU, NTU horticulture)**
- **Confidence:** Medium [^58^]

#### 20. Japan — CiNii Dissertations / IRDB / NDL
- **Name:** CiNii Dissertations (ci.nii.ac.jp/d); IRDB (Institutional Repositories DataBase, WEKO3-based national aggregator, successor to JAIRO); NDL Search (National Diet Library)
- **Organization:** NII (National Institute of Informatics); NDL
- **Geographic coverage:** Japan
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** CiNii Dissertations ~600k+ records (from ~2015 launch, aggregating university repos + NDL); IRDB 1M+ items overall [^68^]
- **Open access vs restricted:** Mixed; Japanese university repos provide OA for many 博士論文 (doctoral theses); NDL digitized-dissertation access is restricted to NDL/partner-library terminals for post-2013 deposits
- **Metadata availability:** CiNii JSON API exists for articles/books; dissertations searchable via CiNii Research (SPARQL + API endpoints documented for CiNii Research)
- **Full-text availability:** Via linked institutional repositories
- **API availability:** CiNii Research API (OpenSearch-style, free); IRDB OAI-PMH (WEKO3 exposes OAI per repository)
- **OAI-PMH support:** Yes at IRDB/WEKO3 repositories (per-institution base URLs)
- **DOI/Handle support:** JaLC DOIs increasingly assigned; handles common
- **Bulk metadata harvesting:** CiNii API + IRDB OAI-PMH
- **Bulk download capability:** OA subset
- **Rate limits:** CiNii API requires free AppID historically; modest limits
- **Authentication requirements:** Free API ID for CiNii
- **Licensing / ToU / TDM / Copyright:** Metadata reusable (NII open policy); Japanese TDM exception (Art. 30-4) is one of world's most permissive — favorable legal context
- **Preferred acquisition method:** CiNii Dissertations API/metadata → resolve university-repo links → harvest OA PDFs (WEKO3 OAI where available)
- **Botanical/orchid relevance:** High — U. Tokyo, Kyoto, Tohoku, Tsukuba (agriculture), Makino herbarium (Kochi)
- **Confidence:** Medium-High [^53^]

#### 21. South Korea — RISS / dCollection (KERIS)
- **Name:** RISS (Research Information Sharing Service) — riss.kr; dCollection institutional ETD system
- **Organization:** KERIS (Korea Education and Research Information Service), Ministry of Education
- **Geographic coverage:** South Korea (all universities; dCollection auto-deposits into RISS)
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** **~2.29 million theses/dissertations** [^48^]
- **Open access vs restricted:** Metadata + full text free for most records (view/download); some publisher-embargoed
- **Metadata availability:** Rich, Korean + some English
- **Full-text availability:** Yes, majority (free per About page) [^48^]
- **API availability:** No public bulk API documented; LOD pilot published [^49^]
- **OAI-PMH support:** Not public
- **DOI/Handle support:** **DOIs assigned to theses since 2021 via Korea DOI Center/KERIS** [^50^]
- **Bulk metadata harvesting:** Not officially — would require KERIS agreement
- **Bulk download capability:** Individual PDF downloads; bulk prohibited
- **Rate limits:** Enforced anti-scraping (login/captcha walls on heavy use)
- **Authentication requirements:** Free; some downloads need account
- **Licensing / ToU / TDM / Copyright:** KERIS ToU restricts systematic download; copyright with authors/universities
- **Preferred acquisition method:** Partnership/API request to KERIS; otherwise discovery via RISS + targeted institutional dCollection harvesting (some dCollection instances expose OAI)
- **Botanical/orchid relevance:** High — Seoul National, Korea U, Kangwon (forest science); Korean orchid flora (Cymbidium, Habenaria)
- **Confidence:** High on scale/model; Medium on technical paths [^48^][^49^][^50^]

#### 22. Australia — Trove (NLA)
- **Name:** Trove (theses within "Books & Libraries" + "Research & Reports" categories)
- **Organization:** National Library of Australia
- **Geographic coverage:** Australia (aggregates all university repositories)
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** Unknown precisely; hundreds of thousands of thesis records (format=Thesis)
- **Open access vs restricted:** Metadata free; full text via source repositories (mostly OA)
- **Metadata availability:** Via Trove API v3 (JSON/XML) [^51^]
- **Full-text availability:** Indirect (links to university repos)
- **API availability:** **Yes — Trove API v3, free API key required** (`api.trove.nla.gov.au/v3/result?category=…&l-format=Thesis`) [^51^][^52^]
- **OAI-PMH support:** No (API only)
- **DOI/Handle support:** Trove work IDs; links to institutional DOIs/handles
- **Bulk metadata harvesting:** API paging; GLAM Workbench provides harvest notebooks [^52^]
- **Bulk download capability:** Not from Trove; fetch PDFs from source repos
- **Rate limits:** Documented per-key quotas (recheck current tier)
- **Authentication requirements:** API key (free registration)
- **Licensing restrictions:** Trove metadata reusable (CC-friendly); source PDFs per institution
- **Terms of use:** Trove API terms; **access tightened 2024–25 — NLA cancelled some long-standing research keys (GLAM Workbench case); new approval workflow** [^53^]
- **TDM permissions:** Metadata fine; full-text TDM at source repos
- **Copyright concerns:** Low for metadata
- **Preferred acquisition method:** Trove API v3 (l-format=Thesis + keyword/subject facets) → de-duplicate → harvest university repos (many DSpace/EPrints/Figshare OAI endpoints)
- **Botanical/orchid relevance:** **Very high — Australia's terrestrial orchid flora is enormous; ANU, UQ, UWA, Adelaide, La Trobe; Royal Botanic Gardens Kew/Sydney/Melbourne links**
- **Confidence:** High [^51^][^52^][^53^]

#### 23. New Zealand — institutional repositories + DigitalNZ
- **Name:** NZresearch.org (retired September 2023); successor discovery via DigitalNZ (nzresearch collection); key repos: ResearchSpace@Auckland, OUR Archive (Otago), UC, Massey, Waikato, Lincoln
- **Organization:** Was National Library of NZ; now DigitalNZ (NLNZ) + universities
- **Geographic coverage:** New Zealand
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** Unknown; ~100k+ theses across NZ repos
- **Open access vs restricted:** Mostly OA
- **Metadata availability:** **DigitalNZ public API (api.digitalnz.org/v3, free key)** includes harvested NZresearch records [^22^]
- **Full-text availability:** Institutional repos
- **API availability:** DigitalNZ API; institutional DSpace/EPrints APIs
- **OAI-PMH support:** Institutional repos yes
- **DOI/Handle support:** Handles; some DOIs
- **Bulk metadata harvesting:** DigitalNZ API + institutional OAI
- **Bulk download capability:** OA PDFs
- **Rate limits / Auth:** DigitalNZ free key
- **Licensing / ToU / TDM / Copyright:** DigitalNZ metadata CC; texts per institution
- **Preferred acquisition method:** DigitalNZ API (content_partner filter) + Lincoln/Massey/Otago OAI-PMH
- **Botanical/orchid relevance:** High — Lincoln University (agriculture), Massey, Otago (southern NZ orchids, Corybas etc.), Landcare Research links
- **Confidence:** Medium-High [^75^]

#### 24. Brazil — BDTD (IBICT) + CAPES Catalogue
- **Name:** BDTD — Biblioteca Digital Brasileira de Teses e Dissertações; Catálogo de Teses e Dissertações (CAPES); institutional repos (USP, UNICAMP, UFRGS…)
- **Organization:** IBICT (Instituto Brasileiro de Informação em Ciência e Tecnologia); CAPES (Ministry of Education)
- **Geographic coverage:** Brazil (100+ institutions federated)
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** BDTD **~900,000 records** [^54^]; CAPES catalogue millions of records (abstracts)
- **Open access vs restricted:** BDTD mostly OA full text; CAPES catalogue abstracts-only
- **Metadata availability:** Central normalized metadata (VuFind interface since Jan 2024) [^54^]
- **Full-text availability:** Yes for OA subset (links + hosted)
- **API availability:** VuFind search API (undocumented); no official REST doc
- **OAI-PMH support:** **Yes — historically `oai.ibict.br` OAI-PMH server (registered in ROAR); new VuFind platform exposes OAI at `bdtd.ibict.br/vufind/OAI/Server` (probe from this environment returned empty — verify at implementation time)** [^55^]
- **DOI/Handle support:** Handles per record
- **Bulk metadata harvesting:** OAI-PMH
- **Bulk download capability:** OA PDFs crawlable from member repos (DSpace)
- **Rate limits / Auth:** None documented
- **Licensing / ToU / TDM / Copyright:** OA policy per Brazilian OA law trend; author copyright
- **Preferred acquisition method:** BDTD OAI-PMH full harvest → filter knowledge area (Ciências Biológicas / Agrárias) → fetch PDFs from USP/UNICAMP/UFV DSpace repos
- **Botanical/orchid relevance:** **Exceptional — Brazil has ~3,500 orchid species; Jardim Botânico do Rio, USP, UNICAMP, UFV, ESALQ; huge orchid taxonomy/ecology output**
- **Confidence:** High [^54^][^55^][^56^]

#### 25. LA Referencia (regional aggregator)
- **Name:** LA Referencia — Red Federada de Repositorios Institucionales de Publicaciones Científicas
- **Organization:** RedCLARA + national science agencies (CONICET, IBICT, CONICYT/ANID, Colciencias/MinCiencias, SENESCYT…)
- **Geographic coverage:** Latin America + Spain/Portugal observers — 10–12 national nodes (Argentina, Brazil, Chile, Colombia, Costa Rica, Ecuador, El Salvador, Mexico, Panama, Peru, Uruguay…) [^15^][^16^]
- **Subject coverage:** All disciplines (theses + articles + research data)
- **Approx. dissertation count:** Unknown precisely (multi-million records network-wide)
- **Open access vs restricted:** OA aggregator (metadata + links)
- **Metadata availability:** Federated harvest of national OAI nodes (DRIVER/OpenAIRE guidelines)
- **Full-text availability:** Links to source repos
- **API availability:** VuFind portal search; no public REST documented
- **OAI-PMH support:** Yes (re-exposes harvested records via OAI-PMH at `lareferencia.info/vufind/oai`) — **BUT probe 2026-07-21: entire lareferencia.info sits behind "Anubis" anti-bot proof-of-work; both web UI and OAI endpoint currently block automated clients** [^14^]
- **DOI/Handle support:** Handles preserved
- **Bulk metadata harvesting:** Blocked at present (Anubis); national nodes individually harvestable
- **Bulk download capability:** Via sources
- **Rate limits / Auth:** N/A while Anubis active
- **Licensing / ToU / TDM / Copyright:** Metadata intended open (DRIVER); source texts per institution
- **Preferred acquisition method:** **Bypass: harvest national nodes directly** — Argentina SNRD (`repositoriosdigitales.mincyt.gob.ar` OAI), Brazil BDTD OAI, Chile/Colombia/Mexico nodes; revisit LA Referencia after contacting RedCLARA for harvester whitelisting
- **Botanical/orchid relevance:** **Very high — Neotropical orchid diversity; Colombia (~4,270 spp.), Ecuador (~4,000 spp.), Peru, Costa Rica (Lankester garden), Mexico**
- **Confidence:** High on architecture/blockage; Low on current record counts [^14^][^15^][^16^]

#### 26. Mexico — TESIUNAM / RI-UNAM + CONAHCYT nodes
- **Name:** TESIUNAM (now integrated into RI-UNAM, repositorio.unam.mx); CONAHCYT national repository network
- **Organization:** UNAM (DGB); CONAHCYT
- **Geographic coverage:** UNAM (TESIUNAM) / Mexico (CONAHCYT network)
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** TESIUNAM 500k+ registered theses; RI-UNAM 2.7M+ resources total [^57^][^58^]
- **Open access vs restricted:** Majority OA full text
- **Metadata availability:** Yes, Spanish (many with English abstracts)
- **Full-text availability:** Yes, large subset (PDFs back to early 20th c.)
- **API availability:** DSpace REST API on repositorio.unam.mx (if DSpace 7)
- **OAI-PMH support:** Yes (DSpace OAI on UNAM repos; e.g., `tesisenlinea.unam.mx` legacy)
- **DOI/Handle support:** Handles
- **Bulk metadata harvesting:** OAI-PMH
- **Bulk download capability:** OA PDFs
- **Rate limits / Auth:** None standard
- **Licensing / ToU / TDM / Copyright:** UNAM open policy; author copyright
- **Preferred acquisition method:** OAI-PMH on RI-UNAM + other Mexican university repos (CINVESTAV, UANL, Colima); Mexico node of LA Referencia
- **Botanical/orchid relevance:** High — UNAM IBUNAM (Jardín Botánico, ~1,100 Mexican orchid spp.), CINVESTAV-Irapuato plant sciences
- **Confidence:** Medium-High [^70^][^71^]

#### 27. South Africa — National ETD Portal (netd.ac.za) + institutional repos
- **Name:** National ETD Portal (netd.ac.za); institutional repositories (UP, UCT, UKZN, Stellenbosch, Wits, UNISA)
- **Organization:** NRF (National Research Foundation) + SABINET heritage + universities
- **Geographic coverage:** South Africa
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** Unknown (union portal across ~26 institutions; UNISA alone 100k+ items)
- **Open access vs restricted:** Strong OA culture (Berlin signatory; Academy of Science SA mandate)
- **Metadata availability:** Portal aggregates via OAI from institutional repos
- **Full-text availability:** Mostly OA
- **API availability:** None documented centrally
- **OAI-PMH support:** Institutional repos (DSpace/EPrints) all expose OAI; portal harvests them [^59^]
- **DOI/Handle support:** Handles
- **Bulk metadata harvesting:** Institutional OAI-PMH
- **Bulk download capability:** OA PDFs
- **Rate limits / Auth:** None standard
- **Licensing / ToU / TDM / Copyright:** Institutional; author copyright
- **Preferred acquisition method:** OAI-PMH from UP (repository.up.ac.za), UKZN, UCT, Stellenbosch (SUNScholar), UNISA; portal for discovery
- **Botanical/orchid relevance:** **Very high — Cape Floristic Region; SANBI-linked theses; Disa/Satyridium orchid research; Pretoria (national herbarium), UKZN, Stellenbosch**
- **Confidence:** Medium-High [^59^]

#### 28. Africa-wide + Kenya/Nigeria — DATAD (AAU) & institutional repos
- **Name:** DATAD — Database of African Theses and Dissertations (Association of African Universities); institutional repos (U. Nairobi, Strathmore, U. Nigeria Nsukka, UI Ibadan…)
- **Organization:** AAU (Accra); DATAD-R current phase
- **Geographic coverage:** Pan-Africa (DATAD); national institutional
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** DATAD ~15–20k records (pilot-university era; growth slow) [^60^][^61^]
- **Open access vs restricted:** DATAD = **subscription**, abstracts/index only (no full text)
- **Metadata availability:** DATAD index; institutional repos provide local metadata
- **Full-text availability:** Institutional repos only (variable uptime)
- **API availability:** None (DATAD); DSpace per institution
- **OAI-PMH support:** Institutional yes; DATAD no
- **DOI/Handle support:** Handles
- **Bulk metadata harvesting:** Institutional OAI
- **Bulk download capability:** Institutional OA PDFs
- **Rate limits / Auth:** DATAD subscription; institutional none
- **Licensing / ToU / TDM / Copyright:** Institutional
- **Preferred acquisition method:** OAI-PMH sweep of Kenyan/Nigerian/Ghanaian university repos (maintenance is spotty — schedule retries); DATAD as discovery index if licensed
- **Botanical/orchid relevance:** Medium-High — U. Nairobi (East African Herbarium), Makerere, Ibadan; tropical orchid conservation theses scattered
- **Confidence:** Medium [^60^][^61^]

#### 29. Turkey — YÖK Ulusal Tez Merkezi
- **Name:** YÖK Ulusal Tez Merkezi (National Thesis Center) — tez.yok.gov.tr
- **Organization:** Council of Higher Education (YÖK), Türkiye
- **Geographic coverage:** Türkiye (all universities; deposit mandatory)
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** 2014 official stats: 189,107 open-access + 160,866 closed theses, 4M+ downloads/yr [^62^]; current total estimated 800k–1M+ (unknown; growth ~50k/yr)
- **Open access vs restricted:** Hybrid — authors choose open/closed (roughly half open historically); embargo options
- **Metadata availability:** Full bibliographic metadata searchable free
- **Full-text availability:** OA subset downloadable (login-free historically; account features exist)
- **API availability:** None public
- **OAI-PMH support:** No
- **DOI/Handle support:** None standard
- **Bulk metadata harvesting:** Not officially supported (no API/OAI) — would require YÖK agreement
- **Bulk download capability:** Individual OA PDFs; bulk not permitted
- **Rate limits:** Enforced (site unreachable from this research environment — possibly geo/IP restrictions)
- **Authentication requirements:** Free registration for some functions
- **Licensing / ToU / TDM / Copyright:** Author-permission model; no TDM provision
- **Preferred acquisition method:** Web discovery; OA PDF fetch with rate discipline; partnership request to YÖK for bulk metadata
- **Botanical/orchid relevance:** Medium-High — Türkiye is an Ophrys/Orchis diversity hotspot; Istanbul, Ankara, Ege, Akdeniz botany departments
- **Confidence:** Medium (older official stats; no machine interface) [^62^]

#### 30. Iran — GANJ (IranDoc)
- **Name:** GANJ (ganj.irandoc.ac.ir) — national theses & dissertations system
- **Organization:** IranDoc (Iranian Research Institute for Information Science and Technology)
- **Geographic coverage:** Iran (deposit mandated nationally)
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** 1.2M+ research documents [^57^]
- **Open access vs restricted:** **Tiered model:** first ~20 pages + bibliography free immediately; full text free after embargo (18 months master's / 30 months doctoral); purchase options [^57^][^58^]
- **Metadata availability:** Full, Persian + English fields
- **Full-text availability:** As above (post-embargo OA)
- **API availability:** None documented
- **OAI-PMH support:** Not documented
- **DOI/Handle support:** IranDoc IDs
- **Bulk metadata harvesting:** Not official
- **Bulk download capability:** Restricted
- **Rate limits / Auth:** Free registration; sanctions-related access issues possible
- **Licensing / ToU / TDM / Copyright:** National ETD framework; TDM unaddressed
- **Preferred acquisition method:** Web search + free pages; partnership for bulk
- **Botanical/orchid relevance:** Medium — Iran flora rich (TARI herbarium); orchid diversity modest (Orchidaceae mostly northern Iran)
- **Confidence:** Medium-High (ETD 2023 conference paper) [^57^][^58^]

#### 31. Israel — institutional repositories
- **Name:** No national ETD service; repos incl. TAU DaTA, Hebrew University (RAMBI/HUJI), Technion, Weizmann, Bar-Ilan
- **Organization:** Universities; MALMAD/IUCC coordination
- **Geographic coverage:** Israel
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** Unknown; tens of thousands across repos
- **Open access vs restricted:** Mostly OA where deposited digitally
- **Metadata availability:** Per repository (Aleph/Primo + DSpace/Figshare)
- **Full-text availability:** OA subset
- **API availability:** Institutional (Ex Libris APIs; Figshare API for some)
- **OAI-PMH support:** Institutional DSpace yes
- **DOI/Handle support:** DOIs/handles institutional
- **Bulk metadata harvesting:** Institutional OAI
- **Bulk download capability:** OA subset
- **Rate limits / Auth:** None standard
- **Licensing / ToU / TDM / Copyright:** Institutional
- **Preferred acquisition method:** Institutional OAI-PMH (HUJI, TAU, Technion, Weizmann); OpenAlex overlay for discovery
- **Botanical/orchid relevance:** Medium — Hebrew U (Jerusalem botanical garden), TAU (Steinhardt Museum), Volcani Center (agriculture)
- **Confidence:** Medium [^63^]

#### 32. Pakistan — HEC Pakistan Research Repository (PRR)
- **Name:** Pakistan Research Repository — prr.hec.gov.pk (formerly hcc.gov.pk/prr)
- **Organization:** Higher Education Commission (HEC), Pakistan
- **Geographic coverage:** Pakistan (PhD theses from HEC-recognized universities; deposit mandated)
- **Subject coverage:** All disciplines
- **Approx. dissertation count:** ~10–20k+ PhD theses (7,000+ as of 2014; grown since) [^64^][^65^]
- **Open access vs restricted:** OA full text for most records (DSpace-based)
- **Metadata availability:** Yes
- **Full-text availability:** Yes, majority
- **API availability:** DSpace REST (version-dependent)
- **OAI-PMH support:** DSpace OAI historically (`/oai/request`)
- **DOI/Handle support:** Handles
- **Bulk metadata harvesting:** OAI-PMH
- **Bulk download capability:** OA PDFs
- **Rate limits / Auth:** None standard
- **Licensing / ToU / TDM / Copyright:** HEC policy; author copyright
- **Preferred acquisition method:** OAI-PMH full harvest (small corpus — trivial)
- **Botanical/orchid relevance:** Medium — Quaid-i-Azam U., Punjab U., PMAS Arid Agriculture; Himalayan orchid flora
- **Confidence:** Medium-High [^64^][^65^]

#### 33. Bangladesh — DAATJ (agricultural theses)
- **Name:** Digital Archive on Agricultural Theses and Journals (DAATJ)
- **Organization:** BARC (Bangladesh Agricultural Research Council) / SAU libraries
- **Geographic coverage:** Bangladesh (agricultural universities)
- **Subject coverage:** Agriculture incl. botany/horticulture
- **Approx. dissertation count:** ~8,700–9,000 theses [^66^][^67^]
- **Open access vs restricted:** OA
- **Metadata availability:** Yes
- **Full-text availability:** Yes
- **API availability:** None documented
- **OAI-PMH support:** DSpace component — likely, unverified
- **DOI/Handle support:** No
- **Bulk metadata harvesting:** Manual/OAI if exposed
- **Bulk download capability:** Yes (small corpus)
- **Rate limits / Auth:** None
- **Licensing / ToU / TDM / Copyright:** BARC policy
- **Preferred acquisition method:** Direct crawl (small)
- **Botanical/orchid relevance:** Medium — horticulture theses; delta flora
- **Confidence:** Medium [^66^][^67^]

---

### Major Players & Sources

| Tier | Player | Role for Calyx |
|---|---|---|
| **A (direct bulk, open)** | theses.fr/ABES; DNB; EADD; RCAAP; Swepub; EThOS CSV dataset; BDTD; TDR; DiVA; NVA API | Machine-ingestable metadata at national scale with open licences or no-auth OAI-PMH |
| **B (open but per-institution)** | Netherlands (post-NARCIS), Switzerland, Denmark, Finland, Israel, South Africa, Kenya/Nigeria, NZ | Harvest top-5–10 DSpace/EPrints endpoints per country; union discovery via OpenAlex |
| **C (open metadata, blocked/restricted bulk)** | Shodhganga (geo-reachability), LA Referencia (Anubis anti-bot), Trove (key approval), RISS (no bulk API), YÖK (no API), POL-on (registered API) | Negotiate/partnership or careful rate-limited access |
| **D (restricted/commercial)** | CNKI/Wanfang (China), TESEO full text (none exists — by design), DATAD (subscription index), GANJ full text (embargoed), Taiwan NDLTD full text (author-permission) | Discovery only; full text via licence or embargo expiry |
| **Cross-cutting fallbacks** | OpenAlex, Semantic Scholar, NDLTD Global ETD Search, OATD, BASE, CORE, OpenAIRE Graph | Deduplication, discovery overlay, gap-filling for Tier B/D countries |

**Infrastructure notes:** OAI-PMH remains the dominant protocol (DSpace, EPrints, VuFind, WEKO3, IRIS all expose it). DSpace 7/8 migrations change OAI paths from `/oai/request` to `/server/oai/request` and add REST APIs — build endpoint auto-detection. National CRIS consolidation (Norway NVA 2025, Italy tesidottorato 2024, Poland POL-on) is the European trend; aggregators die (DART-Europe 2025, NARCIS 2023, NZresearch 2023) while national platforms absorb their role.

### Trends & Signals

1. **Aggregator churn (2023–2026):** DART-Europe closed (Feb 2025)[^7^], NARCIS retired (2023)[^33^][^35^], NZresearch retired into DigitalNZ (2023)[^75^], Brage/Cristin folded into NVA (2025)[^25^][^26^]. Calyx should treat national endpoints as authoritative and aggregators as convenience layers that can vanish.
2. **Open-data licensing maturing in Europe:** France (Etalab)[^8^], Sweden/Swepub (free reuse)[^30^], Germany GND CC0[^13^], Greece open-data page[^40^], Italy adding CC to deposits (Oct 2025)[^36^] — metadata reuse is legally safe across most of the EU; full-text rights remain per-author.
3. **Bulk-friendly formats appearing:** EThOS full CSV dataset (2026)[^5^], theses.fr annual NDJSON/CSV dumps[^8^], Swepub dumps[^30^] — batch onboarding is increasingly feasible without crawling.
4. **Anti-bot escalation:** LA Referencia deployed Anubis (observed 2026-07-21)[^14^]; Shodhganga unreachable from non-Indian egress (observed); CNKI cross-border suspension (2023, ongoing)[^23^][^24^]; YÖK unreachable from test environment. Expect IP-reputation-based blocking to spread; plan for egress diversity and MoUs.
5. **Persistent identifiers improving:** NBN URNs (Germany, Italy, Sweden/Finland/Norway), JaLC DOIs (Japan), KERIS thesis DOIs (Korea, since 2021)[^50^], IdRef ARKs (France) — entity resolution for Calyx is getting easier.
6. **TDM legal clarity diverging:** Japan (Art. 30-4) and EU DSM Art. 3/4 are permissive for research TDM; India, China, Turkey, Iran have no clear TDM framework — route text-mining agreements through repository operators.
7. **Embargo norms crystallizing:** Iran (18/30 months)[^57^], Italy (max 36 months)[^36^], UK university norms (12–36 months) — a rolling "embargo-expiry harvest" strategy will continuously unlock full text.

### Controversies & Conflicting Claims

1. **EThOS restoration scope:** BL statements and library announcements (Jan–Jul 2026) confirm restoration, but the model *changed* — no central downloads, no digitisation-on-demand; some sector voices (THE column) argue the new EThOS is under-powered vs. the pre-attack service[^1^][^4^][^5^]. *Resolution for Calyx: use the CSV dataset + institutional links; do not plan for BL-hosted PDFs.*
2. **DART-Europe death:** the closure is confirmed (Feb 2025)[^7^], yet third-party guides and library pages worldwide still recommend dart-europe.org — stale documentation is now a real hazard for harvester design.
3. **CNKI availability:** reseller catalogs (East View) still advertise CDMD/CDFD subscriptions[^22^] while university notices (Kyoto, Korea) report suspension since April 2023[^23^][^24^]. Likely truth: selective/partial restoration via domestic-Chinese arrangements; Western bulk access unreliable.
4. **LA Referencia openness:** its mission is open metadata federation[^15^][^16^], yet its current Anubis deployment blocks exactly the automated harvesting it invites[^14^]. Unresolvable without contacting RedCLARA.
5. **Shodhganga counts & openness:** sources cite 600k+ (2025)[^17^] vs. older ~400k figures; INFLIBNET markets open access but access from foreign IPs is unreliable (observed) — possibly geo-gating, possibly transient. Needs India-side verification.
6. **Trove API stability:** NLA documents free API access[^51^], but the GLAM Workbench maintainer reported key cancellation and a new approval regime (2024–25)[^53^] — "free" no longer means "unconditional."
7. **RISS "free" full text:** RISS advertises free theses access[^48^], but systematic/bulk use is prohibited by ToU and technical barriers — "free to read" ≠ "free to harvest."
8. **TESEO coverage:** Ministry describes comprehensive national coverage since 1976[^44^], but researchers resorted to unauthorized scraping to obtain analyzable data[^45^] — a sign of unmet TDM demand; legal status of the scraped dump is dubious.

### Recommended Deep-Dive Areas

1. **EThOS CSV dataset** (British Library Research Repository): obtain, profile schema, map institutional links → design UK spider. Highest-value immediate action.[^5^]
2. **theses.fr STAR OAI discipline sets**: enumerate the "domaine disciplinaire" sets for biology/agronomy; test TEF parsing; validate data.gouv.fr dump freshness vs. OAI incrementals.[^8^][^9^][^10^]
3. **DNB Hochschulschriften setSpec tree**: enumerate sub-sets (by year/institution) and full-text URL coverage; test SRU vs OAI throughput.[^11^]
4. **LA Referencia / RedCLARA outreach**: request harvester whitelisting or a data dump; otherwise spec direct harvests of SNRD (AR), BDTD (BR), and the Chile/Colombia/Mexico national nodes.[^14^][^15^]
5. **Shodhganga from Indian egress**: verify OAI endpoint, per-university sets for botany/agriculture (BHU, NEHU, TNAU, UAS), plus KrishiKosh OAI; quantify Orchidaceae records.[^17^][^18^][^20^]
6. **Swepub API + dumps**: test JSON API subject filtering for "växtbiologi/botanik"; compare coverage vs. 50 DiVA endpoints.[^29^][^30^]
7. **NVA API (Norway)**: map degree-thesis categories and file-download fields; confirm bulk-dump availability with Sikt.[^25^][^28^]
8. **Italy tesidottorato platform**: check for emerging API/OAI on the 2024 national platform; otherwise batch-harvest top-10 IRIS OAI endpoints.[^36^][^84^]
9. **RISS/KERIS partnership**: explore data-sharing MoU or the LOD pilot for bulk metadata; fallback = dCollection per-university OAI where exposed.[^48^][^49^]
10. **Japan CiNii Dissertations API**: verify current CiNii Research API dissertation coverage and WEKO3 OAI endpoints at Tokyo/Kyoto/Tsukuba.[^68^]
11. **Trove API application**: apply for an API key under the new regime early; document quota tiers before committing Australia to the pipeline.[^51^][^53^]
12. **YÖK Tez Merkezi**: Turkish-side partner to assess bulk metadata licensing; Türkiye is an orchid-diversity hotspot worth the effort.[^62^]
13. **Orchidaceae probe queries** across all Tier-A endpoints (OAI `ListRecords` with subject/keyword filters): produce a per-repository orchid-thesis count to rank ingestion priority empirically.
14. **Embargo-expiry harvester**: for EADD/Italy/Iran-style tiered systems, schedule re-harvests keyed on defence-date + embargo norms.

---

### References

[^1^]: Times Higher Education — "Give PhD archive the attention it deserves, British Library urged" (2026-01-29): https://www.timeshighereducation.com/news/give-phd-archive-attention-it-deserves-british-library-urged
[^2^]: British Library — EThOS collection page: https://www.bl.uk/collection/ethos
[^3^]: British Library — "EThOS records restored" (news): https://www.bl.uk/stories/news/ethos-records-restored
[^4^]: British Library — "Restoring our services: November 2025 update": https://www.bl.uk/stories/news/restoring-our-services-november-2025-update
[^5^]: University of Stirling Information Services — "EThOS is back" (2026-07-13; quotes new-platform facts incl. 650k records, 65% IR links, CSV dataset): https://isnews.stir.ac.uk/2026/07/13/ethos-is-back/
[^6^]: Ex Libris Knowledge Center — "What is Happening to EThOS records in Primo?": https://knowledge.exlibrisgroup.com/Content/Knowledge_Articles/Primo/Knowledge_Articles/What_is_Happening_to_EThOS_records_in_Primo%3F
[^7^]: arXiv (2026) — French theses linked-open-dataset paper, noting DART-Europe permanent closure 3 Feb 2025: https://arxiv.org/html/2604.08619v1
[^8^]: ABES — "Réutiliser les données" (Etalab licence, OAI-PMH STAR sets/formats): https://abes.fr/reseau-theses/reutiliser-les-donnees/
[^9^]: ABES — Guide de réutilisation des données theses.fr (PDF): https://abes.fr/wp-content/uploads/2022/03/guide-reutilisation-donnees-theses-fr.pdf
[^10^]: GitHub — abes-esr/theses-api-recherche (theses.fr REST API, OpenAPI): https://github.com/abes-esr/theses-api-recherche
[^11^]: DNB OAI-PMH endpoint (probe-verified live 2026-07-21; Identify + Hochschulschriften ListSets): https://services.dnb.de/oai/repository?verb=Identify
[^12^]: ZDB/DNB — OAI-PMH interface description (free, no registration): https://zeitschriftendatenbank.de/services/schnittstellen/oai
[^13^]: Glomas glossary — GND (CC0 licensing): https://www.glomas.de/glossar/gemeinsame-normdatei-gnd
[^14^]: LA Referencia portal (probe 2026-07-21: site + OAI behind Anubis anti-bot): https://www.lareferencia.info/
[^15^]: Revista Pesquisa FAPESP — "Referência latino-americana" (LA Referencia network): https://revistapesquisa.fapesp.br/es/referencia-latinoamericana/
[^16^]: Colibri UDELAR — LA Referencia national-node architecture (PDF): https://www.colibri.udelar.edu.uy/jspui/bitstream/20.500.12008/44978/1/PB%20242%20TFG%20Carolina%20Saravia%20Rebollo.pdf
[^17^]: LIS Academy — INFLIBNET services (Shodhganga 600,000+ theses, May 2025): https://lis.academy/library-information-and-society/inflibnet-library-automation-india/
[^18^]: NDLTD ETD 2023 — Shodhganga case-study paper: https://docs.ndltd.org/collection/etd2023/etd23-1944_2450_44-paper.pdf
[^19^]: Study notes — E-ShodhSindhu & Shodhganga framework: https://study.niteshkverma.com/paper.php?unit=E-ShodhSindhu-and-Shodhganga
[^20^]: Testbook — KrishiKosh facts (270k+ items incl. ~180,000 theses; DSpace; ICAR OA policy): https://testbook.com/question-answer/which-of-the-following-are-true-of-krishi-kosha--66758faf310733cdb147326b
[^21^]: SHUATS — KrishiKosh description (83 SAU/ICAR institutes; full-text searchable; Agrotags): https://shuats.edu.in/krishikosh.asp
[^22^]: East View — CDMD/CDFD product page (500k+ doctoral dissertations; licensed access): https://www.eastview.com/resources/e-collections/cdmd-cdfd/?pdf=true
[^23^]: Kyoto University Library — CNKI service suspension notice (cross-border data regulation): https://www.kulib.kyoto-u.ac.jp/bulletin/1396819?lang=en
[^24^]: Korea University Library — CNKI suspension notice: https://library.korea.ac.kr/?kboard_content_redirect=21339
[^25^]: Sikt — Nasjonalt vitenarkiv (NVA) service page: https://sikt.no/tjenester/nasjonalt-vitenarkiv-nva
[^26^]: INN University — "Today we start using the Norwegian Research Information Repository" (full production 1 Oct 2025): https://www.inn.no/english/news/today-we-start-using-the-norwegian-research-information-repository/
[^27^]: NHH Library — Brage/NVA migration note: https://www.nhh.no/en/library/nhh-brage/
[^28^]: NVA public API (probe-verified responding 2026-07-21): https://api.nva.unit.no/
[^29^]: apis.io — DiVA OAI-PMH (Stockholm University; ETDMS/MODS/MARC21/oai_dc formats): https://apis.io/apis/stockholm/diva-oai/
[^30^]: Kungliga biblioteket — Swepub data access (OAI-PMH, SRU, open APIs, dumps, free reuse): https://www.kb.se/for-bibliotekssektorn/eng/services/swepub-data-access.html
[^31^]: Kungliga biblioteket — "Vad är Swepub": https://www.kb.se/samverkan-och-utveckling/swepub/vad-ar-swepub.html
[^32^]: Journal of Data Science, Informetrics, and Citation Studies — ETD initiatives incl. DiVA statistics (PDF): https://www.jcitation.org/index.php/jdscics/article/download/134/82/692
[^33^]: Ex Libris Knowledge Center — KNAW databases (NARCIS) retired, Dec 2023: https://knowledge.exlibrisgroup.com/Content/Knowledge_Articles/360_KB/Knowledge_Articles/360_KB%3A_Zero-Title_Databases_from_KNAW_(Koninklijke_Nederlandse_Akademie_van_Wetenschappen)%3A_Databases_Will_Be_Retired_--_December_2023
[^34^]: Moravian Library (MZK) — foreign grey-literature sources (NARCIS offline 1.3.2023; lists Shodhganga/DNB/IRDB OAI endpoints; PDF): https://www.mzk.cz/sites/mzk.cz/files/zahranicni_zdroje_sede_literatury_4_-_osf_canada_hal_irdb_shodhganga_dnb_fraunhofer.pdf
[^35^]: University of Minnesota Libraries — European Studies Librarianship handbook (NARCIS discontinued July 2023; CC0 snapshot): https://open.lib.umn.edu/europeanstudieslibrarians/chapter/chapter-2/
[^36^]: European Patent Office academic research — Italian doctoral theses & legal-deposit platform technical report (2022–2025; tesidottorato.depositolegale.it, NBN URN, 36-month embargo, CC from Oct 2025): https://link.epo.org/web/academic-research-programme/completed-research-projects/en-doc-track-2022-2025-final-technical-report.pdf
[^37^]: BNCF — Archive of Doctoral Theses (legal deposit service): https://bncf.cultura.gov.it/en/services/archive-of-doctoral-theses/
[^38^]: European Commission report (2015) — access to scientific information, Poland POL-on/CRPD mandate: http://wavelets.ens.fr/OPEN_SCIENCE/ABOUT_OPEN_ACCESS/REPORTS/2015_11_15_EC_Report_on_Access_to_Scientific_Information.pdf
[^39^]: Orvium — open access to Polish theses/dissertations analysis: https://dapp.orvium.io/deposits/650827cfa96763f43f69cb26/view
[^40^]: EADD — Open data page (OAI-PMH sets incl. `dart`, `hdl_10442_2`; formats): https://www.didaktorika.gr/eadd/opendata
[^41^]: gov.gr — National Archive of PhD Theses (EADD; 43,000+ theses): https://www.gov.gr/en/upourgeia/upourgeio-psephiakes-diakuberneses/ethniko-kentro-tekmerioses-kai-elektronikou-periekhomenou/ethniko-arkheio-didaktorikon-diatribon
[^42^]: EADD OAI-PMH endpoint (probe-verified live 2026-07-21): https://www.didaktorika.gr/eadd-oai/request?verb=Identify
[^43^]: Universidad de Oviedo — description of TDR/Tesisenred (PDF): https://buo.uniovi.es/c/document_library/get_file?folderId=39988&name=DLFE-124540.pdf
[^44^]: Aristotle University Library — TESEO database description (bibliographic since 1976; no full text): https://www.lib.auth.gr/en/base-de-datos-de-tesis-doctorales-teseo-%CE%B9%CF%83%CF%80%CE%B1%CE%BD%CE%AF%CE%B1
[^45^]: M. Blázquez — TESEO scraped catalogue available for download (community dump; note legal ambiguity): https://mblazquez.es/catalogo-de-tesis-doctorales-espanolas-teseo-disponible-para-su-descarga/
[^46^]: BAD Cadernos — RCAAP portal: public REST API (OpenAPI, JSON/XML), OAI-PMH, 1M+ documents: https://publicacoes.bad.pt/revistas/index.php/cadernos/article/download/1951/pdf/5122
[^47^]: FCT — "RCAAP comemora 10 anos": https://www.fct.pt/media/noticias/rcaap-comemora-10-anos/
[^48^]: RISS — About page (2.29M theses; free full text; dCollection auto-deposit): https://m.riss.kr/AboutRiss.do
[^49^]: Int'l Journal of Knowledge Content Development & Technology — RISS linked-open-data pilot: https://ijkcdt.net/_PR/view/?aidx=33031&bidx=2938
[^50^]: Korea DOI Center — KERIS thesis DOI assignment (since 2021): http://doi.kr/guide/collab/status
[^51^]: Trove — API v3 technical guide: https://trove.nla.gov.au/about/create-something/using-api/v3/api-technical-guide
[^52^]: GLAM Workbench — Trove API v3 documentation/notebooks: https://glam-workbench.net/trove-api-v3/
[^53^]: GLAM Workbench — note on NLA API-key cancellation/restriction (Trove Books section): https://glam-workbench.net/trove-books/
[^54^]: BDTD — new VuFind platform (since Jan 2024): https://bdtd.ibict.br/vufind/
[^55^]: ROAR registry — BDTD OAI-PMH entry (oai.ibict.br): http://roar.eprints.org/129/
[^56^]: Gov.br IBICT — news portal (BDTD new-interface announcement, Jan 2024): https://www.gov.br/ibict/pt-br/central-de-conteudos/noticias
[^57^]: NDLTD ETD 2023 — Iran national ETD system paper (GANJ/IranDoc; embargo tiers 18/30 months; first-20-pages model): https://docs.ndltd.org/collection/etd2023/etd23-1944_2431_25-paper.pdf
[^58^]: ResearchGate — "GANJ: A Comprehensive System of Dissertations and Research Reports in IranDoc" (1.2M+ documents): https://www.researchgate.net/publication/381734206
[^59^]: IMM Graduate School (ZA) — National ETD Portal (netd.ac.za) reference: https://learn2022-02.imm.ac.za/mod/forum/discuss.php?d=1475
[^60^]: Association of African Universities — DATAD-R project page: https://aau.org/current-projects/database-of-african-theses-and-dissertations-research-datad-r/
[^61^]: Aristotle University Library — DATAD description (abstracts; subscription; pilot universities): https://www.lib.auth.gr/en/datad
[^62^]: YÖK — "Ulusal Tez Merkezi ve Açık Erişim Arşivi" official stats slide deck (2014; 189,107 open vs 160,866 closed theses; 4M downloads/yr; PDF): http://bhi.nku.edu.tr/basinyonetim/resim/images/editorresimleri/2397/files/yok_ulusal_tez_merk_acik_erisim.pdf
[^63^]: Tel Aviv University Libraries — theses & dissertations access: https://en-scilib.tau.ac.il/theses
[^64^]: UCP Library — Pakistan Research Repository (PRR) resource page: https://library.ucp.edu.pk/collection-resources.php
[^65^]: ResearchGate — "Pakistan Research Repository: A showcase of theses and dissertations" (7,000+ PhD theses, 2014; DSpace; OA): https://www.researchgate.net/publication/275316603_Pakistan_research_repository_A_showcase_of_theses_and_dissertations
[^66^]: Sher-e-Bangla Agricultural University Library — DAATJ portal: https://saulibrary.edu.bd/daatj/
[^67^]: NDLTD ETD 2019 — DAATJ paper (Bangladesh agricultural theses archive; ~8.7k records): https://docs.ndltd.org/collection/etd2019/etd19-2025-paper.pdf
[^68^]: ResearchGate — entomological journals & publishing in Japan (CiNii/IRDB/JAIRO context): https://www.researchgate.net/publication/289983450_Entomological_journals_and_publishing_in_Japan
[^69^]: Seoul National University Library guide — 臺灣博碩士論文知識加值系統 (Taiwan NDLTD, NCL): https://libguide.snu.ac.kr/c.php?g=321560&p=4333717
[^70^]: Tesify — TESIUNAM guide (500k+ theses registered): https://tesify.es/tesis-de-maestria-mexico-guia-completa-2026
[^71^]: UNAM DGRI — Repositorio Institucional UNAM (RI-UNAM; 2.7M+ resources): https://dgru.unam.mx/index.php/repositorio-institucional-unam-2/
[^72^]: Polish Science Database (archiwum.nauka-polska.pl; doctoral dissertations): https://archiwum.nauka-polska.pl/
[^73^]: University of Helsinki — Helda digital repository: https://www.helsinki.fi/en/helsinki-university-library/library-researchers/helda-digital-repository
[^74^]: apis.io — Helda OAI-PMH (DSpace 7 endpoint): https://apis.io/apis/university-of-helsinki/helda-oai/
[^75^]: DigitalNZ — NZ Research collection (successor to nzresearch.org.nz, retired Sept 2023; API): https://digitalnz.org/nzresearch
[^84^]: Tesify — Italian IRIS repositories & OAI-PMH endpoints guide (2026): https://tesify.it/blog/repository-iris-boa-oar-2026-oai-pmh/
[^85^]: University of Bern — research data & publications (BORIS repository context): https://www.unibe.ch/research/strategy_and_focus/projects_and_publications/data_and_publications/index_eng.html
[^86^]: swissbib — network/search portal (union catalogue incl. theses): https://swissbib.ch/search_fr.html

*(Reference numbers 76–83 not used; 84–86 assigned to Swiss/Italian supporting sources. Live probes by this agent on 2026-07-21: DNB OAI ✓, EADD OAI ✓, NVA API ✓; LA Referencia ✗ Anubis-blocked; Shodhganga ✗ connection failure; YÖK ✗ timeout; RCAAP/DiVA/BDTD/theses.fr OAI probes inconclusive from this environment — documented endpoints retained from cited sources.)*
