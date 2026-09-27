# OC-CRM-BACKUP-RESTORE-001 — Society CRM backup/restore drill

Issue: #1659 (mandatory CRM backup/restore proof).

Code:

- `app/constituent_platform/backup_verification.py` — fingerprint, compare, drill.
- `scripts/oc_crm_backup_restore_drill.py` — operator CLI.
- `tests/test_crm_backup_restore.py` — CI proof against real `pg_dump`/`pg_restore` (PostgreSQL 16).

## What the drill does

1. Opens one `REPEATABLE READ READ ONLY` transaction on the source and exports its snapshot.
2. Fingerprints every table in the configured schemas inside that snapshot (see below).
3. Runs `pg_dump --format=custom --snapshot=<same snapshot> --schema=<each schema>`. The dump and the
   fingerprint therefore describe exactly the same state, even on a live database.
4. Creates a new, uniquely named scratch database (`oc_restore_drill_<uuid hex>`, from `template0`) through
   `--admin-dsn` and runs `pg_restore --exit-on-error --single-transaction` into it.
5. Fingerprints the restored copy and compares. Row-level differences are traced to primary keys.
6. Runs functional checks **in the restored copy only**:
   - **roles** — every role referenced by a CRM policy exists in the target cluster;
   - **isolation** — under `SET LOCAL ROLE oc_crm_runtime` (the application's own `tenant_transaction`):
     no tenant set ⇒ zero rows on every protected table; for each sampled organization, exactly that
     organization's rows are visible and never another tenant's;
   - **append-only guards** — an `UPDATE` on `crm_audit_events` and `membership_renewals` is still
     rejected (`CRM_AUDIT_IMMUTABLE`); the probe is rolled back.
7. Drops the scratch database (unless `--keep`) and deletes the dump file (unless `--dump-path`).

The source database is only read. Nothing is written to it.

### What the fingerprint covers

Tables are **discovered from the catalog** for each schema in `--schemas` (default
`oc_constituent,oc_communications`), so tables added later — payments, donations, anything — are covered
with no code change. A new schema (for example `oc_crm_money`) needs only to be added to `--schemas`;
a requested schema that does not exist yet is reported as a warning, not dumped.

Per table: row count; SHA-256 over `row_to_json(row)` ordered by primary key (text keys under `COLLATE "C"`,
session pinned to `TimeZone=UTC`, ISO dates, `extra_float_digits=1`, hex bytea so the digest is stable across
clusters); column definitions; RLS enabled/forced flags; policy names, roles, `USING`/`WITH CHECK`; non-internal
triggers and whether they are enabled; constraints and `convalidated`; indexes; table GRANTs. Per schema:
functions (source hash). Sequences: position, and whether it is ahead of the highest id it owns — a lagging
sequence would reissue ids, which the drill reports as an error.

### Read privileges (important)

Fingerprints must be taken as a superuser or the table owner, **never** as `oc_crm_runtime`: RLS would hide other
tenants and the fingerprint would describe one tenant while looking complete. The harness sets
`row_security = off`; if RLS would still apply to the connecting role, PostgreSQL raises an error rather than
silently filtering. `pg_dump` behaves the same way by default.

### Roles caveat

Roles are cluster-level objects and are **not** in `pg_dump` output. That includes `oc_crm_runtime` (NOLOGIN)
and the `GRANT oc_crm_runtime TO <backend_login>` membership. Before restoring into a new cluster, create them:

```sql
CREATE ROLE oc_crm_runtime NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
GRANT oc_crm_runtime TO <backend_login>;
```

(Re-applying `migrations/20260927_society_crm_p1_tenant_isolation.sql` as the backend login after restore also
does this, idempotently.) The drill's `checks.roles` reports any role a restored policy references but the target
cluster lacks; `pg_restore --exit-on-error` would also fail on the missing role.

## What the drill proves — and what it does not

Proves (when `pass` is `true`):

- A `pg_dump -Fc` of the CRM schemas restores with every row identical, table by table, and with the same RLS
  policies, triggers, constraints (including `NOT VALID` state), indexes, grants, functions, and sequence positions.
- Tenant isolation and audit immutability actually work in the restored copy, not just on paper.
- The comparison is not vacuous: CI tampers with a restored copy (deleted membership, changed preference, RLS
  disabled, trigger disabled, policy dropped, sequence rewound) and asserts each exact discrepancy is reported.

Does **not** prove:

- That Neon/Render provider backups or point-in-time recovery (PITR) work, or how far back they reach.
- **RPO** (how much data could be lost) or **RTO** (how long recovery takes) for production. Both are unmeasured
  until an operator runs the production drill below and records the timings and restore point.
- Anything outside the listed schemas: Supabase auth users, other Orchid Continuum schemas, file storage,
  email-provider state, or roles.
- That the application layer (Render service, environment secrets, `GRANT oc_crm_runtime TO <login>`) is correctly
  reconnected after a restore.
- Tenant isolation between organizations when the data has fewer than two organizations (`checks.isolation.status`
  is then `insufficient_data` and `isolation_verified_between_tenants` is `false`).

## How to run

Requirements: Python with `psycopg`; `pg_dump`/`pg_restore` at least as new as the servers (PostgreSQL 16 client
for a 16 server; set `PG_DUMP_BIN`/`PG_RESTORE_BIN` or `--pg-dump-bin`/`--pg-restore-bin`); a login for
`--admin-dsn` that may `CREATE DATABASE` and `DROP DATABASE` and can `SET ROLE oc_crm_runtime`.

```bash
python scripts/oc_crm_backup_restore_drill.py \
  --source-dsn "$SOURCE_DSN" \
  --admin-dsn "$SCRATCH_ADMIN_DSN" \
  --schemas oc_constituent,oc_communications \
  --output crm-restore-drill.json
```

Exit code `0` = pass, `1` = drill ran and found problems, `2` = drill could not run (connectivity, binaries,
configuration). Passwords are never printed; prefer `PGPASSWORD`/`.pgpass` over passwords embedded in DSNs.

Options: `--keep` leaves the scratch database for inspection (drop it later with
`drop_scratch_database(admin_dsn, name)`, which refuses any name without the `oc_restore_drill_` prefix);
`--dump-path FILE` keeps the dump; `--isolation-org-limit N` bounds how many organizations are exercised (default 20).

### Production drill (operator-run, against a provider copy — never the primary)

The CI proof uses a disposable PostgreSQL. The production proof must be run by an operator against a provider
backup/branch, so the primary is never touched:

**Neon (branch restore):**

1. Neon Console → your project → **Branches** → **Create branch**. Parent: the production branch. Choose
   **point in time** and enter the restore target timestamp (for a routine drill: e.g. 1 hour ago). Record the
   timestamp — that is your restore point.
2. On the new branch, copy the connection string for a role that owns the CRM tables (the same owner role as
   production). Record wall-clock time from step 1 to a connectable branch — that is the provider part of RTO.
3. Run the drill with `--source-dsn` = the **branch** connection string. For `--admin-dsn`, use a role on the
   branch allowed to create databases, or a separate disposable PostgreSQL 16 where `oc_crm_runtime` exists.
   Never point `--admin-dsn` at the production primary.
4. Attach `crm-restore-drill.json` to issue #1659 with: restore-point timestamp, branch-creation time, drill
   timings, and the newest `created_at` in `crm_audit_events` on the branch (the gap to the incident/primary is
   your observed RPO).
5. Delete the branch in the Neon Console when finished.

(Neon's CLI `neonctl branches create` can do step 1; check current Neon documentation for the exact
point-in-time flags before scripting it.)

**Render PostgreSQL:** restore a backup / point-in-time recovery into a **new** database instance from the Render
dashboard, then run the drill with `--source-dsn` pointing at that new instance, exactly as above.

Until at least one production drill is recorded, report RPO and RTO as **unmeasured**.

## Reading the report

- `pass` — the verdict. `true` only when there are no error-severity discrepancies and the roles, isolation, and
  append-only checks did not fail.
- `discrepancies[]` — each has `category`, `object`, `severity`, and a plain-English `message`, e.g.
  `table oc_constituent.memberships: 12 rows in backup source, 11 after restore [missing after restore: id=4412]`.
  `details.rows` lists the primary keys missing/extra/changed after restore (up to 20 each, plus counts).
- `tables{}` — per table: `source_rows`, `restored_rows`, digests, `match`.
- `sequences{}` — source and restored sequence positions.
- `checks.roles|isolation|append_only_guards` — status plus `failures[]` in plain English.
- `warnings[]` — absent schemas, tables present only after restore, isolation not provable with one organization.
- `timings`, `dump_bytes`, `pg_dump_version`, `scratch_database` (+ `scratch_database_dropped`/`_kept`).

## Incident recovery

**Ordinary society administrator (no database access):**

1. Stop making changes in the CRM and tell the platform operator what you saw and when (time, organization,
   which members or records look wrong). Do not re-enter data to "fix" it — that makes reconciliation harder.
2. Ask the operator for the restore point they will use, and confirm which of your recent changes (after that
   time) you will need to re-apply.
3. After the operator confirms recovery, spot-check a few members you know, and re-apply only the changes after
   the restore point.

**Developer / platform operator:**

1. Freeze writes (disable the CRM routes or scale the service to zero). Record the incident start time.
2. Create a provider copy at the last known-good point (Neon branch / Render PITR to a new instance). Never restore
   over the primary.
3. Run this drill against the copy. Do not proceed unless `pass` is `true`; fix every `[error]` first (missing roles:
   create them; missing rows: choose an earlier/later restore point).
4. Ensure `oc_crm_runtime` exists and `GRANT oc_crm_runtime TO <backend_login>` is in place on the target.
5. Repoint the service (`DATABASE_URL`) to the verified copy, or, if only some rows were lost, reconcile those rows
   from the copy into the primary with reviewed SQL (append-only audit/renewal ledgers are never edited; add new
   audit events describing the recovery).
6. Unfreeze, record RPO/RTO actually observed, and attach the drill report to the incident issue.

Owner-governed boundaries still apply: repointing production, restoring over production, or mutating the
production database requires owner authorization.
