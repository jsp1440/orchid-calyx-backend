from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .models import (
    AuditEvent,
    Note,
    Project,
    ProjectDocument,
    ProjectEvidence,
    ProjectTaxon,
    SavedSearch,
    utcnow,
)
from .schemas import (
    DocumentLinkCreate,
    EvidenceLinkCreate,
    NoteCreate,
    ProjectCreate,
    ProjectPatch,
    SavedSearchCreate,
    TaxonLinkCreate,
)


@dataclass
class ResearchWorkspaceError(Exception):
    code: str
    status: int
    extra: dict[str, Any] | None = None


class CanonicalReferenceValidator:
    """Validate identifiers against the canonical owning Calyx stores."""

    QUERIES = {
        "taxon": """
            SELECT 1 FROM oc_graph.kg_nodes
            WHERE canonical_key = :identifier OR kg_node_id::text = :identifier LIMIT 1
        """,
        "document": """
            SELECT 1 FROM oc_intake.documents WHERE id::text = :identifier LIMIT 1
        """,
        "CANDIDATE": """
            SELECT 1 FROM oc_candidate_knowledge.candidates
            WHERE candidate_id::text = :identifier AND active LIMIT 1
        """,
        "AGGREGATE": """
            SELECT 1 FROM oc_candidate_knowledge.aggregate_assertions
            WHERE aggregate_id::text = :identifier LIMIT 1
        """,
    }

    def __init__(self, db: Session):
        self.db = db

    def require(self, kind: str, identifier: str) -> None:
        try:
            exists = self.db.execute(
                text(self.QUERIES[kind]), {"identifier": identifier}
            ).first()
        except SQLAlchemyError as exc:
            raise ResearchWorkspaceError(
                "REFERENCE_VALIDATION_UNAVAILABLE", 503
            ) from exc
        if not exists:
            raise ResearchWorkspaceError(f"{kind.upper()}_NOT_FOUND", 404)


class ResearchWorkspaceService:
    def __init__(
        self, db: Session, validator: CanonicalReferenceValidator | None = None
    ):
        self.db = db
        self.validator = validator or CanonicalReferenceValidator(db)

    @staticmethod
    def _valid_uuid(value: str) -> str:
        try:
            return str(UUID(value))
        except ValueError as exc:
            raise ResearchWorkspaceError("PROJECT_NOT_FOUND", 404) from exc

    def _project(
        self, project_id: str, subject: str, privileged: bool = False
    ) -> Project:
        identifier = self._valid_uuid(project_id)
        statement = select(Project).where(Project.project_id == identifier)
        if not privileged:
            statement = statement.where(Project.owner_subject == subject)
        project = self.db.scalar(statement)
        if project is None:
            raise ResearchWorkspaceError("PROJECT_NOT_FOUND", 404)
        return project

    def _audit(
        self,
        project: Project,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        changes: dict[str, Any] | None = None,
    ):
        safe_changes = {
            key: value
            for key, value in (changes or {}).items()
            if key
            not in {
                "body",
                "description",
                "research_question",
                "hypothesis",
                "token",
                "access_code",
            }
        }
        self.db.add(
            AuditEvent(
                project_id=project.project_id,
                actor_subject=actor,
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id),
                change_summary=safe_changes,
            )
        )

    def _counts(self, project_id: str) -> dict[str, int]:
        tables = {
            "saved_searches": SavedSearch,
            "notes": Note,
            "taxa": ProjectTaxon,
            "documents": ProjectDocument,
            "evidence": ProjectEvidence,
        }
        return {
            key: int(
                self.db.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.project_id == project_id)
                )
                or 0
            )
            for key, model in tables.items()
        }

    def project_dict(self, project: Project) -> dict[str, Any]:
        return {
            "project_id": project.project_id,
            "owner_subject": project.owner_subject,
            "title": project.title,
            "description": project.description,
            "research_question": project.research_question,
            "hypothesis": project.hypothesis,
            "status": project.status,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "archived_at": project.archived_at,
            "version": project.version,
            "permissions": {"can_read": True, "can_update": True, "can_archive": True},
            "link_counts": self._counts(project.project_id),
        }

    def list_projects(
        self,
        subject: str,
        status: str | None,
        archived: bool,
        limit: int,
        offset: int,
        privileged: bool = False,
    ):
        filters = [
            Project.archived_at.is_not(None)
            if archived
            else Project.archived_at.is_(None)
        ]
        if not privileged:
            filters.append(Project.owner_subject == subject)
        if status:
            filters.append(Project.status == status)
        total = int(
            self.db.scalar(select(func.count()).select_from(Project).where(*filters))
            or 0
        )
        items = self.db.scalars(
            select(Project)
            .where(*filters)
            .order_by(Project.updated_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return {
            "items": [self.project_dict(item) for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def create_project(self, subject: str, payload: ProjectCreate):
        project = Project(owner_subject=subject, **payload.model_dump())
        self.db.add(project)
        self.db.flush()
        self._audit(
            project,
            subject,
            "PROJECT_CREATED",
            "PROJECT",
            project.project_id,
            {"status": project.status},
        )
        self.db.commit()
        self.db.refresh(project)
        return self.project_dict(project)

    def get_project(self, project_id: str, subject: str, privileged: bool = False):
        return self.project_dict(self._project(project_id, subject, privileged))

    def update_project(
        self,
        project_id: str,
        subject: str,
        payload: ProjectPatch,
        privileged: bool = False,
    ):
        project = self._project(project_id, subject, privileged)
        if project.archived_at:
            raise ResearchWorkspaceError("PROJECT_ARCHIVED", 409)
        if project.version != payload.expected_version:
            raise ResearchWorkspaceError(
                "VERSION_CONFLICT", 409, {"current_version": project.version}
            )
        changes = payload.model_dump(exclude={"expected_version"}, exclude_unset=True)
        for key, value in changes.items():
            setattr(project, key, value)
        project.version += 1
        project.updated_at = utcnow()
        self._audit(
            project,
            subject,
            "PROJECT_UPDATED",
            "PROJECT",
            project.project_id,
            {"fields": sorted(changes), "version": project.version},
        )
        self.db.commit()
        self.db.refresh(project)
        return self.project_dict(project)

    def set_archive(
        self, project_id: str, subject: str, archived: bool, privileged: bool = False
    ):
        project = self._project(project_id, subject, privileged)
        project.archived_at = utcnow() if archived else None
        project.updated_at = utcnow()
        project.version += 1
        action = "PROJECT_ARCHIVED" if archived else "PROJECT_RESTORED"
        self._audit(
            project,
            subject,
            action,
            "PROJECT",
            project.project_id,
            {"version": project.version},
        )
        self.db.commit()
        self.db.refresh(project)
        return self.project_dict(project)

    def _ensure_mutable(
        self, project_id: str, subject: str, privileged: bool = False
    ) -> Project:
        project = self._project(project_id, subject, privileged)
        if project.archived_at:
            raise ResearchWorkspaceError("PROJECT_ARCHIVED", 409)
        return project

    def list_saved_searches(
        self, project_id: str, subject: str, privileged: bool = False
    ):
        project = self._project(project_id, subject, privileged)
        items = self.db.scalars(
            select(SavedSearch)
            .where(
                SavedSearch.project_id == project.project_id,
                SavedSearch.archived_at.is_(None),
            )
            .order_by(SavedSearch.updated_at.desc())
        ).all()
        return {"items": [self.saved_search_dict(item) for item in items]}

    @staticmethod
    def saved_search_dict(item: SavedSearch):
        return {
            "saved_search_id": item.saved_search_id,
            "project_id": item.project_id,
            "name": item.name,
            "query": item.query_json,
            "result_count_snapshot": item.result_count_snapshot,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "version": item.version,
        }

    def create_saved_search(
        self,
        project_id: str,
        subject: str,
        payload: SavedSearchCreate,
        privileged: bool = False,
    ):
        project = self._ensure_mutable(project_id, subject, privileged)
        duplicate = self.db.scalar(
            select(SavedSearch).where(
                SavedSearch.project_id == project.project_id,
                func.lower(SavedSearch.name) == payload.name.lower(),
                SavedSearch.archived_at.is_(None),
            )
        )
        if duplicate:
            raise ResearchWorkspaceError("SAVED_SEARCH_NAME_EXISTS", 409)
        item = SavedSearch(
            project_id=project.project_id,
            owner_subject=project.owner_subject,
            name=payload.name,
            query_json=payload.query,
            result_count_snapshot=payload.result_count_snapshot,
        )
        self.db.add(item)
        self.db.flush()
        self._audit(
            project,
            subject,
            "SAVED_SEARCH_CREATED",
            "SAVED_SEARCH",
            item.saved_search_id,
            {"name": item.name},
        )
        self.db.commit()
        self.db.refresh(item)
        return self.saved_search_dict(item)

    def list_notes(self, project_id: str, subject: str, privileged: bool = False):
        project = self._project(project_id, subject, privileged)
        items = self.db.scalars(
            select(Note)
            .where(Note.project_id == project.project_id, Note.archived_at.is_(None))
            .order_by(Note.updated_at.desc())
        ).all()
        return {"items": [self.note_dict(item) for item in items]}

    @staticmethod
    def note_dict(item: Note):
        return {
            "note_id": item.note_id,
            "project_id": item.project_id,
            "title": item.title,
            "body": item.body,
            "note_type": item.note_type,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "version": item.version,
            "data_status": "USER_ANNOTATION",
        }

    def create_note(
        self,
        project_id: str,
        subject: str,
        payload: NoteCreate,
        privileged: bool = False,
    ):
        project = self._ensure_mutable(project_id, subject, privileged)
        note = Note(
            project_id=project.project_id,
            owner_subject=project.owner_subject,
            **payload.model_dump(),
        )
        self.db.add(note)
        self.db.flush()
        self._audit(
            project,
            subject,
            "NOTE_CREATED",
            "NOTE",
            note.note_id,
            {"note_type": note.note_type},
        )
        self.db.commit()
        self.db.refresh(note)
        return self.note_dict(note)

    def _links(self, project: Project, model):
        return self.db.scalars(
            select(model)
            .where(model.project_id == project.project_id)
            .order_by(model.created_at.desc())
        ).all()

    @staticmethod
    def _link_dict(item):
        return {
            column.name: getattr(item, column.name) for column in item.__table__.columns
        }

    def list_links(
        self, project_id: str, subject: str, model, privileged: bool = False
    ):
        project = self._project(project_id, subject, privileged)
        return {
            "items": [self._link_dict(item) for item in self._links(project, model)]
        }

    def add_taxon(
        self,
        project_id: str,
        subject: str,
        payload: TaxonLinkCreate,
        privileged: bool = False,
    ):
        project = self._ensure_mutable(project_id, subject, privileged)
        self.validator.require("taxon", payload.taxon_id)
        return self._add_link(
            project, subject, ProjectTaxon, "TAXON", payload.model_dump()
        )

    def add_document(
        self,
        project_id: str,
        subject: str,
        payload: DocumentLinkCreate,
        privileged: bool = False,
    ):
        project = self._ensure_mutable(project_id, subject, privileged)
        self.validator.require("document", payload.document_id)
        return self._add_link(
            project, subject, ProjectDocument, "DOCUMENT", payload.model_dump()
        )

    def add_evidence(
        self,
        project_id: str,
        subject: str,
        payload: EvidenceLinkCreate,
        privileged: bool = False,
    ):
        project = self._ensure_mutable(project_id, subject, privileged)
        self.validator.require(payload.evidence_kind, payload.evidence_id)
        return self._add_link(
            project, subject, ProjectEvidence, "EVIDENCE", payload.model_dump()
        )

    def _add_link(
        self,
        project: Project,
        subject: str,
        model,
        entity_type: str,
        values: dict[str, Any],
    ):
        item = model(
            project_id=project.project_id, created_by_subject=subject, **values
        )
        self.db.add(item)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            query = select(model).where(model.project_id == project.project_id)
            for key in model.__mapper__.primary_key:
                if key.name != "project_id":
                    query = query.where(getattr(model, key.name) == values[key.name])
            existing = self.db.scalar(query)
            if existing:
                return self._link_dict(existing)
            raise
        identifier = (
            values.get("taxon_id")
            or values.get("document_id")
            or values.get("evidence_id")
        )
        self._audit(
            project,
            subject,
            f"{entity_type}_LINKED",
            entity_type,
            str(identifier),
            {"relationship": values["relationship"]},
        )
        self.db.commit()
        self.db.refresh(item)
        return self._link_dict(item)

    def remove_link(
        self,
        project_id: str,
        subject: str,
        model,
        filters: dict[str, str],
        entity_type: str,
        privileged: bool = False,
    ):
        project = self._ensure_mutable(project_id, subject, privileged)
        query = select(model).where(model.project_id == project.project_id)
        for key, value in filters.items():
            query = query.where(getattr(model, key) == value)
        item = self.db.scalar(query)
        if item is None:
            raise ResearchWorkspaceError(f"{entity_type}_LINK_NOT_FOUND", 404)
        identifier = (
            filters.get("taxon_id")
            or filters.get("document_id")
            or filters.get("evidence_id")
        )
        self.db.delete(item)
        self._audit(
            project, subject, f"{entity_type}_UNLINKED", entity_type, str(identifier)
        )
        self.db.commit()
        return {"removed": True}

    def activity(
        self,
        project_id: str,
        subject: str,
        limit: int,
        offset: int,
        privileged: bool = False,
    ):
        project = self._project(project_id, subject, privileged)
        total = int(
            self.db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.project_id == project.project_id)
            )
            or 0
        )
        items = self.db.scalars(
            select(AuditEvent)
            .where(AuditEvent.project_id == project.project_id)
            .order_by(AuditEvent.occurred_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return {
            "items": [
                {
                    "event_id": x.event_id,
                    "project_id": x.project_id,
                    "actor_subject": x.actor_subject,
                    "action": x.action,
                    "entity_type": x.entity_type,
                    "entity_id": x.entity_id,
                    "occurred_at": x.occurred_at,
                    "change_summary": x.change_summary,
                }
                for x in items
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
