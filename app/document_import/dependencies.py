from functools import lru_cache

from .drive import GoogleDriveDocumentGateway
from .repository import PostgresDocumentImportRepository
from .service import DocumentImportService


@lru_cache(maxsize=1)
def get_import_repository() -> PostgresDocumentImportRepository:
    return PostgresDocumentImportRepository()


def get_import_service() -> DocumentImportService:
    return DocumentImportService(get_import_repository(), GoogleDriveDocumentGateway.from_environment())

