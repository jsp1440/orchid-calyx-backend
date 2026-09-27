"""Compose acquisition with existing source, import, intelligence and binding stores."""
from urllib.parse import urlsplit

from psycopg.rows import dict_row, tuple_row

from app.document_import.models import ImportState, RetrievedDocument
from app.document_import.repository import PostgresDocumentImportRepository
from app.document_import.service import DocumentImportService
from app.document_intelligence.lifecycle import ExtractionService
from app.document_intelligence.postgres_repository import PostgresExtractionRepository
from app.source_registry.models import DriveFile
from app.source_registry.repository import PostgresSourceRegistryRepository

from .canonical_binding_resolver import (
    BindingScope,
    DocumentIntelligenceBindingResolver,
    PostgresLiteratureSourceBindingRepository,
)


class _AcquiredDocumentGateway:
    def __init__(self, source):
        self.source = source

    def retrieve(self, document):
        if document.drive_url != self.source.url:
            raise ValueError('ACQUIRED_SOURCE_IDENTITY_MISMATCH')
        return RetrievedDocument(self.source.markdown.encode('utf-8'), None, 'text/markdown', '.md')


class PostgresFirecrawlRegistration:
    def __init__(self, connect, *, scope: BindingScope, actor='oc-autonomy'):
        self.connect = connect
        self.scope = scope
        self.actor = actor

    def _dict_connect(self):
        connection = self.connect()
        connection.row_factory = dict_row
        return connection

    def __call__(self, source, paper):
        raw = source.markdown.encode('utf-8')
        if source.content_hash != paper.source.content_hash:
            raise ValueError('ACQUIRED_SOURCE_HASH_MISMATCH')
        registry = PostgresSourceRegistryRepository(self._dict_connect)
        registered = registry.register_web_source(urlsplit(source.url).hostname, self.actor)
        source_id = str(registered['source_id'])
        scan_id = registry.start_scan(source_id)
        try:
            status = registry.inventory_file(source_id, scan_id, DriveFile(
                file_id=source.url, filename=f'{source.content_hash}.md', folder_path='/Acquisition/',
                mime_type='text/markdown', size=len(raw), checksum=source.content_hash,
                created_at=None, modified_at=None, raw_metadata={
                    'provider': 'firecrawl', 'source_url': source.url, 'mocked': source.mocked,
                    'metadata_only': False, 'public_display_permission': False,
                }))
            registry_id = registry.inventory_id(source_id, source.url)
            registry.finish_scan(scan_id, source_id, 'COMPLETED', 1,
                                 int(status == 'UNCHANGED'), int(status == 'DUPLICATE'), 0)
        except Exception:
            registry.finish_scan(scan_id, source_id, 'FAILED', 0, 0, 0, 1, 'SOURCE_REGISTRATION_FAILED')
            raise
        importer = DocumentImportService(PostgresDocumentImportRepository(self._dict_connect),
                                         _AcquiredDocumentGateway(source), pilot_folder='/Acquisition/')
        result = importer.import_one(registry_id, self.actor)
        if result.state not in {ImportState.IMPORTED, ImportState.UNCHANGED, ImportState.DUPLICATE}:
            raise ValueError(f'SOURCE_IMPORT_FAILED:{result.error_code}')
        with self.connect() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                # Serialize identical content; the existing hash index is the canonical revision identity.
                cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (source.content_hash,))
                cursor.execute('SELECT canonical_revision_id FROM oc_import.hash_index WHERE sha256=%s',
                               (source.content_hash,))
                revision_id = cursor.fetchone()['canonical_revision_id']
                repository = PostgresExtractionRepository(cursor)
                run = ExtractionService(repository).start(revision_id, 'firecrawl-markdown-1', 'build-084-rules-1')
                if run['state'] != 'COMPLETED':
                    raise ValueError('SOURCE_DOCUMENT_EXTRACTION_FAILED')
                record_id = run['record_id']
                cursor.execute("""INSERT INTO oc_document_intelligence.purpose_assignments
                    (record_id,source_object_type,source_object_id,consumer,confidence,rationale,assignment_method,actor)
                    SELECT %s,'LITERATURE_DOCUMENT',%s,'literature',1,'Imported source identity; scientific review required','IMPORT',%s
                    WHERE NOT EXISTS(SELECT 1 FROM oc_document_intelligence.purpose_assignments WHERE record_id=%s)""",
                    (record_id, record_id, self.actor, record_id))
                # Unknown rights never become permission to display acquired text publicly.
                cursor.execute("""INSERT INTO oc_document_intelligence.display_policies
                    (record_id,display_state,public_display_permission,internal_use_permission)
                    VALUES (%s,'UNKNOWN_REQUIRES_REVIEW',FALSE,FALSE) ON CONFLICT DO NOTHING""", (record_id,))
            with connection.cursor(row_factory=tuple_row) as cursor:
                resolved, _ = PostgresLiteratureSourceBindingRepository().resolve_and_create(
                    cursor, resolver=DocumentIntelligenceBindingResolver(), scope=self.scope,
                    paper=paper, raw_bytes=raw)
                return resolved.binding
