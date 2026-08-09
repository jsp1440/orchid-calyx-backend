from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from app.brain.causal_scope import causal_scope_identity, normalize_causal_scope
from app.candidate_knowledge.dependencies import get_candidate_components
from app.candidate_knowledge.models import CandidateKind
from runtime.knowledge_graph.causal_vocabulary import causal_relation_semantics


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _scope(candidate: dict[str, Any]) -> dict[str, Any]:
    qualifiers = dict(candidate.get("qualifiers") or {})
    graph_contract = dict(qualifiers.get("graph_contract") or {})
    declared_scope = qualifiers.get("causal_scope")
    normalized_scope = normalize_causal_scope(declared_scope)
    experimental_context = json.loads(
        json.dumps(
            qualifiers.get("experimental_context") or {}, sort_keys=True, default=str
        )
    )
    quantitative_context = json.loads(
        json.dumps(
            qualifiers.get("quantitative_context") or {}, sort_keys=True, default=str
        )
    )
    return {
        "source_key": graph_contract.get("source_key"),
        "target_key": graph_contract.get("target_key"),
        "causal_scope": normalized_scope,
        "applicability_identity": causal_scope_identity(normalized_scope),
        "experimental_context": experimental_context,
        "quantitative_context": quantitative_context,
    }


def _scope_identity(scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_key": scope.get("source_key"),
        "target_key": scope.get("target_key"),
        "causal_scope": scope.get("applicability_identity"),
    }


def _scope_id(scope: dict[str, Any]) -> str:
    return hashlib.sha256(
        _stable_json(_scope_identity(scope)).encode("utf-8")
    ).hexdigest()


def _evidence_count(repository: Any, candidate_id: int) -> int:
    return sum(
        1
        for item in repository.evidence_links
        if item.get("candidate_id") == candidate_id
    )


def candidate_contradiction_ids(repository: Any, candidate_id: int) -> list[str]:
    report = analyze_mechanistic_contradictions((repository, None))
    return sorted(
        cluster["contradiction_id"]
        for cluster in report["contradictions"]
        if candidate_id in cluster["candidate_ids"]
    )


def analyze_mechanistic_contradictions(
    components: tuple[Any, Any] | None = None,
) -> dict[str, Any]:
    """Account for opposite-polarity mechanistic claims in identical applicability."""
    repository, _service = components or get_candidate_components()
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped: list[dict[str, Any]] = []

    for candidate in repository.candidates:
        if not candidate.get("active", True):
            continue
        if candidate.get("kind") != CandidateKind.MECHANISTIC_RELATIONSHIP.value:
            continue

        qualifiers = dict(candidate.get("qualifiers") or {})
        contract = dict(qualifiers.get("graph_contract") or {})
        relationship = (
            str(contract.get("relationship") or candidate.get("predicate") or "")
            .strip()
            .lower()
        )
        semantics = causal_relation_semantics(relationship)
        if semantics is None or not semantics["causal"]:
            skipped.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "reason": "uncontrolled_or_noncausal_relationship",
                    "relationship": relationship,
                }
            )
            continue

        try:
            scope = _scope(candidate)
        except ValueError as exc:
            skipped.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "reason": "invalid_causal_scope",
                    "detail": str(exc),
                }
            )
            continue
        if not scope["source_key"] or not scope["target_key"]:
            skipped.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "reason": "incomplete_graph_scope",
                }
            )
            continue

        groups[_scope_id(scope)].append(
            {
                "candidate": candidate,
                "scope": scope,
                "relationship": relationship,
                "polarity": int(semantics["polarity"]),
            }
        )

    contradictions: list[dict[str, Any]] = []
    for scope_hash, members in sorted(groups.items()):
        positive = [item for item in members if item["polarity"] > 0]
        negative = [item for item in members if item["polarity"] < 0]
        if not positive or not negative:
            continue

        candidate_ids = sorted(
            int(item["candidate"]["candidate_id"]) for item in members
        )
        contradiction_id = hashlib.sha256(
            f"mechanistic-contradiction:{scope_hash}:{','.join(map(str, candidate_ids))}".encode()
        ).hexdigest()
        contradictions.append(
            {
                "contradiction_id": contradiction_id,
                "scope_id": scope_hash,
                "scope": {
                    "source_key": members[0]["scope"]["source_key"],
                    "target_key": members[0]["scope"]["target_key"],
                    "causal_scope": members[0]["scope"]["causal_scope"],
                },
                "candidate_ids": candidate_ids,
                "positive_candidate_ids": sorted(
                    int(item["candidate"]["candidate_id"]) for item in positive
                ),
                "negative_candidate_ids": sorted(
                    int(item["candidate"]["candidate_id"]) for item in negative
                ),
                "relationships": sorted({item["relationship"] for item in members}),
                "evidence_count": sum(
                    _evidence_count(repository, int(item["candidate"]["candidate_id"]))
                    for item in members
                ),
                "review_states": {
                    str(item["candidate"]["candidate_id"]): item["candidate"].get(
                        "review_state"
                    )
                    for item in members
                },
                "resolved": False,
                "publication_blocking": True,
            }
        )

    return {
        "contract": "calyx-mechanistic-contradictions-v2",
        "scope_contract": "calyx-causal-scope-v1",
        "graph_mutation": False,
        "candidate_mutation": False,
        "truth_decision": False,
        "contradiction_count": len(contradictions),
        "contradictions": contradictions,
        "skipped": skipped,
    }
