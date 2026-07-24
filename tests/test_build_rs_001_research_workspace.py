from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.research_workspace.models import (
    AuditEvent,
    Note,
    Project,
    ProjectDocument,
    ProjectEvidence,
    ProjectTaxon,
    SavedSearch,
)
from app.research_workspace.schemas import (
    DocumentLinkCreate,
    EvidenceLinkCreate,
    NoteCreate,
    ProjectCreate,
    ProjectPatch,
    SavedSearchCreate,
    TaxonLinkCreate,
)
from app.research_workspace.service import (
    ResearchWorkspaceError,
    ResearchWorkspaceService,
)


TABLES = [
    Project.__table__,
    SavedSearch.__table__,
    Note.__table__,
    ProjectTaxon.__table__,
    ProjectDocument.__table__,
    ProjectEvidence.__table__,
    AuditEvent.__table__,
]


class Validator:
    allowed = {
        ("taxon", "taxon:42"),
        ("document", "document-7"),
        ("CANDIDATE", "11"),
        ("AGGREGATE", "12"),
    }

    def require(self, kind, identifier):
        if (kind, identifier) not in self.allowed:
            raise ResearchWorkspaceError(f"{kind}_NOT_FOUND", 404)


@pytest.fixture
def service():
    engine = create_engine(
        "sqlite://",
        execution_options={"schema_translate_map": {"research_station": None}},
    )
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as db:
        yield ResearchWorkspaceService(db, Validator())


def project_payload(title="Pollination evidence"):
    return ProjectCreate(
        title=title,
        description="Review source-backed relationships.",
        research_question="Which relationships are observed?",
        hypothesis=None,
        status="ACTIVE",
    )


def test_project_crud_pagination_archive_restore_and_activity(service):
    first = service.create_project("owner-a", project_payload())
    service.create_project("owner-a", project_payload("Second project"))
    page = service.list_projects("owner-a", None, False, 1, 0)
    assert page["total"] == 2 and len(page["items"]) == 1
    fetched = service.get_project(first["project_id"], "owner-a")
    updated = service.update_project(
        first["project_id"],
        "owner-a",
        ProjectPatch(title="Updated title", expected_version=fetched["version"]),
    )
    assert updated["title"] == "Updated title" and updated["version"] == 2
    archived = service.set_archive(first["project_id"], "owner-a", True)
    assert archived["archived_at"] is not None
    assert service.list_projects("owner-a", None, False, 25, 0)["total"] == 1
    assert service.list_projects("owner-a", None, True, 25, 0)["total"] == 1
    restored = service.set_archive(first["project_id"], "owner-a", False)
    assert restored["archived_at"] is None
    actions = {
        event["action"]
        for event in service.activity(first["project_id"], "owner-a", 50, 0)["items"]
    }
    assert {
        "PROJECT_CREATED",
        "PROJECT_UPDATED",
        "PROJECT_ARCHIVED",
        "PROJECT_RESTORED",
    } <= actions


def test_ownership_isolation_and_version_conflict(service):
    project = service.create_project("owner-a", project_payload())
    with pytest.raises(ResearchWorkspaceError, match="PROJECT_NOT_FOUND"):
        service.get_project(project["project_id"], "owner-b")
    with pytest.raises(ResearchWorkspaceError) as conflict:
        service.update_project(
            project["project_id"],
            "owner-a",
            ProjectPatch(title="Stale", expected_version=99),
        )
    assert conflict.value.code == "VERSION_CONFLICT"
    assert (
        service.get_project(project["project_id"], "service", privileged=True)[
            "project_id"
        ]
        == project["project_id"]
    )


def test_saved_search_notes_links_and_idempotent_duplicates(service):
    project = service.create_project("owner-a", project_payload())
    project_id = project["project_id"]
    search = service.create_saved_search(
        project_id,
        "owner-a",
        SavedSearchCreate(name="Dracula", query={"taxon": "Dracula"}),
    )
    note = service.create_note(
        project_id,
        "owner-a",
        NoteCreate(title="Method", body="Inspect primary sources.", note_type="METHOD"),
    )
    assert search["query"] == {"taxon": "Dracula"}
    assert note["data_status"] == "USER_ANNOTATION"
    taxon = service.add_taxon(
        project_id, "owner-a", TaxonLinkCreate(taxon_id="taxon:42")
    )
    duplicate = service.add_taxon(
        project_id, "owner-a", TaxonLinkCreate(taxon_id="taxon:42")
    )
    assert duplicate["taxon_id"] == taxon["taxon_id"]
    service.add_document(
        project_id, "owner-a", DocumentLinkCreate(document_id="document-7")
    )
    service.add_evidence(
        project_id,
        "owner-a",
        EvidenceLinkCreate(evidence_kind="CANDIDATE", evidence_id="11"),
    )
    detail = service.get_project(project_id, "owner-a")
    assert detail["link_counts"] == {
        "saved_searches": 1,
        "notes": 1,
        "taxa": 1,
        "documents": 1,
        "evidence": 1,
    }
    assert service.remove_link(
        project_id, "owner-a", ProjectTaxon, {"taxon_id": "taxon:42"}, "TAXON"
    ) == {"removed": True}


def test_invalid_payload_missing_reference_archive_mutation_and_audit_redaction(
    service,
):
    with pytest.raises(ValidationError):
        ProjectCreate(title="", description="", status="ACTIVE")
    project = service.create_project("owner-a", project_payload())
    with pytest.raises(ResearchWorkspaceError) as missing:
        service.add_document(
            project["project_id"],
            "owner-a",
            DocumentLinkCreate(document_id="missing"),
        )
    assert missing.value.status == 404
    service.set_archive(project["project_id"], "owner-a", True)
    with pytest.raises(ResearchWorkspaceError, match="PROJECT_ARCHIVED"):
        service.create_note(
            project["project_id"],
            "owner-a",
            NoteCreate(body="blocked", note_type="GENERAL"),
        )
    activities = service.activity(project["project_id"], "owner-a", 50, 0)["items"]
    assert all("body" not in event["change_summary"] for event in activities)


def test_migration_is_additive_idempotent_and_audit_protected():
    sql = (
        Path("migrations/101_research_workspace_foundation.sql")
        .read_text(encoding="utf-8")
        .lower()
    )
    assert sql.count("create table if not exists") == 7
    assert "drop table" not in sql and "truncate" not in sql
    assert "before update or delete" in sql
    assert "revoke all on all tables in schema research_station from public" in sql
