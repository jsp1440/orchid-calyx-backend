# Calyx Dim-05 — Botanical-Priority Repositories: Endpoint Verification & Orchid-Yield Benchmark

Date of live tests: **2026-07-21** (from Calyx research network). Prior file verified/deepened: `calyx_wide04.md`. Confidence: **[H]/[M]/[L]**. ⛔ = blocked/unreachable from our network today.

## 1. Tier-1 Botanical Harvest Table (verified mechanics)

| # | Repository | OAI-PMH base URL (verified) | Set / filter | Est. total records | Est. orchid (dissertations) | License signal | Full-text URL pattern | Botany/Orchid rel. (1–10) | Priority |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **Leiden Scholarly Publications** (Naturalis) | `https://scholarlypublications.universiteitleiden.nl/oai2` ✅ | `hdl_1887_55785` = **OpenDissertations = 7,764 records** (completeListSize, today); `hdl_1887_9744` = Dissertations; `open_access` set also exposed | ~7.8k OA dissertations | 30–60 orchid (OpenAlex shows only 4 — heavy undercount; 25+ yrs of Gravendeel/Merckx orchid PhDs) [M] | Licence agreement per thesis; OA flag via `open_access` set | `…/handle/1887/NNNNNN` → `…/access/item%3AID/view` PDF | 10 | **P0** |
| 2 | **Kew Research Repository** | `https://kew.iro.bl.uk/catalog/oai` ✅ (curl; HTML UI is Cloudflare-challenged ⛔ but OAI passes) | Only set: `collection:admin_set/default`; **total 9,361 records** (completeListSize today); thesis type = `thesis_or_dissertation` work-type, PhD collection | 9,361 (all types); 105 theses in 2023, est. 130–180 today [M] | ~15–30 orchid theses (highest precision/record of any repo) [M] | Green OA, UKRI/Plan S; per-record licence field | `…/concern/thesis_or_dissertations/<uuid>` (+ `/catalog/oai` GetRecord by `oai:hyku:<uuid>`) | 10 | **P0** |
| 3 | **OpenUCT** (Cape orchids, SANBI) | `https://open.uct.ac.za/server/oai/request` ✅ (DSpace 7 path; legacy `/oai/request` also responds per wide04) | DSpace sets by handle; filter `type:Thesis` + subject keyword | large (tens of k) | **36 Orchidaceae dissertations** (OpenAlex, wide04) [H] | UCT OA policy 2014; theses auto-deposited; CC per record | `…/items/<uuid>` + bitstream API `/server/api/core/items/<uuid>/bundles` | 8 | **P0** |
| 4 | **ScholarSpace UH Mānoa** | `https://scholarspace.manoa.hawaii.edu/server/oai/request` ✅ (Identify today) | handle sets (10125/*); ETD community | large | 17 Orchidaceae + 9 orchid-title [H] | OA repository; some campus-only 2020+ (watch rights field) | `…/items/<uuid>`; legacy `10125/` handles | 8 | **P0** |
| 5 | **CUNY Academic Works** (NYBG Plant Sciences) | `https://academicworks.cuny.edu/do/oai/` ✅ (Identify today; adminEmail now Elsevier/bepress DC) | per-site sets (GC ETDs); bepress `do/oai` | ~50k+ | 5–15 orchid (NYBG joint program) [M] | **dataPolicy: "Full content may not be harvested by robots without prior, written approval"** — metadata OK, PDFs need permission [H] | `academicworks.cuny.edu/gc_etds/<n>/` | 8 | **P0 metadata / P2 full-text (permission)** |
| 6 | **EPub Bayreuth** (Gebauer mycoheterotrophy) | `https://epub.uni-bayreuth.de/cgi/oai2` ✅ (EPrints 3.4.3, Identify today) | EPrints subjects; search "orchid" returns first page of 10 (multi-page, total not exposed in HTML) | ~10k | 7 Orchidaceae dissertations (OpenAlex) [H]; ~10+ orchid-keyword items of all types | Explicit metadata/data policy in Identify (non-profit reuse OK w/ attribution) | `https://epub.uni-bayreuth.de/<eprintid>/` → `/id/eprint/<n>/1/<file>.pdf` | 7 | **P0** |
| 7 | **KU Leuven Lirias** (Jacquemyn orchid-mycorrhiza) | `https://lirias.kuleuven.be/oai` ✅ (Identify today; gzip/deflate supported) | no subject set; keyword filter post-harvest | very large | 5–10 orchid theses, high precision [M] | OA mandate; licence per record | `lirias.kuleuven.be/<id>` bitstream links | 7 | **P0** |
| 8 | **Imperial Spiral** (Bidartondo, Kew-linked) | `https://spiral.imperial.ac.uk/server/oai/request` ✅ (DSpace 7; `/oai/request` 301-redirects to `/server/oai/request` — wide04 said "untested", now verified) | sets by handle `10044/1/*`; ETD collection | very large | 7 Orchidaceae dissertations [H] | OA theses; CC-BY common | `…/items/<uuid>`; legacy `10044/1/<n>` | 7 | **P0** |
| 9 | **Ghent Biblio** (Meise Botanic Garden) | `https://biblio.ugent.be/oai` ✅ (Identify today; `oai:archive.ugent.be:<n>` IDs) | sets per faculty; filter dissertation type | very large | 8 Orchidaceae dissertations [H] | OA; licence metadata field | `biblio.ugent.be/publication/<id>/file/<id>.pdf` | 6 | **P1** |
| 10 | **ERA Edinburgh** (RBGE theses) | `https://era.ed.ac.uk/server/oai/request` ✅ (Identify today) | handle sets `1842/*`; thesis collections | large | ~5–10 (RBGE-linked; OpenAlex n/a) [M] | OA theses; CC per record | `…/items/<uuid>`; legacy `1842/<n>` bitstreams | 5–6 | **P1** |
| 11 | **Cornell eCommons** (Bailey Hortorium) | `https://ecommons.cornell.edu/server/oai/request` ✅ (curl today; `/oai/request` redirects → DSpace 7. web_open_url "audit rejected" = tool quirk, endpoint is fine) | handle sets `1813/*` | very large | 5 Orchidaceae + broad botany [H] | OA; rights field per record | `…/items/<uuid>`; legacy `1813/<n>` | 7 | **P1** |
| 12 | **Refubium FU Berlin** (BGBM-linked) | `https://refubium.fu-berlin.de/oai/request` ✅ (Identify today; `fub188/` IDs) | dissertation sets by faculty | large | 3 Orchidaceae [H] | OA (FU OA policy) | `…/fub188/<n>` | 5 | **P1** |
| 13 | **ScholarBank@NUS** (SBG-linked) | `https://scholarbank.nus.edu.sg/server/oai/request` ✅ (curl today; DSpace 7) | handle sets `10635/*` | large | ~5–10 orchid (breeding/SE-Asia botany) [M] | OA theses; some restricted (rights field) | `…/items/<uuid>` | 6 | **P1** |
| 14 | **UPM PSASIR** (Malaysia) | `http://psasir.upm.edu.my/cgi/oai2?verb=Identify` ✅ (EPrints, live today) | EPrints divisions; filter thesis type | tens of k | **21 orchid-title dissertations** (OpenAlex) [H] — top orchid-title yield per repo | OA EPrints | `psasir.upm.edu.my/id/eprint/<n>/` | 8 | **P1** |
| 15 | **IPB/Bogor** (Indonesia) | `https://repository.ipb.ac.id/oai/request` ✅ (DSpace XML today; `/server/oai/request` returns Angular HTML — legacy path correct) | handle sets | large | orchid ETDs present (Indonesian floristics) [M] | mixed OA | `…/handle/…` + bitstreams | 6 | **P1** |
| 16 | **Birkbeck BIROn** (Kew DTP partner) | `https://eprints.bbk.ac.uk/cgi/oai2` ✅ (EPrints, live today) | — | medium | small, Kew-linked plant/fungal [M] | OA | `eprints.bbk.ac.uk/id/eprint/<n>/` | 5 | **P2** |
| 17 | **Reading CentAUR** (Kew degree-awards) | `https://centaur.reading.ac.uk/cgi/oai2` ✅ (EPrints, live today) | — | medium | Kew-registered PhDs (e.g. Abreu Ophrys) [H] | OA | `centaur.reading.ac.uk/<n>/` | 6 | **P1 (Kew dedupe pair)** |
| 18 | **teses.usp.br** (USP, Brazil) | **No OAI-PMH** — `/oai/request` = 404 ✅ tested today; site itself 200 and fully open | harvest via site crawl/search JSON, or BDTD/Oasisbr aggregators (which harvest USP TEDE) | ~300k+ theses | orchid taxonomy corpus (Singer lineage; Lume UFRGS 31 is separate) [M] | "qualquer pessoa pode … baixar os PDFs sem cadastro" (open, no login) | `teses.usp.br/teses/disponiveis/…/*.pdf` | 8 | **P1 (crawler path, not OAI)** |

## 2. Verification log (2026-07-21, ~28 probes)

**Live OAI Identify/List verbs:** Kew ✅ (+ListSets, +ListIdentifiers count 9,361), Leiden ✅ (+ListSets, OpenDissertations count 7,764), OpenUCT ✅ (`/server/oai/request`), ScholarSpace ✅, CUNY ✅, Bayreuth ✅, ERA ✅, Refubium ✅, Ghent ✅, Lirias ✅, Cornell ✅ (curl), NUS ✅ (curl), Imperial Spiral ✅ (curl), Birkbeck ✅, Reading ✅, UPM ✅, IPB ✅ (legacy path).
**Blocked / failed:** UKZN ResearchSpace ⛔ (both `/oai/request` and `/server/oai/request` empty; base site curl = `000` timeout — network-level block, unchanged vs wide04); UCL Discovery ⛔ (Cloudflare "Just a moment" on `/cgi/oai2`); QMUL QMRO ⛔ (JS anti-bot interstitial on OAI); Royal Holloway Pure ⛔ (Cloudflare); UMS eprints ⛔ (empty response); UM Malaya eprints (redirect page, not OAI at `/cgi/oai2`); ANU Digital Collections ⛔ (`/oai` = 404, `/api/oai` = conn-fail — no OAI found on new platform); Wageningen eDepot (404 at `/oai`); teses.usp.br OAI (404); Kew HTML catalog UI ⛔ Cloudflare (OAI unaffected).
**Tool quirks:** web_open_url failed on Cornell ("audit rejected") and NUS ("internal error") — both endpoints verified healthy via curl; crawler fallback strategy validated.

## 3. Orchid-yield benchmark (ranked by orchid density × volume)

Orchid dissertation estimates (OpenAlex cached figures from wide04, live OAI counts from today; OpenAlex API quota exhausted at probe time — budget $0, resets midnight UTC):

1. **Leiden OpenDissertations** — 7,764 OA dissertations; orchid subset est. 30–60 [M]. Density ≈ 0.5–0.8%.
2. **OpenUCT** — 36 Orchidaceae [H]. Density high for its size class.
3. **UPM PSASIR** — 21 orchid-title [H]. Highest orchid-title count of any single IR.
4. **Kew repo** — 9,361 total records; 130–180 theses; orchid share of theses likely 10–20% [M] → **highest precision per harvested record** (0.2–0.3% of total repo but theses-only harvest ≈ every 5th record orchid).
5. **UMS Sabah** — 15 Orchidaceae [H] (endpoint blocked today; OpenAlex fallback).
6. **UH ScholarSpace** — 17 Orchidaceae + 9 title [H].
7. **UWA** — 10 orchid-title [H] (Esploro site 200; OAI path not confirmed — see unknowns).
8. **Ghent 8 / Bayreuth 7 / Spiral 7 / ANU 6 / Cornell 5 / CUNY ~5–15** [H/M].
9. **ERA/RBGE, Refubium, NUS, IPB** — 3–10 each [M].

## 4. UKZN workaround (site fully unreachable from our network)

- **OpenAlex pmh-ID resolution**: OpenAlex already holds 24 UKZN Orchidaceae dissertations with `primary_location.id` like `pmh:oai:researchspace.ukzn.ac.za:…` — resolve metadata + landing URLs from OpenAlex alone [H].
- **Google Scholar / webcache**: `site:researchspace.ukzn.ac.za orchid` via browser automation (Browser tools bypass some WAF rules); Steve Johnson school author lists (e.g., his students' theses) as seed.
- **Aggregator mirrors**: OATD, NDLTD Union Catalog, DART-Europe (no, UK only), LA Referencia n/a — use **NDLTD/OATD** records which carry UKZN handles [M].
- **Manual batch / inter-network**: harvest from non-blocked network (residential proxy); site is DSpace 7 → `/server/oai/request` once reachable.
- **SA federation**: check NRF/HELTASA national ETD portal (other dimension's scope).

## 5. ANU / UWA new platforms

- **ANU Digital Collections** (ex-DSpace Open Research): no OAI at `/oai`, `/api/oai`; exemplar thesis page `digitalcollections.anu.edu.au/items/<uuid>/full`. Platform appears custom/Figshare-like — **probe `/api/` REST routes or sitemap.xml as harvest path; else scrape search API** [M]. ⛔ OAI not found.
- **UWA Profiles & Research Repository** (Esploro): site reachable (200). Esploro exposes OAI-PMH typically at `https://research-repository.uwa.edu.au/view/oai?verb=Identify` (needs confirmation — not tested successfully today) and a REST API (key required for API; OAI usually open). Esploro delivery pattern: `…/esploro/outputs/doctoral/<title>/<id>` + `/filesAndLinks` [M].

## 6. Kew DTP partner IRs — OAI exposure & dedupe

| Partner IR | OAI status today | Note |
|---|---|---|
| Kew repo | ✅ 9,361 records | primary |
| Reading CentAUR | ✅ EPrints | Kew-awarded PhDs (Abreu exemplar) |
| Birkbeck BIROn | ✅ EPrints | TREES partner |
| Imperial Spiral | ✅ DSpace 7 | SSCP partner |
| UCL Discovery | ⛔ Cloudflare | retry via browser; EPrints `/cgi/oai2` exists behind WAF |
| QMUL QMRO | ⛔ JS challenge | endpoint exists; needs real browser |
| Royal Holloway Pure | ⛔ Cloudflare | Pure portal; Pure OAI usually `/ws/oai` — untested |

**Dedupe strategy**: Kew-supervised theses are double-deposited (Kew repo + awarding-university IR). Key on normalized `title + first-author + year`; prefer awarding-university copy for degree metadata, Kew copy when university copy embargoed. Kew record's `Publisher:` field names the awarding university — use as join key [H].

## 7. Malaysia/Indonesia sweep

- **UPM psasir** ✅ OAI live (EPrints) — 21 orchid-title theses; harvest divisions filtered by thesis type. P1.
- **UMS eprints** ⛔ empty response today (host up earlier per wide04's OpenAlex data: 15 Orchidaceae). Retry later; OpenAlex fallback.
- **UM Malaya eprints.um.edu.my** — `/cgi/oai2` returned a redirect/HTML notice, not OAI; OAI likely disabled or moved; investigate `umexpert`/MyTO (Malaysian thesis union) as alternative [M].
- **IPB/Bogor** ✅ OAI live at legacy `/oai/request` (DSpace; `/server/oai/request` = Angular HTML — confirms wide04's dual-path rule in reverse: this DSpace still on 5/6-style path).

## 8. Mycoheterotrophy triangle

- **Bayreuth EPub** ✅ OAI; orchid-keyword search live (multi-page; ≥10 hits); 7 Orchidaceae dissertations (Gebauer stable-isotope theses incl. Schweiger 4098). Explicit non-commercial metadata/data reuse policy in Identify.
- **KU Leuven Lirias** ✅ OAI (gzip). Jacquemyn-group theses; small n, unique content.
- **Imperial Spiral** ✅ OAI verified today (DSpace 7 redirect). 7 Orchidaceae dissertations (Bidartondo mycorrhiza).

## 9. Conflicts / updates vs wide04

1. **Imperial Spiral**: wide04 "standard (untested)" → **verified live** (301 to `/server/oai/request`). Upgrade to [H].
2. **Cornell eCommons**: wide04 listed base `/oai/request`; actual canonical base is **`/server/oai/request`** (redirect). Update endpoint.
3. **Kew repo size**: wide04 cited 5,106 records/105 theses (2023) → **9,361 OAI records today**; thesis count estimate revised 130–180 [M].
4. **Leiden OpenDissertations**: now quantified — **7,764 records** (wide04 gave no count).
5. **CUNY data policy**: bepress OAI Identify explicitly restricts **full-content robot harvesting** (written approval) — wide04 flagged none. Metadata harvest OK; plan permission request or OpenAlex-located PDFs.
6. **UCL/QMUL/RHUL**: wide04 assumed harvestable → all three WAF-blocked to scripts today (browser fallback required). QMUL/RHUL endpoints presumed live behind WAF [M].
7. **teses.usp.br**: wide04 "OAI unverified" → **confirmed NO OAI** (404); crawler/BDTD path required.
8. **OpenAlex quota**: exhausted during this run (shared budget); orchid counts reuse wide04's same-day cached queries — no conflict.

## 10. Unknowns / remaining gaps

- UWA Esploro OAI exact base URL (probe `/view/oai`) — unconfirmed.
- ANU Digital Collections machine-harvest path (REST API? sitemap?) — unresolved.
- Kew thesis-type OAI filtering: no dedicated set (single admin set); must filter on `dc:type` = Thesis after harvest.
- UM Malaya & MyTO national aggregator endpoint.
- Bayreuth/Leiden orchid keyword totals (EPrints/Leiden UI pagination blocked exact counts).
- USP: whether BDTD exposes a USP-scoped OAI set (other dimension).

## Source URLs

[^1^]: https://kew.iro.bl.uk/catalog/oai?verb=Identify (✅ today) ; count: ListIdentifiers completeListSize=9361
[^2^]: https://scholarlypublications.universiteitleiden.nl/oai2?verb=ListSets (sets incl. hdl_1887_55785 OpenDissertations)
[^3^]: https://scholarlypublications.universiteitleiden.nl/oai2?verb=ListIdentifiers&metadataPrefix=oai_dc&set=hdl_1887_55785 (completeListSize=7764)
[^4^]: https://open.uct.ac.za/server/oai/request?verb=Identify (✅)
[^5^]: https://scholarspace.manoa.hawaii.edu/server/oai/request?verb=Identify (✅)
[^6^]: https://academicworks.cuny.edu/do/oai/?verb=Identify (✅; full-content robot restriction in dataPolicy)
[^7^]: https://epub.uni-bayreuth.de/cgi/oai2?verb=Identify (✅ EPrints 3.4.3)
[^8^]: https://era.ed.ac.uk/server/oai/request?verb=Identify (✅)
[^9^]: https://refubium.fu-berlin.de/oai/request?verb=Identify (✅)
[^10^]: https://biblio.ugent.be/oai?verb=Identify (✅)
[^11^]: https://lirias.kuleuven.be/oai?verb=Identify (✅)
[^12^]: https://ecommons.cornell.edu/server/oai/request?verb=Identify (✅ via curl)
[^13^]: https://scholarbank.nus.edu.sg/server/oai/request?verb=Identify (✅ via curl)
[^14^]: https://spiral.imperial.ac.uk/server/oai/request?verb=Identify (✅ via curl)
[^15^]: https://eprints.bbk.ac.uk/cgi/oai2?verb=Identify (✅)
[^16^]: https://centaur.reading.ac.uk/cgi/oai2?verb=Identify (✅)
[^17^]: http://psasir.upm.edu.my/cgi/oai2?verb=Identify (✅)
[^18^]: https://repository.ipb.ac.id/oai/request?verb=Identify (✅)
[^19^]: https://teses.usp.br/oai/request (404 — no OAI); https://teses.usp.br/ (200)
[^20^]: https://researchspace.ukzn.ac.za/ (⛔ timeout/000 from network)
[^21^]: https://discovery.ucl.ac.uk/cgi/oai2?verb=Identify (⛔ Cloudflare)
[^22^]: https://qmro.qmul.ac.uk/cgi/oai2?verb=Identify (⛔ JS challenge)
[^23^]: https://digitalcollections.anu.edu.au/oai (404); /api/oai (conn fail)
[^24^]: https://research-repository.uwa.edu.au/ (200; Esploro OAI path unconfirmed)
[^25^]: https://epub.uni-bayreuth.de/cgi/search/simple?q=orchid… (live search, paginated)
[^26^]: https://api.openalex.org (rate-limited $0 at probe time; counts reused from calyx_wide04.md [^9^–^12^])
[^27^]: https://kew.iro.bl.uk/concern/thesis_or_dissertations/9b20fe87-0cb1-4b9c-8a95-823130882c16 (Abreu exemplar; Publisher: University of Reading — dedupe join key)

*Compiled 2026-07-21 by dim05 probe agent. ⛔ statuses are network-relative; endpoints may be harvestable elsewhere.*
