# CALYX-KG-OCCURRENCE-QUERY-001

## Purpose

Close the retrieval-side gap after identifying the authoritative 580,612-row occurrence corpus. Calyx must be able to answer constrained distribution questions from explicit evidence rather than requiring the user to name a taxon first.

## Implemented

- Added `app/calyx_conversation/occurrence_query.py`.
- The parser recognizes only explicit country + metric elevation constraints and fails closed for unsupported language.
- Supported elevation operators: above, below, between, and at/around a stated metric elevation.
- Queries use `public.orchid_occurrence` as the evidence corpus and resolve every returned taxon to an active `oc_graph.kg_nodes` taxon identity.
- Result payloads include canonical taxonomy id, scientific name, Knowledge Graph node id, qualifying occurrence count, observed elevation bounds, and sample coordinates.
- Raw point elevation and reported min/max ranges are treated as occurrence evidence; this is distinct from the derived taxon elevation-profile nodes materialized elsewhere in PR #901.
- SQL is parameterized, bounded, read-only, and sets the PostgreSQL connection read-only.
- Speak now adds these results to governed context and message metadata; no graph mutation or knowledge publication occurs.
- The deterministic governed provider is upgraded to `calyx-governed-summary-v4-occurrence` and renders matching taxa, occurrence counts, observed elevation bounds, and graph node identity instead of falling back to a generic no-evidence response.
- Zero-result occurrence queries remain explicit zero results. The provider is forbidden from manufacturing a species list when the source query returns none.
- The optional configured generative provider receives the same occurrence evidence plus an explicit instruction that occurrence records are observations and must not be promoted into complete-range claims without supporting evidence.

## Acceptance target

A question such as `List all orchids in Ecuador that occur above 3000 meters` can now be converted into an auditable relational-evidence query whose results are tied back to persisted graph taxon identities and surfaced in the Calyx reply.

A query such as `List orchids in Ecuador at 10000 meters` is treated as a range-containment test against the point/min/max occurrence elevation evidence. A truthful zero-result is valid and preferable to inference.

## Validation

Focused parser regressions cover above, below, between, exact elevation, missing-country/missing-elevation rejection, and avoidance of treating a binomial name as a country. Provider regressions verify positive-result rendering and truthful zero-result behavior. The dedicated KG validation workflow compiles and tests the occurrence-query, Speak, and deterministic-provider integration when a runner actually executes.

Exact-head GitHub-hosted execution remains blocked by the ongoing runner allocation incident: the dedicated KG Bulk Source Validation job is again created with `steps:null`, so checkout, compile, pytest, and Ruff do not execute. Such runs are infrastructure non-execution and are not accepted as code validation.

## Governance

This path is read-only. It does not publish occurrence nodes, alter taxonomy, mutate the Knowledge Graph, or promote Candidate Knowledge. Production graph materialization remains a separate owner-governed action.

## Completion note

This closes the first retrieval-side acceptance slice requested during the live audit: Calyx can now convert an explicit geographic/elevation question into a bounded evidence query over the large occurrence corpus, anchor each returned species to the persisted graph taxonomy backbone, and surface the resulting observations in both deterministic and configured-provider replies. The next high-priority retrieval work is richer taxon-to-literature/evidence retrieval over the 6,725-document research corpus and scientific-method extraction graph.
