from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calyx_flywheel.locality import (
    SensitiveLocalityError,
    assert_no_sensitive_locality,
)
from app.research_workspace.models import Project, SavedSearch

from .models import (
    ScientificMemoryCapture,
    ScientificMemoryDecision,
    ScientificMemoryItem,
)
from .schemas import CaptureCreate, DecisionCreate, MemoryItemCreate

CONTRACT_VERSION = "SCIENTIFIC-MEMORY-MVP-001"


@dataclass
class ScientificMemoryError(Exception):
    code: str
    status: int


class ScientificMemoryService:
    """Persist reviewed scientific context without creating a canonical truth store."""

    @staticmethod
    def _uuid(value: str, code: str) -> str:
        try:
            return str(UUID(str(value)))
        except ValueError as exc:
            raise ScientificMemoryError(code, 404) from exc

    def _project(self, db: Session, project_id: str, owner: str) -> Project:
        identifier = self._uuid(project_id, "PROJECT_NOT_FOUND")
        project = db.scalar(
            select(Project).where(
                Project.project_id == identifier,
                Project.owner_subject == owner,
                Project.archived_at.is_(None),
            )
        )
        if project is None:
            raise ScientificMemoryError("PROJECT_NOT_FOUND", 404)
        return project

    @staticmethod
    def _fingerprint(payload: CaptureCreate) -> str:
        normalized = payload.model_dump(mode="json")
        encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _item_dict(item: ScientificMemoryItem, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "memory_item_id": item.memory_item_id,
            "capture_id": item.capture_id,
            "item_type": item.item_type,
            "authority": item.authority,
            "statement": item.statement,
            "confidence": item.confidence,
            "source": {
                "document_id": item.document_id,
                "revision_id": item.revision_id,
                "identifier": item.source_identifier,
                "locator": item.source_locator,
                "authorized_excerpt": item.authorized_excerpt,
                "rights_basis": item.rights_basis,
            },
            "structured_payload": item.structured_payload,
            "correction_of_item_id": item.correction_of_item_id,
            "review_state": state["review_state"],
            "active": state["active"],
            "decision_history": state["history"],
            "canonical_scientific_knowledge": False,
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
            "created_at": item.created_at,
        }

    def create_capture(
        self, db: Session, project_id: str, owner: str, payload: CaptureCreate
    ) -> dict[str, Any]:
        project = self._project(db, project_id, owner)
        try:
            assert_no_sensitive_locality(payload.filters, path="capture.filters")
            for index, body in enumerate(payload.items):
                assert_no_sensitive_locality(
                    body.source.locator, path=f"capture.items[{index}].source.locator"
                )
                assert_no_sensitive_locality(
                    body.structured_payload,
                    path=f"capture.items[{index}].structured_payload",
                )
        except SensitiveLocalityError as exc:
            raise ScientificMemoryError("SENSITIVE_LOCALITY_FORBIDDEN", 422) from exc
        fingerprint = self._fingerprint(payload)
        existing = db.scalar(
            select(ScientificMemoryCapture).where(
                ScientificMemoryCapture.project_id == project.project_id,
                ScientificMemoryCapture.fingerprint == fingerprint,
            )
        )
        if existing is not None:
            result = self.capture(db, project_id, owner, existing.capture_id)
            result["idempotent_replay"] = True
            return result

        search_name = payload.name
        duplicate_name = db.scalar(
            select(SavedSearch).where(
                SavedSearch.project_id == project.project_id,
                func.lower(SavedSearch.name) == search_name.lower(),
                SavedSearch.archived_at.is_(None),
            )
        )
        if duplicate_name is not None:
            search_name = f"{search_name[:151]} [{fingerprint[:6]}]"
        saved_search = SavedSearch(
            project_id=project.project_id,
            owner_subject=owner,
            name=search_name,
            query_json={
                "contract_version": CONTRACT_VERSION,
                "origin": payload.origin,
                "query": payload.query,
                "filters": payload.filters,
            },
            result_count_snapshot=payload.result_count_snapshot,
        )
        db.add(saved_search)
        db.flush()
        capture = ScientificMemoryCapture(
            project_id=project.project_id,
            saved_search_id=saved_search.saved_search_id,
            owner_subject=owner,
            origin=payload.origin,
            conversation_id=payload.conversation_id,
            query_text=payload.query,
            fingerprint=fingerprint,
        )
        db.add(capture)
        db.flush()
        for body in payload.items:
            self._add_item(db, capture, body)
        db.flush()
        result = self.capture(db, project_id, owner, capture.capture_id)
        result["idempotent_replay"] = False
        return result

    def _add_item(
        self,
        db: Session,
        capture: ScientificMemoryCapture,
        body: MemoryItemCreate,
    ) -> ScientificMemoryItem:
        if body.correction_of_item_id:
            replaced = self._item(db, capture.project_id, body.correction_of_item_id)
            if replaced.project_id != capture.project_id:
                raise ScientificMemoryError("CROSS_PROJECT_CORRECTION_FORBIDDEN", 403)
        source = body.source
        item = ScientificMemoryItem(
            capture_id=capture.capture_id,
            project_id=capture.project_id,
            item_type=body.item_type,
            authority=body.authority,
            statement=body.statement,
            confidence=body.confidence,
            document_id=source.document_id,
            revision_id=source.revision_id,
            source_identifier=source.identifier,
            source_locator=source.locator,
            authorized_excerpt=source.authorized_excerpt,
            rights_basis=source.rights_basis,
            structured_payload=body.structured_payload,
            correction_of_item_id=body.correction_of_item_id,
        )
        db.add(item)
        return item

    def _item(self, db: Session, project_id: str, item_id: str) -> ScientificMemoryItem:
        identifier = self._uuid(item_id, "MEMORY_ITEM_NOT_FOUND")
        item = db.scalar(
            select(ScientificMemoryItem).where(
                ScientificMemoryItem.memory_item_id == identifier,
                ScientificMemoryItem.project_id == project_id,
            )
        )
        if item is None:
            raise ScientificMemoryError("MEMORY_ITEM_NOT_FOUND", 404)
        return item

    def capture(
        self, db: Session, project_id: str, owner: str, capture_id: str
    ) -> dict[str, Any]:
        project = self._project(db, project_id, owner)
        identifier = self._uuid(capture_id, "SCIENTIFIC_MEMORY_CAPTURE_NOT_FOUND")
        capture = db.scalar(
            select(ScientificMemoryCapture).where(
                ScientificMemoryCapture.capture_id == identifier,
                ScientificMemoryCapture.project_id == project.project_id,
            )
        )
        if capture is None:
            raise ScientificMemoryError("SCIENTIFIC_MEMORY_CAPTURE_NOT_FOUND", 404)
        packet = self.recall(db, project_id, owner, capture_id=identifier)
        return {
            "contract_version": CONTRACT_VERSION,
            "capture_id": capture.capture_id,
            "project_id": capture.project_id,
            "saved_search_id": capture.saved_search_id,
            "origin": capture.origin,
            "conversation_id": capture.conversation_id,
            "query": capture.query_text,
            "fingerprint": capture.fingerprint,
            "items": packet["items"],
            "governance": packet["governance"],
            "created_at": capture.created_at,
        }

    @staticmethod
    def _states(
        decisions: list[ScientificMemoryDecision],
    ) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for decision in decisions:
            state = states.setdefault(
                decision.memory_item_id,
                {"review_state": "UNREVIEWED", "active": True, "history": []},
            )
            event = {
                "decision_id": decision.decision_id,
                "action": decision.action,
                "reason": decision.reason,
                "replacement_item_id": decision.replacement_item_id,
                "actor_subject": decision.actor_subject,
                "created_at": decision.created_at,
            }
            state["history"].append(event)
            if decision.action == "ACCEPT_REVIEW":
                state["review_state"] = "ACCEPTED_FOR_RESEARCH_USE"
            elif decision.action == "REJECT":
                state.update(review_state="REJECTED", active=False)
            elif decision.action == "INVALIDATE":
                state.update(review_state="INVALIDATED", active=False)
            elif decision.action == "CORRECT":
                state.update(review_state="CORRECTED", active=False)
        return states

    def recall(
        self,
        db: Session,
        project_id: str,
        owner: str,
        *,
        query: str | None = None,
        capture_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        project = self._project(db, project_id, owner)
        statement = select(ScientificMemoryItem).where(
            ScientificMemoryItem.project_id == project.project_id
        )
        if capture_id:
            statement = statement.where(ScientificMemoryItem.capture_id == capture_id)
        if query:
            statement = statement.where(
                ScientificMemoryItem.statement.ilike(f"%{query.strip()}%")
            )
        items = db.scalars(
            statement.order_by(
                ScientificMemoryItem.created_at, ScientificMemoryItem.memory_item_id
            ).limit(limit)
        ).all()
        item_ids = [item.memory_item_id for item in items]
        decisions = (
            db.scalars(
                select(ScientificMemoryDecision)
                .where(ScientificMemoryDecision.memory_item_id.in_(item_ids))
                .order_by(
                    ScientificMemoryDecision.created_at,
                    ScientificMemoryDecision.decision_id,
                )
            ).all()
            if item_ids
            else []
        )
        states = self._states(list(decisions))
        rendered = []
        for item in items:
            state = states.get(
                item.memory_item_id,
                {"review_state": "UNREVIEWED", "active": True, "history": []},
            )
            rendered.append(self._item_dict(item, state))
        active = [item for item in rendered if item["active"]]
        return {
            "contract_version": CONTRACT_VERSION,
            "project_id": project.project_id,
            "items": rendered,
            "calyx_context": {
                "source_evidence": [
                    item for item in active if item["authority"] == "SOURCE_EVIDENCE"
                ],
                "candidate_knowledge": [
                    item
                    for item in active
                    if item["authority"] == "CANDIDATE_KNOWLEDGE"
                ],
                "prior_calyx_inference": [
                    item for item in active if item["authority"] == "CALYX_INFERENCE"
                ],
                "research_context": [
                    item for item in active if item["authority"] == "RESEARCH_CONTEXT"
                ],
            },
            "consumer_contract": {
                "oasis_can_capture": True,
                "calyx_can_recall": True,
                "research_station_owns_project_scope": True,
            },
            "governance": {
                "engineering_memory_separate": True,
                "conversation_or_model_memory_is_not_evidence": True,
                "accepted_review_does_not_make_canonical": True,
                "canonical_scientific_promotion_requires_separate_review": True,
                "automatic_publication": False,
                "knowledge_graph_mutation": False,
            },
        }

    def record_decision(
        self,
        db: Session,
        project_id: str,
        owner: str,
        item_id: str,
        payload: DecisionCreate,
    ) -> dict[str, Any]:
        project = self._project(db, project_id, owner)
        item = self._item(db, project.project_id, item_id)
        replacement = None
        if payload.replacement_item_id:
            replacement = self._item(
                db, project.project_id, payload.replacement_item_id
            )
            if replacement.correction_of_item_id != item.memory_item_id:
                raise ScientificMemoryError("REPLACEMENT_DOES_NOT_CORRECT_ITEM", 409)
        decision = ScientificMemoryDecision(
            project_id=project.project_id,
            memory_item_id=item.memory_item_id,
            action=payload.action,
            actor_subject=owner,
            reason=payload.reason,
            replacement_item_id=(replacement.memory_item_id if replacement else None),
        )
        db.add(decision)
        db.flush()
        return {
            "decision_id": decision.decision_id,
            "memory_item_id": decision.memory_item_id,
            "action": decision.action,
            "replacement_item_id": decision.replacement_item_id,
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        }
