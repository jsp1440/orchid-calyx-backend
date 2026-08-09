from functools import lru_cache

from .dependencies import get_concept_service
from .glossary import GlossaryService
from .glossary_repositories import PostgresGlossaryRepository


@lru_cache
def get_glossary_service() -> GlossaryService:
    return GlossaryService(PostgresGlossaryRepository(), get_concept_service())
