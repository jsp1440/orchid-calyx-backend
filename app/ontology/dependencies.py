from functools import lru_cache

from .repositories import PostgresOntologyRepository
from .services import CandidateResolutionService, EvidenceRegistryService, OntologyRegistryService, OntologyTermService, PublicationReadinessService


@lru_cache(maxsize=1)
def get_ontology_repository() -> PostgresOntologyRepository:
    return PostgresOntologyRepository()


def get_registry_service() -> OntologyRegistryService:
    return OntologyRegistryService(get_ontology_repository())


def get_term_service() -> OntologyTermService:
    return OntologyTermService(get_ontology_repository())


def get_resolution_service() -> CandidateResolutionService:
    return CandidateResolutionService(get_ontology_repository())


def get_evidence_service() -> EvidenceRegistryService:
    return EvidenceRegistryService(get_ontology_repository())


def get_readiness_service() -> PublicationReadinessService:
    return PublicationReadinessService(get_ontology_repository())
