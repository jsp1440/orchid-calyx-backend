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

## Acceptance target

A question such as `List all orchids in Ecuador that occur above 3000 meters` can now be converted into an auditable relational-evidence query whose results are tied back to persisted graph taxon identities.

A query such as `List orchids in Ecuador at 10000 meters` is treated as a range-containment test against the point/min/max occurrence elevation evidence. A truthful zero-result is valid and preferable to inference.

## Validation

Focused parser regressions cover above, between, exact elevation, missing-country/missing-elevation rejection, and avoidance of treating a binomial name as a country. The dedicated KG validation workflow now compiles and tests the occurrence-query/Speak integration.

GitHub-hosted runner execution remains subject to the existing zero-step allocation incident. `steps:null` is not considered executable validation.

## Governance

This path is read-only. It does not publish occurrence nodes, alter taxonomy, mutate the Knowledge Graph, or promote Candidate Knowledge. Production graph materialization remains a separate owner-governed action.
