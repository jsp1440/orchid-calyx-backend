from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


@dataclass(frozen=True)
class ProviderCandidate:
    key: str
    capabilities: frozenset[str]
    priority: int
    cost_rank: int
    healthy: bool = True
    enabled: bool = True
    managed: bool = True


def _text(source: dict[str, Any]) -> str:
    parts = [source.get("title") or "", source.get("content") or "", source.get("source_text") or ""]
    return " ".join(str(part) for part in parts).lower()


def build_recommendations(source: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate deterministic, explainable recommendations from an approved intake source."""
    text = _text(source)
    recommendations: list[dict[str, Any]] = []

    def add(kind: str, title: str, rationale: str, *, priority: str = "MEDIUM", confidence: float = 0.8,
            action_type: str = "TASK", destination: str = "intelligence-center", capability: str = "reasoning",
            estimated_cost_usd: float = 0.02) -> None:
        recommendations.append({
            "recommendation_type": kind,
            "title": title,
            "rationale": rationale,
            "priority": priority,
            "confidence": confidence,
            "expected_benefit": "Convert reviewed intelligence into a traceable next action.",
            "estimated_effort_minutes": 30,
            "estimated_ai_cost_usd": estimated_cost_usd,
            "proposed_action_type": action_type,
            "proposed_destination": destination,
            "required_capability": capability,
            "evidence": {"source_id": source.get("id"), "matched_rule": kind},
        })

    if any(token in text for token in ("new species", "sp. nov", "species nova", "new taxon")):
        add("NEW_TAXON_REVIEW", "Review newly described orchid taxon",
            "The intake appears to describe a new taxon and should be checked against the canonical taxonomy.",
            priority="HIGH", confidence=0.94, action_type="TAXONOMY_REVIEW", destination="taxonomy-review",
            capability="taxonomy", estimated_cost_usd=0.08)

    if any(token in text for token in ("doi", "journal", "paper", "publication", "study")):
        add("LITERATURE_EXTRACTION", "Extract scientific assertions and evidence",
            "The intake contains literature signals suitable for structured extraction and provenance capture.",
            action_type="LITERATURE_EXTRACTION", destination="literature-extraction", capability="long_document",
            estimated_cost_usd=0.12)

    if any(token in text for token in ("grant", "funding", "deadline", "proposal", "application closes")):
        add("GRANT_ACTION", "Create grant review and deadline workflow",
            "The intake appears to contain a funding opportunity or deadline requiring operational follow-through.",
            priority="HIGH", confidence=0.9, action_type="GRANT", destination="grants", capability="reasoning",
            estimated_cost_usd=0.03)

    if any(token in text for token in ("api", "database", "repository", "dataset", "connector", "integration")):
        add("CONNECTOR_EVALUATION", "Evaluate external service or dataset connector",
            "The intake names an external technical resource that may fill a data or workflow gap.",
            action_type="CONNECTOR_REVIEW", destination="connector-review", capability="coding",
            estimated_cost_usd=0.06)

    if any(token in text for token in ("image", "photograph", "media", "illustration", "figure")):
        add("MEDIA_REVIEW", "Review and connect media evidence",
            "The intake contains media signals that may support identification, education, or graph coverage.",
            action_type="MEDIA_SEARCH", destination="media-search", capability="vision", estimated_cost_usd=0.05)

    if any(token in text for token in ("pollinator", "pollination", "mycorrhiza", "fungus", "habitat", "climate")):
        add("ECOLOGICAL_LINKAGE", "Extract ecological relationships",
            "The intake contains ecological terms that may create evidence-backed graph relationships.",
            action_type="LITERATURE_EXTRACTION", destination="ecological-extraction", capability="scientific_extraction",
            estimated_cost_usd=0.1)

    if not recommendations:
        add("GENERAL_REVIEW", "Review intake and determine next action",
            "No specialized deterministic rule matched; the intake still requires an explicit review decision.",
            confidence=0.6, estimated_cost_usd=0.01)

    recommendations.sort(key=lambda item: ({"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}[item["priority"]], item["recommendation_type"]))
    return recommendations


def evaluate_budget(*, spent_usd: float, proposed_usd: float, soft_limit_usd: float | None,
                    hard_limit_usd: float | None, policy_mode: str = "WARN") -> dict[str, Any]:
    projected = round(spent_usd + proposed_usd, 8)
    if hard_limit_usd is not None and projected > hard_limit_usd:
        return {"decision": "BLOCK", "projected_spend_usd": projected, "reason": "hard limit exceeded"}
    if soft_limit_usd is not None and projected > soft_limit_usd:
        decision = "DOWNGRADE" if policy_mode == "DOWNGRADE" else "WARN"
        return {"decision": decision, "projected_spend_usd": projected, "reason": "soft limit exceeded"}
    return {"decision": "ALLOW", "projected_spend_usd": projected, "reason": "within budget"}


def choose_provider(*, capability: str, providers: Iterable[ProviderCandidate], preferred_provider: str | None = None,
                    budget_decision: str = "ALLOW") -> dict[str, Any]:
    candidates = [p for p in providers if p.enabled and p.healthy and capability in p.capabilities]
    if preferred_provider:
        preferred = [p for p in candidates if p.key == preferred_provider]
        if preferred:
            candidates = preferred + [p for p in candidates if p.key != preferred_provider]
    if budget_decision == "DOWNGRADE":
        candidates.sort(key=lambda p: (p.cost_rank, p.priority, p.key))
    else:
        candidates.sort(key=lambda p: (p.priority, p.cost_rank, p.key))
    if not candidates:
        return {"selected": None, "fallbacks": [], "reason": "no healthy provider supports capability"}
    return {
        "selected": candidates[0].key,
        "fallbacks": [p.key for p in candidates[1:]],
        "reason": "selected by capability, health, policy, priority, and cost",
        "routed_at": datetime.now(timezone.utc).isoformat(),
    }
