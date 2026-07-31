BEGIN;

CREATE SCHEMA IF NOT EXISTS oc_brain;

CREATE TABLE IF NOT EXISTS oc_brain.connector_registrations (
    connector_id text PRIMARY KEY,
    name text NOT NULL,
    version text NOT NULL,
    capabilities jsonb NOT NULL DEFAULT '[]'::jsonb,
    enabled boolean NOT NULL DEFAULT false,
    configuration_reference text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(capabilities) = 'array')
);

CREATE TABLE IF NOT EXISTS oc_brain.outreach_nodes (
    outreach_node_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    node_type text NOT NULL,
    canonical_key text NOT NULL UNIQUE,
    display_label text NOT NULL,
    expertise jsonb NOT NULL DEFAULT '[]'::jsonb,
    audiences jsonb NOT NULL DEFAULT '[]'::jsonb,
    interests jsonb NOT NULL DEFAULT '[]'::jsonb,
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oc_brain.outreach_edges (
    outreach_edge_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    edge_type text NOT NULL,
    from_node_id bigint NOT NULL REFERENCES oc_brain.outreach_nodes(outreach_node_id),
    to_node_id bigint NOT NULL REFERENCES oc_brain.outreach_nodes(outreach_node_id),
    confidence numeric(7,6) CHECK (confidence >= 0 AND confidence <= 1),
    evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
    engagement_history jsonb NOT NULL DEFAULT '[]'::jsonb,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (edge_type, from_node_id, to_node_id),
    CHECK (from_node_id <> to_node_id)
);

CREATE INDEX IF NOT EXISTS outreach_nodes_type_idx ON oc_brain.outreach_nodes(node_type) WHERE is_active;
CREATE INDEX IF NOT EXISTS outreach_edges_from_idx ON oc_brain.outreach_edges(from_node_id, edge_type) WHERE is_active;
CREATE INDEX IF NOT EXISTS outreach_edges_to_idx ON oc_brain.outreach_edges(to_node_id, edge_type) WHERE is_active;

COMMIT;
