from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.research_workspace.models import Project

from .models import ConversationMessage, ConversationSession, utcnow


@dataclass
class ConversationMemoryError(Exception):
    code: str
    status: int


class ConversationMemoryService:
    """Persist private conversation context without elevating it to evidence."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _uuid(value: str, code: str) -> str:
        try:
            return str(UUID(str(value)))
        except ValueError as exc:
            raise ConversationMemoryError(code, 404) from exc

    def _owned_project(self, project_id: str, owner: str) -> Project:
        identifier = self._uuid(project_id, "PROJECT_NOT_FOUND")
        project = self.db.scalar(
            select(Project).where(
                Project.project_id == identifier,
                Project.owner_subject == owner,
                Project.archived_at.is_(None),
            )
        )
        if project is None:
            raise ConversationMemoryError("PROJECT_NOT_FOUND", 404)
        return project

    def _session(self, conversation_id: str, owner: str) -> ConversationSession:
        identifier = self._uuid(conversation_id, "CONVERSATION_NOT_FOUND")
        session = self.db.scalar(
            select(ConversationSession).where(
                ConversationSession.conversation_id == identifier,
                ConversationSession.owner_subject == owner,
                ConversationSession.archived_at.is_(None),
            )
        )
        if session is None:
            raise ConversationMemoryError("CONVERSATION_NOT_FOUND", 404)
        return session

    @staticmethod
    def session_dict(session: ConversationSession) -> dict[str, Any]:
        return {
            "conversation_id": session.conversation_id,
            "owner_subject": session.owner_subject,
            "project_id": session.project_id,
            "title": session.title,
            "active_taxon_id": session.active_taxon_id,
            "active_document_id": session.active_document_id,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "archived_at": session.archived_at,
            "version": session.version,
            "data_status": "CONVERSATION_CONTEXT",
            "evidence_authority": False,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }

    @staticmethod
    def message_dict(message: ConversationMessage) -> dict[str, Any]:
        return {
            "message_id": message.message_id,
            "conversation_id": message.conversation_id,
            "role": message.role,
            "content": message.content,
            "epistemic_status": message.epistemic_status,
            "context": message.context_json,
            "source_refs": message.source_refs_json,
            "tool_trace": message.tool_trace_json,
            "created_at": message.created_at,
            "data_status": message.data_status,
            "evidence_authority": message.evidence_authority,
            "scientific_publication_authorized": message.scientific_publication_authorized,
            "knowledge_graph_mutation_authorized": message.knowledge_graph_mutation_authorized,
        }

    def create_session(
        self,
        owner: str,
        *,
        project_id: str | None = None,
        title: str = "Calyx conversation",
        active_taxon_id: str | None = None,
        active_document_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_project = None
        if project_id:
            normalized_project = self._owned_project(project_id, owner).project_id
        session = ConversationSession(
            owner_subject=owner,
            project_id=normalized_project,
            title=" ".join(title.strip().split()) or "Calyx conversation",
            active_taxon_id=self._optional(active_taxon_id),
            active_document_id=self._optional(active_document_id),
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return self.session_dict(session)

    def list_sessions(
        self,
        owner: str,
        *,
        project_id: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        filters = [
            ConversationSession.owner_subject == owner,
            ConversationSession.archived_at.is_(None),
        ]
        if project_id:
            normalized_project = self._owned_project(project_id, owner).project_id
            filters.append(ConversationSession.project_id == normalized_project)
        total = int(
            self.db.scalar(
                select(func.count()).select_from(ConversationSession).where(*filters)
            )
            or 0
        )
        sessions = self.db.scalars(
            select(ConversationSession)
            .where(*filters)
            .order_by(ConversationSession.updated_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return {
            "items": [self.session_dict(session) for session in sessions],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def get_session(self, conversation_id: str, owner: str) -> dict[str, Any]:
        session = self._session(conversation_id, owner)
        messages = self.db.scalars(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == session.conversation_id,
                ConversationMessage.owner_subject == owner,
            )
            .order_by(ConversationMessage.created_at, ConversationMessage.message_id)
        ).all()
        return {
            **self.session_dict(session),
            "messages": [self.message_dict(message) for message in messages],
        }

    def append_exchange(
        self,
        conversation_id: str,
        owner: str,
        *,
        question: str,
        answer: str,
        epistemic_status: str,
        context: dict[str, Any],
        evidence: list[dict[str, Any]],
        tool_trace: list[dict[str, Any]],
    ) -> dict[str, Any]:
        session = self._session(conversation_id, owner)
        project_context = context.get("active_project_id")
        if (
            session.project_id
            and project_context
            and str(session.project_id) != str(project_context)
        ):
            raise ConversationMemoryError("CONVERSATION_PROJECT_CONTEXT_MISMATCH", 409)

        source_refs = [self._source_ref(item) for item in evidence]
        operator = ConversationMessage(
            conversation_id=session.conversation_id,
            owner_subject=owner,
            role="OPERATOR",
            content=question,
            context_json=dict(context),
            source_refs_json=[],
            tool_trace_json=[],
        )
        calyx = ConversationMessage(
            conversation_id=session.conversation_id,
            owner_subject=owner,
            role="CALYX",
            content=answer,
            epistemic_status=epistemic_status,
            context_json=dict(context),
            source_refs_json=source_refs,
            tool_trace_json=[dict(item) for item in tool_trace],
        )
        self.db.add_all([operator, calyx])
        session.active_taxon_id = self._optional(context.get("active_taxon_id"))
        session.active_document_id = self._optional(context.get("active_document_id"))
        session.updated_at = utcnow()
        session.version += 1
        self.db.commit()
        self.db.refresh(operator)
        self.db.refresh(calyx)
        self.db.refresh(session)
        return {
            "conversation": self.session_dict(session),
            "messages": [self.message_dict(operator), self.message_dict(calyx)],
        }

    @staticmethod
    def _source_ref(evidence: dict[str, Any]) -> dict[str, Any]:
        citation = dict(evidence.get("citation") or {})
        return {
            "result_id": evidence.get("result_id"),
            "object_type": evidence.get("object_type"),
            "title": evidence.get("title"),
            "citation": {
                "document_id": citation.get("document_id"),
                "revision_id": citation.get("revision_id"),
                "identifier": citation.get("identifier"),
                "locator": citation.get("locator"),
                "document_title": citation.get("document_title"),
            },
        }

    @staticmethod
    def _optional(value: Any) -> str | None:
        text = " ".join(str(value or "").strip().split())
        return text or None
