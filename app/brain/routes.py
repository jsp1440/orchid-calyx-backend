from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key
from runtime.knowledge_graph import PostgresGraphRepository

from .connectors import ConnectorRegistry, default_registry
from .reasoning import InferenceEngine, InferenceType
from .schemas import ConnectRequest, GraphQuery, InferRequest

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
    return default_registry()


GraphRepositoryDependency = Annotated[Any, Depends(get_graph_repository)]


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
            return {"connector_id": connector.id, "health": connector.health()}
        return connector.execute(request.action, request.payload)
    except Exception as exc:
        _translate(exc)
        raise
