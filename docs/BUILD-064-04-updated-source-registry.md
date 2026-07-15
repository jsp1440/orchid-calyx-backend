# BUILD-064 Deliverable 4 — Updated Source Registry

The registry (`runtime/knowledge_graph/source_registry.py`) now carries a
`metadata` block per domain (status, identifier strategy, join strategy,
crosswalk-required, confidence, expected vs actual counts, last verification,
operator notes). Snapshot at verification date 2026-07-15:

| Domain | Status | Join strategy | Crosswalk req. | Confidence | Expected | Actual | Verified |
| --- | --- | --- | --- | --- | ---: | ---: | --- |
| occurrences | READY WITH OPERATOR REVIEW | direct_id | False | high | 580000 | 26 | 2026-07-15 |
| traits | READY WITH OPERATOR REVIEW | resolved_view_id | False | medium | 33791 | 2807 | 2026-07-15 |
| pollinators | READY WITH OPERATOR REVIEW | name_join (crosswalk-upgradable) | True | high | 23 | 23 | 2026-07-15 |
| mycorrhiza | PARTIALLY READY | name_join (crosswalk-upgradable) | True | medium | 462 | 626 | 2026-07-15 |
| conservation | PARTIALLY READY | direct_id | False | high | 2 | 2 | 2026-07-15 |
| climate | BLOCKED | direct_id | False | low | 0 | 19263 | 2026-07-15 |
| literature | PARTIALLY READY | name_join | True | medium | 35 | 29 | 2026-07-15 |
| media | READY | direct_id | False | high | 51 | 51 | 2026-07-15 |

Full operator notes live in the code and in Deliverables 1–3. The `metadata`
field is surfaced through `SourceQuery.to_dict()` and validated by the
BUILD-064 tests. Projection SQL is unchanged from BUILD-062, so DRY_RUN output
is stable; only connection-quality metadata was added.
