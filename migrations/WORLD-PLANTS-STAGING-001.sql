BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_source;

CREATE TABLE IF NOT EXISTS oc_source.world_plants_releases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_system text NOT NULL DEFAULT 'world_plants_hassler',
    version_label text NOT NULL,
    acquired_at date NOT NULL,
    original_filename text NOT NULL,
    sha256 text NOT NULL UNIQUE,
    byte_count bigint NOT NULL CHECK (byte_count >= 0),
    row_count integer NOT NULL CHECK (row_count >= 0),
    source_encoding text,
    status text NOT NULL DEFAULT 'inspected'
        CHECK (status IN ('inspected', 'staged', 'compared', 'awaiting_owner', 'approved', 'promoted', 'rejected', 'superseded', 'failed')),
    notes text,
    inspection jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    promoted_at timestamptz,
    promoted_by text,
    CONSTRAINT world_plants_release_promotion_guard CHECK (
        (status <> 'promoted') OR (promoted_at IS NOT NULL AND promoted_by IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS oc_source.world_plants_release_rows (
    release_id uuid NOT NULL REFERENCES oc_source.world_plants_releases(id) ON DELETE RESTRICT,
    source_row_number integer NOT NULL CHECK (source_row_number > 1),
    taxon_code text NOT NULL,
    world_plants_number text,
    scientific_name text NOT NULL,
    literature text,
    trivial_name text,
    distribution text,
    synonyms_raw text,
    status_raw text,
    remarks text,
    conservation_status text,
    raw_values jsonb NOT NULL,
    identity_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (release_id, source_row_number)
);

CREATE INDEX IF NOT EXISTS idx_world_plants_rows_identity
    ON oc_source.world_plants_release_rows (release_id, identity_key);

CREATE TABLE IF NOT EXISTS oc_source.world_plants_release_photos (
    release_id uuid NOT NULL REFERENCES oc_source.world_plants_releases(id) ON DELETE RESTRICT,
    source_row_number integer NOT NULL,
    slot smallint NOT NULL CHECK (slot BETWEEN 1 AND 4),
    photo text,
    orientation text,
    author text,
    PRIMARY KEY (release_id, source_row_number, slot),
    FOREIGN KEY (release_id, source_row_number)
        REFERENCES oc_source.world_plants_release_rows(release_id, source_row_number)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS oc_source.world_plants_release_deltas (
    release_id uuid NOT NULL REFERENCES oc_source.world_plants_releases(id) ON DELETE RESTRICT,
    previous_release_id uuid REFERENCES oc_source.world_plants_releases(id) ON DELETE RESTRICT,
    delta_type text NOT NULL CHECK (delta_type IN ('added', 'removed', 'unchanged', 'changed', 'duplicate', 'ambiguous')),
    identity_key text NOT NULL,
    previous_payload jsonb,
    current_payload jsonb,
    review_status text NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending', 'accepted', 'rejected', 'manual_review')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (release_id, delta_type, identity_key)
);

CREATE TABLE IF NOT EXISTS oc_source.world_plants_promotion_receipts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    release_id uuid NOT NULL REFERENCES oc_source.world_plants_releases(id) ON DELETE RESTRICT,
    actor text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('approve', 'reject', 'promote', 'rollback')),
    reason text,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

COMMIT;
