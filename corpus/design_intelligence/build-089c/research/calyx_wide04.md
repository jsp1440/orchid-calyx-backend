# Calyx Wide Exploration — Facet Report

## Facet: Botanical Priority Sources

Scope: subject-specific layer beneath the global ETD aggregators — which institutions, herbaria, botanic gardens and repositories actually hold orchid/plant-science graduate research. All OAI-PMH endpoints below were tested live on **2026-07-21** (OAI `Identify` verb) unless marked otherwise. Confidence tags: **[H]**igh / **[M]**edium / **[L]**ow.

### Key Findings

1. **RBG Kew runs its own open repository with a dedicated thesis work-type** — `kew.iro.bl.uk` (British Library Shared Repository Service, Hyku/Hyrax). It held **"105 theses and dissertations"** among ~5,106 records as of 2023 [^1^], including Kew-registered PhDs (awarded by partner universities, e.g. University of Reading) and Kew MSc theses. Orchid exemplar: Abreu (2021) *"Co-occurring Mediterranean orchids … Ophrys fusca and Ophrys dyris"*, supervised by M. Fay, "In Collection: PhD theses" [^2^]. **OAI-PMH verified: `https://kew.iro.bl.uk/catalog/oai`** (Blacklight OAI provider) [^3^][H].
2. **Leiden University / Naturalis is the densest verified orchid-dissertation hub in Europe.** Leiden's Scholarly Publications repository hosts full-text orchid PhDs from the Naturalis systematics group, e.g. Kusuma Wati (2021) *Systematics, epidermal defense and bioprospecting of wild orchids* [^4^] and Subedi (2011) *New species, pollinator interactions and pharmaceutical potential of Himalayan orchids* [^5^]. **OAI-PMH verified: `https://scholarlypublications.universiteitleiden.nl/oai2`**, with dedicated `Dissertations` and `OpenDissertations` OAI sets [^6^][H]. Naturalis also runs its own IR (`repository.naturalis.nl`) for series such as the Leiden Botanical Series [^7^].
3. **Orchid dissertation volume (OpenAlex, queried 2026-07-21):** Orchidaceae concept `C2781370656` (18,728 works overall) [^8^]; `type:dissertation` + full-text "orchid" = **5,767** [^9^]; + full-text "Orchidaceae" = **2,296** [^10^]; + Orchidaceae concept = **497** [^11^]; + "orchid" in title = **527** [^12^]. OATD indexes ~7.4M OA theses globally (could not re-query for orchid subset — Cloudflare) [^13^][H for totals, M for subset estimates].
4. **Source-level concentration (OpenAlex group_by, dissertations mentioning "Orchidaceae", n=2,296):** LA Referencia (Latin America federation) 388; Universidad Industrial de Santander (Colombia) 37; OpenUCT 36; Lume/UFRGS 31; IRDB (Japan) 31; RCAAP (Portugal) 27; ResearchSpace UKZN 24; SUNScholar 20; UPM (Malaysia) 18; ScholarSpace UH Mānoa 17; HAL 17; Shodhganga 17; UMS Sabah 15; eScholarship 14; Digilib Unila (Indonesia) 12; UWA 8; Ghent 8; Imperial Spiral 7; EPub Bayreuth 7; ANU 6; Minerva Access 6; eCommons Cornell 5; MINDS@UW 4; Leiden 4 (partial — many Leiden theses surface under other sources); UPSpace 3 [^10^]. For title-contains-"orchid" (n=527): LA Referencia 50; Czech National Repository of Grey Literature (NUŠL) 44; Shodhganga 42; **Universiti Putra Malaysia 21**; UWA 10; ScholarSpace UH 9; ANU 7; theses.fr 7 [^12^].
5. **Latin America is the single largest orchid-dissertation region by open full-text.** UNAM's Repositorio Institucional (`repositorio.unam.mx`) is CC-licensed and **OAI-PMH verified: `https://repositorio.unam.mx/oai/request`** [^14^][H]; Mexican orchid output also flows through ECOSUR's DSpace (`ecosur.repositorioinstitucional.mx`) [^15^] and Jardín Botánico/INECOL-affiliated programs. Note much Mexican output is *tesis de licenciatura* (undergraduate) — filter by degree level.
6. **Jardim Botânico do Rio de Janeiro (Escola Nacional de Botânica Tropical, ENBT)** produced ≥144 graduate works 2005–2014 (46 doctoral theses + 98 master's dissertations; verbatim: "It had been identified 46 theses … and 98 dissertations") including orchid taxonomy (e.g., Menini Neto 2011, *Sistemática de Pseudolaelia (Orchidaceae)*) [^16^]. JBRJ publishes defense metadata as open data (CKAN) [^17^]; **no standalone JBRJ DSpace was found** — full texts route via BDTD/CAPES (other agents' facet) [L-M].
7. **South African orchid/botany theses are openly harvestable**: OpenUCT (DSpace; **OAI verified** `https://open.uct.ac.za/oai/request`) [^18^]; SUNScholar (**OAI verified** `https://scholar.sun.ac.za/server/oai/request`) [^19^]; UPSpace (**OAI listed** in COAR IRD as `https://repository.up.ac.za//oai/request`, curl from our network failed) [^20^][M]; ResearchSpace UKZN (Steve Johnson pollination-biology school; site unreachable from our network — likely firewall/geo-block; OpenAlex harvested 24 Orchidaceae dissertations from it) [^10^][M].
8. **US botanical-powerhouse repositories are OAI-harvestable**: Cornell eCommons (L.H. Bailey Hortorium/Plant Biology; **verified** `https://ecommons.cornell.edu/oai/request`) [^21^]; UH Mānoa ScholarSpace (tropical botany; **verified** `https://scholarspace.manoa.hawaii.edu/server/oai/request`; UH hosts 9 orchid-title + 17 Orchidaceae dissertations in OpenAlex) [^22^][H]; UW–Madison MINDS@UW (**verified** `https://minds.wisc.edu/server/oai/request`; Dept. of Botany community exists, handle 1793/35948) [^23^]; eScholarship/UC (**verified** `https://escholarship.org/oai`; public GraphQL API, no credentials) [^24^]; OSU Knowledge Bank (OAI live at `https://kb.osu.edu/oai/request`) [^25^][H]; UF's ETDs live in UF Digital Collections (platform rebuilt — OAI endpoint unconfirmed) [^26^][M]. CUNY Academic Works (NYBG–CUNY Plant Sciences PhDs; **verified** bepress OAI `https://academicworks.cuny.edu/do/oai/`) [^27^][H].
9. **Australia/NZ orchid theses concentrate at ANU + UWA + Melbourne**: ANU Digital Collections (`digitalcollections.anu.edu.au`) hosts flagship orchid work, e.g. 2026 thesis *Understanding Australian Orchids and their Mycorrhizal Fungi* (Diurideae phylogenomics, Pterostylis GBS) [^28^][H]; the legacy `openresearch-repository.anu.edu.au` domain no longer resolves — platform migrated [M]. UWA (Kings Park/Kingsley Dixon orchid-conservation axis) holds 10 orchid-title dissertations in OpenAlex [^12^].
10. **Mycoheterotrophy/mycorrhiza flagship labs are in OAI-open repositories**: University of Bayreuth EPub (**verified** EPrints OAI `https://epub.uni-bayreuth.de/cgi/oai2`) — Gebauer lab stable-isotope orchid theses (e.g., Schweiger/Schiebold dissertation) [^29^][H]; KU Leuven Lirias (**verified** `https://lirias.kuleuven.be/oai`) — Jacquemyn orchid-mycorrhiza group [^30^]; Imperial College Spiral (7 Orchidaceae dissertations — Bidartondo) [^10^]; Ghent University Biblio (**verified** `https://biblio.ugent.be/oai`) — Meise Botanic Garden partner [^31^]; FU Berlin Refubium (**verified** `https://refubium.fu-berlin.de/oai/request`) — BGBM-linked botany theses [^32^].
11. **Asia**: ScholarBank@NUS **OAI verified** (`https://scholarbank.nus.edu.sg/server/oai/request`) — Singapore Botanic Gardens-linked botany [^33^]. Malaysia is a standout: UPM 21 orchid-title dissertations, UMS Sabah 15 Orchidaceae dissertations (OpenAlex) [^10^][^12^]. CAS institutes run Chinese-language IRs with theses: XTBG-IR (est. 2011, "contains … doctoral theses and dissertations", >200k downloads claimed) [^34^][H for existence, L for OA coverage]; KIB (Kunming) IR similar; access/embargo varies. Japan's IRDB aggregates Kyoto U and others (31 Orchidaceae dissertations) [^10^].
12. **UK doctoral training structure matters for targeting**: Kew PhDs are registered at partner universities via DTPs — TREES (UCL-led: QMUL, Royal Holloway, Birkbeck, KCL, Brunel + Kew/NHM/ZSL; final cohort 2029), SSCP (Imperial + Kew), LIDo (BBSRC) [^35^][^36^][H]. So Kew-linked theses scatter across UCL Discovery, QMUL, Royal Holloway Pure, Birkbeck BIROn, Imperial Spiral, Reading CentAUR **and** the Kew repository — harvest both ends.
13. **Botanical institution libraries mostly index rather than host theses.** Missouri Botanical Garden's Peter H. Raven Library is a BHL contributor; MOBOT trains graduates via Washington University/UMSL/SLU — theses land in those universities' repositories, not Tropicos (specimen data) [^37^][M]. Smithsonian's repository.si.edu (DSpace-based Smithsonian Research Online) exists but was Cloudflare-blocked to scripted OAI tests [^38^][M]. Kew's own repository (Finding #1) is the exception: a botanic garden that *does* host theses openly.
14. **Wageningen**: all WUR PhD theses via "Wageningen University & Research eDepot" (`edepot.wur.nl`, live) + "WUR MSc theses online" + Research@WUR portal [^39^][H for existence, M for OAI]. Strong horticulture/phylogenetics but relatively few orchid-taxonomy theses (1 orchid-title dissertation in OpenAlex) [^12^].
15. **USP** `teses.usp.br` (TEDE/BDTD-USP) is fully open ("repositório … de acesso aberto — qualquer pessoa pode pesquisar e baixar os PDFs sem cadastro ou login"), occasional author embargo [^40^][H]. Orchid taxonomy theses exist across USP/UNICAMP/UFRGS/UNESP (Lume UFRGS alone: 31 Orchidaceae dissertations) [^10^].

### Priority Institution Profiles

| Institution | Program strength | Repository URL | Platform | OAI-PMH endpoint (status 2026-07-21) | OA policy | Orchid relevance (1–10) | Est. botanical thesis volume |
|---|---|---|---|---|---|---|---|
| **Royal Botanic Gardens, Kew** (+ partner unis: QMUL, Royal Holloway, UCL, Birkbeck, Imperial, Reading) | World #1 orchid science (Chase/Fay/Bidartondo); Kew–QMUL MSc Plant & Fungal Taxonomy; DTP-hosted PhDs | https://kew.iro.bl.uk | Hyku (BL Shared Repository) | `https://kew.iro.bl.uk/catalog/oai` ✅ | Green OA, UKRI/Plan S compliant | **10** | 105 theses/dissertations (2023) [^1^]; more at partner-university IRs |
| **Leiden University / Naturalis Biodiversity Center** | Malesian orchid systematics (Gravendeel), mycoheterotrophs (Merckx); Leiden Botanical Series | https://scholarlypublications.universiteitleiden.nl ; https://repository.naturalis.nl | Custom (DARE/DAREnet lineage) | `https://scholarlypublications.universiteitleiden.nl/oai2` ✅ (sets: Dissertations, OpenDissertations) | Theses OA with licence agreement | **10** | Dozens of orchid PhDs 2000s–2020s |
| **University of KwaZulu-Natal** | Steve Johnson pollination-biology school — orchid pollination/deception | https://researchspace.ukzn.ac.za | DSpace | expected `/oai/request` — unreachable from test network ⛔ | OA mandate | **9** | 24 Orchidaceae dissertations (OpenAlex sample) |
| **Australian National University (+ ANBG)** | Australian terrestrial orchids, orchid–mycorrhizal fungi, Diurideae | https://digitalcollections.anu.edu.au | New custom platform (ex-DSpace "ANU Open Research") | not found on new platform ⛔ | OA theses | **9** | 7 orchid-title dissertations (OpenAlex) |
| **University of Hawai'i at Mānoa** | Tropical botany, Hawaiian/Pacific orchids, Lyon Arboretum | https://scholarspace.manoa.hawaii.edu | DSpace 7 | `https://scholarspace.manoa.hawaii.edu/server/oai/request` ✅ | OA repository | **8** | 9 orchid-title + 17 Orchidaceae dissertations |
| **University of Cape Town (Bolus/Compton herbaria, SANBI links)** | Cape flora, orchid systematics/ecology | https://open.uct.ac.za | DSpace 7 | `https://open.uct.ac.za/oai/request` ✅ | OA policy (2014); theses auto-deposited | **8** | 36 Orchidaceae dissertations (OpenAlex) |
| **UNAM (Instituto de Biología + Facultad de Ciencias)** | Mexican orchid megadiversity (Salazar, Soto-Arenas legacy) | https://repositorio.unam.mx | Custom (DGB UNAM) | `https://repositorio.unam.mx/oai/request` ✅ | CC BY-NC-ND licenses | **8** | Large; LA Referencia federation = 388 Orchidaceae dissertations across nodes |
| **Universiti Putra Malaysia / Universiti Malaysia Sabah** | Malesian orchid taxonomy, horticulture | upm / ums IRs (DSpace) | DSpace | standard DSpace `/oai/request` (not individually tested) | OA | **8** | UPM 21 orchid-title; UMS 15 Orchidaceae (OpenAlex) |
| **Stellenbosch University (+ Compton Herbarium/SANBI)** | Cape botany, pollination, restoration | https://scholar.sun.ac.za | DSpace 7 | `https://scholar.sun.ac.za/server/oai/request` ✅ | OA | **7** | 20 Orchidaceae dissertations |
| **University of Western Australia (+ Kings Park BG)** | Orchid conservation, mycorrhizal symbiosis (Dixon), Rhizanthella | UWA Profiles & Research Repository | Esploro | unverified | OA theses | **8** | 10 orchid-title dissertations |
| **Cornell University (L.H. Bailey Hortorium)** | Plant systematics, neotropical botany | https://ecommons.cornell.edu | DSpace 7 | `https://ecommons.cornell.edu/oai/request` ✅ | OA | **7** | 5 Orchidaceae + broad botany ETDs |
| **University of Florida** | Orchid micropropagation/germination (Kane lab, Env. Horticulture); FLMNH | https://ufdc.ufl.edu (ETD collection) | Custom UFDC (rebuilt) | legacy `/oai2` unconfirmed ⚠ | OA ETDs | **7** | Large ETD corpus; orchid subset small but specialized |
| **University of Wisconsin–Madison (Botany, WIS herbarium)** | Plant systematics/ecology | https://minds.wisconsin.edu + UWDC | DSpace 7 | `https://minds.wisc.edu/server/oai/request` ✅ | OA | **6** | 4 Orchidaceae dissertations; Botany community 1793/35948 |
| **UC system (Berkeley/Davis/Riverside/Irvine)** | Jepson flora, plant evolution | https://escholarship.org | eScholarship (CDL) | `https://escholarship.org/oai` ✅ + public GraphQL | UC OA policy | **6** | 14 Orchidaceae dissertations |
| **CUNY Graduate Center + NYBG** | Joint Plant Sciences PhD based at NYBG (orchid systematics, genomics) | https://academicworks.cuny.edu | bepress Digital Commons | `https://academicworks.cuny.edu/do/oai/` ✅ | OA | **8** | Program-scale (tens of plant-science PhDs/decade) |
| **University of Bayreuth** | Stable-isotope mycoheterotrophy lab (Gebauer) | https://epub.uni-bayreuth.de | EPrints 3.4 | `https://epub.uni-bayreuth.de/cgi/oai2` ✅ | OA (DFG-compliant) | **7** | 7 Orchidaceae dissertations |
| **KU Leuven** | Orchid mycorrhiza/population biology (Jacquemyn) | https://lirias.kuleuven.be | Lirias | `https://lirias.kuleuven.be/oai` ✅ | OA mandate | **7** | Small, highly targeted |
| **Imperial College London (+ Kew)** | Orchid mycorrhiza (Bidartondo) | https://spiral.imperial.ac.uk | Spiral | standard (untested) | OA theses | **7** | 7 Orchidaceae dissertations |
| **Ghent University (+ Meise Botanic Garden)** | African orchids, Apocynaceae | https://biblio.ugent.be | Biblio | `https://biblio.ugent.be/oai` ✅ | OA | **6** | 8 Orchidaceae dissertations |
| **FU Berlin (+ BGBM)** | Botanic Garden Berlin-linked botany | https://refubium.fu-berlin.de | DSpace | `https://refubium.fu-berlin.de/oai/request` ✅ | OA | **5** | 3 Orchidaceae dissertations |
| **Wageningen University & Research** | Horticulture, biosystematics (Herbarium Vadense legacy now at Naturalis) | https://edepot.wur.nl ; library.wur.nl | eDepot + Pure | untested | All PhD theses OA | **5** | Very large total; ~1 orchid-title dissertation |
| **University of Edinburgh (+ RBGE)** | RBGE-linked tropical botany (Begoniaceae, Zingiberales) | https://era.ed.ac.uk | DSpace 7 | `https://era.ed.ac.uk/server/oai/request` ✅ | OA theses | **5** | Moderate |
| **NUS (+ Singapore Botanic Gardens)** | SE Asian botany, orchid breeding history | https://scholarbank.nus.edu.sg | DSpace 7 | `https://scholarbank.nus.edu.sg/server/oai/request` ✅ | OA | **6** | Moderate |
| **CAS: KIB (Kunming) + XTBG** | SW China orchid conservation hotspot research | ir.kib.ac.cn / XTBG-IR | CAS IR Grid | unverified ⚠ | Partial OA, Chinese metadata | **7** (content) | Significant, poorly exposed |
| **JBRJ / ENBT (Rio)** | Brazilian orchid taxonomy school | via BDTD/CAPES; CKAN defense data | — | none found | BDTD OA | **8** (content) | ≥144 theses+dissertations 2005–2014 |
| **Ohio State (Herbarium OS)** | Plant systematics | https://kb.osu.edu | DSpace | `https://kb.osu.edu/oai/request` ✅ (live) | OA | **4** | Large general corpus |
| **University of Pretoria (+ SANBI/PRE)** | Southern African flora | https://repository.up.ac.za | DSpace | `https://repository.up.ac.za//oai/request` (COAR-listed; curl failed) ⚠ | OA | **6** | 3 Orchidaceae dissertations (OpenAlex) |
| **USP / UNICAMP / UFRGS / UNESP (Brazil)** | Orchid pollination (Singer), taxonomy | teses.usp.br; Lume (UFRGS); repositório UNESP | TEDE/DSpace | USP OAI unverified ⚠; UFRGS DSpace standard | OA | **8** | UFRGS 31, UNESP 7 Orchidaceae dissertations |

### Botanical Institution Libraries

| Library / institution | Holdings relevant to theses | Access |
|---|---|---|
| **RBG Kew — Kew Research Repository** (distinct from Kew Library catalogue) | Directly **hosts** PhD/MSc theses incl. orchid work (105 theses, 2023; growing) | Open web + OAI-PMH ✅ [^1^][^3^] |
| **Missouri Botanical Garden — Peter H. Raven Library** | Catalogue indexes botany literature; MOBOT grad students register at WashU/UMSL/SLU; Tropicos = specimens, not ETDs | BHL for legacy lit; theses via partner-university IRs [^37^][M] |
| **NYBG — LuEsther T. Mertz Library** | Supports CUNY Plant Sciences PhD program physically based at NYBG | Theses → CUNY Academic Works ✅ OAI [^27^] |
| **Smithsonian (NMNH Botany + SIL)** | Smithsonian Research Online (repository.si.edu, DSpace) hosts staff output; Smithsonian confers no degrees — fellows' theses stay at home universities (e.g., GWU) | Cloudflare-blocked to scripts; human access fine [^38^][M] |
| **Royal Botanic Garden Edinburgh Library** | RBGE students register at Univ. Edinburgh (ERA ✅) and other Scottish unis | ERA OAI-PMH ✅ [H] |
| **Naturalis/Leiden** | repository.naturalis.nl for institutional series; Leiden theses ✅ OAI | [^6^][^7^] |
| **Meise Botanic Garden** | No own ETD host; theses via Ghent Biblio ✅ OAI | [^31^] |
| **BGBM Berlin** | No own ETD host; theses via FU Refubium ✅ OAI | [^32^] |
| **JBRJ Barbosa Rodrigues Library** | Historically curates ENBT theses; citation study confirms holdings [^16^]; defenses published as CKAN open data [^17^] | Full text via BDTD |
| **Field Museum** | No degree program/thesis repository; joint programs (U Chicago, UIC) → those IRs | [M] |

### Orchid Dissertation Concentration Map

**Regions (by open-repository dissertation volume, OpenAlex 2026-07-21 samples):**
1. **Latin America** — dominant: LA Referencia 388 Orchidaceae dissertations (Colombia UIS 37, UNAM/ECOSUR Mexico, Brazil UFRGS 31/UNESP 7/USP, Costa Rica 8). Topics: floristics, epiphyte diversity, Vanilla, taxonomy [^10^].
2. **South & SE Asia** — Malaysia (UPM 21 title-orchid; UMS 15), Indonesia (Unila 12, IPB, Andalas, Pasundan), Thailand (PSU 6), India (Shodhganga 42 title-orchid — other agent), China (KIB/XTBG IRs, weak OA), Japan (IRDB 31; Kyoto classic orchid germination theses; Kobe U mycoheterotrophy school) [^10^][^12^].
3. **Europe** — Czech NUŠL grey-lit 44 title-orchid (Central-European orchid ecology school, e.g. Jersáková); UK (Kew repo + Spiral + White Rose + BIROn); Germany (Bayreuth 7, Würzburg 12, FU 3); Belgium (Ghent 8, KU Leuven); Netherlands (Leiden) [^10^][^12^].
4. **Africa** — South Africa (OpenUCT 36, UKZN 24, SUNScholar 20, UPSpace 3, UNISA, NWU Boloka 4): Cape orchid systematics + pollination biology [^10^].
5. **North America** — distributed (eScholarship 14, UH 17, TAMU 7, Cornell 5, UW 4, UBC 15); Florida orchid biology at UF/FIU [^10^].
6. **Oceania** — ANU 7 + UWA 10 title-orchid; terrestrial orchids + orchid mycorrhizal fungi (OMF) specialization; Massey/Canterbury NZ (terrestrial orchid ecology) [^12^].

**Topics → labs whose students' theses matter:**
- *Orchid–mycorrhiza / mycoheterotrophy*: Bayreuth (Gebauer), Imperial+Kew (Bidartondo), KU Leuven (Jacquemyn), Naturalis (Merckx), UWA/Kings Park (Dixon), ANU, Kobe U (Suetsugu) [^29^][^30^].
- *Pollination biology*: UKZN (Johnson), UFMG/USP (Singer lineage), Naples/Catania (Cozzolino lineage), Stellenbosch.
- *Taxonomy/systematics*: Kew (Chase/Fay — Ophrys, Goodyerinae), Leiden/Naturalis (Malesian Coelogyninae, Glomera), JBRJ (Pseudolaelia, Brazilian Laeliinae), UNAM (Mexican orchids), UPM/UMS (Malesian).
- *Conservation genetics*: ANU (Pterostylis GBS), UWA, Kew partners.
- *Horticulture/germination*: UF (Kane), UPM, Kyoto lineage.

### Trends & Signals

- **Botanic gardens increasingly self-host theses** (Kew repo is the model; BL shared Hyku service also serves NHM/British Library partners) — watch NHM's tenant on `bl.iro.bl.uk` for NHM-registered botany PhDs [^1^][H].
- **DSpace 7 migrations moved OAI-PMH to `/server/oai/request`** (ScholarSpace, MINDS, OpenUCT, SUNScholar, ERA, ScholarBank, eCommons) — legacy `/oai/request` paths often return the Angular app instead of XML; Calyx crawlers must try both [H, tested].
- **Repository platform churn**: ANU retired its DSpace domain for Digital Collections (2020s); UF rebuilt UFDC (React app, OAI unclear); harvest via OpenAlex `primary_location` pmh: IDs as fallback [M].
- **Cloudflare is a practical barrier**: repository.si.edu, researchspace.ukzn.ac.za, oatd.org all challenge scripted clients — plan browser-based or API-key access, or use OpenAlex/DataCite mirrors [^10^][^13^][H].
- **Latin-American orchid ETD growth** tracks national repository federations (LA Referencia, BDTD, repositorio.unam.mx OAI) — high-yield, CC-licensed, multilingual (PT/ES) [^10^][^14^].
- **Degree-type filtering needed** in Mexico/Brazil (licenciatura/TCC mixed with MSc/PhD) and Malaysia (undergrad projects in IRs) [H].
- **OpenAlex is an effective pre-harvest index**: its `pmh:oai:` location IDs encode the exact OAI endpoint + identifier per thesis (verified pattern: `pmh:oai:epub.uni-bayreuth.de:5317`) — Calyx can resolve sources → endpoints at scale [^9^][^11^][H].
- **Kew-linked theses are double-deposited** (Kew repo + degree-awarding university IR): dedupe on title/author [^2^][^35^][M].
- bioRxiv/BioOne do **not** host theses — exclude from Calyx acquisition, note only [H].

### Recommended Deep-Dive Areas

1. **Kew repository full harvest** (`kew.iro.bl.uk/catalog/oai`) + parallel sweeps of UCL Discovery, QMUL, Royal Holloway, Birkbeck BIROn, Imperial Spiral, Reading CentAUR for Kew-supervised orchid theses. Highest precision orchid source per record. [^1^][^35^]
2. **Leiden OAI sets** (`Dissertations`, `OpenDissertations`) filtered by Orchidaceae keywords — 25+ years of Naturalis orchid PhDs (Gravendeel/Merckx groups). [^4^][^6^]
3. **South African triangle**: OpenUCT + SUNScholar OAI harvests (verified) + UKZN ResearchSpace via browser/REST workaround — the Johnson school's orchid-pollination corpus. [^18^][^19^]
4. **LA Referencia nodes**: UNAM (OAI ✅), ECOSUR, UIS, UFRGS Lume, UNESP — quantify orchid subset; add degree-level filter. [^10^][^14^]
5. **Malaysia/Indonesia/Singapore**: UPM (21 orchid-title!), UMS, ScholarBank ✅, Unila/IPB — Malesian orchid taxonomy underexploited by Western aggregators. [^12^]
6. **Australia**: ANU Digital Collections (new platform — probe for API/OAI) + UWA repository; terrestrial orchid + OMF theses (2026 exemplar found). [^28^]
7. **Mycoheterotrophy triangle**: Bayreuth ✅ + Imperial Spiral + KU Leuven ✅ — small but uniquely high-value orchid-physiology theses. [^29^][^30^]
8. **CAS institutes** (KIB/XTBG): assess OA fraction vs. CNKI; SW-China orchid conservation theses largely invisible to OpenAlex. [^34^]
9. **JBRJ/ENBT backfile**: cross-walk CKAN defense metadata [^17^] with BDTD records (other agent) to complete the Brazilian orchid-taxonomy corpus.
10. **Cornell/Smithsonian/MOBOT triangle** for neotropical systematics: eCommons ✅; probe repository.si.edu via browser; WashU Open Scholarship for MOBOT-linked theses. [^21^][^37^][^38^]

### Source URLs

[^1^]: https://bl.iro.bl.uk/concern/conference_items/e7752eec-30b8-4144-bce2-7cb855efef93 — "The Kew repository now holds 5,106 publicly visible records … 105 theses and dissertations" (2023)
[^2^]: https://kew.iro.bl.uk/concern/thesis_or_dissertations/9b20fe87-0cb1-4b9c-8a95-823130882c16 — Abreu 2021 Ophrys thesis, "In Collection: PhD theses", Publisher: University of Reading
[^3^]: https://kew.iro.bl.uk/catalog/oai?verb=Identify — verified 2026-07-21 (Blacklight OAI provider)
[^4^]: https://scholarlypublications.universiteitleiden.nl/handle/1887/3157143 — Kusuma Wati 2021 wild orchids dissertation
[^5^]: https://scholarlypublications.universiteitleiden.nl/access/item%3A2936752/view — Subedi 2011 Himalayan orchids dissertation
[^6^]: https://scholarlypublications.universiteitleiden.nl/oai2?verb=ListSets — verified; sets include Dissertations, OpenDissertations, DAREnet
[^7^]: https://repository.naturalis.nl/ — Naturalis Institutional Repository (Leiden Botanical Series)
[^8^]: https://api.openalex.org/concepts?search=Orchidaceae — C2781370656, 18,728 works
[^9^]: https://api.openalex.org/works?filter=type:dissertation&search=orchid&per-page=1 — count 5,767
[^10^]: https://api.openalex.org/works?filter=type:dissertation&search=Orchidaceae&group_by=primary_location.source.id&per-page=100 — count 2,296 + source distribution
[^11^]: https://api.openalex.org/works?filter=type:dissertation,concepts.id:C2781370656&per-page=1 — count 497
[^12^]: https://api.openalex.org/works?filter=type:dissertation,title.search:orchid&group_by=primary_location.source.id&per-page=100 — count 527 + source distribution
[^13^]: https://oatd.org/ — "OATD currently indexes 7,464,811 theses and dissertations"
[^14^]: https://repositorio.unam.mx/oai/request?verb=Identify — "Repositorio Institucional UNAM", verified; example orchid thesis: https://repositorio.unam.mx/contenidos/ficha/polinizacion-y-morfologia-floral-de-tres-especies-de-orquideas-en-una-region-tropical-estacionalmente-seca-del-sur-de-122976
[^15^]: https://ecosur.repositorioinstitucional.mx/ — ECOSUR repository (DSpace)
[^16^]: http://www.repositorio-bc.unirio.br:8080/xmlui/bitstream/handle/unirio/10842/Disserta%C3%A7%C3%A3o%20vers%C3%A3o%20final_julho2017%20revista.pdf?sequence=1&isAllowed=y — Carneiro 2017 citation analysis of ENBT theses (46 theses, 98 dissertations 2005–2014)
[^17^]: https://ckan.jbrj.gov.br/dataset/defesas-de-dissertacoes-e-teses — JBRJ open data: thesis/dissertation defenses
[^18^]: https://libguides.lib.uct.ac.za/OpenUCT — OpenUCT OA policy; OAI verified https://open.uct.ac.za/oai/request?verb=Identify
[^19^]: https://scholar.sun.ac.za/server/oai/request?verb=Identify — "SUNScholar", verified
[^20^]: https://ird.coar-repositories.org/systems/e47a335c-a3af-4f41-8bc6-d8cd03f1f8eb — COAR IRD: UPSpace OAI-PMH base URL https://repository.up.ac.za//oai/request
[^21^]: https://ecommons.cornell.edu/oai/request?verb=Identify — verified
[^22^]: https://guides.library.manoa.hawaii.edu/c.php?g=648812&p=4550346 — ScholarSpace overview; OAI verified https://scholarspace.manoa.hawaii.edu/server/oai/request
[^23^]: https://www.library.wisc.edu/research-support/minds/ + https://minds.wisconsin.edu/handle/1793/35948 (Dept. of Botany); OAI verified https://minds.wisc.edu/server/oai/request
[^24^]: https://help.escholarship.org/support/solutions/articles/9000223035-about-escholarship-apis — "supports … KBart, OAI-PMH, and RSS/ATOM"; OAI verified https://escholarship.org/oai
[^25^]: https://kb.osu.edu/oai/request — live OAI (parameter-error response confirms endpoint)
[^26^]: https://ufdc.ufl.edu/ — "UF Digital Collections" (ETD host; platform rebuilt)
[^27^]: https://academicworks.cuny.edu/do/oai/?verb=Identify — "CUNY Academic Works", verified; NYBG–CUNY joint program attested by program alumni (https://www.x-mol.com/paper/1603247820650434560)
[^28^]: https://digitalcollections.anu.edu.au/items/86d1236a-3e8d-4343-a643-35b466a0eefb/full — "Understanding Australian Orchids and their Mycorrhizal Fungi" (ANU thesis, 2026)
[^29^]: https://epub.uni-bayreuth.de/cgi/oai2?verb=Identify — "EPub Bayreuth" (EPrints 3.4.3), verified; Schweiger dissertation https://epub.uni-bayreuth.de/4098/
[^30^]: https://lirias.kuleuven.be/oai?verb=Identify — verified
[^31^]: https://biblio.ugent.be/oai?verb=Identify — "Ghent University Institutional Archive", verified
[^32^]: https://refubium.fu-berlin.de/oai/request?verb=Identify — "Refubium", verified
[^33^]: https://scholarbank.nus.edu.sg/server/oai/request?verb=Identify — "ScholarBank@NUS", verified
[^34^]: http://english.xtbg.cas.cn/ptsc/au/lib/ — "XTBG-IR contains … journal articles, conference papers, doctoral theses and dissertations"
[^35^]: https://www.kew.org/science/training-and-education/phd-opportunities/available-phd-opportunities — Kew studentships with partner universities
[^36^]: https://www.ukri.org/publications/doctoral-landscape-awards/doctoral-landscape-award-investments/ — TREES DLA (UCL + Kew + NHM + ZSL; QMUL/RHUL/Birkbeck/KCL/Brunel)
[^37^]: https://www.biodiversitylibrary.org/ — MOBOT Raven Library as BHL contributor (theses via partner universities — inference)
[^38^]: https://repository.si.edu/ — Smithsonian Research Online (Cloudflare-challenged to scripted OAI test 2026-07-21)
[^39^]: https://www.wur.nl/en/library/databases-and-collections — "PhD Theses — search all WUR dissertations … WUR MSc theses online"; eDepot live at https://edepot.wur.nl
[^40^]: https://teses.usp.br/ (+ https://tesify.pt/usp-teses-dissertacoes-como-acessar-repositorio-2026/) — open access, no login

*Report compiled 2026-07-21. Endpoint statuses reflect live tests from this research environment on that date; endpoints marked ⚠/⛔ may still be harvestable from other networks.*
