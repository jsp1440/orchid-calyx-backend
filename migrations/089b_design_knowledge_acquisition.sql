-- BUILD-089B additive semantic reasoning layer. No source or BUILD-089A rows are mutated.
CREATE TABLE IF NOT EXISTS oc_design_intelligence.semantic_units (
 unit_id CHAR(64) PRIMARY KEY,
 document_id BIGINT NOT NULL REFERENCES oc_design_intelligence.documents(document_id),
 document_version INTEGER NOT NULL CHECK(document_version > 0),
 ordinal INTEGER NOT NULL CHECK(ordinal > 0),
 parent_unit_id CHAR(64) REFERENCES oc_design_intelligence.semantic_units(unit_id),
 unit_type TEXT NOT NULL CHECK(unit_type IN(
  'HEADING','SECTION','PARAGRAPH','BULLET_LIST','NUMBERED_PROCEDURE','TABLE','CAPTION',
  'CODE_EXAMPLE','QUOTED_GUIDANCE','RECOMMENDATION','WARNING','ANTI_PATTERN','BEST_PRACTICE')),
 authorized_text TEXT NOT NULL,
 source_location JSONB NOT NULL,
 domains JSONB NOT NULL DEFAULT '[]'::jsonb,
 educational_classifications JSONB NOT NULL DEFAULT '[]'::jsonb,
 knowledge_types JSONB NOT NULL DEFAULT '[]'::jsonb,
 classification_confidence NUMERIC NOT NULL CHECK(classification_confidence BETWEEN 0 AND 1),
 classification_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
 classification_version TEXT NOT NULL,
 embedding JSONB NOT NULL,
 embedding_metadata JSONB NOT NULL,
 search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', authorized_text)) STORED,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(document_id, document_version, ordinal)
);

CREATE TABLE IF NOT EXISTS oc_design_intelligence.semantic_relationships (
 relationship_id CHAR(64) PRIMARY KEY,
 source_unit_id CHAR(64) NOT NULL REFERENCES oc_design_intelligence.semantic_units(unit_id),
 target_unit_id CHAR(64) NOT NULL REFERENCES oc_design_intelligence.semantic_units(unit_id),
 relationship_type TEXT NOT NULL CHECK(relationship_type IN(
  'SUPPORTS','CONTRADICTS','EXTENDS','SPECIALIZES','RELATED_TO','USED_BY','IMPROVES','REQUIRES','REFERENCES')),
 confidence NUMERIC NOT NULL CHECK(confidence BETWEEN 0 AND 1),
 rationale TEXT NOT NULL,
 provenance JSONB NOT NULL,
 generator_version TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 CHECK(source_unit_id <> target_unit_id),
 UNIQUE(source_unit_id, target_unit_id, relationship_type, generator_version)
);

CREATE TABLE IF NOT EXISTS oc_design_intelligence.semantic_audit_events (
 semantic_audit_event_id BIGSERIAL PRIMARY KEY,
 unit_id CHAR(64) REFERENCES oc_design_intelligence.semantic_units(unit_id),
 relationship_id CHAR(64) REFERENCES oc_design_intelligence.semantic_relationships(relationship_id),
 event_type TEXT NOT NULL,
 details JSONB NOT NULL DEFAULT '{}'::jsonb,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 CHECK(unit_id IS NOT NULL OR relationship_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS design_semantic_document_idx
 ON oc_design_intelligence.semantic_units(document_id, document_version, ordinal);
CREATE INDEX IF NOT EXISTS design_semantic_fts_idx
 ON oc_design_intelligence.semantic_units USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS design_semantic_domains_idx
 ON oc_design_intelligence.semantic_units USING GIN(domains);
CREATE INDEX IF NOT EXISTS design_semantic_types_idx
 ON oc_design_intelligence.semantic_units USING GIN(knowledge_types);
CREATE INDEX IF NOT EXISTS design_relationship_source_idx
 ON oc_design_intelligence.semantic_relationships(source_unit_id, relationship_type);
CREATE INDEX IF NOT EXISTS design_relationship_target_idx
 ON oc_design_intelligence.semantic_relationships(target_unit_id, relationship_type);

DO $$ DECLARE table_name TEXT; BEGIN
 FOREACH table_name IN ARRAY ARRAY['semantic_units','semantic_relationships','semantic_audit_events'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='protect_089b_'||table_name) THEN
   EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON oc_design_intelligence.%I FOR EACH ROW EXECUTE FUNCTION oc_design_intelligence.reject_mutation()','protect_089b_'||table_name,table_name);
  END IF;
 END LOOP;
END $$;
REVOKE UPDATE, DELETE ON oc_design_intelligence.semantic_units,
 oc_design_intelligence.semantic_relationships,
 oc_design_intelligence.semantic_audit_events FROM PUBLIC;
