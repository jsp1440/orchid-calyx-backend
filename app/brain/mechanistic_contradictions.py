from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from app.candidate_knowledge.dependencies import get_candidate_components
from app.candidate_knowledge.models import CandidateKind
from runtime.knowledge_graph.causal_vocabulary import causal_relation_semantics


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _scope(candidate: dict[str, Any]) -> dict[str, Any]:
    qualifiers = dict(candidate.get("qualifiers") or {})
    graph_contract = dict(qualifiers.get("graph_contract") or {})
    return {
        "source_key": graph_contract.get("source_key"),
        "target_key": graph_contract.get("target_key"),
        "taxon_scope": qualifiers.get("taxon_scope"),
        "experimental_context": qualifiers.get("experimental_context", {}),
        "quantitative_context": qualifiers.get("quantitative_context", {}),
    }


def _scope_id(scope: dict[str, Any]) -> str:
    return hashlib.sha256(_stable_json(scope).encode("utf-8")).hexdigest()


def _evidence_count(repository: Any, candidate_id: int) -> int:
    return sum(
        1 for item in repository.evidence_links if item.get("candidate_id") == candidate_id
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
        relationship = str(
            contract.get("relationship") or candidate.get("predicate") or ""
        ).strip().lower()
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

        scope = _scope(candidate)
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
                "role": semantics["role"],
            }
        )

    contradictions: list[dict[str, Any]] = []
    for scope_hash, members in sorted(groups.items()):
        positive = [item for item in members if item["polarity"] > 0]
        negative = [item for item in members if item["polarity"] < 0]
        if not positive or not negative:
            continue

        candidate_ids = sorted(int(item["candidate"]["candidate_id"]) for item in members)
        contradiction_id = hashlib.sha256(
            f"mechanistic-contradiction:{scope_hash}:{','.join(map(str, candidate_ids))}".encode(
                "utf-8"
            )
        ).hexdigest()
        contradictions.append(
            {
                "contradiction_id": contradiction_id,
                "scope_id": scope_hash,
                "scope": members[0]["scope"],
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
        "contract": "calyx-mechanistic-contradictions-v1",
        "graph_mutation": False,
        "candidate_mutation": False,
        "contradiction_count": len(contradictions),
        "contradictions": contradictions,
        "skipped": skipped,
    }
