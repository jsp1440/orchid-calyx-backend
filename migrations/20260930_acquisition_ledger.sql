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
--     is added only when no single-column unique index on resource_key exists.
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
-- Apply with scripts/activate_acquisition_ledger_schema.py (preflight by
-- default; --apply plus an explicit confirmation), which runs this file in a
-- single transaction. Production application is an owner deployment action.

SET LOCAL lock_timeout = '5s';

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

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_index AS i
        JOIN pg_attribute AS a
          ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]
        WHERE i.indrelid = 'acquisition_ledger'::regclass
          AND i.indisunique
          AND i.indnkeyatts = 1
          AND i.indpred IS NULL
          AND a.attname = 'resource_key'
    ) THEN
        ALTER TABLE acquisition_ledger
            ADD CONSTRAINT uq_acquisition_resource_key UNIQUE (resource_key);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_acquisition_ledger_resource_key
    ON acquisition_ledger (resource_key);
CREATE INDEX IF NOT EXISTS ix_acquisition_ledger_provider
    ON acquisition_ledger (provider);
