from functools import lru_cache

from .drive import GoogleDriveDocumentGateway
from .repository import PostgresDocumentImportRepository
from .service import DocumentImportService
from .bulk import BulkImportService
from .bulk_repository import PostgresBulkImportRepository
from app.source_registry.dependencies import get_scan_service, get_source_repository


@lru_cache(maxsize=1)
def get_import_repository() -> PostgresDocumentImportRepository:
    return PostgresDocumentImportRepository()


def get_import_service() -> DocumentImportService:
    return DocumentImportService(get_import_repository(), GoogleDriveDocumentGateway.from_environment())


def get_bulk_import_service() -> BulkImportService:
    importer = DocumentImportService(get_import_repository(), GoogleDriveDocumentGateway.from_environment(), folder_prefix="/")
    return BulkImportService(PostgresBulkImportRepository(), get_scan_service(), get_source_repository(), importer)
