from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.brain_mission.api import router as brain_mission_router
from app.calyx_agent.routes import router as calyx_agent_router
from app.calyx_engineering.routes import router as calyx_engineering_router
from app.calyx_journalism.routes import router as calyx_journalism_router
from app.calyx_orchestrator.routes import router as calyx_orchestrator_router
from app.canonical_brain.api import create_brain_router
from app.database import get_db
from app.reasoning_ledger.routes import _invoke
from app.reasoning_ledger.serialization import ledger_to_dict
from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key
from runtime.connector_registry import ConnectorRegistry, default_brain_registry
from runtime.knowledge_graph import PostgresGraphRepository

from .diagnostic_hypotheses import DiagnosticHypothesisRequest, rank_diagnostic_hypotheses
from .education_design_routes import router as education_design_router
from .ledger_bridge import InferenceLedgerBridge
from .plant_diagnostic_context import (
    PlantDiagnosticContextRequest,
    compose_plant_diagnostic_context,
)
from .reasoning import InferenceEngine, InferenceType
from .reasoning_map import ReasoningMapEngine
from .schemas import (
    ConnectRequest,
    GraphQuery,
    InferenceLedgerSubmission,
    InferRequest,
    ReasoningMapRequest,
)
from .scoped_reasoning_map import ScopedReasoningMapRequest, build_scoped_reasoning_map

router = APIRouter(
    prefix="/brain",
    tags=["orchid-continuum-brain"],
    dependencies=[
        Depends(verify_owner_or_api_key),
        Depends(add_mission_control_cors_headers),
    ],
)


def get_graph_repository():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HTTPException(503, detail={"code": "BRAIN_DATABASE_NOT_CONFIGURED"})
    return PostgresGraphRepository(database_url)


def get_connector_registry() -> ConnectorRegistry:
    return default_brain_registry()


GraphRepositoryDependency = Annotated[Any, Depends(get_graph_repository)]
AuthDependency = Annotated[dict, Depends(verify_owner_or_api_key)]
DbDependency = Annotated[Session, Depends(get_db)]


def _subject(auth: dict) -> str:
    subject = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not subject:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_SUBJECT_REQUIRED"})
    return subject


def _translate(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(404, detail={"code": str(exc)}) from exc
    if isinstance(exc, (ValueError, RuntimeError)):
        raise HTTPException(422, detail={"code": str(exc)}) from exc
    raise exc


@router.get("/node/{node_id}")
def node(node_id: int, repository: GraphRepositoryDependency) -> dict[str, Any]:
    found = repository.get_node(node_id)
    if found is None:
        raise HTTPException(404, detail={"code": "NODE_NOT_FOUND"})
    return found.to_dict()


@router.get("/relationships/{node_id}")
def relationships(
    node_id: int,
    repository: GraphRepositoryDependency,
    edge_type: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    if repository.get_node(node_id) is None:
        raise HTTPException(404, detail={"code": "NODE_NOT_FOUND"})
    edges = repository.get_outgoing_edges(
        [node_id], [edge_type] if edge_type else None, limit=limit
    )
    return {"node_id": node_id, "relationships": [edge.to_dict() for edge in edges]}


def _infer(repository, subject_node_id: int, inference_type: InferenceType, limit: int):
    try:
        return InferenceEngine(repository).infer(
            subject_node_id, inference_type, limit=limit
        )
    except Exception as exc:
        _translate(exc)
        raise


@router.get("/reason")
def reason(
    subject_node_id: Annotated[int, Query(gt=0)],
    inference_type: Annotated[InferenceType, Query()],
    repository: GraphRepositoryDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    return _infer(repository, subject_node_id, inference_type, limit)


@router.post("/infer")
def infer(
    request: InferRequest, repository: GraphRepositoryDependency
) -> dict[str, Any]:
    return _infer(
        repository, request.subject_node_id, request.inference_type, request.limit
    )


@router.post("/reasoning-map")
def reasoning_map(
    request: ReasoningMapRequest, repository: GraphRepositoryDependency
) -> dict[str, Any]:
    """Build a deterministic, evidence-bearing causal pathway over the Knowledge Graph."""
    try:
        return ReasoningMapEngine(repository).build(
            request.subject_node_id,
            direction=request.direction,
            profile=request.profile,
            max_depth=request.max_depth,
            limit=request.limit,
            edge_types=request.edge_types,
            causal_only=request.causal_only,
        )
    except Exception as exc:
        _translate(exc)
        raise


@router.post("/reasoning-map/scoped")
def scoped_reasoning_map(
    request: ScopedReasoningMapRequest,
    repository: GraphRepositoryDependency,
) -> dict[str, Any]:
    """Evaluate causal pathways against an explicit taxon/tissue/environment scope."""
    try:
        return build_scoped_reasoning_map(repository, request)
    except Exception as exc:
        _translate(exc)
        raise


@router.post("/diagnostic-context")
def plant_diagnostic_context(
    request: PlantDiagnosticContextRequest,
    repository: GraphRepositoryDependency,
) -> dict[str, Any]:
    """Compose scoped canonical reasoning with bounded local plant observations."""
    try:
        return compose_plant_diagnostic_context(repository, request)
    except Exception as exc:
        _translate(exc)
        raise


@router.post("/diagnostic-hypotheses")
def diagnostic_hypotheses(
    request: DiagnosticHypothesisRequest,
    repository: GraphRepositoryDependency,
) -> dict[str, Any]:
    """Rank possible explanations without creating or publishing scientific claims."""
    try:
        return rank_diagnostic_hypotheses(repository, request)
    except Exception as exc:
        _translate(exc)
        raise


@router.post(
    "/inferences/{subject_node_id}/submit-to-ledger",
    status_code=201,
)
def submit_inference_to_ledger(
    subject_node_id: int,
    payload: InferenceLedgerSubmission,
    request: Request,
    auth: AuthDependency,
    db: DbDependency,
    repository: GraphRepositoryDependency,
) -> dict[str, Any]:
    owner = _subject(auth)
    result = _invoke(
        db,
        request,
        lambda: InferenceLedgerBridge(db, repository).submit(
            ledger_id=str(payload.ledger_id),
            project_id=str(payload.project_id),
            owner=owner,
            expected_version=payload.expected_version,
            subject_node_id=subject_node_id,
            inference_type=payload.inference_type,
            candidate_node_id=payload.candidate_node_id,
            inference_content_hash=payload.inference_content_hash,
        ),
    )
    result["ledger"] = ledger_to_dict(result["ledger"])
    return result


@router.post("/query")
def query(request: GraphQuery, repository: GraphRepositoryDependency) -> dict[str, Any]:
    nodes = repository.all_nodes()
    if request.node_type:
        nodes = [node for node in nodes if node.node_type == request.node_type]
    if request.canonical_key:
        nodes = [node for node in nodes if node.canonical_key == request.canonical_key]
    node_ids = {node.kg_node_id for node in nodes}
    edges = repository.all_edges() if request.edge_type else []
    if request.edge_type:
        edges = [
            edge
            for edge in edges
            if edge.edge_type == request.edge_type and edge.from_node_id in node_ids
        ]
    return {
        "nodes": [
            node.to_dict()
            for node in sorted(nodes, key=lambda item: item.kg_node_id)[: request.limit]
        ],
        "edges": [
            edge.to_dict()
            for edge in sorted(edges, key=lambda item: item.kg_edge_id)[: request.limit]
        ],
        "limit": request.limit,
        "read_only": True,
    }


@router.post("/connect")
def connect(
    request: ConnectRequest,
    registry: Annotated[ConnectorRegistry, Depends(get_connector_registry)],
) -> dict[str, Any]:
    try:
        connector = registry.get(request.connector_id)
        if request.action == "health":
            return {"connector_id": connector.name, "health": connector.health()}
        return connector.execute(request.action, **request.payload)
    except Exception as exc:
        _translate(exc)
        raise


router.include_router(brain_mission_router)
router.include_router(create_brain_router(prefix="/canonical"))
router.include_router(calyx_agent_router)
router.include_router(calyx_journalism_router)
router.include_router(calyx_orchestrator_router)
router.include_router(calyx_engineering_router)
router.include_router(education_design_router)
