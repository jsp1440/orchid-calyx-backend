"""PostgreSQL adapter for the existing ExtractionService and BUILD-084 schema."""
from dataclasses import asdict

from psycopg.types.json import Jsonb


class PostgresExtractionRepository:
    def __init__(self, cursor):
        self.cursor = cursor

    def _one(self, sql, params):
        self.cursor.execute(sql, params)
        return self.cursor.fetchone()

    def source_revision(self, revision_id):
        row = self._one("""SELECT r.revision_id,r.registry_id,r.sha256,r.content_bytes AS content,
            r.provenance,d.filename,d.mime_type FROM oc_import.document_revisions r
            JOIN oc_sources.document_inventory d ON d.inventory_id=r.registry_id
            WHERE r.revision_id=%s""", (revision_id,))
        if not row:
            raise LookupError("SOURCE_REVISION_NOT_FOUND")
        return row

    def ensure_record(self, source):
        self.cursor.execute("""INSERT INTO oc_document_intelligence.records
            (revision_id,registry_id,source_sha256,source_filename,source_mime_type,source_provenance)
            VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(revision_id) DO NOTHING""",
            (source['revision_id'], source['registry_id'], source['sha256'], source['filename'],
             source['mime_type'], Jsonb(source['provenance'])))
        return self._one("SELECT * FROM oc_document_intelligence.records WHERE revision_id=%s", (source['revision_id'],))

    def ensure_run(self, record_id, extractor, ruleset, config):
        self.cursor.execute("""INSERT INTO oc_document_intelligence.extraction_runs
            (record_id,extractor_version,ruleset_version,configuration_hash,state)
            VALUES (%s,%s,%s,%s,'PENDING') ON CONFLICT DO NOTHING""", (record_id, extractor, ruleset, config))
        return self._one("""SELECT * FROM oc_document_intelligence.extraction_runs
            WHERE record_id=%s AND extractor_version=%s AND ruleset_version=%s AND configuration_hash=%s""",
            (record_id, extractor, ruleset, config))

    def run(self, run_id):
        return self._one("SELECT * FROM oc_document_intelligence.extraction_runs WHERE extraction_run_id=%s", (run_id,))

    def source_revision_for_run(self, run_id):
        row = self._one("""SELECT r.revision_id FROM oc_document_intelligence.records r
            JOIN oc_document_intelligence.extraction_runs e USING(record_id) WHERE extraction_run_id=%s""", (run_id,))
        return self.source_revision(row['revision_id'])

    def transition(self, run_id, state):
        return self._one("""UPDATE oc_document_intelligence.extraction_runs SET state=%s,updated_at=NOW(),
            completed_at=CASE WHEN %s='COMPLETED' THEN NOW() ELSE completed_at END
            WHERE extraction_run_id=%s RETURNING *""", (state, state, run_id))

    def classify(self, record_id, value):
        self.cursor.execute("""INSERT INTO oc_document_intelligence.classifications
            (record_id,document_class,subclass,confidence,method,version,evidence) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (record_id, value.document_class.value, value.subclass, value.confidence, value.method,
             value.version, Jsonb(list(value.evidence))))

    def persist_intermediate(self, run_id, revision_id, adapter, version, document):
        for block in document.blocks:
            anchor = block.anchor
            row = self._one("""INSERT INTO oc_document_intelligence.structural_objects
                (extraction_run_id,section_type,hierarchy_level,sequence,char_start,char_end,complete_text,source_anchor)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(extraction_run_id,sequence)
                DO UPDATE SET sequence=EXCLUDED.sequence RETURNING structural_id""",
                (run_id, block.kind, block.heading_level, block.sequence, anchor.char_start, anchor.char_end,
                 block.text, Jsonb(asdict(anchor))))
            self.cursor.execute("""INSERT INTO oc_document_intelligence.source_anchors
                (revision_id,extraction_run_id,structural_id,char_start,char_end,ordered_span,extraction_method,ocr_derived,confidence)
                VALUES (%s,%s,%s,%s,%s,0,%s,%s,%s) ON CONFLICT(structural_id,ordered_span) DO NOTHING""",
                (revision_id, run_id, row['structural_id'], anchor.char_start, anchor.char_end,
                 f'{adapter}:{version}', anchor.ocr_derived, anchor.confidence))
        for warning in document.warnings:
            self.warning(run_id, 'ADAPTER_WARNING', warning)

    def create_chunks(self, run_id):
        self.cursor.execute("""INSERT INTO oc_document_intelligence.retrieval_chunks
            (extraction_run_id,structural_id,text,text_kind,source_anchor,complete_object_pointer)
            SELECT s.extraction_run_id,s.structural_id,s.complete_text,s.section_type,s.source_anchor,
                jsonb_build_object('structural_id',s.structural_id)
            FROM oc_document_intelligence.structural_objects s WHERE s.extraction_run_id=%s
            AND s.complete_text<>'' AND NOT EXISTS(SELECT 1 FROM oc_document_intelligence.retrieval_chunks c
                WHERE c.structural_id=s.structural_id)""", (run_id,))

    def warning(self, run_id, code, message):
        self.cursor.execute("""INSERT INTO oc_document_intelligence.extraction_warnings
            (extraction_run_id,code,message) VALUES (%s,%s,%s)""", (run_id, code, message))

    def has_structures(self, run_id):
        return bool(self._one("SELECT structural_id FROM oc_document_intelligence.structural_objects WHERE extraction_run_id=%s LIMIT 1", (run_id,)))

    def cancel_requested(self, run_id):
        return self.run(run_id)['cancellation_requested_at'] is not None

    def cancel(self, run_id):
        self.cursor.execute("UPDATE oc_document_intelligence.extraction_runs SET cancellation_requested_at=NOW() WHERE extraction_run_id=%s", (run_id,))
        return self.transition(run_id, 'CANCELLED')
