from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.calyx_conversation.evidence_synthesis import provider_context
from app.database import Base
from app.research_workspace.models import Project, SavedSearch
from app.scientific_memory.models import (
    ScientificMemoryCapture,
    ScientificMemoryDecision,
    ScientificMemoryItem,
)
from app.scientific_memory.schemas import CaptureCreate, DecisionCreate
from app.scientific_memory.service import ScientificMemoryError, ScientificMemoryService

TABLES = (
    Project.__table__,
    SavedSearch.__table__,
    ScientificMemoryCapture.__table__,
    ScientificMemoryItem.__table__,
    ScientificMemoryDecision.__table__,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"research_station": None}},
    )
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as session:
        yield session


def project(db: Session, owner: str = "owner-a") -> Project:
    value = Project(owner_subject=owner, title="Orchid physiology")
    db.add(value)
    db.commit()
    db.refresh(value)
    return value


def capture_payload() -> CaptureCreate:
    return CaptureCreate.model_validate(
        {
            "origin": "OASIS",
            "name": "Phragmipedium CAM physiology",
            "query": "primary literature on Phragmipedium leaf physiology",
            "result_count_snapshot": 2,
            "filters": {"open_access": True},
            "items": [
                {
                    "item_type": "EVIDENCE",
                    "authority": "SOURCE_EVIDENCE",
                    "statement": "The study reported diel acid fluctuation.",
                    "confidence": 0.91,
                    "source": {
                        "document_id": "oa-paper-1",
                        "revision_id": "sha256:fixture-v1",
                        "identifier": "doi:10.0000/open.fixture",
                        "locator": {"page": 4, "section": "Results"},
                        "authorized_excerpt": "A short authorized fixture excerpt.",
                        "rights_basis": "OPEN_ACCESS",
                    },
                    "structured_payload": {"trait": "diel acid fluctuation"},
                },
                {
                    "item_type": "CLAIM",
                    "authority": "CALYX_INFERENCE",
                    "statement": "The observation may justify a CAM follow-up experiment.",
                    "confidence": 0.55,
                    "source": {
                        "identifier": "calyx:fixture-analysis",
                        "locator": {},
                        "rights_basis": "METADATA_ONLY",
                    },
                },
            ],
        }
    )


def test_oasis_capture_becomes_recallable_calyx_context(db):
    workspace = project(db)
    service = ScientificMemoryService()
    created = service.create_capture(
        db, workspace.project_id, "owner-a", capture_payload()
    )
    db.commit()

    assert created["origin"] == "OASIS"
    assert created["saved_search_id"]
    recalled = service.recall(db, workspace.project_id, "owner-a")
    assert len(recalled["calyx_context"]["source_evidence"]) == 1
    assert len(recalled["calyx_context"]["prior_calyx_inference"]) == 1
    assert (
        recalled["calyx_context"]["prior_calyx_inference"][0][
            "canonical_scientific_knowledge"
        ]
        is False
    )

    model_context = provider_context({"scientific_memory": recalled})
    assert model_context["scientific_memory"]["project_id"] == workspace.project_id
    assert recalled["consumer_contract"] == {
        "oasis_can_capture": True,
        "calyx_can_recall": True,
        "research_station_owns_project_scope": True,
    }


def test_capture_is_idempotent_and_does_not_duplicate_saved_search(db):
    workspace = project(db)
    service = ScientificMemoryService()
    first = service.create_capture(
        db, workspace.project_id, "owner-a", capture_payload()
    )
    db.commit()
    second = service.create_capture(
        db, workspace.project_id, "owner-a", capture_payload()
    )
    db.commit()
    assert second["capture_id"] == first["capture_id"]
    assert second["idempotent_replay"] is True
    assert len(db.scalars(select(SavedSearch)).all()) == 1


def test_exact_source_anchor_is_required_for_source_evidence():
    payload = capture_payload().model_dump()
    payload["items"][0]["source"]["locator"] = {}
    with pytest.raises(ValidationError, match="exact locator"):
        CaptureCreate.model_validate(payload)


def test_owner_scope_is_fail_closed(db):
    workspace = project(db)
    with pytest.raises(ScientificMemoryError, match="PROJECT_NOT_FOUND"):
        ScientificMemoryService().create_capture(
            db, workspace.project_id, "owner-b", capture_payload()
        )


def test_structured_protected_locality_fails_closed(db):
    workspace = project(db)
    payload = capture_payload().model_dump()
    payload["items"][0]["structured_payload"]["decimalLatitude"] = -6.12345
    with pytest.raises(ScientificMemoryError, match="SENSITIVE_LOCALITY_FORBIDDEN"):
        ScientificMemoryService().create_capture(
            db,
            workspace.project_id,
            "owner-a",
            CaptureCreate.model_validate(payload),
        )


def test_metadata_only_record_cannot_claim_source_evidence():
    payload = capture_payload().model_dump()
    payload["items"][0]["source"]["rights_basis"] = "METADATA_ONLY"
    with pytest.raises(ValidationError, match="cannot become source evidence"):
        CaptureCreate.model_validate(payload)


def test_append_only_invalidation_excludes_item_from_calyx_context(db):
    workspace = project(db)
    service = ScientificMemoryService()
    created = service.create_capture(
        db, workspace.project_id, "owner-a", capture_payload()
    )
    db.commit()
    evidence = next(
        item for item in created["items"] if item["authority"] == "SOURCE_EVIDENCE"
    )
    decision = service.record_decision(
        db,
        workspace.project_id,
        "owner-a",
        evidence["memory_item_id"],
        DecisionCreate(action="INVALIDATE", reason="Source revision was withdrawn."),
    )
    db.commit()
    recalled = service.recall(db, workspace.project_id, "owner-a")
    assert decision["automatic_publication"] is False
    assert recalled["calyx_context"]["source_evidence"] == []
    invalidated = next(
        item
        for item in recalled["items"]
        if item["memory_item_id"] == evidence["memory_item_id"]
    )
    assert invalidated["review_state"] == "INVALIDATED"
    assert (
        invalidated["decision_history"][0]["reason"] == "Source revision was withdrawn."
    )


def test_review_acceptance_never_promotes_to_canonical(db):
    workspace = project(db)
    service = ScientificMemoryService()
    created = service.create_capture(
        db, workspace.project_id, "owner-a", capture_payload()
    )
    db.commit()
    evidence = next(
        item for item in created["items"] if item["authority"] == "SOURCE_EVIDENCE"
    )
    service.record_decision(
        db,
        workspace.project_id,
        "owner-a",
        evidence["memory_item_id"],
        DecisionCreate(
            action="ACCEPT_REVIEW", reason="Provenance verified for research use."
        ),
    )
    db.commit()
    recalled = service.recall(db, workspace.project_id, "owner-a")
    accepted = next(
        item
        for item in recalled["items"]
        if item["memory_item_id"] == evidence["memory_item_id"]
    )
    assert accepted["review_state"] == "ACCEPTED_FOR_RESEARCH_USE"
    assert accepted["canonical_scientific_knowledge"] is False
    assert recalled["governance"]["automatic_publication"] is False
    assert recalled["governance"]["engineering_memory_separate"] is True


def test_migration_is_append_only_and_not_an_activation():
    sql = Path("migrations/141_scientific_memory_mvp.sql").read_text().casefold()
    assert "scientific_memory_is_append_only" in sql
    assert "before update or delete" in sql
    assert "revoke all" in sql
    assert "applying this migration remains a separately governed action" in sql
