from typing import Any, Callable

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key

from .dependencies import get_evidence_service, get_readiness_service, get_registry_service, get_resolution_service, get_term_service
from .schemas import ActorReason, EvidenceAction, ManualResolution, ReadinessAction, RegistryCreate, RegistryPatch, ResolutionPatch, ResolveRequest, SynonymCreate, TermCreate, TermPatch
from .services import CandidateResolutionService, EvidenceRegistryService, OntologyRegistryService, OntologyTermService, PublicationReadinessService

router = APIRouter(prefix="/api/ontology", tags=["ontology-evidence-registry"], dependencies=[Depends(verify_owner_or_api_key), Depends(add_mission_control_cors_headers)])


def _invoke(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except LookupError as exc:
        raise HTTPException(404, detail={"code": str(exc)}) from exc
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(409, detail={"code": "ONTOLOGY_VERSION_OR_RECORD_CONFLICT"}) from exc
    except RuntimeError as exc:
        raise HTTPException(503, detail={"code": "ONTOLOGY_DATABASE_UNAVAILABLE"}) from exc
    except ValueError as exc:
        code = str(exc)
        status = 409 if any(token in code for token in ("LOCKED", "DUPLICATE", "TRANSITION", "MULTIPLE_ACCEPTED", "CONFLICT")) else 422
        raise HTTPException(status, detail={"code": code}) from exc


@router.get("/registries")
def registries(service: OntologyRegistryService = Depends(get_registry_service)) -> dict[str, Any]:
    return {"items": _invoke(service.list_registries)}


@router.post("/registries", status_code=201)
def create_registry(payload: RegistryCreate, service: OntologyRegistryService = Depends(get_registry_service)) -> dict[str, Any]:
    return _invoke(lambda: service.create_registry(payload.model_dump(mode="json")))


@router.get("/registries/{registry_id}")
def registry_detail(registry_id: int, service: OntologyRegistryService = Depends(get_registry_service)) -> dict[str, Any]:
    return _invoke(lambda: service.get_registry(registry_id))


@router.patch("/registries/{registry_id}")
def patch_registry(registry_id: int, payload: RegistryPatch, service: OntologyRegistryService = Depends(get_registry_service)) -> dict[str, Any]:
    return _invoke(lambda: service.update_draft_registry(registry_id, payload.model_dump(exclude={"actor", "reason"}, exclude_none=True, mode="json"), payload.actor, payload.reason))


@router.post("/registries/{registry_id}/activate")
def activate_registry(registry_id: int, payload: ActorReason, service: OntologyRegistryService = Depends(get_registry_service)) -> dict[str, Any]:
    return _invoke(lambda: service.activate_registry(registry_id, payload.actor, payload.reason))


@router.get("/terms/search")
def search_terms(q: str = Query(min_length=1), registry_id: int | None = Query(default=None, gt=0), service: OntologyTermService = Depends(get_term_service)) -> dict[str, Any]:
    return {"items": _invoke(lambda: service.search_terms(q, registry_id))}


@router.post("/terms", status_code=201)
def create_term(payload: TermCreate, service: OntologyTermService = Depends(get_term_service)) -> dict[str, Any]:
    return _invoke(lambda: service.create_term(payload.model_dump()))


@router.get("/terms/{term_id}")
def term_detail(term_id: int, service: OntologyTermService = Depends(get_term_service)) -> dict[str, Any]:
    return _invoke(lambda: service.get_term(term_id))


@router.patch("/terms/{term_id}")
def patch_term(term_id: int, payload: TermPatch, service: OntologyTermService = Depends(get_term_service)) -> dict[str, Any]:
    return _invoke(lambda: service.update_draft_term(term_id, payload.model_dump(exclude={"actor", "reason"}, exclude_none=True), payload.actor, payload.reason))


@router.post("/terms/{term_id}/synonyms", status_code=201)
def add_synonym(term_id: int, payload: SynonymCreate, service: OntologyTermService = Depends(get_term_service)) -> dict[str, Any]:
    return _invoke(lambda: service.add_synonym(term_id, payload.model_dump()))


@router.post("/resolve/candidate/{candidate_id}", status_code=201)
def resolve_candidate(candidate_id: int, payload: ResolveRequest, service: CandidateResolutionService = Depends(get_resolution_service)) -> dict[str, Any]:
    return {"items": _invoke(lambda: service.resolve_one(candidate_id, payload.actor, payload.fuzzy_threshold)), "canonical_graph_mutated": False}


@router.post("/resolve/session/{session_id}", status_code=201)
def resolve_session(session_id: int, payload: ResolveRequest, service: CandidateResolutionService = Depends(get_resolution_service)) -> dict[str, Any]:
    return _invoke(lambda: service.resolve_session(session_id, payload.actor, payload.fuzzy_threshold))


@router.post("/resolve/manual", status_code=201)
def manual_resolution(payload: ManualResolution, service: CandidateResolutionService = Depends(get_resolution_service)) -> dict[str, Any]:
    return _invoke(lambda: service.manual_assign(payload.candidate_id, payload.ontology_term_id, payload.actor, payload.reason))


@router.get("/resolutions/candidate/{candidate_id}")
def candidate_resolutions(candidate_id: int, service: CandidateResolutionService = Depends(get_resolution_service)) -> dict[str, Any]:
    return {"items": _invoke(lambda: service.list_proposed_matches(candidate_id))}


@router.patch("/resolutions/{resolution_id}")
def patch_resolution(resolution_id: int, payload: ResolutionPatch, service: CandidateResolutionService = Depends(get_resolution_service)) -> dict[str, Any]:
    return _invoke(lambda: service.decide(resolution_id, payload.status, payload.actor, payload.reason))


@router.post("/evidence/register/{evidence_object_id}", status_code=201)
def register_evidence(evidence_object_id: int, payload: EvidenceAction, service: EvidenceRegistryService = Depends(get_evidence_service)) -> dict[str, Any]:
    return _invoke(lambda: service.register(evidence_object_id, payload.actor))


@router.get("/evidence/{evidence_object_id}")
def evidence_detail(evidence_object_id: int, service: EvidenceRegistryService = Depends(get_evidence_service)) -> dict[str, Any]:
    return _invoke(lambda: service.get(evidence_object_id))


@router.post("/evidence/{evidence_object_id}/validate")
def validate_evidence(evidence_object_id: int, payload: EvidenceAction, service: EvidenceRegistryService = Depends(get_evidence_service)) -> dict[str, Any]:
    return _invoke(lambda: service.revalidate(evidence_object_id, payload.actor))


@router.post("/readiness/candidate/{candidate_id}")
def evaluate_candidate(candidate_id: int, payload: ReadinessAction, service: PublicationReadinessService = Depends(get_readiness_service)) -> dict[str, Any]:
    return _invoke(lambda: service.evaluate_candidate(candidate_id, payload.actor))


@router.post("/readiness/session/{session_id}")
def evaluate_session(session_id: int, payload: ReadinessAction, service: PublicationReadinessService = Depends(get_readiness_service)) -> dict[str, Any]:
    return _invoke(lambda: service.evaluate_session(session_id, payload.actor))


@router.get("/readiness/candidate/{candidate_id}")
def readiness_detail(candidate_id: int, service: PublicationReadinessService = Depends(get_readiness_service)) -> dict[str, Any]:
    return _invoke(lambda: service.get(candidate_id))
