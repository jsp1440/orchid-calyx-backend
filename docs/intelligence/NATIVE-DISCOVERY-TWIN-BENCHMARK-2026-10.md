# Native discovery vs. TWIN — October 2026 benchmark

Reference only. The TWIN briefing is **not** an input to native discovery, and
nothing below is hardcoded into `app/intake/discovery/`. This records an
independent source-location attempt for six representative TWIN items, made
on 2026-10-11 during development of the Milestone 1 vertical slice.

## Method and limits

- The development container's egress policy blocks `api.crossref.org`,
  `api.openalex.org` and `www.ebi.ac.uk`, so the native adapters could **not**
  be executed live here. Their behaviour is covered by fixture-based tests.
- Source location for this benchmark used the existing Firecrawl integration
  (6 searches + 3 page reads, ≈27 credits). The PubMed page read failed.
- "Verified" below means *source identity* (the cited primary page exists and
  says what the summary says it says). No scientific claim is verified here.

## Results

| # | TWIN item | Original source located | Claim vs. source | DOI / permanent URL | Datasets identified | In native M1 scope | Follow-up generated |
|---|---|---|---|---|---|---|---|
| 1 | Orchid pollination decline from preserved flowers | Yes: *Global Change Biology* paper; Australian National Herbarium *Caladenia* specimens (10,494 flowers, per the PubMed snippet) | Source identity confirmed through two independent secondary sources (The Conversation, CSIRO) that link the DOI. Paper page not read directly. → **PARTIALLY_VERIFIED** | `10.1111/gcb.70793`; PubMed 41873588; EcoEvoRxiv preprint 9991 | Not determined (data-availability statement not read) | **Yes** (Crossref/OpenAlex/Europe PMC literature profile) | Would be: `EVALUATE_RELATIONSHIP_EVIDENCE` → pollinator_network; Atlas route. Not run live. |
| 2 | Newly described Ecuadorian *Lepanthes* | Yes: Tobar et al., *Phytotaxa* 774(3): 201–218, published 2026-09-17 | Publisher page metadata (`citation_doi`, title, authors) read directly. → **VERIFIED** (identity) | `10.11646/phytotaxa.774.3.1` | None stated on the landing page | **Yes** (literature + taxonomic-novelties profiles) | Would be: `RECONCILE_TAXONOMY` for *Lepanthes berthana* and *L. mongei* (unreconciled), plus a distribution-record note for *L. chrysokallos*. Not run live. |
| 3 | DiSSCo UK museum digitisation | Yes: DiSSCo UK programme-launch post (£155.6M Full Business Case, UKRI Infrastructure Fund, hub-and-node model, next application round 2027) | Official page read through a search excerpt → **SOURCE_LOCATED** | https://dissco-uk.org/post/2026/programme-launch/ | Programme will mobilise specimen data; no dataset yet | **No**: institutional announcements are a Milestone 2 adapter | None (out of scope) |
| 4 | Chicago Botanic Garden orchid living-collections coordination | Partially: CBG Orchidarium page says it "integrates living plants, seed banking, fungal cultures, and herbarium specimens" | The specific "coordination" claim was not found → **UNRESOLVED** | https://www.chicagobotanic.org/collections/orchidarium | None | **No** | None |
| 5 | U.S. Action Plan for Plant Conservation | Yes: BGCI 2026 Summit page; Center for Plant Conservation archive | The plan is in development (summit produced a consensus framework; working groups drafting). It is not a published plan. → **PARTIALLY_VERIFIED** | https://www.bgci.org/news-events/2026-u-s-action-plan-for-plant-conservation-summit/ | None | **No** (policy/news adapter is Milestone 2) | None |
| 6 | Trebek Initiative funding | Yes: trebekinitiative.com FAQ | Award ceilings disagree: FAQ says "up to $75K CAD"; INQ page "$100K CAD"; UCalgary page "up to USD $70,000". Newsletter excerpt says the RFP is for National Geographic Explorers working in Canada. → **CONTRADICTED** on award range. Eligibility for a U.S. organisation is *possible but unconfirmed* (likely not eligible). | https://www.trebekinitiative.com/faq | n/a | **No** (funding adapter is Milestone 2) | None. No application or contact initiated. |

## What this shows

- Both scholarly items (1, 2) resolve to DOIs and fall inside the queries the
  Milestone 1 profiles run. Item 2 (published 2026-09-17) would be classed
  `NEW_PUBLICATION`. Item 1's coverage dates from April 2026, so native
  discovery would class it `HISTORICAL_RECOVERY` rather than report it as new
  in October.
- Items 3–6 are institutional, policy and funding intelligence. Milestone 1
  has no native adapter for those domains, and the digest reports that gap
  explicitly (`coverage_gaps`) rather than omitting it.
- Item 6 shows why funding records need explicit confirmed-vs-possible
  eligibility and award-range contradiction handling (Milestone 2).
