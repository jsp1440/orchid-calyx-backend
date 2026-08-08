from __future__ import annotations

import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.brain.reasoning_map import (
    ReasoningDirection,
    ReasoningMapEngine,
    ReasoningProfile,
)
from app.evidence_retrieval.models import RetrievalQuery
from app.security import verify_owner_or_api_key
from runtime.knowledge_graph import PostgresGraphRepository

from .routes import ENGINE

router = APIRouter(
    prefix="/calyx",
    tags=["calyx-reasoning"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


class CalyxReasoningMapRequest(BaseModel):
    subject_node_id: int = Field(gt=0)
    direction: ReasoningDirection = ReasoningDirection.FORWARD
    profile: ReasoningProfile = ReasoningProfile.BIOLOGICAL_MECHANISM
    max_depth: int = Field(default=4, ge=1, le=8)
    limit: int = Field(default=100, ge=1, le=500)
    edge_types: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    causal_only: bool = True


class CalyxReasoningQueryRequest(CalyxReasoningMapRequest):
    message: str = Field(min_length=1, max_length=5000)
    retrieval_mode: Literal["LEXICAL", "SEMANTIC", "HYBRID"] = "HYBRID"
    evidence_limit: int = Field(default=8, ge=1, le=25)
    internal_access: bool = True
    pathway_limit: int = Field(default=5, ge=1, le=20)


def _graph_repository() -> PostgresGraphRepository:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise ValueError("Knowledge Graph database is not configured")
    return PostgresGraphRepository(dsn)


def run_reasoning_map(request: CalyxReasoningMapRequest) -> dict[str, Any]:
    return ReasoningMapEngine(_graph_repository()).build(
        request.subject_node_id,
        direction=request.direction,
        profile=request.profile,
        max_depth=request.max_depth,
        limit=request.limit,
        edge_types=request.edge_types,
        causal_only=request.causal_only,
    )


def _retrieval(
    message: str,
    mode: str,
    limit: int,
    internal_access: bool,
) -> dict[str, Any]:
    query = RetrievalQuery(
        text=message[:500],
        mode=mode,
        limit=limit,
        per_source_limit=3,
        parent_expansion="AUTO",
        internal_access=internal_access,
    )
    return ENGINE.search(query)


def _reasoning_path_summary(path: dict[str, Any], index: int) -> str:
    confidence = float(path.get("confidence", 0.0))
    polarity = path.get("polarity_label") or "mixed_or_unspecified"
    explanation = path.get("explanation") or "unlabeled pathway"
    return f"{index}. {explanation} [confidence={confidence:.3f}; polarity={polarity}]"


def _evidence_summary(result: dict[str, Any], index: int) -> str:
    title = result.get("title") or result.get("object_type") or f"Evidence {index}"
    citation = result.get("citation") or {}
    source = citation.get("document_title") or citation.get("source_type") or "Orchid Continuum evidence"
    state = result.get("verification_state") or "unknown"
    return f"{index}. {title} — {source} [{state}]"


def compose_reasoning_answer(
    message: str,
    reasoning_map: dict[str, Any],
    retrieval: dict[str, Any],
    *,
    pathway_limit: int,
) -> str:
    paths = reasoning_map.get("paths", [])[:pathway_limit]
    evidence = retrieval.get("results", [])
    summary = reasoning_map.get("summary", {})
    lines = [
        "Calyx built a read-only causal reasoning map from Orchid Continuum graph state and searched indexed evidence before answering.",
        "",
        f"Reasoning map: {summary.get('node_count', 0)} nodes, {summary.get('edge_count', 0)} edges, {summary.get('path_count', 0)} pathways.",
    ]
    if paths:
        lines.append("")
        lines.append("Highest-priority inspectable pathways:")
        lines.extend(
            _reasoning_path_summary(path, index)
            for index, path in enumerate(paths, start=1)
        )
    else:
        lines.append("")
        lines.append(
            "No qualifying causal pathway was present in the current graph for this subject and profile."
        )

    lines.append("")
    if evidence:
        eligible = retrieval.get("total_eligible_results", len(evidence))
        lines.append(
            f"Indexed evidence: {eligible} eligible objects; showing {len(evidence)}."
        )
        lines.extend(
            _evidence_summary(result, index)
            for index, result in enumerate(evidence, start=1)
        )
    else:
        lines.append(
            "No eligible indexed evidence object was retrieved for the question. This is a coverage result, not proof that external literature is absent."
        )

    lines.extend(
        [
            "",
            "Interpretation boundary: a graph pathway is an explanatory hypothesis structure, not proof of causality. New scientific claims remain candidate knowledge until evidence and publication governance are satisfied.",
            "",
            "Question: " + message,
        ]
    )
    return "\n".join(lines)


@router.post("/reasoning-map")
def reasoning_map(payload: CalyxReasoningMapRequest) -> dict[str, Any]:
    """Return an inspectable read-only causal reasoning map for Calyx."""
    try:
        return run_reasoning_map(payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/reasoning-query")
def reasoning_query(payload: CalyxReasoningQueryRequest) -> dict[str, Any]:
    """Combine deterministic causal pathways with indexed evidence for a Calyx answer."""
    try:
        reasoning = run_reasoning_map(payload)
        retrieval = _retrieval(
            payload.message,
            payload.retrieval_mode,
            payload.evidence_limit,
            payload.internal_access,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "answer": compose_reasoning_answer(
            payload.message,
            reasoning,
            retrieval,
            pathway_limit=payload.pathway_limit,
        ),
        "reasoning_map": reasoning,
        "retrieval": retrieval,
        "question": payload.message,
        "epistemic_policy": {
            "continuum_first": True,
            "reasoning_map_read_only": True,
            "reasoning_path_is_not_proof_of_causality": True,
            "generative_claims_without_evidence": False,
            "automatic_scientific_publication": False,
            "knowledge_graph_mutation": False,
        },
    }
