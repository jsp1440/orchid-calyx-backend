"""Proposal-only bridge from a governed run manifest to candidate knowledge.

This module produces a deterministic, reviewable handoff request for the
existing candidate-knowledge pipeline. It deliberately does not persist a
candidate, publish science, or mutate the Knowledge Graph.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.parallel_platform.reasoning_contract_bridge import (
    DomainLiteral,
    verification_packet_to_handoff_request,
)

from .governance import check_manifest_governance

PROPOSAL_CONTRACT = "oc-candidate-knowledge-proposal-v1"


def _proposal_id(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return f"candidate-proposal:{hashlib.sha256(encoded).hexdigest()}"


def build_candidate_knowledge_proposal(
    *,
    manifest: dict[str, Any],
    verification_packet: dict[str, Any],
    domain: DomainLiteral,
    source_object_type: str,
    source_object_id: int,
    revision_id: int,
    extraction_run_id: int,
) -> dict[str, Any]:
    """Build a deterministic candidate proposal without executing the handoff."""

    decision = check_manifest_governance(manifest, "human_review_submission")
    if not decision.admitted:  # defensive: currently always admitted for valid manifests
        raise ValueError("HUMAN_REVIEW_SUBMISSION_NOT_ADMITTED")

    required_manifest_flags = {
        "human_review_required": True,
        "automatic_scientific_publication_allowed": False,
        "canonical_knowledge_mutation_allowed": False,
        "canonical_activation_requires_human_authority": True,
        "immutable": True,
    }
    if any(
        manifest.get(key) is not value
        for key, value in required_manifest_flags.items()
    ):
        raise ValueError("MANIFEST_GOVERNANCE_INVALID")
    if manifest.get("verification_state") != "ready_for_review":
        raise ValueError("MANIFEST_NOT_READY_FOR_REVIEW")

    candidate = (verification_packet.get("reasoning") or {}).get(
        "candidate_knowledge"
    ) or {}
    manifest_taxon = str(manifest.get("taxon_id") or "").strip()
    candidate_subject = str(candidate.get("subject_id") or "").strip()
    if not manifest_taxon or candidate_subject != manifest_taxon:
        raise ValueError("CANDIDATE_SUBJECT_MANIFEST_MISMATCH")

    handoff = verification_packet_to_handoff_request(
        verification_packet,
        domain=domain,
        source_object_type=source_object_type,
        source_object_id=source_object_id,
        revision_id=revision_id,
        extraction_run_id=extraction_run_id,
    )
    handoff_payload = handoff.model_dump(mode="json")
    identity = {
        "run_fingerprint": manifest["run_fingerprint"],
        "candidate_id": candidate["candidate_id"],
        "domain": domain,
        "source_object_type": source_object_type,
        "source_object_id": source_object_id,
        "revision_id": revision_id,
        "extraction_run_id": extraction_run_id,
    }

    return {
        "contract_version": PROPOSAL_CONTRACT,
        "proposal_id": _proposal_id(identity),
        "run_id": manifest.get("run_id"),
        "run_fingerprint": manifest["run_fingerprint"],
        "candidate_handoff_request": handoff_payload,
        "review_required": True,
        "owner_submission_required": True,
        "candidate_persistence_performed": False,
        "automatic_approval": False,
        "automatic_scientific_publication": False,
        "canonical_knowledge_mutation": False,
        "knowledge_graph_mutation": False,
    }
