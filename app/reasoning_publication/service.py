from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.reasoning_ledger import gate as ledger_gate
from app.reasoning_ledger.models import (
    LedgerEntryKind,
    LedgerValidationError,
    ReviewOutcome,
)
from app.reasoning_ledger.operational_service import OperationalReasoningLedgerService

from .gateway import CanonicalPublicationGate, PublicationGateError
from .identity import publication_identity
from .models import PublicationArtifact, PublicationStatus
from .repository import PublicationArtifactRepository

PRIVATE_KEYS = {
    "chain_of_thought",
    "chain-of-thought",
    "private_cot",
    "hidden_reasoning",
}
SUPPORTED_OPERATIONS = {
    "CREATE_EDGE",
    "CREATE_NODE",
    "ADD_ASSERTION_SUPPORT",
    "ADD_CONFLICTING_EVIDENCE",
}


def _reject_private(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).casefold() in PRIVATE_KEYS:
                raise LedgerValidationError("PRIVATE_REASONING_PROHIBITED")
            _reject_private(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_private(nested)


class ReasoningLedgerPublicationService:
    def __init__(self, db, gate: CanonicalPublicationGate | None) -> None:
        self.db = db
        self.ledgers = OperationalReasoningLedgerService(db)
        self.artifacts = PublicationArtifactRepository(db)
        self.gate = gate

    def publish(
        self,
        ledger_id: str,
        *,
        owner: str,
        expected_version: int,
        expected_review_content_hash: str,
        note: str = "",
    ) -> tuple[dict[str, Any], bool]:
        ledger = self.ledgers.current(ledger_id, owner)
        if ledger.version != expected_version:
            raise LedgerValidationError("STALE_LEDGER_VERSION")
        if ledger.review_content_hash != expected_review_content_hash:
            raise LedgerValidationError("STALE_REVIEW_CONTENT_HASH")
        blockers = ledger_gate.evaluate(ledger)
        if blockers:
            raise LedgerValidationError(
                "PUBLICATION_BLOCKED:" + ",".join(item.code for item in blockers)
            )
        approvals = [
            d
            for d in ledger.review_decisions
            if d.outcome is ReviewOutcome.APPROVED
            and d.ledger_version == ledger.version
            and d.reviewed_content_hash == ledger.review_content_hash
        ]
        if len(approvals) != 1:
            raise LedgerValidationError("EXACT_APPROVAL_REQUIRED")
        approval = approvals[0]
        conclusions = [
            entry
            for entry in ledger.entries
            if entry.kind is LedgerEntryKind.CONCLUSION
        ]
        if len(conclusions) != 1:
            raise LedgerValidationError("EXACTLY_ONE_PUBLICATION_CONCLUSION_REQUIRED")
        conclusion = conclusions[0]
        attrs = dict(conclusion.attributes)
        _reject_private(attrs)
        if any(
            "outreach" in tag.casefold() or "marketing" in tag.casefold()
            for entry in ledger.entries
            for tag in entry.tags
        ):
            raise LedgerValidationError("OUTREACH_PUBLICATION_PROHIBITED")
        if any(
            entry.provenance
            and entry.provenance.source_kind.casefold()
            in {"outreach", "marketing", "outreach_graph"}
            for entry in ledger.entries
        ):
            raise LedgerValidationError("OUTREACH_PUBLICATION_PROHIBITED")
        operation = str(attrs.get("graph_operation_type", ""))
        if operation not in SUPPORTED_OPERATIONS:
            raise LedgerValidationError("UNSUPPORTED_GRAPH_OPERATION")
        subject = attrs.get("subject_canonical_node_id")
        object_id = attrs.get("object_canonical_node_id")
        literal = attrs.get("canonical_literal_value")
        if not isinstance(subject, int) or subject <= 0:
            raise LedgerValidationError("AMBIGUOUS_SUBJECT_IDENTITY")
        if (object_id is None) == (literal is None):
            raise LedgerValidationError("AMBIGUOUS_OBJECT_IDENTITY")
        if object_id is not None and (not isinstance(object_id, int) or object_id <= 0):
            raise LedgerValidationError("AMBIGUOUS_OBJECT_IDENTITY")
        subject_key = str(attrs.get("subject_canonical_key", "")).strip()
        object_key = str(attrs.get("object_canonical_key", "")).strip() or None
        if not subject_key or (object_id is not None and not object_key):
            raise LedgerValidationError("CANONICAL_GRAPH_KEY_REQUIRED")
        predicate = str(attrs.get("predicate", "")).strip()
        if not predicate:
            raise LedgerValidationError("MISSING_GRAPH_PREDICATE")
        for entry in ledger.entries:
            self.ledgers.literature.validate(entry.provenance)
        supporting = tuple(
            str(value) for value in attrs.get("supporting_evidence_references", ())
        )
        literature = tuple(
            str(value) for value in attrs.get("literature_evidence_ids", ())
        )
        source_hashes = tuple(
            str(value) for value in attrs.get("source_document_hashes", ())
        )
        if not supporting or not literature or not source_hashes:
            raise LedgerValidationError("PUBLICATION_EVIDENCE_INCOMPLETE")
        identity = {
            "ledger_id": ledger_id,
            "ledger_version": ledger.version,
            "review_content_hash": ledger.review_content_hash,
            "approval_id": str(approval.decision_id),
            "operation": operation,
            "subject": subject,
            "predicate": predicate,
            "object": object_id if object_id is not None else literal,
            "owner": owner,
            "project_id": ledger.project_id,
        }
        artifact_id, artifact_hash = publication_identity(identity)
        artifact = PublicationArtifact(
            publication_artifact_id=artifact_id,
            artifact_hash=artifact_hash,
            ledger_id=ledger_id,
            ledger_version=ledger.version,
            review_content_hash=ledger.review_content_hash,
            approval_id=str(approval.decision_id),
            approval_decision=approval.outcome.value,
            approval_timestamp=approval.decided_at,
            reviewer_identity=approval.reviewer,
            submitting_actor=owner,
            owner_identity=owner,
            project_id=ledger.project_id,
            subject_canonical_node_id=subject,
            subject_canonical_key=subject_key,
            object_canonical_node_id=object_id,
            object_canonical_key=object_key,
            canonical_literal_value=literal,
            predicate=predicate,
            graph_operation_type=operation,
            supporting_evidence_references=supporting,
            counterevidence_references=tuple(
                map(str, attrs.get("counterevidence_references", ()))
            ),
            literature_evidence_ids=literature,
            source_document_hashes=source_hashes,
            inference_family=str(attrs.get("inference_family", "")),
            inference_rule_id=str(attrs.get("inference_rule_id", "")),
            inference_rule_version=str(attrs.get("inference_rule_version", "")),
            confidence=conclusion.uncertainty.confidence
            if conclusion.uncertainty
            else 0.0,
            rationale=(note.strip() or approval.rationale)[:4000],
            provenance_chain=tuple(attrs.get("provenance_chain", ())),
            originating_candidate_ids=tuple(
                map(str, attrs.get("originating_candidate_ids", ()))
            ),
            originating_inference_hash=str(attrs.get("originating_inference_hash", "")),
            canonical_assertion_id=int(attrs.get("canonical_assertion_id", 0)),
            canonical_assertion_version=int(
                attrs.get("canonical_assertion_version", 0)
            ),
            policy_id=str(attrs.get("publication_policy_id", "")),
            policy_version=int(attrs.get("publication_policy_version", 0)),
            created_at=datetime.now(timezone.utc),
        )
        if (
            min(
                artifact.canonical_assertion_id,
                artifact.canonical_assertion_version,
                artifact.policy_version,
            )
            <= 0
            or not artifact.policy_id
        ):
            raise LedgerValidationError("CANONICAL_PUBLICATION_BINDING_REQUIRED")
        snapshot = artifact.to_dict()
        row = self.artifacts.save_prepared(snapshot)
        if row.status == PublicationStatus.PUBLISHED.value:
            return self._row(row), False
        if self.gate is None:
            raise LedgerValidationError("KNOWLEDGE_GRAPH_GATE_REQUIRED")
        try:
            result = self.gate.publish(snapshot)
        except PublicationGateError as exc:
            row.status = PublicationStatus.REJECTED.value
            row.failure_reason = str(exc)
            self.artifacts.record_attempt(row, "REJECTED", owner, {"reason": str(exc)})
            self.db.commit()
            return self._row(row), True
        row.status = PublicationStatus.PUBLISHED.value
        row.canonical_publication_id = result.get("publication_id")
        row.canonical_graph_result = result
        self.artifacts.record_attempt(row, "PUBLISHED", owner, result)
        self.db.commit()
        return self._row(row), True

    @staticmethod
    def _row(row) -> dict[str, Any]:
        graph = (row.canonical_graph_result or {}).get("graph", {})
        graph_ids = [
            f"graph_version:{graph['graph_version_id']}"
            for _ in (0,)
            if graph.get("graph_version_id") is not None
        ]
        return {
            **dict(row.snapshot),
            "publication_status": row.status,
            "canonical_publication_id": row.canonical_publication_id,
            "publication_gate_result": row.canonical_graph_result,
            "canonical_graph_ids": graph_ids,
            "failure_reason": row.failure_reason,
        }

    def get(self, artifact_id: str, owner: str) -> dict[str, Any] | None:
        row = self.artifacts.get(artifact_id, owner)
        return self._row(row) if row else None

    def history(self, ledger_id: str, owner: str) -> list[dict[str, Any]]:
        self.ledgers.current(ledger_id, owner)
        return [self._row(row) for row in self.artifacts.history(ledger_id, owner)]
