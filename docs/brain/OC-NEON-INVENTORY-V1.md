# Neon scientific-memory inventory

The command below inventories the historical Orchid Continuum PostgreSQL/Neon store without mutating it:

    python scripts/oc_neon_inventory.py > neon-inventory.json

The script intentionally targets DATABASE_URL because app/database.py currently documents DATABASE_URL as the Neon/Orchid Continuum database while PGHOST may refer to a separate Calyx runtime database.

Safety properties:
- PostgreSQL default_transaction_read_only is forced and verified.
- No DDL or DML is executed.
- No scientific rows are sampled.
- Counts use PostgreSQL statistics rather than full-table scans.
- Credentials and raw connection strings are never emitted.

The inventory is evidence for architectural reconciliation. It is not authority to create, merge, delete, rename, or migrate any Neon schema.

Next step after obtaining the receipt: classify each existing schema/relation as canonical scientific memory, runtime/control state, cache/derived state, archive candidate, duplicate/legacy candidate, or unknown. Unknown and legacy candidates remain untouched until provenance and consumers are identified.
