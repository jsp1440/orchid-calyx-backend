-- Shared acquisition ledger (app/source_federation/acquisition_models.py).
--
-- The ledger leases paid external acquisitions (Firecrawl Map). Before this
-- file nothing created the table outside the tests, and the lease-fencing
-- column ``lease_token`` (PR #1697) had no migration at all.
--
-- Additive and idempotent: running it twice is a no-op. It never drops,
-- truncates, rewrites or retypes anything, and it never updates a row.
--   * CREATE TABLE IF NOT EXISTS with the model's exact columns, types,
--     nullability, primary key and unique constraint.
--   * ADD COLUMN IF NOT EXISTS for every NULLABLE model column, so a table
--     created from an older model (the pre-#1697 table has no lease_token)
--     converges. Adding a nullable column without a default is a catalog-only
--     change in PostgreSQL 11+: no table rewrite, existing rows read NULL,
--     which the ledger treats as "written before the token column existed".
--   * The unique constraint on resource_key (claim coalescing depends on it)
--     is added unless a valid, non-partial unique key on it already exists.
--   * The two model indexes, IF NOT EXISTS.
--
-- A NOT NULL column missing from an existing table, or a column with an
-- incompatible type, is deliberately NOT repaired here (either would need a
-- default or a rewrite). The runtime schema check
-- (app/source_federation/acquisition_ledger_schema.py) reports it and the
-- ledger fails closed with zero paid calls.
--
-- Unqualified names, exactly like the model (no __table_args__ schema): the
-- table resolves through the connection's search_path, as the ORM does.
--
-- Run it as ONE transaction: SET LOCAL and the advisory lock are
-- transaction-scoped. Either scripts/activate_acquisition_ledger_schema.py
-- (preflight by default; --apply plus an explicit confirmation), or
--   psql -1 -v ON_ERROR_STOP=1 -f migrations/20260930_acquisition_ledger.sql
-- Re-running it is always safe. Production application is an owner
-- deployment action.

SET LOCAL lock_timeout = '5s';
-- Serialise concurrent runs: two sessions racing CREATE TABLE IF NOT EXISTS on
-- an empty database would otherwise fail in the loser.
SELECT pg_advisory_xact_lock(hashtext('oc_acquisition_ledger_migration'));

CREATE TABLE IF NOT EXISTS acquisition_ledger (
    id SERIAL NOT NULL,
    resource_key VARCHAR(64) NOT NULL,
    provider VARCHAR(80) NOT NULL,
    canonical_url TEXT NOT NULL,
    status VARCHAR(24) NOT NULL,
    content_hash VARCHAR(64),
    durable_object_ref TEXT,
    payload_json TEXT,
    etag TEXT,
    last_modified TEXT,
    provenance_json TEXT NOT NULL,
    consumers_json TEXT NOT NULL,
    credits_spent INTEGER NOT NULL,
    failure_count INTEGER NOT NULL,
    next_retry_at TIMESTAMP WITH TIME ZONE,
    lease_holder VARCHAR(160),
    lease_token VARCHAR(64),
    lease_expires_at TIMESTAMP WITH TIME ZONE,
    retrieved_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_acquisition_resource_key UNIQUE (resource_key)
);

ALTER TABLE acquisition_ledger ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);
ALTER TABLE acquisition_ledger ADD COLUMN IF NOT EXISTS durable_object_ref TEXT;
ALTER TABLE acquisition_ledger ADD COLUMN IF NOT EXISTS payload_json TEXT;
ALTER TABLE acquisition_ledger ADD COLUMN IF NOT EXISTS etag TEXT;
ALTER TABLE acquisition_ledger ADD COLUMN IF NOT EXISTS last_modified TEXT;
ALTER TABLE acquisition_ledger ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE acquisition_ledger ADD COLUMN IF NOT EXISTS lease_holder VARCHAR(160);
ALTER TABLE acquisition_ledger ADD COLUMN IF NOT EXISTS lease_token VARCHAR(64);
ALTER TABLE acquisition_ledger ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE acquisition_ledger ADD COLUMN IF NOT EXISTS retrieved_at TIMESTAMP WITH TIME ZONE;

-- The unique key claim coalescing depends on. Only a NON-partial, valid,
-- ready, immediate unique index on exactly (resource_key) counts: a partial
-- index or an INVALID one (left by a failed CREATE UNIQUE INDEX CONCURRENTLY)
-- does not stop a second insert of the same key, i.e. a second paid lease.
-- If none exists the real constraint is added; anything that prevents that
-- raises a clear error (the whole transaction rolls back). Never skipped.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_index AS i
        JOIN pg_attribute AS a
          ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]
        WHERE i.indrelid = 'acquisition_ledger'::regclass
          AND i.indisunique
          AND i.indisvalid
          AND i.indisready
          AND i.indislive
          AND i.indimmediate
          AND i.indpred IS NULL
          AND i.indexprs IS NULL
          AND i.indnkeyatts = 1
          AND a.attname = 'resource_key'
    ) THEN
        IF EXISTS (
            SELECT 1 FROM acquisition_ledger
            GROUP BY resource_key HAVING count(*) > 1
        ) THEN
            RAISE EXCEPTION
                'acquisition_ledger has duplicate resource_key rows and no valid unique key; resolve the duplicates (owner decision) and re-run';
        END IF;
        IF to_regclass('uq_acquisition_resource_key') IS NOT NULL THEN
            RAISE EXCEPTION
                'relation uq_acquisition_resource_key exists but is not a valid non-partial unique key on resource_key (e.g. an INVALID index from a failed CREATE INDEX CONCURRENTLY); remove or rebuild it (owner decision) and re-run';
        END IF;
        ALTER TABLE acquisition_ledger
            ADD CONSTRAINT uq_acquisition_resource_key UNIQUE (resource_key);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_acquisition_ledger_resource_key
    ON acquisition_ledger (resource_key);
CREATE INDEX IF NOT EXISTS ix_acquisition_ledger_provider
    ON acquisition_ledger (provider);
