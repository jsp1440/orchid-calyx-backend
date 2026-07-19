from functools import lru_cache

from .repositories import PostgresPublicationRepository
from .services import PublicationService


@lru_cache(maxsize=1)
def get_publication_repository() -> PostgresPublicationRepository:
    return PostgresPublicationRepository()


def get_publication_service() -> PublicationService:
    return PublicationService(get_publication_repository())
