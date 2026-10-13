# TRAITBANK-PILOT-001 — Real-data ingestion pilot (prepared; awaiting owner approval)

**Status:** prepared only. Nothing has been downloaded, no pilot database has been created, and nothing has been written.
**Manifest:** `docs/pilots/traitbank_pilot_001_manifest.json`
**Script:** `scripts/traitbank_pilot.py`. Gates are tested in `tests/test_traitbank_pilot.py`.

## What the pilot proves

Real EOL TraitBank rows and real literature can be ingested into TraitBank. The pilot checks that the result keeps:
- the original values;
- citations;
- observation levels;
- units;
- conflicts.

It does this in a **separate** PostgreSQL database, and reports exactly what could not be mapped and why.

## Approvals needed (each is a separate decision)

1. **Source.** Choose one:
   - **(a) The EOL "All trait data" archive** (Zenodo record 13305577).
     - A search result describes it as about 592 MB, but that wasn't verifiable here because `zenodo.org` doesn't resolve from this environment.
     - It must be downloaded whole, even though only Orchidaceae rows are kept, so it exceeds a "small" pilot.
     - Its exact file URL, license and checksum must be read from the record, entered in the manifest, and reviewed before `status` becomes `approved_for_fetch`.
   - **(b) A smaller EOL export you obtain or authorise**, such as a per-resource or per-taxon download. Add it to the manifest with its URL, license, `max_bytes` and (if known) `sha256`.
   - **(c) Literature only.** Use the Darwin (1862) fixture already in the repository plus a named set of existing literature-extraction outputs. No download is needed, but reading those outputs needs your approval of the data source.
2. **Pilot database.** You approve creating a separate database, for example `traitbank_pilot`. The script refuses a URL that equals `DATABASE_URL` or `TRAITBANK_DATABASE_URL`, and it refuses a database whose name lacks `pilot` or `test`.
3. **Canonical taxonomy subset.** TraitBank only stores rows whose taxon resolves in the canonical taxonomy. The pilot database needs a read-only export of `public.orchid_taxonomy`, all of it or the genera you name, and creating that export is your decision.
4. **Network.** Option (a) or (b) needs the source host allowed in this environment's network policy, or the fetch must be run where it is.

## Runbook (after approval)

```
export TRAITBANK_PILOT_DATABASE_URL=postgresql://.../traitbank_pilot
python scripts/traitbank_pilot.py plan
python scripts/traitbank_pilot.py fetch <source_id> --workdir /var/tmp/traitbank-pilot \
       --approval-reference <link to your approval> --i-have-owner-approval
python scripts/traitbank_pilot.py inspect /var/tmp/traitbank-pilot/<file>
psql "$TRAITBANK_PILOT_DATABASE_URL" -f migrations/20261011_oc_traitbank_v1.sql
psql "$TRAITBANK_PILOT_DATABASE_URL" -f migrations/20261013_oc_traitbank_v2_supersession.sql
TRAITBANK_DATABASE_URL="$TRAITBANK_PILOT_DATABASE_URL" python -m app.traitbank.cli load-definitions --apply
python scripts/traitbank_pilot.py normalize /var/tmp/traitbank-pilot/<file> --source-id <source_id> \
       --out /var/tmp/traitbank-pilot/batch.json
python scripts/traitbank_pilot.py ingest /var/tmp/traitbank-pilot/batch.json             # dry run
python scripts/traitbank_pilot.py ingest /var/tmp/traitbank-pilot/batch.json --apply --ingested-by <you>
```

Every phase except `fetch` is offline.

`fetch` enforces the following:
- it requires owner approval;
- it streams with a byte cap;
- it records the sha256, and verifies it against a pinned value once one is in the manifest;
- it refuses a working directory inside the repository, so downloaded data can't be committed.

`inspect` refuses any layout that lacks `eol_pk`, `predicate`, a value column and a way to name the taxon (`scientific_name`, or `page_id` together with `pages.csv`).

## Defects found while preparing (fixed in TRAITBANK-002)

- **Real measurements were read as missing.** EOL stores values in `measurement` / `normal_measurement` (with their own units), `value_uri` / `object_term`, or `literal` (EOL/publishing `doc/trait-schema.md`). `TraitBankHarvester._normalize` reads none of these. Before the fix, every real EOL measurement would have been stored as "missing: not reported". The adapter now reads the EOL columns, keeping each value with its own unit.
- **An unmapped statistical method was read as a single value.** An unmapped method, often an ontology URI, is now refused (`statistical_method_not_mapped`) rather than read as `single`.

## Still unverified

The column names come from EOL's schema documentation, not from an actual archive header. `inspect` is the first pilot step for exactly that reason.
