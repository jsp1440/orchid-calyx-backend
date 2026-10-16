# Applying the Atlas occurrence projection (OWNER-APPLIED)

This runbook turns `public.orchid_occurrence` into the relation the Atlas
viewport API reads. Nothing here runs automatically. Every step that touches the
database is performed by the owner, against the Calyx database (`DATABASE_URL`).

Until step 4, the Atlas API answers `source_not_configured` and serves no
records. That is the safe default, not a fault.

## 0. Measure first (read-only)

```bash
DATABASE_URL=... python scripts/diagnose_atlas_occurrence_projection.py
```

It writes `atlas-occurrence-projection-diagnostic.json` and prints a verdict. It
emits counts, column names, family names and genus names only — never a
coordinate, locality, identifier or payload value — so the verdict can be pasted
into a PR.

Read these fields before deciding:

| Verdict field | What it decides |
|---|---|
| `projectable_rows` | How many records the Atlas can serve at all (linked to `public.orchid_taxonomy`, usable coordinates). |
| `rows_excluded_as_non_orchid` and `genera_stating_non_orchid_family` | Records that state a non-orchid family (e.g. *Hypoxis*). They are kept out of the Atlas automatically. A large number points at contamination upstream. |
| `rows_relying_on_backbone_for_family` | Records that state no family and are treated as Orchidaceae because they link to the orchid backbone. **Decision A** below. |
| `backbone_family` | Whether `public.orchid_taxonomy` has a family column that could replace the backbone assumption. |
| `licence_stated_rows` | How many records state a licence. **Decision B** below. |
| `uncertainty_stated_rows` | How many records state coordinate uncertainty. |
| `assessment_source_rows` | Conservation assessments available (2 at the last audit). With none wired in, every public point is generalised to at least 0.05°. |
| `source_indexes` | Whether `public.orchid_occurrence` already has the indexes the materialized-view build benefits from. |

## Decisions the projection encodes (owner to confirm)

- **A. Family basis for unstated records.** The view treats a record that states
  no family as Orchidaceae when it links to `public.orchid_taxonomy`
  (`family_basis = orchid_backbone_link`). If `backbone_family` shows non-orchid
  families, or `genera_stating_non_orchid_family` shows the backbone contains
  non-orchid genera, do not apply as written: restrict the view to
  `family_basis = 'source_stated'` or join the backbone's own family column.
- **B. Records without a stated licence** are served with "licence not stated"
  and dataset attribution. To require a stated licence instead, add
  `AND NULLIF(btrim(o.raw_payload ->> 'license'), '') IS NOT NULL` to the view's
  `WHERE` clause before applying.
- **C. No conservation source** is joined. Approve one before any record can be
  shown more precisely than the 0.05° precaution allows.

## 1. Apply

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f docs/atlas-explorer/20261011_atlas_public_occurrences_v1.sql
```

One transaction. Preconditions abort it if the source or backbone lacks a column
it reads. It creates `oc_atlas.public_occurrences_v1` and its indexes, revokes
PUBLIC access, and never modifies `public.orchid_occurrence`.

## 2. Verify (counts only)

```sql
SELECT count(*) AS rows,
       count(*) FILTER (WHERE family = 'Orchidaceae') AS served,
       count(*) FILTER (WHERE family <> 'Orchidaceae') AS excluded_non_orchid,
       count(*) FILTER (WHERE family_basis = 'orchid_backbone_link') AS backbone_family,
       count(*) FILTER (WHERE license IS NOT NULL) AS licence_stated
FROM oc_atlas.public_occurrences_v1;
```

`served` should be close to the diagnostic's `projectable_rows` minus
`rows_excluded_as_non_orchid`.

## 3. Grant read access to the backend role only

Grant `SELECT` on `oc_atlas.public_occurrences_v1` to the role in `DATABASE_URL`
if it is not the owner. Never grant it to `anon`, `authenticated` or `PUBLIC`:
the view holds precise coordinates and the API is what generalises them.

## 4. Configure the backend

Set `ATLAS_OCCURRENCE_RELATION=oc_atlas.public_occurrences_v1` (leave
`ATLAS_OCCURRENCE_USE_POSTGIS` unset; the view has a latitude/longitude index)
and restart. `GET /atlas/capabilities` should then report
`atlas.occurrences.query` as `available`.

## 5. Refresh

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY oc_atlas.public_occurrences_v1;
```

Run after each occurrence ingest. The unique index on `occurrence_id` allows a
concurrent refresh.

## Rollback

Unset `ATLAS_OCCURRENCE_RELATION`, then:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f docs/atlas-explorer/20261011_atlas_public_occurrences_v1_rollback.sql
```

## Evidence

`tests/test_atlas_projection_migration.py` applies the migration to a disposable
PostgreSQL 16 database whose `public.orchid_occurrence` is built from the column
list recorded by the read-only production diagnostic
(`docs/evidence/audit-measurement-002/integration-gap-diagnostic.json`), with
synthetic rows. It checks the contract, Orchidaceae scoping (*Hypoxis* excluded),
fail-closed preconditions, re-application, rollback, and that the diagnostic
emits no coordinates or localities.
