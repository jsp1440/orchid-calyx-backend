"""Retrieval- and graph-grounded conversational access to the Orchid Continuum.

CALYX-634 established extractive, provenance-preserving synthesis over Evidence
Retrieval. CALYX-635 adds an explicit read-only Knowledge Graph tool when a taxon
context is supplied. Neither layer uses general model knowledge, publishes scientific
knowledge, or mutates the Knowledge Graph.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.evidence_retrieval.engine import RetrievalEngine
from app.evidence_retrieval.models import RetrievalQuery
from app.semantic_index.provider import DeterministicLocalProvider
from app.semantic_index.routes import REPO
from runtime.continuum_graph_tool import (
    KnowledgeGraphReadProtocol,
    ReadOnlyKnowledgeGraphTool,
)

CONVERSATION_SCHEMA_VERSION = "calyx-continuum-conversation/v2"


class RetrievalEngineProtocol(Protocol):
    def search(self, query: RetrievalQuery) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ConversationContext:
    active_project_id: str | None = None
    active_taxon_id: str | None = None
    active_document_id: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> ConversationContext:
        values = payload or {}
        return cls(
            active_project_id=_optional_text(values.get("active_project_id")),
            active_taxon_id=_optional_text(values.get("active_taxon_id")),
            active_document_id=_optional_text(values.get("active_document_id")),
        )

    def as_dict(self) -> dict[str, str | None]:
        return {
            "active_project_id": self.active_project_id,
            "active_taxon_id": self.active_taxon_id,
            "active_document_id": self.active_document_id,
        }


def _optional_text(value: Any) -> str | None:
    text = " ".join(str(value or "").strip().split())
    return text or None


def _question(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        raise ValueError("CONTINUUM_QUESTION_REQUIRED")
    if len(text) > 500:
        raise ValueError("CONTINUUM_QUESTION_TOO_LONG")
    return text


def _authorized_excerpt(result: dict[str, Any]) -> str | None:
    excerpt = result.get("authorized_excerpt")
    if not isinstance(excerpt, str):
        return None
    normalized = " ".join(excerpt.split())
    return normalized or None


class ContinuumConversationService:
    """Answer questions from governed Continuum evidence and read-only graph context."""

    def __init__(
        self,
        retrieval: RetrievalEngineProtocol | None = None,
        graph_tool: KnowledgeGraphReadProtocol | None = None,
    ) -> None:
        self.retrieval = retrieval or RetrievalEngine(REPO, DeterministicLocalProvider())
        self.graph_tool = graph_tool or ReadOnlyKnowledgeGraphTool()

    def ask(
        self,
        question: str,
        *,
        context: dict[str, Any] | None = None,
        limit: int = 6,
        internal_access: bool = True,
    ) -> dict[str, Any]:
        text = _question(question)
        if not 1 <= int(limit) <= 12:
            raise ValueError("CONTINUUM_RESULT_LIMIT_INVALID")
        active_context = ConversationContext.from_payload(context)
        query = RetrievalQuery(
            text=text,
            mode="HYBRID",
            limit=int(limit),
            per_source_limit=2,
            parent_expansion="AUTO",
            internal_access=bool(internal_access),
        )
        retrieval = self.retrieval.search(query)
        results = list(retrieval.get("results") or [])
        evidence = [self._evidence_record(item) for item in results]
        usable = [item for item in evidence if item["authorized_excerpt"]]

        graph_context = None
        if active_context.active_taxon_id:
            graph_context = self.graph_tool.lookup_taxon(
                active_context.active_taxon_id,
                depth=1,
                limit=50,
            )

        answer, epistemic_status = self._compose_answer(
            text,
            evidence,
            usable,
            graph_context,
        )
        tool_trace = [
            {
                "tool": "evidence_retrieval",
                "mode": retrieval.get("retrieval_mode", "HYBRID"),
                "ranking_configuration_version": retrieval.get(
                    "ranking_configuration_version"
                ),
                "total_candidates": retrieval.get("total_candidates", 0),
                "total_eligible_results": retrieval.get("total_eligible_results", 0),
                "elapsed_ms": retrieval.get("elapsed_ms"),
            }
        ]
        if graph_context is not None:
            tool_trace.append(
                {
                    "tool": "knowledge_graph_read",
                    "status": graph_context.get("status"),
                    "taxon_id": graph_context.get("taxon_id"),
                    "canonical_key": graph_context.get("canonical_key"),
                    "node_count": (graph_context.get("graph") or {}).get("node_count", 0),
                    "edge_count": (graph_context.get("graph") or {}).get("edge_count", 0),
                    "read_only": True,
                    "knowledge_graph_mutation_authorized": False,
                }
            )

        return {
            "schema_version": CONVERSATION_SCHEMA_VERSION,
            "question": text,
            "answer": answer,
            "epistemic_status": epistemic_status,
            "context": active_context.as_dict(),
            "evidence_count": len(evidence),
            "usable_excerpt_count": len(usable),
            "evidence": evidence,
            "graph_context": graph_context,
            "tool_trace": tool_trace,
            "model_knowledge_used": False,
            "scientific_interpretation_generated": False,
            "human_review_required_for_scientific_conclusion": True,
            "scientific_publication_authorized": False,
            "knowledge_graph_read_authorized": True,
            "knowledge_graph_mutation_authorized": False,
            "answering_policy": "ASK_THE_CONTINUUM_FIRST",
        }

    @staticmethod
    def _evidence_record(result: dict[str, Any]) -> dict[str, Any]:
        citation = dict(result.get("citation") or {})
        reliability = dict(result.get("reliability_signals") or {})
        return {
            "result_id": result.get("result_id"),
            "rank": result.get("rank"),
            "fused_score": result.get("fused_score"),
            "object_type": result.get("object_type"),
            "title": result.get("title"),
            "authorized_excerpt": _authorized_excerpt(result),
            "citation": citation,
            "reliability_signals": reliability,
            "review_state": result.get("review_state"),
            "verification_state": result.get("verification_state"),
            "temporal_status": result.get("temporal_status"),
            "display_policy": result.get("display_policy"),
            "collections": list(result.get("collections") or []),
        }

    @staticmethod
    def _compose_answer(
        question: str,
        evidence: list[dict[str, Any]],
        usable: list[dict[str, Any]],
        graph_context: dict[str, Any] | None,
    ) -> tuple[str, str]:
        evidence_text, evidence_status = ContinuumConversationService._evidence_answer(
            question,
            evidence,
            usable,
        )
        if not graph_context or graph_context.get("status") != "found":
            return evidence_text, evidence_status

        graph = dict(graph_context.get("graph") or {})
        focal = dict(graph_context.get("focal_node") or {})
        label = _optional_text(focal.get("label")) or str(graph_context.get("taxon_id"))
        edge_types = [str(value) for value in graph_context.get("edge_types") or []]
        domains = sorted(str(value) for value in (graph_context.get("domain_coverage") or {}))
        gaps = [str(value) for value in graph_context.get("data_gaps") or []]
        graph_text = (
            f" Read-only Knowledge Graph context for {label} contains "
            f"{int(graph.get('node_count', 0))} connected node(s) and "
            f"{int(graph.get('edge_count', 0))} edge(s)."
        )
        if edge_types:
            graph_text += f" Recorded relationship types: {', '.join(edge_types[:12])}."
        if domains:
            graph_text += f" Graph domains represented: {', '.join(domains)}."
        if gaps:
            graph_text += f" Explicit graph data gaps include: {', '.join(gaps[:8])}."
        graph_text += (
            " These are stored graph relationships and coverage signals, not a new causal or "
            "scientific interpretation."
        )

        if evidence_status == "continuum_evidence":
            status = "continuum_evidence_and_graph"
        elif evidence_status == "continuum_evidence_metadata_only":
            status = "continuum_graph_and_evidence_metadata"
        else:
            status = "continuum_graph"
        return evidence_text + graph_text, status

    @staticmethod
    def _evidence_answer(
        question: str,
        evidence: list[dict[str, Any]],
        usable: list[dict[str, Any]],
    ) -> tuple[str, str]:
        if not evidence:
            return (
                (
                    "I asked the Orchid Continuum, but it returned no eligible evidence for this "
                    "question. I am not substituting general model knowledge for missing Continuum "
                    "evidence. The next step is to broaden retrieval or add relevant sources."
                ),
                "unknown",
            )
        if not usable:
            return (
                (
                    f"I found {len(evidence)} eligible Continuum record(s) for '{question}', but their "
                    "display policies do not authorize an excerpt that I can safely synthesize here. "
                    "I can still show the source metadata and citations for review."
                ),
                "continuum_evidence_metadata_only",
            )
        statements: list[str] = []
        for item in usable[:3]:
            title = _optional_text(item.get("title")) or "Untitled Continuum record"
            excerpt = str(item["authorized_excerpt"])
            if len(excerpt) > 420:
                excerpt = excerpt[:417].rstrip() + "…"
            statements.append(f"{title}: {excerpt}")
        joined = " ".join(statements)
        answer = (
            f"I asked the Orchid Continuum and found {len(evidence)} eligible evidence record(s). "
            f"The strongest retrievable evidence says: {joined} "
            "This is a retrieval-grounded evidence summary, not a reviewed scientific conclusion; "
            "the cited records and provenance remain the authority."
        )
        return answer, "continuum_evidence"
