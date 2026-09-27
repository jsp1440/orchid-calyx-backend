# OC-CRM-IMPORT-EXPORT-001 — Neon import, reconciliation, and export (FCOS shadow pilot)

Issue: #1655. Code: `app/constituent_platform/crm_import.py`, `crm_reconcile.py`, `crm_export.py`.
Tests: `tests/test_society_crm_import_export.py`.

## Posture

- **Neon remains the system of record** for the whole shadow pilot. Orchid Continuum (OC)
  holds a shadow copy that is checked against Neon; OC never pushes data back to Neon.
- Import creates only new records. **It never overwrites an OC record.** Differences
  between Neon and OC are reported as conflicts for a person to resolve.
- Every apply run, reconciliation, and export is audited (`import.started` /
  `import.completed` / `import.failed`, `reconciliation.run`, `export.roster`,
  `export.organization`). Audit metadata holds counts and hashes only, never names,
  emails, or addresses.

Required capabilities: import and reconciliation need `member.import` (admin,
membership_editor). Roster CSV export needs `roster.export` (admin, membership_editor,
treasurer). Full organization export needs `organization.export` (admin only).

## Shadow-pilot procedure

1. **Export from Neon.** Use the same saved Neon report every time, so the columns do not
   change between runs. Export it as CSV (UTF-8).
2. **Verify the mapping** against that file (checklist below) before the first run, and
   again whenever the Neon report changes.
3. **Dry run.** `import_members(..., dry_run=True)` is the default and writes nothing to the
   database, not even an audit event. Read the report:
   - `accepted: false` → the mapping or the file is wrong; see `fatal_errors`. Nothing ran.
   - `unknown_headers` → Neon columns the mapping does not use. Confirm each one should be ignored.
   - `counts` → `create`, `unchanged`, `conflict`, `possible_duplicate`, `invalid`,
     `duplicate_in_file`. They always add up to `total_rows`.
   - Each row has its row number, the Neon id, reason codes, and a message saying what to fix.
4. **Fix** what the report shows: fix it in Neon and export again, or change the mapping.
   Re-run the dry run until only rows you expect remain.
5. **Apply.** Run again with `dry_run=False`. Each new member is written as one unit
   (person, email, phone, address, membership, Neon link). If a row fails, only that row
   is rolled back, and it is reported as `invalid`.
6. **Reconcile.** Run `reconcile(...)` on each new Neon export: daily while memberships
   are being entered, weekly after that. Review `missing_in_oc`, `extra_in_oc` and `changed`.
7. **Repeat safely.** Running the same file again does nothing: every linked row comes back
   `unchanged`, and no new records are created.

## Mapping verification checklist

`NEON_DEFAULT_MAPPING` is **an unverified assumption**. Nobody has checked it against a
real FCOS export yet. Before the first apply run:

- [ ] Every header in the mapping exists in the file, spelled exactly the same (the import
      rejects the file if one is missing).
- [ ] The `source_record_id` column (assumed to be `Account ID`) is Neon's stable id. It
      must not be a row number or a membership-transaction id that changes on renewal.
      If Neon exports one row per membership term, decide which id identifies the member.
- [ ] Name columns: `First Name`/`Last Name`, or a single display-name column.
- [ ] Every distinct `Membership Level` value is listed in `level_value_map`, and each maps
      to an existing, active OC level code. (The default map is empty on purpose.)
- [ ] Every distinct `Membership Status` value is listed in `status_value_map`
      (the default map assumes Active/Grace/Lapsed/Pending/Cancelled).
- [ ] Every distinct `Country` value either maps in `country_value_map` or is already a
      two-letter code.
- [ ] The date format matches the file (the default is `%m/%d/%Y`). List only one format
      unless you are sure the formats cannot be confused. If two listed formats read the
      same value as different dates, the row is rejected as `DATE_AMBIGUOUS`. The import
      never guesses a date.
- [ ] `Email 1` is the member's primary email, not a household or billing address.
- [ ] A dry run on the real file shows no unexpected `invalid` rows.

## Conflict resolution policy

- `conflict` (import) and `changed` (reconciliation) come with a field-level diff showing
  both values: `{"field": {"oc": ..., "incoming": ...}}`. **The import does not pick a
  winner.**
- During the pilot, the Neon value is presumed correct, unless the OC value records a
  change the member asked for that Neon has not received yet. Then update Neon first.
- To resolve a conflict, correct the record in the system that is wrong, through its normal
  audited edit path (OC: the member edit, status or level operations). Then reconcile again.
  Do not delete links or records to make a report clean.
- `possible_duplicate`: an unlinked OC person already has this email. Confirm whether it is
  the same person. If it is, merge or link the records by hand. If it is not, give one of
  them a distinct email in Neon.
- `duplicate_in_file`: the same Neon id or email appears more than once in the export. Fix
  it in Neon. Only the first row with that id or email was considered.
- A membership's `status` can differ only because time has passed. For example, the OC
  lifecycle moved a member from active to grace at expiry before Neon was exported again.
  That shows up as `changed`. Check the dates before treating it as an error.

## What "clean" means

`ReconciliationReport.clean` is `true` only when the mapping was accepted and all of the
following are empty: `missing_in_oc`, `extra_in_oc`, `changed`, `invalid`, and
`duplicate_in_file`. So every row in the Neon export is linked to an OC membership whose
mapped fields match, and OC has no membership the export does not account for. A clean
report says the two systems agree on the mapped fields at the moment of that export.
It says nothing about fields the mapping does not carry.

## Membership dates and the renewal ledger

An imported membership gets the status and dates Neon reports, with `source_kind='import'`
and `source_ref='neon:<id>'`. No row is added to `membership_renewals`. That ledger records
renewals OC itself applied, and a renewal computed in OC cannot reproduce Neon's
paid-through date without inventing a renewal date. A Neon `Cancelled` member is created
as pending, with its dates, and then cancelled through the audited status transition.

## How to leave Orchid Continuum (full export)

`export_organization(...)` needs an admin. It returns one versioned JSON document
(`schema_version`, `exported_at`, `row_counts`, `body_sha256`) with every row the society
owns in the CRM: the organization, levels, people, emails, phones, addresses, memberships,
renewals, household members, staff roles, identity bindings, entitlements, communication
preferences, suppressions, communication intents, external (Neon) links, and the full audit
trail. It is read in one consistent snapshot under the society's row-level-security
context, so it contains no other society's rows.

- Check the file with `verify_organization_export(doc)`. It recomputes the sha256 of the
  canonical JSON body.
- The export contains personal data. Store and send it as you would the member roster.
- Not included: platform-global account links (`identity_links`) and communication audience
  and approval tables. Those tables are not organization-scoped in the current schema.
- The export's own `export.organization` audit event is written after the snapshot, so the
  export does not contain it.

The roster CSV (`export_roster_csv`) is for mailings and spreadsheets. It is not a
complete export. To protect against formula injection, any cell that starts with
`= + - @`, a tab, or a carriage return gets a leading `'`. That means phone numbers appear
as `'+1...`.
