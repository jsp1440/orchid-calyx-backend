from __future__ import annotations

import hashlib
import json
from typing import Any

from app.candidate_knowledge.dependencies import get_candidate_components
from app.candidate_knowledge.models import CandidateKind
from runtime.knowledge_graph.causal_vocabulary import (
    CAUSAL_REASONING_NODE_TYPES,
    causal_relation_semantics,
)
from runtime.knowledge_graph.models import Edge, Node
from runtime.knowledge_graph.repository import InMemoryGraphRepository
from runtime.knowledge_graph.validation import validate_graph

from .mechanistic_contradictions import candidate_contradiction_ids


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _candidate(repository: Any, candidate_id: int) -> dict[str, Any]:
    candidate = next(
        (
            item
            for item in repository.candidates
            if item["candidate_id"] == candidate_id
        ),
        None,
    )
    if candidate is None:
        raise LookupError("MECHANISTIC_CANDIDATE_NOT_FOUND")
    return candidate


def _open_review_blockers(repository: Any, candidate_id: int) -> list[str]:
    return sorted(
        f"open_review:{review['category']}:{review['review_id']}"
        for review in repository.reviews.values()
        if review.get("candidate_id") == candidate_id and review.get("state") == "OPEN"
    )


def _open_conflict_blockers(repository: Any, candidate_id: int) -> list[str]:
    return sorted(
        f"open_conflict:{conflict_id}"
        for conflict_id, conflict in repository.conflicts.items()
        if conflict.get("state") == "OPEN"
        and candidate_id in conflict.get("candidate_ids", [])
    )


def _evidence_for_candidate(repository: Any, candidate_id: int) -> list[dict[str, Any]]:
    return [
        link
        for link in repository.evidence_links
        if link.get("candidate_id") == candidate_id
    ]


def _canonical_source_pk(node_type: str, canonical_key: str) -> str | None:
    prefix = f"{node_type}:"
    if not canonical_key.startswith(prefix):
        return None
    source_pk = canonical_key[len(prefix) :].strip()
    return source_pk or None


def _graph_from_candidate(
    candidate: dict[str, Any],
) -> tuple[list[Node], list[Edge], list[str]]:
    blockers: list[str] = []
    qualifiers = dict(candidate.get("qualifiers") or {})
    contract = dict(qualifiers.get("graph_contract") or {})
    source_type = str(contract.get("source_node_type") or "").strip().lower()
    target_type = str(contract.get("target_node_type") or "").strip().lower()
    source_key = str(contract.get("source_key") or "").strip()
    target_key = str(contract.get("target_key") or "").strip()
    relationship = (
        str(contract.get("relationship") or candidate.get("predicate") or "")
        .strip()
        .lower()
    )

    if source_type not in CAUSAL_REASONING_NODE_TYPES:
        blockers.append(f"invalid_source_type:{source_type or 'missing'}")
    if target_type not in CAUSAL_REASONING_NODE_TYPES:
        blockers.append(f"invalid_target_type:{target_type or 'missing'}")
    if not source_key:
        blockers.append("missing_source_key")
    if not target_key:
        blockers.append("missing_target_key")

    source_pk = _canonical_source_pk(source_type, source_key)
    target_pk = _canonical_source_pk(target_type, target_key)
    if source_key and source_pk is None:
        blockers.append("invalid_source_canonical_key")
    if target_key and target_pk is None:
        blockers.append("invalid_target_canonical_key")

    semantics = causal_relation_semantics(relationship)
    if semantics is None or not semantics["causal"]:
        blockers.append(f"invalid_causal_relationship:{relationship or 'missing'}")
    if blockers:
        return [], [], blockers

    assert source_pk is not None
    assert target_pk is not None
    confidence = float(candidate.get("confidence", 0.0))
    candidate_id = int(candidate["candidate_id"])
    preview_source = "synthetic.mechanistic_publication_plan"
    common_payload = {
        "candidate_id": candidate_id,
        "experimental_context": qualifiers.get("experimental_context", {}),
        "quantitative_context": qualifiers.get("quantitative_context", {}),
        "provenance": qualifiers.get("provenance", {}),
        "reviewed_candidate": True,
        "publication_plan_only": True,
    }
    source = Node(
        kg_node_id=1,
        node_type=source_type,
        canonical_key=source_key,
        display_label=str(candidate.get("normalized_subject") or source_key),
        source_table=preview_source,
        source_pk=source_pk,
        evidence_class="reviewed_mechanistic_candidate",
        confidence_score=confidence,
        confidence_label="reviewed_candidate",
        payload=common_payload,
    )
    target = Node(
        kg_node_id=2,
        node_type=target_type,
        canonical_key=target_key,
        display_label=str(candidate.get("object_value") or target_key),
        source_table=preview_source,
        source_pk=target_pk,
        evidence_class="reviewed_mechanistic_candidate",
        confidence_score=confidence,
        confidence_label="reviewed_candidate",
        payload=common_payload,
    )
    edge = Edge(
        kg_edge_id=1,
        edge_type=relationship,
        from_node_id=1,
        to_node_id=2,
        source_table="oc_candidate_knowledge.candidates",
        source_pk=str(candidate_id),
        evidence_class="reviewed_mechanistic_candidate",
        confidence_score=confidence,
        confidence_label="reviewed_candidate",
        rule_name="BUILD_616_MECHANISTIC_PUBLICATION_PLAN_V1",
        payload={
            **common_payload,
            "role": semantics["role"],
            "polarity": semantics["polarity"],
            "causal": semantics["causal"],
        },
    )
    return [source, target], [edge], []


def plan_mechanistic_candidate_publication(
    candidate_id: int,
    components: tuple[Any, Any] | None = None,
) -> dict[str, Any]:
    """Return a deterministic plan only; never authorize or execute publication."""
    repository, _service = components or get_candidate_components()
    candidate = _candidate(repository, candidate_id)
    blockers: list[str] = []

    if candidate.get("kind") != CandidateKind.MECHANISTIC_RELATIONSHIP.value:
        blockers.append("candidate_kind_not_mechanistic")
    if not candidate.get("active", True):
        blockers.append("candidate_inactive_or_superseded")
    if candidate.get("review_state") != "APPROVED":
        blockers.append("scientific_review_not_approved")
    if bool(candidate.get("published")):
        blockers.append("candidate_already_published")

    evidence = _evidence_for_candidate(repository, candidate_id)
    evidence_link_ids = sorted(
        int(link["evidence_link_id"])
        for link in evidence
        if link.get("evidence_link_id")
    )
    if not evidence_link_ids:
        blockers.append("exact_evidence_required")
    blockers.extend(_open_review_blockers(repository, candidate_id))
    blockers.extend(_open_conflict_blockers(repository, candidate_id))
    blockers.extend(
        f"mechanistic_contradiction:{contradiction_id}"
        for contradiction_id in candidate_contradiction_ids(repository, candidate_id)
    )

    nodes, edges, graph_blockers = _graph_from_candidate(candidate)
    blockers.extend(graph_blockers)
    validation: dict[str, Any] = {
        "healthy": False,
        "total_problems": 1,
        "skipped": True,
    }
    if nodes and edges:
        validation = validate_graph(InMemoryGraphRepository(nodes, edges))
        if not validation.get("healthy", False):
            blockers.append("projected_graph_validation_failed")

    blockers = sorted(set(blockers))
    operations: list[dict[str, Any]] = []
    if not graph_blockers:
        operations = [
            {
                "order": 0,
                "operation_type": "CREATE_NODE",
                "object_key": nodes[0].canonical_key,
                "payload": nodes[0].to_dict(),
            },
            {
                "order": 1,
                "operation_type": "CREATE_NODE",
                "object_key": nodes[1].canonical_key,
                "payload": nodes[1].to_dict(),
            },
            {
                "order": 2,
                "operation_type": "CREATE_EDGE",
                "object_key": f"mechanistic-candidate:{candidate_id}:{edges[0].edge_type}",
                "payload": edges[0].to_dict(),
            },
        ]

    plan_core = {
        "candidate_id": candidate_id,
        "candidate_hash": candidate.get("candidate_hash"),
        "evidence_link_ids": evidence_link_ids,
        "operations": operations,
        "blockers": blockers,
        "validation_healthy": bool(validation.get("healthy")),
    }
    ready = not blockers and bool(validation.get("healthy"))
    return {
        "contract": "calyx-mechanistic-publication-plan-v1",
        "candidate_id": candidate_id,
        "plan_id": _digest(plan_core),
        "ready_for_controlled_publication_gate": ready,
        "authorized": False,
        "commit_capability": False,
        "production_write_executed": False,
        "canonical_graph_mutated": False,
        "requires_explicit_publication_authorization": True,
        "evidence_count": len(evidence_link_ids),
        "evidence_link_ids": evidence_link_ids,
        "operations": operations,
        "validation": validation,
        "blockers": blockers,
        "operator_action": (
            "Translate this reviewed plan into the existing Reasoning Ledger publication contract and obtain explicit authorization."
            if ready
            else "Resolve all blockers, preserve evidence, and regenerate the plan."
        ),
    }
