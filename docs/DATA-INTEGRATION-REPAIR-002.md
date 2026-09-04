# DATA-INTEGRATION-REPAIR-002

Dry-run repair package for the two orchid-side taxonomy linkage gaps that
DATA-INTEGRATION-REPAIR-001 measured.

Nothing here has been executed against production. No scientific data is
mutated, no taxonomy is activated, no graph edges are published. This document
describes a package that produces a reviewable mapping and a reviewable SQL
statement; running it is a separate, owner-gated act.

## What was already established, and by whom

DATA-INTEGRATION-REPAIR-001 (`docs/DATA-INTEGRATION-REPAIR-001.md`, PR #1020)
measured both relations against production:

| Relation | key | resolves into `public.orchid_taxonomy` |
|---|---|---|
| `oc_interactions.orchid_interaction_edges` | `orchid_taxonomy_id` | 23 of 23 |
| `oc_mycorrhiza.orchid_fungal_associations` | `orchid_taxonomy_id` | 2 of 2 |

Those are the numbers from that measurement, not from this package. Two things
follow from them, and both shape what this package does.

**The populated ids are not broken.** Every id that exists resolves. They were
previously read as broken only because the audit joined them against
`oc_taxonomy.taxa`, a different registry those ids were never meant to resolve
into. So this package never rewrites a populated id. Rewriting a correct value
is the one change that could turn a measurement artifact into real data loss.

**The gap is absence, not corruption.** The mycorrhiza relation holds 462 rows
of which 2 carry an id, while the name join that the Knowledge Graph source
registry (`runtime/knowledge_graph/source_registry.py`) already uses for this
relation reached 462 rows across 218 taxa. The rows carry the relationship; the
id column was simply never filled in. That is what is repairable here.

## The package

- `app/readiness/taxonomy_id_repair.py` — measurement, resolution, mapping, SQL
  generation, and the only function that can write.
- `scripts/repair_pollinator_mycorrhiza_taxonomy_ids.py` — CLI. Dry run by
  default; writing needs an explicit flag *and* an owner-set token.
- `tests/test_taxonomy_id_repair.py` — regression tests.

### Resolution policy

`canonical-orchid-taxonomy-normalized-exact/v1`. A row's stored
`orchid_scientific_name` is normalized (whitespace collapsed, underscores
treated as spaces, genus/epithet cased, infraspecific rank preserved) and must
match a `public.orchid_taxonomy` row's normalized `scientific_name` exactly.

This mirrors `app.trait_genomics.taxon_target_resolver.CanonicalTaxonTargetResolver`,
the resolver this repository already uses against the same canonical table. The
normalization regex is a local copy rather than an import, so a read-only
measurement module does not pull in that resolver's psycopg/pydantic dependency
chain; the *policy* is what is being reused, and a regression test pins the two
to the same normalized output so they cannot silently drift.

No synonym expansion. No fuzzy matching. No nearest-neighbour fallback.

### Failing closed

Four outcomes, and only the first can ever be written:

| outcome | meaning | action |
|---|---|---|
| `resolved` | exactly one canonical row, or one exact-text row among homonyms | write candidate |
| `ambiguous` | several canonical rows share the normalized name | human review |
| `unresolved` | no canonical row has that normalized name | no action |
| `invalid` | the stored value is not a parseable scientific name | no action |

Ambiguity resolves automatically in exactly one case: several canonical rows
share the normalized taxon identity and precisely one of them matches the
submitted text exactly. Anything else is a human's decision, and the row waits.

Unavailable is never rendered as zero. A missing table, a missing canonical
table, or a missing required column returns `state: "unavailable"` with the
reason, and the mapping artifact for that target is empty rather than reading
as "nothing to repair" — the same convention
`app/readiness/relationship_measurement.py` uses.

### The orchid side, and only the orchid side

`partner_taxon_id` and `fungal_taxon_id` identify the *other* endpoint of the
relationship — a pollinator, a fungus. An orchid taxonomy id written into
either would be a scientifically false statement, not merely a bad row. Three
independent things prevent it:

1. Only `orchid_taxonomy_id` is ever named on the write side of any statement
   this package builds, and a test asserts the partner column's name does not
   appear anywhere in the generated SQL for either target.
2. A hardcoded two-table allowlist is checked before any query runs, so the
   package cannot be pointed at the partner-side relation, nor at
   `oc_mycorrhiza.species_mycorrhiza_unified_endpoint_cache` (an HTTP response
   cache, not a mycorrhizal corpus).
3. At the write boundary, every planned id is checked against the canonical
   candidates the measurement recorded for that specific row. An id that did
   not come out of `public.orchid_taxonomy` for that row — or a plan carrying
   no provenance at all — aborts the apply before the first `UPDATE`.

### Idempotency

Every statement, generated or executed, is guarded by
`AND orchid_taxonomy_id IS NULL`. The guard is what makes re-running safe, not
an external bookkeeping table: a plan applied twice touches zero rows the
second time, and a row a concurrent process populated in between is left alone
rather than clobbered. Execute mode additionally compares `rows_updated`
against `planned` per target and rolls back on any mismatch rather than
committing a partial write.

### Generated SQL renders values, not Python

Values are rendered as quoted SQL literals and cast to the columns' catalog
types, read from `information_schema.columns` during the same read-only pass:

```sql
BEGIN;
UPDATE oc_mycorrhiza.orchid_fungal_associations AS t
SET orchid_taxonomy_id = v.resolved_orchid_taxonomy_id::int8
FROM (VALUES
  ('...', '...')
) AS v(row_pk, resolved_orchid_taxonomy_id)
WHERE t.association_id = v.row_pk::uuid
  AND t.orchid_taxonomy_id IS NULL;
COMMIT;
```

Both halves matter. `repr()` of a `uuid.UUID` — a plausible type for
`association_id`/`edge_id` — is `UUID('...')`, which is not SQL, and `repr()`
of a value containing an apostrophe produces a double-quoted string, which
Postgres reads as an identifier. And without the cast, an unknown-typed literal
in a `VALUES` list resolves to `text`, so joining it against a `uuid` or
`bigint` key fails outright. When the catalog types are unavailable the SQL is
still emitted, but carries an explicit `-- WARNING` telling the reviewer to
confirm the types first.

### Provenance mapping

Each dry run writes one CSV per target accounting for **every** candidate row,
not only the writable ones. Each row states the source relation and primary
key, the stored name, the normalized form the policy derived, the canonical
relation and columns consulted, every candidate that relation offered, the
selected id and the rule that selected it, the pre-state (`null` — known, not
merely absent), the action, the reason, and the partner column that was not
written. Header order is fixed so two runs diff cleanly.

A row queued for human review carries its full candidate set and the reason it
failed closed, so the reviewer sees the alternatives the resolver saw rather
than a bare "ambiguous".

In execute mode the mapping and SQL are written *before* the transaction
commits, so the provenance of a write exists on disk even if that write is
rolled back or interrupted.

## Running it

Dry run — read-only, needs no write permission, always rolled back:

```bash
DATABASE_URL=... python3 scripts/repair_pollinator_mycorrhiza_taxonomy_ids.py
```

Writes `taxonomy-id-repair-report.json`, plus
`taxonomy-id-repair-mapping.{pollinators,mycorrhiza}.csv` and
`taxonomy-id-repair.{pollinators,mycorrhiza}.sql`. Paths are overridable with
`--report`, `--mapping-out`, `--sql-out`.

Executing requires **both** `--execute` and the exact token in
`CALYX_TAXONOMY_ID_REPAIR_CONFIRMATION`
(`REPAIR-POLLINATOR-MYCORRHIZA-TAXONOMY-IDS-CONFIRMED`), mirroring the owner
gate in `scripts/upload_hassler_release_guarded.py`. `--execute` alone exits
non-zero before opening a connection. Only the repository owner can set that
token; this package does not.

## What has not been done

The dry run has not been executed against production — no `DATABASE_URL` was
available to the session that built this. So the current live null-row count is
unknown here; the 462-row / 2-populated shape above is
DATA-INTEGRATION-REPAIR-001's measurement, not a re-measurement, and it may
have drifted. Running the dry run and reading the mapping
is the next step, and it is the step that must happen before anyone considers
`--execute`.
