BEGIN;

CREATE TABLE IF NOT EXISTS oc_concepts.concept_labels (
    label_id UUID PRIMARY KEY,
    concept_id UUID NOT NULL REFERENCES oc_concepts.concepts(concept_id),
    label_type TEXT NOT NULL CHECK (label_type IN (
        'PREFERRED','ALTERNATE','HIDDEN','HISTORICAL','ABBREVIATION',
        'SCIENTIFIC_NAME','COMMON_NAME','MISSPELLING'
    )),
    label TEXT NOT NULL CHECK (btrim(label) <> ''),
    normalized_label TEXT NOT NULL CHECK (btrim(normalized_label) <> ''),
    language TEXT NOT NULL DEFAULT 'und',
    script TEXT,
    editorial_context TEXT NOT NULL DEFAULT 'default',
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_state TEXT NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revised_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_concept_preferred_label_context
ON oc_concepts.concept_labels(concept_id, language, editorial_context)
WHERE label_type = 'PREFERRED';

CREATE INDEX IF NOT EXISTS ix_concept_labels_normalized
ON oc_concepts.concept_labels(normalized_label);

CREATE INDEX IF NOT EXISTS ix_concept_labels_concept
ON oc_concepts.concept_labels(concept_id);

CREATE TABLE IF NOT EXISTS oc_concepts.concept_definitions (
    definition_id UUID PRIMARY KEY,
    concept_id UUID NOT NULL REFERENCES oc_concepts.concepts(concept_id),
    definition_type TEXT NOT NULL CHECK (definition_type IN (
        'NORMATIVE_SCIENTIFIC','GLOSSARY','GROWER','LEARNER',
        'PLAIN_LANGUAGE','HISTORICAL'
    )),
    text TEXT NOT NULL CHECK (btrim(text) <> ''),
    language TEXT NOT NULL DEFAULT 'und',
    script TEXT,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_state TEXT NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revised_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_concept_definitions_concept
ON oc_concepts.concept_definitions(concept_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_concept_definition_variant
ON oc_concepts.concept_definitions(concept_id, definition_type, language);

REVOKE ALL ON oc_concepts.concept_labels FROM PUBLIC;
REVOKE ALL ON oc_concepts.concept_definitions FROM PUBLIC;

COMMIT;
