# Calyx Deep-Dive — Dimension 03
## Asia / Latin America / Africa / Oceania ETD repositories — verified acquisition specs
*Research date: 2026-07-21. Verifies/deepens `calyx_wide02.md` (Asia/LatAm/Africa sections) and `calyx_wide04.md` (botanical priority sources). "Probe" = live check by this agent on 2026-07-21 from this environment; geo-blocks marked explicitly. Confidence: [H]/[M]/[L]. Inline `[^n^]`; URL list at end.*

---

## 1. Shodhganga (INFLIBNET, India) — STILL UNREACHABLE; OpenAlex fallback quantified

- **Access status (probe 2026-07-21):** `https://shodhganga.inflibnet.ac.in/oai/request?verb=Identify` → connection failure/empty from this (non-Indian) egress, confirming wide02. Treat as **geo-blocked / egress-restricted** [H — observation, two independent probes across sessions]. No public statement of an official geo-block policy was found; INFLIBNET presents Shodhganga as open.[^1^]
- **Architecture:** DSpace (classic UI; handle prefix `hdl.handle.net/10603`). OAI-PMH documented historically at `/oai/request` (DSpace standard). INFLIBNET's own design note: Shodhganga is the central ETD repository and INFLIBNET also runs a harvester over member-university OAI endpoints — i.e., **member-university DSpace repos are an alternate harvest path** for the same theses.[^2^][M]
- **No documented bulk-access arrangement or public mirror found.** Terms framing is "free access / fair research use"; no TDM grant; no data dump. [M]
- **OpenAlex quantification (live queries 2026-07-21):** OpenAlex source `S4377209701` ("Shodhganga", INFLIBNET) holds **117,620 works** — far below the official 600k+ theses, and coverage collapses after 2020 (2020: 2,202 works; 2021: 7) → **OpenAlex's Shodhganga snapshot is stale** (last strong harvest ~2019-2020).[^3^][H]
- **Orchid records in that snapshot:** `type:dissertation` + full-text "orchid" = **42**; title-contains-"orchid" (any type) = **53**.[^4^][^5^] wide04's "42 orchid-title" figure matches the dissertation+full-text query; both reflect only the stale pre-2021 subset.
- **XPAC/PDF fallback — CONFIRMED workable pattern:** OpenAlex `primary_location.landing_page_url` points **directly at Shodhganga bitstream PDFs** on the legacy host, e.g. `http://shodhganga.inflibnet.ac.in:8080/jspui/bitstream/10603/83145/1/01_title%20page.pdf` (1991 orchid in-vitro thesis, OpenAlex W2789295406).[^4^] So: OpenAlex → handle 10603/xxxxx → construct bitstream/landing URLs. Caveat: `:8080/jspui` paths are legacy; current UI path must be re-verified from Indian egress. [H for URL pattern in index, M for current resolvability]
- **Fallback plan (recommended):** (a) OpenAlex filter `primary_location.source.id:S4377209701` for the pre-2021 backfile; (b) OATD/NDLTD Global ETD + Google-indexed handles for newer records; (c) India-based egress (partner institution or cloud region) for OAI-PMH full harvest — endpoint to re-verify at `/oai/request` and `/server/oai/request`; (d) harvest member-university DSpace repos (IARI, TNAU, UAS, NEHU, BHU) which duplicate deposits.
- **Acquisition spec:** Metadata = OAI-PMH (when reachable) or OpenAlex snapshot; full text = per-record bitstream PDF fetch; licence = none stated, © authors/universities; TDM = grey zone (India has no TDM exception; ANI v. OpenAI still pending as of 2026-04).[^6^]

## 2. KrishiKosh (ICAR, India) — migrated to DSpace 7

- **Probe 2026-07-21:** `https://krishikosh.egranth.ac.in/` returns a **DSpace 7 Angular app** (`<ds-app>`) — platform migration since wide02's sources. DNS resolution of the host was intermittent from this environment (worked once, then NXDOMAIN) — Indian-egress verification advised. [H for platform, M for reachability]
- **OAI endpoint:** not directly probe-confirmed; DSpace 7 standard is **`https://krishikosh.egranth.ac.in/server/oai/request`** (returned DNS failure on probe day, not 404 — flag as *probable, unverified*). [M]
- **Volume/OA terms:** ~270k items incl. ~180,000 theses across ICAR institutes + State Agricultural Universities (KrishiPrabha legacy backfile); full-text searchable, ICAR open-access policy; Agrotags descriptors.[^7^][M]
- **Acquisition spec:** OAI-PMH (DSpace 7 XOAI, oai_dc/xoai formats; `dc.type` degree-level filter) → bitstream PDFs. High botanical value (horticulture/plant-breeding theses incl. orchids).

## 3. BDTD Brazil (IBICT) — counts confirmed; OAI behind anti-bot wall on probe day

- **Volume confirmed (2026 source):** **565,311 dissertations + 214,079 theses ≈ 780k records, 129 institutions** — consistent with wide02's ~900k order of magnitude.[^8^][H]
- **Probe 2026-07-21:** `https://bdtd.ibict.br/vufind/OAI/Server?verb=Identify` returned an **"Oasisbr — Verificando seu navegador" JavaScript/anti-bot interstitial** (browser-check page, same family as the Anubis deployments seen elsewhere on probe day). DNS from a second egress failed outright. **Conclusion: VuFind OAI-PMH endpoint exists at `/vufind/OAI/Server` but is currently not script-harvestable from this environment** — needs whitelisting request to IBICT or egress variation. [H for current blockage]
- **Architecture:** LA Referencia software stack (LRHarvester/LRProvider + VuFind); metadata aggregated from member repos via OAI-PMH; **full texts remain at member institutions** — BDTD links out ("full texts remain at the institution where it was defended, and a direct access link is made available").[^9^][^10^][H] → PDF resolution = parse record → member-repo URL (USP TEDE `teses.usp.br` — fully open, no login[^11^]; Lume/UFRGS; UNESP; UNICAMP — all DSpace OAI).
- **Orchid relevance:** Lume/UFRGS alone = 31 Orchidaceae dissertations in OpenAlex; LA Referencia federation 388 (wide04). JBRJ/ENBT backfile crosswalk via CKAN defense data (wide04 finding 6) still applies.
- **Acquisition spec:** Preferred = BDTD OAI-PMH full harvest (filter knowledge area Ciências Biológicas/Agrárias; degree level via `dc.type`) **after** arranging access past the anti-bot wall; interim = harvest top member repos' OAI directly + OpenAlex discovery. No auth/licence documented for OAI; OA per Brazilian OA norms; © authors.

## 4. LA Referencia national nodes — verified per-node status

| Node | Endpoint probed 2026-07-21 | Status |
|---|---|---|
| **Regional (LA Referencia)** | `lareferencia.info/vufind/oai` | ⛔ **Anubis anti-bot PoW** (within.website xess assets) — not harvestable (confirms wide02) [^12^][H] |
| **Mexico (UNAM)** | `repositorio.unam.mx/oai/request?verb=Identify` | ✅ live; reachable; CC BY-NC-ND records; wide04 verified Identify [^13^][H] |
| **Argentina (SNRD)** | `repositoriosdigitales.mincyt.gob.ar/vufind/oai` → **301 → `repositoriosdigitales.sicyt.gob.ar/vufind/oai`** | ⚠️ Domain migrated to **sicyt.gob.ar** (SSL chain misconfigured — curl needs `-k`); `/vufind/oai` returns an HTML "Servidor OAI" page, and `/vufind/OAI/Server?verb=Identify` answers **"OAI Server Not Configured"** → **VuFind OAI data-provider currently NOT functional**; harvest via institutional repos (CONICET Digital `ri.conicet.gov.ar`, UBA, etc.) [^14^][H] |
| **Chile** | `repositorio.uchile.cl/oai/request` | ✅ live OAI-PMH (XML Identify) [^15^][H]. National node `repositorio.anid.cl` is DSpace 7 (Angular); OAI path not yet confirmed (probe returned SPA at both `/oai/request` and `/server/oai/request` — verify backend host at implementation) [M] |
| **Peru** | `renati.sunedu.gob.pe/oai/request` | ⛔ **Anubis** (same within.website PoW) [^16^][H]. RENATI (SUNEDU) collects theses *from* ALICIA (CONCYTEC, VuFind national node); `alicia.concytec.gob.pe` returned a WordPress 404 page for `/oai/request` — real VuFind base path to be re-derived (try `/vufind/OAI/Server`) [^17^][M] |
| **Colombia** | — | Node = RedCol/MinCiencias; interoperability docs (redcol.readthedocs.io) describe OAI-PMH requirements for members but **no public provider endpoint verified**; `bibliotecadigital.min-ciencias.gov.co` NXDOMAIN. Harvest top repos directly (UIS — 37 Orchidaceae dissertations in OpenAlex; UNAL `repositorio.unal.edu.co`; Javeriana; Andes) [^18^][M] |

- **Degree-level filtering strategy:** OAI `dc.type`/`type` values from DRIVER/LA Referencia guidelines (`info:eu-repo/semantics/doctoralThesis`, `masterThesis`, `bachelorThesis`); in Mexico/Brazil filter out *licenciatura/TCC* via type + collection (wide04: much Mexican output is licenciatura). Where types are noisy (SNRD HTML-mode, Alicia), filter by source-repository OAI sets per institution.
- **Bottom line:** harvestable today = **UNAM, UChile, member repos in AR/CO/PE/BR directly**. Blocked today = LA Referencia central, RENATI, BDTD central (all anti-bot), SNRD provider (misconfigured). [H]

## 5. Japan — CiNii Dissertations is DEAD (May 2025); IRDB OAI live

- **CiNii Dissertations discontinued 2025-05-12, integrated into CiNii Research** (integration 2024-12-09; parallel run ended 2025-05-12). Full-text search discontinued; OpenSearch/RDF/JSON-LD endpoints redirect to CiNii Research equivalents (`ci.nii.ac.jp/naid/<naid>.json` JSON-LD per-record still documented). Corpus at closure: ~600k dissertations (NDL bibliographic) + ~131k NDL digitized + ~130k IR full-text links.[^19^][^20^][^21^][H — conflicts with wide02's live-service description; **correction**]
- **IRDB OAI-PMH probe-verified LIVE:** `https://irdb.nii.ac.jp/oai?verb=Identify` → "Institutional Repositories DataBase (IRDB)", OAI-PMH 2.0, earliestDatestamp 2013-01-01, admin ir@nii.ac.jp. ListSets exposes DOI-registration sets (jalc, crossref, datacite…).[^22^][H] WEKO3 per-institution endpoints remain the granular path (U. Tokyo, Kyoto, Tsukuba, Kobe — Suetsugu mycoheterotrophy school).
- **CiNii Research OpenSearch** (`cir.nii.ac.jp/opensearch/...`) — documented successor API (RSS/Atom/JSON-LD, appid); probe from this environment timed out/blocked — verify at implementation. [M]
- **NDL:** digitized dissertations post-FY2013 e-deposit; access tiers = Internet / partner-library terminals / NDL premises only — **not a bulk source**; use as discovery via NDL Search API. [H]
- **Art. 30-4 TDM law (deepened):** Japan's Copyright Act Art. 30-4 permits use of works for "non-enjoyment" purposes (incl. TDM/AI training, commercial or not) without permission; Agency for Cultural Affairs' "General Understanding on AI and Copyright" (2024) adds guardrails: coexisting enjoyment purpose voids it, "unreasonably prejudicing copyright-owner interests" (e.g., mining databases sold for that purpose), and **circumventing technical measures/robots.txt-type blocks is not privileged**. Implication for Calyx: TDM of *lawfully accessed* Japanese thesis PDFs (OA IR copies) is on the firmest legal ground worldwide; but respect each repo's ToU/robots (contract/CFAA-type exposure remains).[^23^][^24^][H]
- **Acquisition spec:** IRDB OAI (junii2/oai_dc) + CiNii Research OpenSearch for NDL-only records → university WEKO3 repos for PDFs. OpenAlex: 19 Japanese orchid-fulltext dissertations; IRDB 31 Orchidaceae (wide04).

## 6. Korea RISS/dCollection — Open API EXISTS (application-based)

- **RISS OpenAPI is real but gated:** KERIS librarian-community notice (2014, still the cited mechanism) — "RISS OpenAPI exposes domestic/international journal articles, **theses (학위논문)**, books… for external developers"; application via KERIS; documented use in TDM research (XML via API).[^25^][^26^] Also listed in Korean public-API directories as "한국교육학술정보원 학술연구정보 — apiKey".[^27^][H — upgrades wide02's "no documented open bulk API"]
- **Scale/model (wide02 confirmed):** ~2.29M theses, free full text for most, DOIs since 2021 via Korea DOI Center (KERIS registers thesis DOIs by API for dCollection universities).[^28^] `riss.kr` reachable from this environment (probe 2026-07-21). dCollection per-university instances (e.g., dcollection.korea.ac.kr) run local UREKA analytics.[^29^]
- **Acquisition spec:** (1) Apply for RISS OpenAPI key (KERIS; describe TDM/research use — precedent exists); (2) fallback: targeted dCollection institutional harvesting where OAI exposed (unverified per-instance); (3) discovery overlay via OpenAlex (Korea orchid dissertations sparse there — only 2 KR in full-text "orchid" sample — so RISS API is essential). ToU prohibits systematic scraping; no OAI-PMH public.

## 7. Trove (NLA Australia) — new tiered approval; AI use = Level 3/4 + exemption

- **API key process (official, current):** Trove account → "Request a Trove API key" form → **4-level review** (Technical / Level 1 personal-education-academic / Level 2 non-commercial / **Level 3 commercial or "AI modelling/Machine learning" — exemption required** / **Level 4 training generative AI — exemption required**, possibly a **data-sharing agreement**). Most answered within a week. **v2 API discontinued Sept 2024; v3 only.**[^30^][H]
- **Theses access pattern:** `api.trove.nla.gov.au/v3/result?category=book&q=...&l-format=Thesis` (also `category=research`); **`bulkHarvest=true` parameter exists specifically for systematic harvests** (sorts by identifier, guarantees complete paging); max 100 results/page, cursor `nextStart`.[^31^][^32^][H]
- **Rate limits:** call rate stated per approved key ("200m" tier notation on the form = ~200 calls/min baseline tier); custom rates via technical review.[^30^][M]
- **Calyx implication:** thesis *metadata* harvest = Level 1, easy. **Using harvested theses for AI-model training = Level 3/4 — declare it upfront**; NLA reviews for copyright/ICIP/reputational risk and may require a data-sharing agreement. Full text still comes from source university repos (ANU, UWA, Melbourne, UQ — wide04), not Trove.
- **NZ:** DigitalNZ API v3 (free key) + institutional OAI (Otago, Massey, Lincoln, Canterbury — terrestrial-orchid ecology) per wide02/wide04; no new conflicts.

## 8. China + Taiwan — CNKI international access RESTORED (2024); update wide02

- **CNKI CDMD (doctoral dissertations):** UC/CDL confirms the April-2023 cross-border suspension was **lifted: "As of April 2024, CDMD is fully restored, including all series"**, via `oversea.cnki.net` (licensed through East View; UC holds Series F,G,H,J).[^33^][H — **revises wide02 finding 7**: suspension was real but ended Mar–Apr 2024; access = **licensed subscription, not open**, and politically fragile]. No open API/OAI; bulk/TDM only via negotiated licence.
- **OpenAlex coverage of Chinese theses is negligible** (7 CN dissertations in orchid-fulltext sample) — OpenAlex is NOT a workaround for CNKI full text; Chinese theses are under-indexed globally.[^34^][H]
- **CAS institutional repos (KIB/XTBG):** XTBG-IR documented (theses incl. doctoral; est. 2011, Chinese metadata, partial OA); `ir.kib.ac.cn` probe timed out from this environment (possible geo/instability). Treat as small, Chinese-language, selectively open supplements. [M]
- **Taiwan NCL NDLTD:** `ndltd.ncl.edu.tw` reachable (probe 2026-07-21, 200). No public API/OAI documented; author-permission OA subset downloadable without login. Web discovery + OA PDF fetch; strong orchid-breeding corpus (NCHU, NTU, Tainan). [M]
- **Acquisition spec:** China = licensed CNKI via East View (if budget) + CAS IRs + OpenAlex discovery; Taiwan = NCL web crawl of OA subset with rate discipline.

## 9. Turkey / Iran / South Africa

- **YÖK Ulusal Tez Merkezi (Türkiye):** `tez.yok.gov.tr` — DNS/timeout from this environment on probe day (consistent with wide02) → **geo-block probable** [H as observation]. No API, no OAI; ~50k theses/yr growth; author open/closed choice; bulk needs YÖK partnership. OpenAlex: 1 TR orchid dissertation — YÖK is invisible to global indexes; needs Turkish partner. [M]
- **Iran GANJ (IranDoc):** no new contradicting data; embargo model (first ~20 pages free; full text after 18 mo master's / 30 mo doctoral) stands per wide02 [^35^][M]. Sanctions/egress risk unprobed.
- **South Africa (probe-verified today):**
  - **SUNScholar (Stellenbosch):** `https://scholar.sun.ac.za/server/oai/request?verb=Identify` ✅ live (DSpace 7) [^36^][H] — 20 Orchidaceae dissertations (wide04).
  - **WIReDSpace (Wits):** `https://wiredspace.wits.ac.za/server/oai/request?verb=Identify` ✅ live (DSpace 7, repositoryName "WIReDSpace") [^37^][H — new, fills wide02 gap].
  - **UPSpace (Pretoria):** `repository.up.ac.za/oai/request` ⛔ timeout (HTTP+HTTPS) from this environment — COAR-listed endpoint; likely geo/firewall; OpenAlex shows 3 Orchidaceae dissertations; retry from ZA egress. [M]
  - UKZN ResearchSpace: unreachable (wide04) — still geo/firewall-blocked; OpenAlex harvested 24 Orchidaceae dissertations from it, so content is OA — needs egress workaround. [M]
  - National ETD Portal (netd.ac.za): harvests institutional OAI; portal itself not machine-friendly — go direct to repos. [M]
- **Acquisition spec:** OAI-PMH DSpace 7 XOAI from SUNScholar + WIReDSpace + OpenUCT (wide04) + UNISA + NWU; `dc.type=Thesis`/collection filters for doctoral/masters; ZA-egress for UP/UKZN.

---

## Conflicts / corrections vs wide02 & wide04

1. **CiNii Dissertations (wide02 profile 20):** described as live service → **service ended 2025-05-12**; APIs redirect to CiNii Research. IRDB OAI unaffected (verified live). [^19^][^20^]
2. **CNKI (wide02 finding 7):** "access largely China-domestic / treat as restricted" → **international CDMD access restored as of April 2024** via oversea.cnki.net/East View (licensed). Still no open/bulk route, but "suspended" is no longer accurate. [^33^]
3. **RISS (wide02 profile 21):** "no documented open bulk API" → **RISS OpenAPI exists (application-based, incl. 학위논문 theses, XML)**; not anonymous, but documented and used in published TDM research. [^25^][^26^]
4. **SNRD Argentina (wide02 recommended harvest):** endpoint moved to **sicyt.gob.ar**; VuFind OAI **data-provider not configured** on probe day — wide02's "`repositoriosdigitales.mincyt.gob.ar` OAI" path needs replacement (institutional repos instead). [^14^]
5. **BDTD OAI (wide02: "probe returned empty — verify"):** verified reason — **anti-bot interstitial ("Oasisbr" browser check)** now fronts the VuFind OAI server; wide02's URL is right, access is the blocker. [^38^]
6. **RENATI Peru:** newly found **Anubis-blocked** (same as LA Referencia) — add to wide02's blocked list.
7. **Shodhganga OpenAlex coverage:** wide04's orchid counts (42/53) confirmed but contextualized — they reflect a **stale pre-2021 snapshot** of ~118k works vs 600k+ official; do not extrapolate totals from OpenAlex. [^3^]
8. **KrishiKosh:** now **DSpace 7** (new finding) — OAI path moves to `/server/oai/request`.
9. **Trove:** wide02's "tightened access" now fully specified — tiered review; **AI/ML use triggers Level 3–4 + possible data-sharing agreement**; v2 gone. [^30^]

## Unknowns / for implementation-time verification

- Shodhganga OAI path & current bitstream URL scheme from Indian egress; whether INFLIBNET will whitelist a Calyx harvester (no documented channel found).
- KrishiKosh `/server/oai/request` live confirmation (DNS instability on probe day).
- BDTD: whether IBICT whitelists harvesters past the Oasisbr check; current record count post-2026.
- ANID Chile DSpace 7 backend OAI path; Alicia Peru VuFind OAI base path; RedCol Colombia provider endpoint.
- CiNii Research OpenSearch rate limits/appid requirement (probe blocked here).
- RISS OpenAPI: current application terms, quotas, and whether non-Korean applicants are accepted.
- YÖK: reachability from Turkish egress; any official bulk-data channel (none found).
- UPSpace/UKZN ZA-egress OAI confirmation.
- OpenAlex XPAC→Shodhganga `:8080/jspui` URLs — do they still resolve post any DSpace upgrade?

## References

[^1^]: Probe log 2026-07-21 (this agent): shodhganga.inflibnet.ac.in connection failure (curl, 2 egresses) — consistent with wide02 probe.
[^2^]: LISLinks — INFLIBNET/Shodhganga OAI-PMH architecture description: https://www.lislinks.com/forum/topics/search-and-browse-etds-at
[^3^]: OpenAlex Sources API — Shodhganga S4377209701 (117,620 works; counts_by_year): https://api.openalex.org/sources?search=Shodhganga
[^4^]: OpenAlex — orchid full-text dissertations at Shodhganga (count 42; exemplar W2789295406 with 10603/83145 bitstream URL): https://api.openalex.org/works?filter=type:dissertation,primary_location.source.id:S4377209701&search=orchid&per-page=1
[^5^]: OpenAlex — title "orchid" at Shodhganga (count 53): https://api.openalex.org/works?filter=primary_location.source.id:S4377209701,title.search:orchid&per-page=1
[^6^]: Intepat — India copyright/AI (no TDM exception; ANI v. OpenAI status 2026-04): https://www.intepat.com/blog/intellectual-property-law-for-artificial-intelligence
[^7^]: wide02 refs [^20^][^21^] (KrishiKosh volume/OA); probe 2026-07-21: krishikosh.egranth.ac.in = DSpace 7 Angular app.
[^8^]: Mettzer blog (2026-04-13) — BDTD 565,311 dissertations + 214,079 theses, 129 institutions: https://blog.mettzer.com/bdtd/
[^9^]: Asklepion journal — BDTD model (metadata central, full text at member institutions): https://asklepionrevista.info/asklepion/article/download/38/67/318
[^10^]: RDBCI/SciELO — BDTD VuFind + LA Referencia collector architecture: https://www.scielo.br/j/rdbci/a/XbdZdMMTGFkSdxhL858PdCt/?format=pdf&lang=en
[^11^]: USP TEDE (open, no login): https://teses.usp.br/
[^12^]: Probe 2026-07-21: https://www.lareferencia.info/vufind/oai?verb=Identify → Anubis "Making sure you're not a bot" (within.website/xess assets).
[^13^]: UNAM RI OAI: https://repositorio.unam.mx/oai/request?verb=Identify (wide04-verified; probe-reachable today)
[^14^]: Probe 2026-07-21: mincyt.gob.ar 301 → https://repositoriosdigitales.sicyt.gob.ar/vufind/oai (HTML "Servidor OAI"; `/vufind/OAI/Server?verb=Identify` → "OAI Server Not Configured"; SSL chain broken).
[^15^]: Probe 2026-07-21: https://repositorio.uchile.cl/oai/request?verb=Identify → OAI-PMH XML.
[^16^]: Probe 2026-07-21: https://renati.sunedu.gob.pe/oai/request?verb=Identify → Anubis page.
[^17^]: UNESCO/LatAm OA policies report — ALICIA/RENATI relationship (RENATI collects theses from ALICIA; DRIVER guidelines): https://cdn.prod.website-files.com/615f0ec368dc44a3d513e3ba/6409e66349a8c603a19b0e8e_open%20access%20policies%20in%20latin%20america%20the%20caribbean-KI0922473ENN.pdf
[^18^]: RedCol interoperability docs (OAI-PMH member requirements): https://redcol.readthedocs.io/es/latest/interoperabilidad.html
[^19^]: NII support — Integration of CiNii Dissertations into CiNii Research (ended 2025-05-12): https://support.nii.ac.jp/en/cir/cid_integration
[^20^]: NII support — About CiNii Dissertations (600k corpus; NDL/IR sources): https://support.nii.ac.jp/en/cinii_dissertations
[^21^]: NII support — CiNii Dissertations JSON-LD spec (per-record API): https://support.nii.ac.jp/en/cid/api/d_json
[^22^]: Probe 2026-07-21: https://irdb.nii.ac.jp/oai?verb=Identify (live; ListSets jalc/crossref/datacite…)
[^23^]: WIPO/Ueno — "General Understanding on AI and Copyright in Japan" (Art. 30-4 limits): https://www.wipo.int/documents/d/office-japan/docs-en-tatsuhiro-ueno_general-understanding-on-ai-and-copyright-in-japan_set.pdf
[^24^]: Springer IIC (2025) — comparative TDM exceptions, Art. 30-4(ii) analysis: https://link.springer.com/article/10.1007/s40319-025-01569-6
[^25^]: KERIS librarian community — "RISS Open API 신청 안내" (application notice): http://librarian.riss.kr/boardArticle/boardArticleView.do?boardArticleBean.articleId=000000016237
[^26^]: PMC — TDM study using RISS API (XML): https://pmc.ncbi.nlm.nih.gov/articles/PMC7728078/
[^27^]: GitHub public-apis-4Kr — KERIS 학술연구정보 apiKey listing: https://github.com/yybmion/public-apis-4Kr
[^28^]: Korea DOI Center — KERIS thesis DOI collaboration: http://doi.kr/guide/collab/status
[^29^]: dCollection/UREKA (Korea U example): https://dcollection.korea.ac.kr/intro
[^30^]: Trove — Using the API (key application, review levels 1–4, AI/ML exemptions, v2 retired Sept 2024): https://trove.nla.gov.au/about/create-something/using-api
[^31^]: Trove — API v3 technical guide (l-format=Thesis; bulkHarvest; paging): https://trove.nla.gov.au/about/create-something/using-api/v3/api-technical-guide
[^32^]: Wragge Labs — Trove API console (thesis query examples): https://wraggelabs.com/troveapiconsole/
[^33^]: CDLinfo (2024-04-25) — "Access Restored to CNKI Resources" (CDMD fully restored as of April 2024; oversea.cnki.net): https://cdlib.org/cdlinfo/2024/04/25/access-restored-to-cnki-resources/
[^34^]: OpenAlex — orchid full-text dissertations by institution country (CN=7, JP=19, IN=3, KR=2, ZA=6, BR=45, MX=18…): https://api.openalex.org/works?filter=type:dissertation&search=orchid&group_by=institutions.country_code&per-page=100
[^35^]: NDLTD ETD 2023 — Iran GANJ embargo model: https://docs.ndltd.org/collection/etd2023/etd23-1944_2431_25-paper.pdf
[^36^]: Probe 2026-07-21: https://scholar.sun.ac.za/server/oai/request?verb=Identify (live)
[^37^]: Probe 2026-07-21: https://wiredspace.wits.ac.za/server/oai/request?verb=Identify (live, "WIReDSpace")
[^38^]: Probe 2026-07-21: https://bdtd.ibict.br/vufind/OAI/Server?verb=Identify → "Oasisbr — Verificando seu navegador" interstitial.
[^39^]: MDPI Publications (2020) — BDTD architecture (TEDE/DSpace, MTD-BR, OAI-PMH federation): https://www.mdpi.com/2304-6775/8/2/24
[^40^]: NDLTD ETD 2023 — Shodhganga case study: https://docs.ndltd.org/collection/etd2023/etd23-1944_2450_44-paper.pdf

*Live probes this session (2026-07-21): IRDB ✅, SNRD ⚠️(moved/misconfigured), UChile ✅, SUNScholar ✅, WIReDSpace ✅, UNAM ✅(reachability), RISS ✅(site), NDLTD TW ✅(site), RENATI ⛔Anubis, LA Referencia ⛔Anubis, BDTD ⛔anti-bot, Shodhganga ⛔conn-fail, KrishiKosh ⚠️DNS-flaky (DSpace 7 confirmed), YÖK ⛔DNS/timeout, KIB IR ⛔timeout, UPSpace ⛔timeout, ANID ⚠️SPA, Alicia ⚠️404-path, OpenAlex API ✅(5 queries), Trove docs ✅. ~30 probes/searches total.*
