from functools import lru_cache

from .repositories import PostgresCandidateRepository, PostgresReviewRepository
from .services import ExtractionOrchestrationService, RuleBasedSemanticExtractor


@lru_cache(maxsize=1)
def get_candidate_repository() -> PostgresCandidateRepository:
    return PostgresCandidateRepository()


@lru_cache(maxsize=1)
def get_review_repository() -> PostgresReviewRepository:
    return PostgresReviewRepository()


def get_extraction_service() -> ExtractionOrchestrationService:
    return ExtractionOrchestrationService(get_candidate_repository(), RuleBasedSemanticExtractor())
