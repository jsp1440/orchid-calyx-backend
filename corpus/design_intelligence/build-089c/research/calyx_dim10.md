# Calyx Dimension 10 — Legal Compliance Architecture for Automated Dissertation Acquisition & TDM

Research date: 2026-07-21. Build on wide-03 legal summary (calyx_wide03.md). Confidence tags: [HIGH] primary source / court holding / live gov document; [MED] reputable firm or scholarly analysis; [LOW] inference or unstable area.

**Calyx activities:** (a) metadata harvesting · (b) full-text download · (c) local TDM/analysis · (d) storing full text · (e) displaying excerpts · (f) redistributing derived data (entities/claims/citations) · (g) redistributing full text.

Legend: ✅ clear legal basis / low risk · ⚠️ conditional (see note) · ❌ not permitted / high risk · ◻ not jurisdiction-relevant.

---

## 1. United States

### Fair use for TDM
- *Authors Guild v. HathiTrust*, 755 F.3d 87 (2d Cir. 2014): creating a full-text searchable database is "a quintessentially transformative use"; non-expressive computational reuse (search, TDM, accessibility) is fair use. Limits: security measures mattered; display of more than search snippets would change the analysis.[^31^][^32^] [HIGH]
- *Authors Guild v. Google*, 804 F.3d 202 (2d Cir. 2015), cert. denied 136 S. Ct. 1658 (2016): whole-book scanning for search + *limited* snippets fair use; courts stressed Google's anti-leakage security.[^30^][^31^] [HIGH]
- 2024–2026 AI rulings (district level, all N.D. Cal./D. Del., non-binding but influential):
  - *Thomson Reuters v. Ross Intelligence*, No. 1:20-cv-613 (D. Del., Feb. 11, 2025, Bibas J.): **first rejection of fair use for AI training** — commercial, non-generative legal-research tool built on Westlaw headnotes; market harm (competing product + licensing market) decisive. Court itself limited the holding to non-generative AI.[^1748^][^1738^] [HIGH]
  - *Bartz v. Anthropic* (N.D. Cal., June 23, 2025, Alsup J.): training Claude on **lawfully acquired** books = "exceedingly transformative" fair use; digitizing purchased print = fair use; **building a permanent central library from pirated downloads (LibGen/PiLiMi) = NOT fair use** ("piracy of otherwise available copies is inherently, irredeemably infringing"). Case ended in a $1.5B class settlement (Sept 2025) with destruction of pirated datasets.[^1751^][^1745^][^1752^] [HIGH]
  - *Kadrey v. Meta* (N.D. Cal., June 25, 2025, Chhabria J.): fair use for training Llama **on this record only** — plaintiffs offered no market-dilution evidence; Chhabria warned the ruling "does not stand for the proposition that Meta's use … is lawful" and that "in many circumstances it will be illegal"; explicitly noted **nonprofit research uses (e.g., medical research) might survive even with some market dilution**. Torrenting/distribution claims left live.[^1759^][^1755^] [HIGH]
  - **US Copyright Office, *Copyright and AI, Part 3: Generative AI Training* (pre-publication, May 9, 2025)**: copying for training is prima facie infringement; fair use assessed on a "continuum of transformativeness" — research / closed, non-substitutive systems at the high-transformativeness end; expressive-content-generating commercial models at the low end; recognizes an emerging licensing market. Still marked pre-publication; Register Perlmutter's firing/reinstatement litigation left the report's status anomalous — **non-binding guidance, not law**.[^1902^][^1917^][^1918^] [HIGH for existence; MED for weight]
- **Net for Calyx (non-commercial scientific research, no generative outputs substituting theses):** activities (b)–(d)(f) on lawfully accessed full text sit in the strongest zone of US law (HathiTrust/Google + Kadrey nonprofit dicta + USCO "closed system/research" category). What they do NOT bless: (g) redistributing full text, and (b) acquiring from pirate/shadow sources or behind paywalls. [HIGH for cases; MED for extrapolation]

### Thesis ownership & licenses
- Copyright in an ETD vests in the **student author**; universities take a **non-exclusive** repository deposit license; ProQuest takes a non-exclusive distribution license (traditional publishing option) and sells access. No transfer of copyright is standard.[^36^][^1972^] [MED]
- **ProQuest contractual layer:** ProQuest/aggregators prohibit systematic downloading/scraping; the only sanctioned TDM channel is **ProQuest TDM Studio** (cloud environment; no export of full text). Library licenses warn that crawler use can get the *entire institution* cut off. **Calyx must not scrape ProQuest PQDT**; use institutional repositories instead.[^1964^][^1969^] [HIGH]

---

## 2. European Union

- **DSM Directive 2019/790 Art. 3** (transposed by all Member States): mandatory, **contract-override-proof** (Art. 7(1)) exception for TDM by **research organisations and cultural heritage institutions** for scientific research. Conditions: (i) **lawful access** (open access, subscriptions, or content freely available online); (ii) copies stored with appropriate security, retainable for verification of results. **Rightholders cannot opt out.**[^29^][^1831^][^1836^] [HIGH]
- **"Research organisation"** (Art. 2(1)): universities, research institutes, libraries, or any entity whose **primary goal is scientific research on a not-for-profit basis** (or reinvesting all profits in research), not controlled by a commercial undertaking that has preferential access to results. Calyx qualifies only if operated by/within such an entity; a spin-out with commercial control breaks Art. 3. [HIGH]
- **Art. 4**: TDM by anyone for any purpose **unless rightholders expressly reserve rights** ("opt-out"); for online content the reservation must be **machine-readable**.[^29^][^1830^] [HIGH]
- **Machine-readable opt-out standards (2026 state):**
  - **OLG Hamburg, Kneschke v. LAION, 5 U 104/24 (Dec. 10, 2025):** natural-language opt-outs in ToS are **insufficient** under Art. 4(3); reservation must be machine-readable (robots.txt, TDM Reservation Protocol/`tdm-reservation` HTTP header, ai.txt). (Underlying LG Hamburg 2024 decision had upheld LAION's Art. 3/60d research use.) [^1341^] [HIGH]
  - **TDMRep (W3C community spec):** `/.well-known/tdmrep.json` + `TDM-Reservation: 1` header; the most legally weighty signal; adoption growing but far from universal. ai.txt/llms.txt = conventions, not standards.[^1341^][^1835^] [MED]
  - **EU AI Act Art. 53(1)(c)** (in force for GPAI since Aug 2, 2025): GPAI providers must implement copyright policies and **state-of-the-art detection of Art. 4(3) reservations**; GPAI Code of Practice requires robots.txt (RFC 9309) compliance. Only directly binds model providers, but sets the de-facto crawling-compliance baseline.[^1341^][^1918^] [HIGH]
- **Sui generis database right** (Directive 96/9/EC Art. 7): protects databases showing substantial investment against extraction/reutilization of all/substantial parts. Harvesting **metadata aggregations** (e.g., re-harvesting an entire national ETD index) can trigger it even where individual records are uncopyrightable; repeated systematic extraction of insubstantial parts can also infringe. Art. 3 DSM gives research orgs an exception to it; Art. 4 too (subject to opt-out). **Ryanair v. PR Aviation, C-30/14 (CJEU 2015):** where a database enjoys *neither* copyright *nor* sui generis protection, the owner may still impose **contractual** restrictions (browsewrap ToS enforceable under national law) — contract fills the IP gap.[^1815^][^1812^] [HIGH]
- Practical rule: metadata harvesting of OAI-PMH endpoints = designed-for-harvesting, low risk; but bulk re-extraction of a *curated commercial* database's metadata ≠ same thing.

---

## 3. United Kingdom (post-Brexit)

- **No DSM transposition.** Only TDM exception: **CDPA 1988 s.29A** — computational analysis for the **sole purpose of non-commercial research**, lawful access required, sufficient acknowledgment, copy **not transferable to any other person**; contract-override-proof (s.29A(5)); does NOT cover communication to the public. Kretschmer (CREATe, Jan 2026 evidence): s.29A(2)(a) transfer ban creates uncertainty even for academic consortia/shared corpora.[^1909^][^1908^] [HIGH]
- **2024–2026 policy arc:** Dec 2024–Feb 2025 consultation (11,520 responses; 81–88% favored licensing-in-all-cases, 3% favored the government's preferred opt-out exception); House of Lords Comms & Digital Committee report (HL 267, Mar 6, 2026) called the opt-out proposal unworkable, recommended licensing + transparency; **Government's statutory Report + Impact Assessment under Data (Use and Access) Act 2025 ss.135–136 (Mar 18, 2026): DROPPED the broad TDM exception — "wait and see", industry-led licensing, status quo preserved.** s.29A remains the only exception.[^1743^][^1744^][^1905^][^1907^] [HIGH]
- *Getty Images v. Stability AI* [2025] EWHC 2863 (Ch), Nov 4, 2025: model weights are not "infringing copies" (no stored copies in the model); primary-infringement/training claims dropped for lack of UK nexus — **UK lawfulness of scraping-to-train remains unresolved**; appeal on secondary infringement granted Dec 2025.[^1913^][^1916^] [HIGH]
- **For Calyx:** as a non-commercial research project with lawful access, s.29A covers (b)(c)(d) for analysis; (e)(f) need separate justification (quotation exception s.30 criticism/review with acknowledgment; derived-data is facts); (g) ❌.

---

## 4. Japan, Singapore, Switzerland, and other favorable regimes

### Japan — Copyright Act Art. 30-4 (broadest major-jurisdiction regime)
- Exploitation of works "not for the purpose of enjoying the thoughts or sentiments expressed" is permitted **in any way, to the extent necessary** — expressly includes machine learning/information analysis; **no non-commercial limitation, no lawful-access requirement, no opt-out** (2018 amendment, in force 2019).[^1642^][^1662^] [HIGH]
- **Agency for Cultural Affairs, "Perspectives Regarding AI and Copyright" (Mar 15, 2024) + General Understanding:** Art. 30-4 does NOT apply where enjoyment and non-enjoyment purposes co-exist (e.g., training to output a specific work's expression; **RAG input databases intended to surface creative expression**); proviso bars uses unreasonably prejudicing the owner (market conflict, e.g., mining a database *sold for* data analysis); technological protection measures/robots.txt-type barriers may negate the exception.[^1651^][^1833^][^1842^] [HIGH]
- For Calyx: analysis corpus of theses = clean Art. 30-4(ii) use; a **RAG system that retrieves and displays thesis text verbatim risks falling outside 30-4** per the Bunka-chō view. [MED]

### Singapore — Copyright Act 2021, computational data analysis (CDA) exception (ss. 243–244)
- Copying/communication for CDA permitted for **any purpose incl. commercial**, contract-override-proof; conditions: **lawful access** (no circumvention of paywalls/TPMs), copies not distributed to others (except verification/collaboration among researchers), derived works not infringing. One of the two most permissive regimes with Japan.[^1643^][^1780^ (cf.)] [MED — no primary text retrieved this pass; section numbers per ICLG/Intepat summaries]

### Switzerland
- **No general TDM exception.** Research exception **Art. 24d CopA**: use for scientific research where reproduction is integral to a technical process and access is legal; covers public **and private** research, but the **primary purpose must be scientific research** (parallel commercial purpose tolerated only if secondary). Whether scraping publicly available works = "legal access" is debated.[^1780^] [MED]

### Others (brief)
- **South Korea:** AI Basic Act in force Jan 2026 (risk-based framework); copyright TDM exception bills pending — monitor. [LOW]
- **Germany:** Art. 3/4 transposed as UrhG §§44b/60d; Kneschke/LAION line above; Nov 2025 Munich I decision against OpenAI (lyrics memorization = infringement) shows output-side risk.[^1776^] [MED]

---

## 5. China, Brazil, India

### China
- **No TDM exception** in PRC Copyright Law; fair-use-style three-step closed list. Court signals (2023–24 Guangzhou/Beijing AI cases) mixed. [MED]
- **Access layer dominates:** CNKI underwent CAC **cybersecurity review** (June 2022) and **suspended foreign access to dissertation/thesis, census and statistical databases from Apr 1, 2023** pending review of cross-border services; the Data Security Law + PIPL + cross-border data rules make bulk export of Chinese academic databases legally fraught. CNKI theses are also licensed works — authors have sued CNKI (Zhao Dexin case) over uncompensated distribution. **Calyx rule: do not bulk-harvest CNKI full text; metadata via licensed channels only.**[^1790^] [HIGH for CNKI events]

### Brazil
- **Lei 9.610/98:** closed list of exceptions (arts. 46–48), **no TDM exception**; STJ/CJF Statement 115 reads the list extensively per fundamental rights — flexible but untested for TDM.[^1963^][^1967^] [HIGH]
- **PL 2338/2023 (AI Framework):** Senate approved Dec 10, 2024; in Chamber of Deputies (special committee) as of mid-2026, copyright the main deadlock; **not enacted**. Senate text **Art. 42** would create a TDM exception for research/journalism organizations, museums, archives, libraries: no mere-reproduction purpose, necessity, no unjustified harm, no competition with normal exploitation, lawful access, security of retained copies; the disclosure/opt-out/remuneration chapter **does not apply to non-commercial research organizations**.[^1966^][^1820^][^1818^] [HIGH for status]
- LGPD applies to personal data in theses (mirrors GDPR analysis below). [MED]

### India
- **No TDM exception; s.52 fair dealing is a closed list** (research/private study/criticism/review) interpreted strictly; DPIIT's Dec 2025 Working Paper (Part 1) proposes a **hybrid compulsory-licensing model** ("one nation, one licence, one payment", CRCAT royalty body); consultation closed Jan 7, 2026; **no statutory amendment as of July 2026**.[^1643^][^1788^][^1777^] [HIGH]
- **ANI Media v. OpenAI, CS(COMM) 1028/2024 (Delhi HC):** four issues framed (storage = infringement? outputs? s.52? jurisdiction); amici split; interim relief argued over 32 hearings; **judgment reserved by Justice Amit Bansal (Apr 2026) — pending**. Watch-case for all India-sourced content.[^1776^][^1793^] [HIGH]
- **Shodhganga (INFLIBNET):** ~475k+ full-text theses, open access; universities grant INFLIBNET non-exclusive hosting rights; repository states **CC BY-NC-SA 4.0** for hosted ETDs → NC blocks commercial reuse, SA applies to adaptations; documented misuse (theses republished as e-books) shows enforcement weakness but doesn't enlarge Calyx's rights. DSpace/OAI-PMH harvestable.[^681^][^1972^] [HIGH]

---

## 6. Activity × Jurisdiction matrix

Assumptions: Calyx is (or is hosted by) a non-commercial research organisation; access is lawful (OA repositories, OAI-PMH, licensed APIs); no paywall circumvention; no pirate sources.

| Jurisdiction | (a) metadata | (b) FT download | (c) local TDM | (d) store FT | (e) display excerpts | (f) redistribute derived data | (g) redistribute FT |
|---|---|---|---|---|---|---|---|
| **US** | ✅ facts/thin ©; Feist | ✅ if lawful access (HathiTrust/Bartz lawful-input line) | ✅ fair use, research = strongest end | ✅ w/ security (Bartz: permanent *pirated* library ❌) | ⚠️ short snippets w/ attribution; fair-use quantity limits | ✅ facts/entities not ©able (Feist); cite sources | ❌ |
| **EU** | ✅ (watch sui generis on curated DBs) | ✅ Art. 3 (research org, lawful access); else ⚠️ Art. 4 opt-out check | ✅ Art. 3 mandatory | ✅ Art. 3 (security, retention for verification) | ⚠️ quotation right (InfoSoc 5(3)(d), attribution, only as needed) | ✅ facts; sui generis re-check for DB-structured exports | ❌ (not covered by Art. 3/4) |
| **UK** | ✅ | ✅ s.29A (non-commercial, lawful access) | ✅ s.29A | ⚠️ s.29A(2)(a): no transfer to others; keep internal | ⚠️ s.30 quotation (criticism/review, acknowledgment) | ✅ facts | ❌ |
| **Japan** | ✅ | ✅ Art. 30-4 | ✅ Art. 30-4 (broadest) | ✅ | ⚠️ RAG-style surfacing of expression may lose 30-4 cover | ✅ | ❌ Art. 30-4 is non-enjoyment only |
| **Singapore** | ✅ | ✅ s.243–244 CDA (lawful access) | ✅ (commercial OK too) | ✅ w/ conditions | ⚠️ | ✅ | ❌ |
| **Switzerland** | ✅ | ⚠️ Art. 24d (primary research purpose; "legal access" debate) | ⚠️ same | ⚠️ | ⚠️ quotation right | ✅ | ❌ |
| **China** | ⚠️ cross-border/data-security review for CNKI-type sources | ❌ bulk CNKI FT (license + DSL/PIPL) | ⚠️ no TDM exception; low enforcement risk for internal research | ⚠️ | ⚠️ | ⚠️ export-control & data-security review | ❌ |
| **Brazil** | ✅ | ⚠️ no exception until PL 2338 enacted; STJ flexible reading helps research | ⚠️ same | ⚠️ | ⚠️ art. 46 quotation limits | ✅ facts | ❌ |
| **India** | ✅ | ⚠️ closed fair dealing; research limb arguable; ANI pending | ⚠️ same; non-commercial research strongest | ⚠️ | ⚠️ s.52 criticism/review | ✅ facts | ❌ |
| **Shodhganga content (CC BY-NC-SA)** | ✅ | ✅ license permits | ✅ non-commercial | ✅ | ✅ w/ attribution | ⚠️ SA: share adaptations under BY-NC-SA | ⚠️ verbatim redistribution allowed by license (NC-SA, attribution) but not by Calyx policy for non-CC theses |

---

## 7. CC license × activity matrix

Applies where an ETD bears a CC license (check ETD-MS/OAI `dc:rights` — **reliability caveat:** license metadata is sparse, free-text, often missing or contradictory with repository-level statements (e.g., Shodhganga asserts CC BY-NC-SA repo-wide); treat missing license = all rights reserved, not open).[^1380^][^681^] [MED]

| License | (a) | (b) | (c) | (d) | (e) excerpts | (f) derived data | (g) FT redistribution |
|---|---|---|---|---|---|---|---|
| **CC0** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **CC BY** | ✅ | ✅ | ✅ | ✅ | ✅ attribution | ✅ attribution | ✅ attribution |
| **CC BY-SA** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ SA: license adapted datasets BY-SA | ✅ |
| **CC BY-NC** | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ NC blocks any commercialized Calyx service | ✅ non-commercial only |
| **CC BY-NC-SA** (Shodhganga default) | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ NC + SA both | ✅ non-commercial, SA |
| **CC BY-ND** | ✅ | ✅ | ✅ internal analysis OK | ✅ | ⚠️ verbatim excerpts = reproduction (OK), but **abridged/annotated/adapted excerpts = Adapted Material → may NOT be shared** | ⚠️ extracted entities as facts OK; repackaged text = ND problem | ✅ unmodified only, attribution |
| **CC BY-NC-ND** | ✅ | ✅ | ✅ internal | ✅ | ⚠️ verbatim only, NC | ⚠️ strictest: facts only | ⚠️ unmodified, non-commercial |

**ND rule to encode:** never display *processed* excerpts (summaries-as-replacements, translations, annotated snippets) from ND-licensed theses; verbatim quotation with attribution is reproduction, not adaptation. **NC rule:** if Calyx ever monetizes any tier, NC-licensed corpus must be filtered out or licensed separately.[^1830^] [HIGH for license mechanics; MED for edge interpretation]

---

## 8. Contract / ToS risk table

| Source class | Typical restriction | Enforceability risk for Calyx | Rule |
|---|---|---|---|
| **ProQuest PQDT** | No scraping/systematic download; TDM only via TDM Studio | High — breach of contract + institutional access cutoff; license is a signed agreement (no Van Buren shield against contract claims) | ❌ Never scrape; TDM Studio if needed; use IRs for the same theses [^1964^][^1969^] |
| **Institutional repositories (DSpace/EPrints/Digital Commons)** | OAI-PMH offered for harvesting; site ToS rarely restrict OAI | Low — OAI-PMH is an invitation to harvest metadata; FT links publicly posted. Respect robots.txt & rate etiquette | ✅ OAI-PMH + ResourceSync; honor deleted records |
| **Aggregators (BASE, OpenAIRE, CORE)** | BASE: API gated/registration, ToS limits automated use; CORE: ODC-BY dumps, free research API | BASE: contract risk if scraping UI — negotiate; CORE: comply with ODC-BY attribution | ⚠️ BASE only with agreement; CORE dumps preferred [^21^ wide03] |
| **National ETD aggregators (DART, HAL, NARCIS, Shodhganga)** | Vary; Shodhganga CC BY-NC-SA | Low–medium | ✅ honor license + ToS |
| **CNKI** | License + Chinese data-security regime | High incl. regulatory | ❌ no bulk FT [^1790^] |

**US access-law posture:** *Van Buren v. US*, 593 U.S. 374 (2021) — CFAA "exceeds authorized access" requires accessing off-limits areas, not improper purpose; *hiQ v. LinkedIn* (9th Cir. 2019/2022) — scraping **public** pages likely not "without authorization"; BUT hiQ ended in Nov 2022 district-court ruling that hiQ **breached LinkedIn's User Agreement**, followed by confidential settlement/consent judgment with data destruction — contract claims survive where a ToS relationship exists (logged-in/clickwrap). No final merits ruling; 9th Cir. CFAA precedent intact. *Meta v. Bright Data* (2024): logged-out scraping = no ToS = no breach.[^1809^][^1811^][^1814^] [HIGH]
**EU:** *Ryanair v. PR Aviation* C-30/14 (2015): unprotected databases can still be contract-fenced; Database Directive's mandatory lawful-user rights (arts. 6(1), 8, 15) apply only where copyright/sui generis right exists.[^1815^] [HIGH]

---

## 9. Embargo, privacy, cultural sensitivity

### Embargo mechanics
- Universities grant ETD embargoes (commonly 6 mo–6 yr); repositories suppress FT during embargo and expose it on lift. Calyx must (i) honor OAI-PMH **`deleted` record headers** (purge/restrict local copies), (ii) re-harvest with `from` datestamps to catch status changes, (iii) maintain a per-record `access_status` field (`open / embargoed-until-YYYY-MM-DD / withdrawn`) and block FT download/display when not open, (iv) honor takedown notices within a set SLA.[^wide03][^1972^] [HIGH as design rule]

### GDPR / privacy (author personal data)
- Thesis author names, emails, acknowledgments (which name third parties), CV sections = personal data. Basis for processing published metadata: **legitimate interest, Art. 6(1)(f)** — requires a documented **Legitimate Interest Assessment** (purpose: scholarly indexing; necessity; balancing vs. data-subject expectations — authors publishing in OA repositories have reasonable expectation of indexing, but NOT of bulk email harvesting or profiling). Rules: data minimization (strip emails/phone numbers from derived products), honor objection/erasure requests (Art. 21/17), no special-category inference, DPIA if large-scale. EDPB/regulators have fined mass-scrapers (Clearview) — posture matters.[^1810^] [MED]

### Culturally sensitive data (ethnobotany theses)
- **CARE Principles** (Collective benefit, Authority to control, Responsibility, Ethics; Carroll et al. 2020, *Data Science Journal*) — complement, don't replace, FAIR; not self-certifiable; relational governance.[^1825^] [HIGH]
- **Local Contexts TK/BC Labels and Notices** — machine-readable community-protocol metadata; not legal instruments but governance signals; by 2026 supported by growing numbers of repositories/Mukurtu.[^1826^][^1829^] [HIGH]
- **Rule:** where a thesis carries TK Labels/Notices or contains indigenous knowledge (ethnobotanical use, sacred/ceremonial knowledge), apply the strictest label semantics to derived data: community attribution, NC where labeled, suppress flagged content, and offer community-initiated takedown.

---

## 10. Poaching / overcollection risk — sensitive locality data policy

Calyx extracts orchid occurrences from theses. Frameworks to adopt:

1. **GBIF/Chapman, *Current Best Practices for Generalizing Sensitive Species Occurrence Data* (2020, doi:10.15468/doc-5jp4-5g10)** — sensitivity categories → coordinate generalization: Cat 1 (extreme) withhold / 1° rounding; Cat 2 (high) 0.1°; Cat 3 (medium) 0.01°; Cat 4 (low) 0.001°; always document method + `coordinateUncertaintyInMeters`; publish at coarsest defensible precision.[^1858^][^1862^] [HIGH]
2. **iNaturalist model** — automatic **taxon geoprivacy**: observations of taxa with at-risk conservation status are auto-obscured into a 0.2°×0.2° cell (~400 km²), random point within cell; **orchids are explicitly cited as auto-obscured because sought by poachers**; private = no public location.[^1848^][^1850^] [HIGH]
3. **Criteria for Calyx sensitive-species list:** (i) CITES Appendix I (and treat heavily-traded App. II genera — e.g., *Paphiopedilum*, *Cypripedium*, novelty/described-species — as sensitive); (ii) IUCN CR/EN + collection/harvest threat; (iii) national red lists; (iv) any taxon flagged by source repository or community. **All wild *Paphiopedilum* and Appendix-I orchids → Cat 2 minimum (0.1°) or full withholding for new/locality-unpublished records.** [MED, synthesis]
4. **Publication rule:** derived-data exports carry fuzzed coordinates + uncertainty + sensitivity flag; full-precision coordinates only via vetted data-access requests (GBIF/iNat-style trusted-researcher model); never publish locality data absent from the source's own public version (respect the source's own obscuring).[^1858^][^1851^] [HIGH]

---

## 11. Compliance checklist — automatable pipeline rules

1. **Source allow-list:** harvest only (i) OAI-PMH/ResourceSync endpoints, (ii) CC/ODC-licensed dumps (OpenAlex CC0, CORE ODC-BY), (iii) licensed APIs (Crossref, DataCite). **Deny-list: ProQuest PQDT web, CNKI FT, any login/paywalled source, Sci-Hub/LibGen-type mirrors** (Bartz piracy rule). [HIGH]
2. **Lawful-access gate:** record acquisition channel + license/ToS snapshot per source (provenance log). EU Art. 3/4 and Japan proviso both hinge on it. [HIGH]
3. **Opt-out parser:** per host, fetch and honor robots.txt (RFC 9309), `TDM-Reservation` header, `/.well-known/tdmrep.json`, ai.txt; negative signal → skip FT download under Art. 4 posture (Art. 3 research-org route unaffected, but log signals anyway). Machine-readable only — natural-language ToS is not an Art. 4(3) opt-out (OLG Hamburg 2025) but IS contract risk if accepted.[^1341^] [HIGH]
4. **License normalizer:** parse `dc:rights`/ETD-MS rights fields into {CC0, BY, BY-SA, BY-NC, BY-NC-SA, BY-ND, BY-NC-ND, ARR-unknown}; **default = all-rights-reserved**; NC flag blocks commercial features; ND flag blocks adapted-excerpt display. [HIGH]
5. **Embargo/takedown sync:** incremental OAI harvest ≥ weekly; process `deleted` headers → restrict within 72 h; store `access_status`; honor email takedowns with SLA + audit log. [HIGH]
6. **Display filter:** excerpts only (e.g., ≤ ~300 chars or quotation-exception-scoped), verbatim (ND-safe), attribution always; no full-text serving of ARR theses; derived-data products contain facts/entities only. [MED]
7. **Sensitive-data engine:** taxon watch-list (CITES App. I + flagged genera + IUCN CR/EN w/ harvest threat) → coordinate fuzzing per Chapman categories; TK Label detection → community-attribution/NC/suppression semantics. [HIGH]
8. **GDPR kit:** documented LIA for author metadata; email/phone stripping in exports; objection/erasure endpoint; DPIA before public launch. [MED]
9. **Security & retention:** store FT corpus encrypted, access-controlled (Bartz/HathiTrust security theme; EU Art. 3(2) requirement); segregate embargoed items. [HIGH]
10. **Status monitors (re-check quarterly):** ANI v. OpenAI judgment; Brazil PL 2338 Chamber vote; UK DUAA follow-ons; USCO Part 3 finalization; EU Art. 4 opt-out case law; US appeals of Bartz/Kadrey-type rulings. [HIGH]

---

## 12. Biggest legal unknowns (as of 2026-07-21)

1. **US appellate law on AI/TDM training** — all favorable 2025 rulings are district-level, fact-bound; Kadrey was won on plaintiffs' empty record, not principle. [HIGH]
2. **EU Art. 3 "lawful access" for freely available web content** — widely read to include publicly accessible repositories, but not CJEU-tested. [MED]
3. **India** — ANI judgment + DPIIT compulsory-licensing proposal could move India from "no exception" to "statutory licence w/ royalties" — pipeline-affecting. [HIGH]
4. **UK** — government dropped reform Mar 2026 but the file is open; s.29A transfer ban's effect on shared research corpora unresolved. [HIGH]
5. **Brazil** — PL 2338 could give research orgs a clean Art. 42 TDM exception or a remuneration regime; timing unknown. [HIGH]
6. **RAG-style excerpt surfacing under Japan Art. 30-4** — Bunka-chō's co-existing-purpose doctrine is guidance, untested in court. [MED]

---

### References

[^29^]: https://eur-lex.europa.eu/eli/dir/2019/790/oj/eng — DSM Directive 2019/790 (Arts. 2–4, 7)
[^30^]: https://www.copyright.gov/fair-use/summaries/authorsguild-google-2dcir2015.pdf — USCO fair use summary, Authors Guild v. Google
[^31^]: https://www.law.berkeley.edu/wp-content/uploads/2016/05/Authors-Guild-v-Google-804_F.3d_202.pdf — 2d Cir. opinion ("quintessentially transformative use")
[^32^]: https://www.gtlaw.com/-/media/files/events/2023/06/ballon01/copyright-fair-use.pdf — HathiTrust 755 F.3d 87 holding; cert. denied 136 S. Ct. 1658 (2016)
[^36^]: https://www.ndltd.org/ — NDLTD ETD community (ownership/embargo practice)
[^681^]: https://docs.ndltd.org/collection/etd2023/etd23-1944_2450_44-paper.pdf — Shodhganga case study (475k+ theses; CC BY-NC-SA 4.0; MoU non-exclusive rights; misuse reports)
[^1341^]: https://blckalpaca.at/en/knowledge-base/seo-geo/technical-seo/robotstxt-and-ai-eu-legal-situation-and-tdm-opt-out — OLG Hamburg 5 U 104/24 (10 Dec 2025) machine-readable opt-out; AI Act Art. 53; TDMRep
[^1380^]: https://journals.ala.org/lrts/article/view/5963/7586 — ETD metadata standards evolution (ETD-MS/MODS; license/embargo fields)
[^1642^]: https://globallawexperts.com/generative-ai-copyright-japan/ — Japan Art. 30-4 non-enjoyment scope, ACA General Understanding
[^1643^]: https://www.intepat.com/blog/intellectual-property-law-for-artificial-intelligence — India: no TDM exception; ANI v. OpenAI status (reserved Apr 2026); DPIIT Working Paper; Singapore/Japan/EU comparison
[^1651^]: https://link.springer.com/article/10.1007/s40319-025-01569-6 — Senftleben, Control & Compensation (Japan Art. 30-4; ACA 2024 report; robots.txt as reservation)
[^1662^]: https://www.researchgate.net/publication/361362852 — Senftleben & Ueno, national TDM rules & international copyright
[^1738^]: https://www.arxiv.org/pdf/2511.21755 — comparative AI-copyright analysis (Thomson Reuters v. Ross, Bartz, Kadrey)
[^1743^]: https://www.hlc.com/en/publications/copyright-and-ai-uk-government-publishes-statement-of-progress — UK DUAA statement of progress; consultation stats
[^1744^]: https://www.aoshearman.com/en/insights/ao-shearman-on-tech/where-are-we-on-copyright-and-ai-in-the-uk — UK government drops TDM exception (Mar 2026 report)
[^1745^]: https://kindlepreneur.com/anthropic-ai-lawsuit/ — Bartz rulings table + $1.5B settlement facts
[^1748^]: https://law.justia.com/cases/federal/district-courts/delaware/dedce/1:2020cv00613/72109/770/ — Thomson Reuters v. Ross, D. Del. Feb. 11, 2025 (Doc. 770, Bibas J.)
[^1751^]: https://www.lexology.com/library/detail.aspx?g=b3d3aa98-6c02-4d1e-b194-f092e5d6a500 — Bartz v. Anthropic split decision analysis
[^1752^]: https://www.lexology.com/library/detail.aspx?g=eb18336c-881a-488a-9b50-55be58295b79 — Alsup/Chhabria rulings compared; "irredeemably infringing" piracy dicta
[^1755^]: https://www.hsfkramer.com/insights/2025-06/federal-judges-back-ai-training-as-fair-use-but-questions-remain — Kadrey narrowness; Chhabria cautions
[^1759^]: https://law.justia.com/cases/federal/district-courts/california/candce/3:2023cv03417/415175/598/ — Kadrey v. Meta, Doc. 598 (nonprofit-research fair use dicta)
[^1776^]: https://www.mondaq.com/india/copyright/1786566/is-training-ai-on-copyrighted-content-an-infringement — India s.52; DPIIT position; ANI
[^1777^]: https://www.lexology.com/library/detail.aspx?g=ffc0c58c-3727-4472-9914-5fa6a33ffffd — MeitY guidelines; DPIIT hybrid licensing (CRCAT); India litigation
[^1780^]: https://connectontech.bakermckenzie.com/switzerlands-ai-copyright-debate-legal-developments-and-outlook/ — Switzerland Art. 24d CopA analysis
[^1788^]: https://www.dpiit.gov.in/static/uploads/2025/12/ff266bbeed10c48e3479c941484f3525.pdf — DPIIT Working Paper Part 1 (Dec 2025): no TDM exception; hybrid licensing proposal
[^1790^]: https://www.govinfo.gov/content/pkg/GPO-USCC-2023/pdf/GPO-USCC-2023.pdf — US-China Commission 2023 report: CNKI cybersecurity review (June 2022), cross-border suspension (Apr 2023)
[^1793^]: https://cms.law/en/swe/publication/artificial-intelligence-and-copyright-case-tracker/ani-media-pvt-ltd-v.-openai-opco-llc — ANI v. OpenAI case tracker
[^1809^]: https://www.zwillgen.com/tag/computer-fraud-and-abuse-act-cfaa/ — hiQ timeline; Van Buren; Nov 2022 breach-of-contract ruling; Dec 2022 settlement
[^1810^]: https://cdn.financialreports.eu/financialreports/media/filings/6629/2026/RNS/6629_rns_2026-03-19_86b0eb49-727f-4a2f-a1d3-9ef7d736ce90.pdf — scraper risk filing (hiQ uncertainty; GDPR scraping enforcement)
[^1811^]: https://files.deepnoodle.ai/research/linkedin-legal-battles.pdf — hiQ outcome analysis (contract claims survive; CFAA precedent intact)
[^1812^]: https://bdigital.uexternado.edu.co/server/api/core/bitstreams/5abd583d-ae25-453d-b1d8-2a4803049694/content — Ryanair v. PR Aviation analysis (Spanish)
[^1814^]: https://scrap.io/scrape-google-gaps-legal — scraping case table incl. Meta v. Bright Data (2024)
[^1815^]: https://eulawradar.com/case-c-3014-ryanair-grounding-a-go-compare-an-airfare-website/ — C-30/14 full judgment text (ECLI:EU:C:2015:10)
[^1818^]: https://douglasvilar.com.br/artigos/posts/2026-06-13_marco-legal-ia-pl-2338-regulacao-brasil — PL 2338 Chamber status (June 2026)
[^1820^]: https://www.dataprivacybr.org/en/the-artificial-intelligence-legislation-in-brazil-technical-analysis-of-the-text-to-be-voted-on-in-the-federal-senate-plenary/ — PL 2338 copyright chapter; research-org carve-out conditions
[^1825^]: https://casrai.org/news/indigenous-data-governance-care-principles-2026 — CARE in practice; TK/BC Labels adoption 2026
[^1826^]: https://casrai.org/dictionary/domain/indigenous-data-care — CARE/TK Label definitions
[^1829^]: https://casrai.org/news/care-alongside-fair-indigenous-data-governance-tk-labels/ — TK Labels as machine-readable governance
[^1830^]: https://www.mondaq.com/new-technology/1747270/text-and-data-mining-for-ai-training — Finland transposition; lawful access definition
[^1831^]: https://kempitlaw.com/insights/copyright-text-and-data-mining-new-rules/ — DSM Art. 2(2), 3, 4; lawful access definition
[^1833^]: https://iclg.com/practice-areas/copyright-laws-and-regulations/japan/ — Japan ICLG 2026: Art. 30-4 + proviso; ACA Mar 2024 Report co-existing purposes
[^1835^]: https://blog.promise.legal/visual-artist-ai-training-opt-out-guide/ — TDMRep well-known JSON; ai.txt/llms.txt non-standard; Cloudflare 2025 defaults
[^1836^]: https://www.uu.nl/en/organisation/ai-policy/students/copyrights-and-ai — Utrecht: Art. 3 vs Art. 4 conditions in practice
[^1842^]: https://www.mondaq.com/technology/1517436/ — Japan General Understanding: co-existing purposes; RAG; proviso factors
[^1848^]: https://www.inaturalist.org/pages/geoprivacy — iNaturalist geoprivacy mechanics (0.2° cell; taxon geoprivacy)
[^1850^]: https://help.inaturalist.org/en/support/solutions/articles/151000169938-what-is-geoprivacy-what-does-it-mean-for-an-observation-to-be-obscured- — iNat FAQ: orchids auto-obscured (poaching)
[^1851^]: https://repositorium.uminho.pt/server/api/core/bitstreams/6944eb87-e028-4deb-8779-2de3f2c420e0/content — iNat curator policy on obscuring threatened taxa
[^1858^]: https://docs.gbif.org/sensitive-species-best-practices/master/en/ — Chapman 2020: categories 1–4 generalization table; documentation requirements; iDigBio/SANBI implementations
[^1862^]: https://www.gbif.org/news/18GVsWZ6Heas1RBAEmHHSv/gbif-releases-new-guide-for-publication-of-data-on-sensitive-species — GBIF sensitive-species guide release
[^1902^]: https://www.ddg.fr/actualite/generative-ai-training-and-copyright-law-in-the-united-states-in-depth-review-of-the-u-s-copyright-offices-may-2025-report-and-its-political-reverberations — USCO Part 3 report analysis
[^1905^]: https://www.prokopievlaw.com/post/uk-government-publishes-report-and-impact-assessment-on-copyright-and-ai-united-kingdom-march-2026 — UK Mar 18, 2026 Report & Impact Assessment (DUAA ss.135–136)
[^1907^]: https://www.prokopievlaw.com/post/uk-house-of-lords-recommends-opt-out-copyright-regime-for-ai-training-march-2026 — HL Paper 267 (Mar 6, 2026)
[^1908^]: https://committees.parliament.uk/writtenevidence/162683/html/ — Kretschmer evidence: s.29A transfer ban problems
[^1909^]: https://www.shma.co.uk/our-thoughts/data-protection-and-the-adoption-of-the-eu-tdm-exemption/ — s.29A text; UK consultation
[^1913^]: https://www.ropesgray.com/en/insights/viewpoints/102lvxe/getty-image-loses-copyright-infringement-claim-against-stability-ai-in-uks-first — Getty v Stability [2025] EWHC 2863 (Ch)
[^1916^]: https://www.lw.com/en/insights/getty-images-v-stability-ai-english-high-court-rejects-secondary-copyright-claim — model weights not infringing copies; intangible "article"
[^1917^]: https://www.nealandleroy.com/post/taking-a-closer-look-what-the-copyright-office-s-2025-ai-reports-mean-for-2026 — USCO continuum of transformativeness; market-harm pivot
[^1918^]: https://legalblogs.wolterskluwer.com/copyright-blog/eu-copyright-law-roundup-second-and-third-trimester-of-2025/ — EU/US roundup: AI Act GPAI guidelines, USCO Part 3 status (Perlmutter)
[^1963^]: https://www.aippi.org/news/data-mining-and-the-training-of-artificial-intelligence-models-in-brazil/ — Brazil arts. 46–48; no TDM exception; PL 2338
[^1964^]: https://www.unisg.ch/en/university/library/text-data-mining-tdm/ — ProQuest TDM Studio; systematic-download prohibitions; institutional access risk
[^1966^]: https://lirias.kuleuven.be/retrieve/99301647-ef51-420c-ba76-8818aa1997e6 — Schirru/de Souza: PL 2338 Art. 42 TDM exception text (translation)
[^1967^]: https://legalblogs.wolterskluwer.com/copyright-blog/tdm-and-brazilian-copyright-recent-developments/ — Brazil L&E flexibility; Statement 115; draft Art. 42
[^1969^]: https://library.cranfield.ac.uk/text-and-data-mining/publisher-policies — publisher TDM policy survey (ProQuest via TDM channels; CUP non-commercial)
[^1972^]: https://www.epw.in/engage/article/shodhganga-gentle-nudge-or-coercive-push — Shodhganga mandate, MoU coverage (787 institutes, 2026)
