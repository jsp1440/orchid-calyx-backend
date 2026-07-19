from functools import lru_cache

from .drive import GoogleApiDriveGateway
from .repository import PostgresSourceRegistryRepository
from .service import SourceScanService


@lru_cache(maxsize=1)
def get_source_repository() -> PostgresSourceRegistryRepository:
    return PostgresSourceRegistryRepository()


def get_scan_service() -> SourceScanService:
    return SourceScanService(get_source_repository(), GoogleApiDriveGateway.from_environment())

