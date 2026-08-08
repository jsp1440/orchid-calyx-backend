"""Retrieval-grounded conversational access to the Orchid Continuum.

CALYX-634 deliberately starts with extractive, provenance-preserving synthesis over
existing Evidence Retrieval results. It does not use general model knowledge, create
reviewed scientific interpretations, publish knowledge, or mutate the Knowledge Graph.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.evidence_retrieval.engine import RetrievalEngine
from app.evidence_retrieval.models import RetrievalQuery
from app.semantic_index.provider import DeterministicLocalProvider
from app.semantic_index.routes import REPO

CONVERSATION_SCHEMA_VERSION = "calyx-continuum-conversation/v1"


class RetrievalEngineProtocol(Protocol):
    def search(self, query: RetrievalQuery) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ConversationContext:
    active_project_id: str | None = None
    active_taxon_id: str | None = None
    active_document_id: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "ConversationContext":
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
    """Answer operator questions from governed Orchid Continuum evidence only."""

    def __init__(self, retrieval: RetrievalEngineProtocol | None = None) -> None:
        self.retrieval = retrieval or RetrievalEngine(REPO, DeterministicLocalProvider())

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
        answer, epistemic_status = self._compose_answer(text, evidence, usable)
        return {
            "schema_version": CONVERSATION_SCHEMA_VERSION,
            "question": text,
            "answer": answer,
            "epistemic_status": epistemic_status,
            "context": active_context.as_dict(),
            "evidence_count": len(evidence),
            "usable_excerpt_count": len(usable),
            "evidence": evidence,
            "tool_trace": [
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
            ],
            "model_knowledge_used": False,
            "scientific_interpretation_generated": False,
            "human_review_required_for_scientific_conclusion": True,
            "scientific_publication_authorized": False,
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
    ) -> tuple[str, str]:
        if not evidence:
            return (
                "I asked the Orchid Continuum, but it returned no eligible evidence for this "
                "question. I am not substituting general model knowledge for missing Continuum "
                "evidence. The next step is to broaden retrieval or add relevant sources.",
                "unknown",
            )
        if not usable:
            return (
                f"I found {len(evidence)} eligible Continuum record(s) for ‘{question}’, but their "
                "display policies do not authorize an excerpt that I can safely synthesize here. "
                "I can still show the source metadata and citations for review.",
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
