"""Provider-free JournalClub.io technical-intelligence intake.

This module converts owner-authorized Journal Club transcript text into bounded
technology-intelligence candidates.  It does not fetch subscription content,
call an LLM/provider, publish scientific knowledge, change taxonomy, deploy
production, or automatically apply implementation recommendations.

The transcript itself remains owned by the existing intake/source layer.  This
module emits derived candidate intelligence with exact text spans so the
existing intelligence ledger can preserve observations and route them through
verification/review.
"""

from __future__ import annotations

from hashlib import sha256
import re
from typing import Any

from .intelligence import (
    APPROVAL_REQUIRED_ACTIONS,
    AUTO_INTERNAL_ACTIONS,
    knowledge_fingerprint,
)

JOURNAL_CLUB_PARSER_VERSION = "journal-club-tech-intelligence-v1"


TECHNIQUES: tuple[dict[str, Any], ...] = (
    {
        "key": "GRAPH_RAG",
        "label": "Graph RAG",
        "terms": ("graph rag", "graph-rag", "graph retrieval augmented generation"),
        "targets": ("knowledge_graph", "calyx_retrieval", "research_station"),
        "recommendation": "Evaluate graph-constrained retrieval with provenance-preserving neighborhood evidence before generation.",
    },
    {
        "key": "HYBRID_RETRIEVAL",
        "label": "Hybrid retrieval",
        "terms": ("hybrid search", "hybrid retrieval", "dense and sparse", "bm25 and vector"),
        "targets": ("calyx_retrieval", "literature_intelligence", "research_station"),
        "recommendation": "Benchmark lexical-plus-vector retrieval against the current evidence retrieval path using fixed relevance fixtures.",
    },
    {
        "key": "QUERY_ADAPTIVE_RETRIEVAL",
        "label": "Query-adaptive retrieval",
        "terms": ("query-adaptive", "query adaptive", "adaptive retrieval"),
        "targets": ("calyx_retrieval", "calyx_model_router"),
        "recommendation": "Route retrieval strategy from observable query features and validate against a fixed evaluation set.",
    },
    {
        "key": "DYNAMIC_KNOWLEDGE_GRAPH",
        "label": "Dynamic knowledge-graph learning",
        "terms": ("dynamic knowledge graph", "temporal knowledge graph", "knowledge graph learning"),
        "targets": ("knowledge_graph", "reasoning_ledger", "engineering_memory"),
        "recommendation": "Evaluate append-only temporal relationship updates without bypassing review or provenance gates.",
    },
    {
        "key": "RERANKING",
        "label": "Retrieval reranking",
        "terms": ("reranker", "re-ranker", "reranking", "re-ranking"),
        "targets": ("calyx_retrieval", "literature_intelligence"),
        "recommendation": "Benchmark reranking only after first-stage recall is measured; preserve source/evidence identity through ranking.",
    },
    {
        "key": "EMBEDDINGS",
        "label": "Embedding retrieval",
        "terms": ("embedding model", "vector embedding", "dense retrieval", "vector search"),
        "targets": ("calyx_retrieval", "design_intelligence", "literature_intelligence"),
        "recommendation": "Evaluate embeddings on Orchid Continuum retrieval fixtures for recall, calibration, latency, and provenance retention.",
    },
    {
        "key": "MODEL_ROUTING",
        "label": "Model routing",
        "terms": ("model routing", "model router", "mixture of models", "route queries to models"),
        "targets": ("calyx_model_router", "autonomous_engine"),
        "recommendation": "Use task/capability evidence to choose the least-cost adequate model while retaining a provider-free deterministic lane.",
    },
    {
        "key": "CONTEXT_ENGINEERING",
        "label": "Context engineering",
        "terms": ("context engineering", "context window", "context compression", "prompt compression"),
        "targets": ("calyx_reasoning", "scientific_memory", "engineering_memory"),
        "recommendation": "Build context from provenance-ranked evidence and explicit task state rather than unbounded conversation history.",
    },
    {
        "key": "AGENT_ORCHESTRATION",
        "label": "Agent orchestration",
        "terms": ("agent orchestration", "multi-agent", "multi agent", "agentic workflow", "agent workflow"),
        "targets": ("autonomous_engine", "calyx_orchestrator", "engineering_memory"),
        "recommendation": "Map agent roles to explicit capabilities, bounded leases, replay receipts, and owner gates.",
    },
    {
        "key": "EVALUATION",
        "label": "LLM/ML evaluation",
        "terms": ("evaluation benchmark", "evals", "benchmark", "ablation", "calibration"),
        "targets": ("evaluation_engine", "calyx_reasoning", "research_station"),
        "recommendation": "Require fixed, versioned evaluation fixtures before adopting a technique as an Orchid Continuum improvement.",
    },
    {
        "key": "FINE_TUNING",
        "label": "Fine-tuning",
        "terms": ("fine-tuning", "fine tuning", "finetuning", "lora", "qlora"),
        "targets": ("model_lifecycle", "evaluation_engine"),
        "recommendation": "Consider task-specific fine-tuning only after a gold evaluation set exists and retrieval/prompt baselines are measured.",
    },
    {
        "key": "DISTILLATION",
        "label": "Model distillation",
        "terms": ("knowledge distillation", "model distillation", "distilled model"),
        "targets": ("model_lifecycle", "evaluation_engine", "autonomous_engine"),
        "recommendation": "Evaluate smaller distilled models for bounded classification/extraction tasks with explicit quality and cost gates.",
    },
    {
        "key": "MEMORY",
        "label": "Agent/LLM memory",
        "terms": ("long-term memory", "agent memory", "episodic memory", "semantic memory"),
        "targets": ("scientific_memory", "engineering_memory", "calyx_reasoning"),
        "recommendation": "Keep scientific evidence, engineering memory, and conversational context as separate governed stores with explicit provenance.",
    },
)


def _stable_hash(*parts: str) -> str:
    normalized = "\x1f".join(" ".join(part.split()).casefold() for part in parts)
    return sha256(normalized.encode("utf-8")).hexdigest()


def _term_spans(text: str, terms: tuple[str, ...]) -> list[dict[str, object]]:
    spans: list[dict[str, object]] = []
    lowered = text.casefold()
    for term in terms:
        pattern = re.compile(re.escape(term.casefold()))
        for match in pattern.finditer(lowered):
            start, end = match.span()
            spans.append(
                {
                    "term": term,
                    "start": start,
                    "end": end,
                    "exact_text": text[start:end],
                }
            )
    spans.sort(key=lambda value: (int(value["start"]), int(value["end"]), str(value["term"])))
    return spans


def canonical_journal_club_text(
    *,
    title: str,
    transcript: str,
    source_url: str | None = None,
    episode_id: str | None = None,
    doi: str | None = None,
) -> str:
    headers = [
        f"Title: {title.strip()}",
        "Source-System: JournalClub.io",
        "X-Orchid-Intake-Kind: journal-club-transcript",
    ]
    if episode_id:
        headers.append(f"Episode-ID: {episode_id.strip()}")
    if doi:
        headers.append(f"DOI: {doi.strip()}")
    if source_url:
        headers.append(f"Source-URL: {source_url.strip()}")
    return "\n".join(headers) + "\n\n" + transcript.strip() + "\n"


def parse_journal_club_transcript(
    *,
    title: str,
    transcript: str,
    source_url: str | None = None,
    episode_id: str | None = None,
    doi: str | None = None,
) -> list[dict[str, object]]:
    """Return review-bound implementation intelligence from transcript text.

    One candidate is emitted per supported technique with one or more exact
    matches.  Unsupported/irrelevant text emits no candidate rather than an
    inferred guess.
    """
    if not title.strip() or not transcript.strip():
        raise ValueError("JOURNAL_CLUB_TITLE_AND_TRANSCRIPT_REQUIRED")

    items: list[dict[str, object]] = []
    for technique in TECHNIQUES:
        spans = _term_spans(transcript, tuple(technique["terms"]))
        if not spans:
            continue

        item_title = f"{title.strip()} — {technique['label']}"
        urls = [source_url.strip()] if source_url and source_url.strip() else []
        dois = [doi.strip()] if doi and doi.strip() else []
        evidence_terms = sorted({str(span["exact_text"]) for span in spans}, key=str.casefold)
        identity = episode_id or doi or source_url or title
        observation_id = _stable_hash(
            "journalclub",
            str(identity),
            str(technique["key"]),
            sha256(transcript.encode("utf-8")).hexdigest(),
        )
        canonical_id = knowledge_fingerprint("technology", item_title, dois)

        scout = {
            "source_system": "JournalClub.io",
            "technique": technique["key"],
            "label": technique["label"],
            "oc_targets": list(technique["targets"]),
            "evidence_spans": spans,
            "recommendation": technique["recommendation"],
            "review_state": "CANDIDATE",
            "automatic_implementation_prohibited": True,
            "parser_version": JOURNAL_CLUB_PARSER_VERSION,
        }
        items.append(
            {
                "intelligence_id": observation_id,
                "knowledge_fingerprint": canonical_id,
                "lifecycle": "DISCOVERED",
                "knowledge_delta": "UNASSESSED",
                "domain": "technology",
                "title": item_title,
                "normalized_title": " ".join(item_title.split()).casefold(),
                "priority": "MEDIUM",
                "detail": (
                    f"Journal Club technique candidate: {technique['label']}. "
                    f"Matched exact transcript evidence: {', '.join(evidence_terms)}. "
                    f"Candidate OC targets: {', '.join(technique['targets'])}."
                ),
                "source_urls": urls,
                "dois": dois,
                "verification_required": True,
                "canonical_destinations": list(technique["targets"]),
                "follow_up_tasks": [
                    "VERIFY_PRIMARY_SOURCE",
                    "COMPARE_EXISTING_KNOWLEDGE",
                    "EVALUATE_OC_IMPLEMENTATION",
                ],
                "automatic_actions_allowed": list(AUTO_INTERNAL_ACTIONS),
                "approval_required_for": list(APPROVAL_REQUIRED_ACTIONS)
                + ["production_implementation", "model_provider_spending"],
                "external_contacted": False,
                "canonical_graph_mutated": False,
                "publication_performed": False,
                "technology_scout": scout,
                "parser_version": JOURNAL_CLUB_PARSER_VERSION,
            }
        )

    return items


def journal_club_summary(items: list[dict[str, object]]) -> dict[str, object]:
    techniques = sorted(
        {
            str(item.get("technology_scout", {}).get("technique"))
            for item in items
            if isinstance(item.get("technology_scout"), dict)
        }
    )
    targets = sorted(
        {
            str(target)
            for item in items
            for target in item.get("canonical_destinations", [])
        }
    )
    return {
        "parser_version": JOURNAL_CLUB_PARSER_VERSION,
        "items_discovered": len(items),
        "techniques": techniques,
        "oc_targets": targets,
        "provider_calls": 0,
        "provider_cost_usd": 0,
        "external_contacted": False,
        "canonical_graph_mutated": False,
        "publication_performed": False,
        "automatic_implementation_performed": False,
    }
