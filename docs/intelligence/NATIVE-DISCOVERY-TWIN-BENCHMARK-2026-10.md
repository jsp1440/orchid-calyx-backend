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
  (8 searches + 3 page reads, ≈31 credits). The PubMed page read failed.
- After the first pass, the owner supplied the full TWIN PDF (*Orchid Continuum
  Daily Briefing — Sunday, October 11, 2026*). Items 4 and 6 were re-checked
  against its exact wording.
- "Verified" below means *source identity* (the cited primary page exists and
  says what the summary says it says). No scientific claim is verified here.

## Results

| # | TWIN item | Original source located | Claim vs. source | DOI / permanent URL | Datasets identified | In native M1 scope | Follow-up generated |
|---|---|---|---|---|---|---|---|
| 1 | Orchid pollination decline from preserved flowers | Yes: *Global Change Biology* paper; Australian National Herbarium *Caladenia* specimens (10,494 flowers, per the PubMed snippet) | Source identity confirmed through two independent secondary sources (The Conversation, CSIRO) that link the DOI. Paper page not read directly. → **PARTIALLY_VERIFIED** | `10.1111/gcb.70793`; PubMed 41873588; EcoEvoRxiv preprint 9991 | Not determined (data-availability statement not read) | **Yes** (Crossref/OpenAlex/Europe PMC literature profile) | Would be: `EVALUATE_RELATIONSHIP_EVIDENCE` → pollinator_network; Atlas route. Not run live. |
| 2 | Newly described Ecuadorian *Lepanthes* | Yes: Tobar et al., *Phytotaxa* 774(3): 201–218, published 2026-09-17 | Publisher page metadata (`citation_doi`, title, authors) read directly. → **VERIFIED** (identity) | `10.11646/phytotaxa.774.3.1` | None stated on the landing page | **Yes** (literature + taxonomic-novelties profiles) | Would be: `RECONCILE_TAXONOMY` for *Lepanthes berthana* and *L. mongei* (unreconciled), plus a distribution-record note for *L. chrysokallos*. Not run live. |
| 3 | DiSSCo UK museum digitisation | Yes: DiSSCo UK programme-launch post (£155.6M Full Business Case, UKRI Infrastructure Fund, hub-and-node model, next application round 2027) | Official page read through a search excerpt → **SOURCE_LOCATED** | https://dissco-uk.org/post/2026/programme-launch/ | Programme will mobilise specimen data; no dataset yet | **No**: institutional announcements are a Milestone 2 adapter | None (out of scope) |
| 4 | Chicago Botanic Garden orchid living-collections coordination (TWIN: "2026 IMLS Grants to Public Gardens") | Yes: IMLS award MG-260156-OMS-26 ("will first focus on orchids held in various institution collections as a means of establishing data collection and work processes"); also listed on the APGA 2026 IMLS grants page | Official federal award page, read through a search excerpt → **SOURCE_LOCATED** (the government page is authoritative, but the full award record was not read). TWIN's companion claim about Center for Plant Conservation consensus taxonomy was not checked separately. | https://www.imls.gov/grants/awarded/mg-260156-oms-26 | None yet (the framework is the deliverable) | **No** (institutional/funding adapter is Milestone 2) | None. TWIN recommends contacting CBG/CPC; that is owner-gated external contact and was not done. |
| 5 | U.S. Action Plan for Plant Conservation | Yes: BGCI 2026 Summit page; Center for Plant Conservation archive | The plan is in development (summit produced a consensus framework; working groups drafting). It is not a published plan. → **PARTIALLY_VERIFIED** | https://www.bgci.org/news-events/2026-u-s-action-plan-for-plant-conservation-summit/ | None | **No** (policy/news adapter is Milestone 2) | None |
| 6 | Trebek Initiative RFP (TWIN: deadline 28 October 2026) | Yes: official 2026 RFP page and FAQ | Deadline **confirmed** on the official RFP page: Wednesday 28 October 2026, 11:59 PM ET. Scope confirmed: projects that impact land, water, wildlife, culture or history *in Canada*. Award ceiling **contradicted** across sources: FAQ "up to $75K CAD", INQ page "$100K CAD", UCalgary "up to USD $70,000". → **PARTIALLY_VERIFIED** (deadline and scope verified; award range contradicted). Eligibility for a U.S. organisation: *possible, unconfirmed*. It requires a Canada-impact project. | https://www.trebekinitiative.com/2026rfp | n/a | **No** (funding adapter is Milestone 2) | None. No application or contact initiated. The deadline is 17 days out, so this is a human decision. |

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

## Observations on the TWIN report itself (2026-10-11 issue)

- 22 items across six sections: Funding 6, Research 4, Taxonomy 5,
  Conservation 2, Partnerships 2, Technology 3.
- Every item ends in "Read source →". In the PDF those links are not
  visible, and no item states a DOI, journal volume/pages or an author list,
  apart from free-text mentions such as "Lankesteriana (Vol. 26, No. 2, 2026)".
  That is the provenance gap native discovery is meant to close.
- Duplication: the IMLS/CBG item appears twice (Funding and Partnerships), and
  the AWS credit item appears twice (Funding and Technology). The ledger's
  fingerprinting groups these by domain + normalized title, so repeated
  wording within a domain converges. The same story under two domains stays
  two items until compared.
- Staleness: the pollination study's public coverage dates from April 2026,
  but TWIN reports it as a top-5 priority in October. Native novelty
  classification would show it as `HISTORICAL_RECOVERY`.
- Several recommended actions are owner-gated by Orchid Continuum policy
  (contacting CBG/CPC, attending or submitting to the Summit, enrolling in
  AWS/Microsoft programs, drafting a Trebek proposal). Native discovery
  records them as decisions for the owner. It does not act on them.
- Of the 22 items, the 9 Research/Taxonomy items are scholarly publications
  within reach of the Milestone 1 registry profiles. Examples: *Telipogon
  vasqueznunezii* and *Catasetum × guarayense* in *Lankesteriana* 26(2), and
  *Cynorkis benaraensis* in *Adansonia*. The *Maxillaria paucicolorata* item
  cites a society magazine and may not be registry-indexed. The remaining
  13 items need Milestone 2 adapters.
