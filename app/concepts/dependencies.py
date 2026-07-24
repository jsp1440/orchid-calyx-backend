from functools import lru_cache

from .repositories import PostgresConceptRepository
from .services import ConceptRegistryService


@lru_cache
def get_concept_service() -> ConceptRegistryService:
    return ConceptRegistryService(PostgresConceptRepository())
