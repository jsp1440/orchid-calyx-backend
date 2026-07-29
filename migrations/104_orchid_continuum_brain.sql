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

CREATE TABLE IF NOT EXISTS oc_brain.inference_runs (
    inference_run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subject_node_id bigint NOT NULL REFERENCES oc_graph.kg_nodes(kg_node_id),
    inference_type text NOT NULL,
    rule_version text NOT NULL,
    graph_version_id bigint,
    requested_by text NOT NULL,
    status text NOT NULL DEFAULT 'CANDIDATE',
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status IN ('CANDIDATE', 'REVIEWED', 'REJECTED', 'SUPERSEDED'))
);

CREATE TABLE IF NOT EXISTS oc_brain.inference_results (
    inference_result_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    inference_run_id bigint NOT NULL REFERENCES oc_brain.inference_runs(inference_run_id),
    candidate_node_id bigint REFERENCES oc_graph.kg_nodes(kg_node_id),
    confidence numeric(7,6) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
    supporting_citations jsonb NOT NULL DEFAULT '[]'::jsonb,
    reasoning_chain jsonb NOT NULL DEFAULT '[]'::jsonb,
    review_status text NOT NULL DEFAULT 'PENDING',
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (review_status IN ('PENDING', 'ACCEPTED', 'REJECTED', 'NEEDS_REVISION')),
    CHECK (jsonb_typeof(evidence) = 'array'),
    CHECK (jsonb_typeof(supporting_citations) = 'array'),
    CHECK (jsonb_typeof(reasoning_chain) = 'array')
);

CREATE TABLE IF NOT EXISTS oc_brain.literature_records (
    literature_record_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider text NOT NULL,
    provider_record_id text NOT NULL,
    doi text,
    title text,
    authors jsonb NOT NULL DEFAULT '[]'::jsonb,
    keywords jsonb NOT NULL DEFAULT '[]'::jsonb,
    abstract text,
    citation_count integer,
    source_payload_hash text NOT NULL,
    retrieved_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_record_id),
    CHECK (jsonb_typeof(authors) = 'array'),
    CHECK (jsonb_typeof(keywords) = 'array')
);

CREATE UNIQUE INDEX IF NOT EXISTS literature_records_provider_doi_uq
    ON oc_brain.literature_records(provider, lower(doi)) WHERE doi IS NOT NULL;

CREATE TABLE IF NOT EXISTS oc_brain.literature_graph_links (
    literature_record_id bigint NOT NULL REFERENCES oc_brain.literature_records(literature_record_id),
    kg_node_id bigint NOT NULL REFERENCES oc_graph.kg_nodes(kg_node_id),
    link_type text NOT NULL,
    confidence numeric(7,6) CHECK (confidence >= 0 AND confidence <= 1),
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (literature_record_id, kg_node_id, link_type)
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

CREATE INDEX IF NOT EXISTS inference_runs_subject_idx ON oc_brain.inference_runs(subject_node_id, created_at DESC);
CREATE INDEX IF NOT EXISTS inference_results_run_idx ON oc_brain.inference_results(inference_run_id);
CREATE INDEX IF NOT EXISTS outreach_nodes_type_idx ON oc_brain.outreach_nodes(node_type) WHERE is_active;
CREATE INDEX IF NOT EXISTS outreach_edges_from_idx ON oc_brain.outreach_edges(from_node_id, edge_type) WHERE is_active;
CREATE INDEX IF NOT EXISTS outreach_edges_to_idx ON oc_brain.outreach_edges(to_node_id, edge_type) WHERE is_active;

COMMIT;
