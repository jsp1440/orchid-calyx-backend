-- BUILD-031 — Institutional Memory and Founding Charter
-- Creates the oc_philosophy schema for permanent Orchid Continuum philosophy memory.

CREATE SCHEMA IF NOT EXISTS oc_philosophy;

CREATE TABLE IF NOT EXISTS oc_philosophy.documents (
    id BIGSERIAL PRIMARY KEY,
    document_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    version_label TEXT NOT NULL DEFAULT '1.0',
    status TEXT NOT NULL DEFAULT 'active',
    document_type TEXT NOT NULL,
    body_markdown TEXT NOT NULL,
    source_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_philosophy.principles (
    id BIGSERIAL PRIMARY KEY,
    principle_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    category TEXT NOT NULL,
    source_document_key TEXT REFERENCES oc_philosophy.documents(document_key),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_philosophy.constitution_articles (
    id BIGSERIAL PRIMARY KEY,
    article_number INTEGER NOT NULL UNIQUE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    source_document_key TEXT REFERENCES oc_philosophy.documents(document_key),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oc_philosophy.institutional_memory (
    id BIGSERIAL PRIMARY KEY,
    memory_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    body_markdown TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    source_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON SCHEMA oc_philosophy IS 'Permanent philosophical and institutional memory for the Orchid Continuum.';
COMMENT ON TABLE oc_philosophy.documents IS 'Founding documents, charters, constitutions, and philosophical essays.';
COMMENT ON TABLE oc_philosophy.principles IS 'Operational principles used by Calyx and contributors to evaluate future work.';
COMMENT ON TABLE oc_philosophy.constitution_articles IS 'Constitutional articles for the Orchid Continuum founding philosophy.';
COMMENT ON TABLE oc_philosophy.institutional_memory IS 'Narrative memory preserving why major philosophical and architectural decisions were made.';
