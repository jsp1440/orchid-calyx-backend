from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.reasoning_ledger.identity import deterministic_inference_entry_id
from app.reasoning_ledger.models import (
    LedgerEntry,
    LedgerEntryKind,
    LedgerProvenance,
    LedgerValidationError,
    UncertaintyMarker,
)
from app.reasoning_ledger.operational_service import OperationalReasoningLedgerService
from runtime.knowledge_graph import GraphRepository

from .reasoning import InferenceEngine, InferenceType


class InferenceLedgerBridge:
    """Submit graph inference output to canonical Reasoning Ledger governance."""

    def __init__(self, db: Session, graph: GraphRepository) -> None:
        self.ledger = OperationalReasoningLedgerService(db)
        self.graph = graph

    def submit(
        self,
        *,
        ledger_id: str,
        project_id: str,
        owner: str,
        expected_version: int,
        subject_node_id: int,
        inference_type: InferenceType,
        candidate_node_id: int,
        inference_content_hash: str,
    ) -> dict[str, Any]:
        current = self.ledger.current(ledger_id, owner)
        if current.project_id != project_id:
            raise LedgerValidationError("PROJECT_SCOPE_MISMATCH")
        inference = InferenceEngine(self.graph).infer(
            subject_node_id, inference_type, limit=100
        )
        matches = [
            item
            for item in inference["results"]
            if item["candidate_node_id"] == candidate_node_id
        ]
        if not matches:
            raise LedgerValidationError("MISSING_INFERENCE_EVIDENCE")
        if len(matches) != 1:
            raise LedgerValidationError("AMBIGUOUS_INFERENCE_CANDIDATE")
        artifact = matches[0]
        if artifact["inference_content_hash"] != inference_content_hash:
            raise LedgerValidationError("INFERENCE_CONTENT_HASH_MISMATCH")
        if not artifact["evidence_edge_ids"]:
            raise LedgerValidationError("MISSING_INFERENCE_EVIDENCE")

        subject = self._require_unambiguous_node(subject_node_id)
        candidate = self._require_unambiguous_node(candidate_node_id)
        created_at = datetime.now(timezone.utc)
        entry = LedgerEntry(
            entry_id=deterministic_inference_entry_id(
                UUID(ledger_id), inference_content_hash
            ),
            kind=LedgerEntryKind.HYPOTHESIS,
            text=(
                f"Candidate {inference_type.value}: {subject.canonical_key} "
                f"{artifact['proposed_relationship']['predicate']} "
                f"{candidate.canonical_key}."
            ),
            author=owner,
            tenant_id=owner,
            project_id=project_id,
            provenance=LedgerProvenance(
                source_kind="knowledge_graph_inference",
                source_id=inference_content_hash,
                rs_project_id=project_id,
                method_id=artifact["rule_id"],
                tool_id="build-ocb-010-inference-engine",
                content_hash=inference_content_hash,
                retrieved_at=created_at,
                collector=owner,
                extra={
                    "subject_node_ids": [subject_node_id],
                    "candidate_node_id": candidate_node_id,
                    "evidence_edge_ids": artifact["evidence_edge_ids"],
                    "literature_evidence_references": artifact[
                        "literature_evidence_references"
                    ],
                    "source_hashes": artifact["source_hashes"],
                    "originating_connector_ids": artifact["originating_connector_ids"],
                },
            ),
            uncertainty=UncertaintyMarker(
                confidence=artifact["confidence"],
                rationale=(
                    f"Deterministic {artifact['rule_id']}@"
                    f"{artifact['rule_version']} score over canonical graph edges."
                ),
            ),
            tags=("inference_candidate", inference_type.value),
            attributes={
                "artifact_type": "deterministic_inference_candidate",
                "canonical_status": "candidate_not_published",
                "inference_family": inference_type.value,
                "subject_node_ids": [subject_node_id],
                "proposed_relationship": artifact["proposed_relationship"],
                "confidence": artifact["confidence"],
                "rule_id": artifact["rule_id"],
                "rule_version": artifact["rule_version"],
                "rule_trace": artifact["rule_trace"],
                "evidence_edge_ids": artifact["evidence_edge_ids"],
                "literature_evidence_references": artifact[
                    "literature_evidence_references"
                ],
                "citations": artifact["citations"],
                "source_hashes": artifact["source_hashes"],
                "inference_content_hash": inference_content_hash,
                "originating_connector_ids": artifact["originating_connector_ids"],
                "created_at": created_at.isoformat(),
                "automatically_approved": False,
                "automatically_published": False,
            },
            created_at=created_at,
        )
        updated, created = self.ledger.append_inference_candidate(
            ledger_id,
            entry,
            owner=owner,
            expected_version=expected_version,
            inference_content_hash=inference_content_hash,
        )
        return {
            "created": created,
            "duplicate_reused": not created,
            "inference_content_hash": inference_content_hash,
            "entry_id": str(entry.entry_id),
            "ledger": updated,
            "automatically_approved": False,
            "automatically_published": False,
        }

    def _require_unambiguous_node(self, node_id: int):
        node = self.graph.get_node(node_id)
        if node is None:
            raise LedgerValidationError("CANONICAL_NODE_NOT_FOUND")
        identities = {
            item.kg_node_id
            for item in self.graph.all_nodes()
            if item.canonical_key == node.canonical_key
        }
        if identities != {node_id}:
            raise LedgerValidationError("AMBIGUOUS_CANONICAL_IDENTITY")
        return node
