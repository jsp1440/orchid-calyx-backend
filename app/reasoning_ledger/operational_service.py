from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.source_binding import (
    FileLiteratureSourceBindingRepository,
)
from app.research_workspace.models import Project

from . import gate as publication_gate
from .identity import deterministic_ledger_id
from .models import (
    LedgerEntry,
    LedgerProvenance,
    LedgerStatus,
    LedgerValidationError,
    ReasoningLedger,
    ReviewDecision,
)
from .persistence import SqlAlchemyReasoningLedgerRepository
from .service import _assign_sequence


class ProjectNotFoundError(LedgerValidationError):
    pass


class CanonicalProjectValidator:
    def __init__(self, db: Session) -> None:
        self.db = db

    def require_owned(self, project_id: str, owner: str) -> Project:
        project = self.db.scalar(
            select(Project).where(
                Project.project_id == project_id,
                Project.owner_subject == owner,
                Project.archived_at.is_(None),
            )
        )
        if project is None:
            raise ProjectNotFoundError("PROJECT_NOT_FOUND")
        return project


class CanonicalLiteratureValidator:
    """Validate references against Literature Intelligence without copying content."""

    def __init__(
        self,
        papers: LiteratureResultRepository | None = None,
        bindings: FileLiteratureSourceBindingRepository | None = None,
    ) -> None:
        root = Path(
            os.getenv("LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction")
        )
        self.papers = papers or LiteratureResultRepository(root)
        self.bindings = bindings or FileLiteratureSourceBindingRepository(root)

    def validate(self, provenance: LedgerProvenance | None) -> None:
        if provenance is None or provenance.source_kind.casefold() != "literature":
            return
        resolution_state = str(provenance.extra.get("resolution_state", "resolved"))
        if resolution_state == "unresolved":
            return
        if resolution_state != "resolved":
            raise LedgerValidationError("INVALID_LITERATURE_RESOLUTION_STATE")
        paper = self.papers.get(provenance.source_id)
        if paper is None:
            raise LedgerValidationError("LITERATURE_PAPER_NOT_FOUND")
        if (
            provenance.content_hash
            and provenance.content_hash != paper.source.content_hash
        ):
            raise LedgerValidationError("LITERATURE_CONTENT_HASH_MISMATCH")
        claim_id = provenance.extra.get("claim_id")
        evidence_id = (
            provenance.extra.get("evidence_id") or provenance.literature_record_id
        )
        if claim_id and claim_id not in {claim.claim_id for claim in paper.claims}:
            raise LedgerValidationError("LITERATURE_CLAIM_NOT_FOUND")
        if evidence_id and evidence_id not in {
            evidence.evidence_id for evidence in paper.evidence
        }:
            raise LedgerValidationError("LITERATURE_EVIDENCE_NOT_FOUND")
        extraction_run_id = provenance.extra.get("extraction_run_id")
        if extraction_run_id is not None:
            binding = self.bindings.get(paper.paper_id)
            if binding is None or binding.extraction_run_id != int(extraction_run_id):
                raise LedgerValidationError("LITERATURE_EXTRACTION_RUN_NOT_FOUND")


class OperationalReasoningLedgerService:
    def __init__(
        self,
        db: Session,
        *,
        project_validator: CanonicalProjectValidator | None = None,
        literature_validator: CanonicalLiteratureValidator | None = None,
    ) -> None:
        self.repository = SqlAlchemyReasoningLedgerRepository(db)
        self.projects = project_validator or CanonicalProjectValidator(db)
        self.literature = literature_validator or CanonicalLiteratureValidator()

    def create(
        self,
        *,
        owner: str,
        project_id: str,
        title: str,
        description: str,
    ) -> tuple[ReasoningLedger, bool]:
        self.projects.require_owned(project_id, owner)
        ledger = ReasoningLedger(
            ledger_id=deterministic_ledger_id(owner, project_id, title),
            tenant_id=owner,
            project_id=project_id,
            title=title,
            description=description,
            created_by=owner,
        )
        return self.repository.create(ledger, owner)

    def append(
        self,
        ledger_id: str,
        entry: LedgerEntry,
        *,
        owner: str,
        expected_version: int,
    ) -> ReasoningLedger:
        self.literature.validate(entry.provenance)

        def operation(current: ReasoningLedger) -> ReasoningLedger:
            self.projects.require_owned(current.project_id, owner)
            if current.status in {LedgerStatus.PUBLISHED, LedgerStatus.BLOCKED}:
                raise LedgerValidationError(
                    f"cannot append entries to a {current.status.value} ledger"
                )
            if entry.tenant_id != owner or entry.project_id != current.project_id:
                raise LedgerValidationError("ENTRY_SCOPE_MISMATCH")
            return current.append(_assign_sequence(entry, len(current.entries)))

        return self.repository.mutate(
            ledger_id,
            owner,
            expected_version,
            owner,
            "ENTRY_APPENDED",
            operation,
            {"entry_id": str(entry.entry_id), "kind": entry.kind.value},
        )

    def append_inference_candidate(
        self,
        ledger_id: str,
        entry: LedgerEntry,
        *,
        owner: str,
        expected_version: int,
        inference_content_hash: str,
    ) -> tuple[ReasoningLedger, bool]:
        """Append one governed inference candidate without approving it."""
        if entry.kind.value != "hypothesis":
            raise LedgerValidationError("INFERENCE_ENTRY_MUST_BE_HYPOTHESIS")
        if entry.attributes.get("inference_content_hash") != inference_content_hash:
            raise LedgerValidationError("INFERENCE_CONTENT_HASH_MISMATCH")

        def operation(current: ReasoningLedger) -> ReasoningLedger:
            self.projects.require_owned(current.project_id, owner)
            if current.status in {LedgerStatus.PUBLISHED, LedgerStatus.BLOCKED}:
                raise LedgerValidationError(
                    f"cannot append entries to a {current.status.value} ledger"
                )
            if entry.tenant_id != owner or entry.project_id != current.project_id:
                raise LedgerValidationError("ENTRY_SCOPE_MISMATCH")
            return current.append(_assign_sequence(entry, len(current.entries)))

        return self.repository.mutate_once(
            ledger_id,
            owner,
            expected_version,
            owner,
            "INFERENCE_CANDIDATE_APPENDED",
            operation,
            dedupe_attribute="inference_content_hash",
            dedupe_value=inference_content_hash,
            event_payload={
                "entry_id": str(entry.entry_id),
                "kind": entry.kind.value,
                "inference_content_hash": inference_content_hash,
                "rule_id": entry.attributes.get("rule_id"),
                "rule_version": entry.attributes.get("rule_version"),
                "automatically_approved": False,
                "automatically_published": False,
            },
        )

    def current(self, ledger_id: str, owner: str) -> ReasoningLedger:
        ledger = self.repository.current(ledger_id, owner)
        self.projects.require_owned(ledger.project_id, owner)
        return ledger

    def history(self, ledger_id: str, owner: str):
        self.current(ledger_id, owner)
        return {
            "revisions": self.repository.history(ledger_id, owner),
            "audit_events": self.repository.audit_history(ledger_id, owner),
        }

    def validate(self, ledger_id: str, owner: str) -> list[dict[str, str]]:
        ledger = self.current(ledger_id, owner)
        return [
            {"code": violation.code, "message": violation.message}
            for violation in publication_gate.evaluate(ledger)
        ]

    def review(
        self,
        ledger_id: str,
        decision: ReviewDecision,
        *,
        owner: str,
        expected_version: int,
    ) -> ReasoningLedger:
        return self.repository.mutate(
            ledger_id,
            owner,
            expected_version,
            owner,
            "REVIEW_RECORDED",
            lambda current: current.with_review(decision),
            {
                "decision_id": str(decision.decision_id),
                "outcome": decision.outcome.value,
            },
        )

    def resolve_conflict(
        self,
        ledger_id: str,
        conflict_id: UUID,
        *,
        owner: str,
        expected_version: int,
        resolution_state: str,
        rationale: str,
    ) -> ReasoningLedger:
        return self.repository.mutate(
            ledger_id,
            owner,
            expected_version,
            owner,
            "CONFLICT_RESOLVED",
            lambda current: current.resolve_conflict(conflict_id),
            {
                "conflict_id": str(conflict_id),
                "resolution_state": resolution_state,
                "rationale": rationale,
            },
        )

    def list_for_project(self, project_id: str, owner: str) -> list[ReasoningLedger]:
        self.projects.require_owned(project_id, owner)
        return self.repository.list_for_project(owner, project_id)
