from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.reasoning_ledger.models import (
    LedgerEntry,
    LedgerEntryKind,
    LedgerProvenance,
    ReviewDecision,
    ReviewOutcome,
    UncertaintyMarker,
)
from app.reasoning_ledger.operational_service import (
    CanonicalLiteratureValidator,
    OperationalReasoningLedgerService,
)
from app.reasoning_ledger.persistence import (
    TABLES,
    StaleLedgerVersionError,
)
from app.reasoning_ledger.routes import project_router, router
from app.reasoning_ledger.serialization import (
    dict_to_ledger,
    ledger_to_canonical_json,
    ledger_to_dict,
)
from app.research_workspace.models import Project
from app.security import verify_owner_or_api_key


def _database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={
            "schema_translate_map": {
                "research_station": None,
                "reasoning_ledger": None,
            }
        },
    )
    Base.metadata.create_all(engine, tables=[Project.__table__, *TABLES])
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _project(db: Session, owner="owner-a"):
    project = Project(owner_subject=owner, title="Reasoning project", description="")
    db.add(project)
    db.commit()
    return str(project.project_id)


def _entry(owner, project_id, kind=LedgerEntryKind.SUPPORT, confidence=0.9):
    return LedgerEntry(
        kind=kind,
        text=f"Auditable {kind.value}",
        author=owner,
        tenant_id=owner,
        project_id=project_id,
        uncertainty=UncertaintyMarker(confidence=confidence),
    )


def test_persistent_idempotency_history_stale_write_and_isolation():
    session_local = _database()
    with session_local() as db:
        project_id = _project(db)
        service = OperationalReasoningLedgerService(db)
        first, created = service.create(
            owner="owner-a", project_id=project_id, title="Question", description=""
        )
        repeated, created_again = service.create(
            owner="owner-a", project_id=project_id, title="Question", description=""
        )
        assert created is True and created_again is False
        assert first.ledger_id == repeated.ledger_id
        updated = service.append(
            str(first.ledger_id),
            _entry("owner-a", project_id),
            owner="owner-a",
            expected_version=1,
        )
        assert updated.version == 2 and updated.entries[0].sequence == 0
        with pytest.raises(StaleLedgerVersionError):
            service.append(
                str(first.ledger_id),
                _entry("owner-a", project_id),
                owner="owner-a",
                expected_version=1,
            )
        with pytest.raises(Exception, match="ledger not found"):
            service.current(str(first.ledger_id), "owner-b")
        history = service.history(str(first.ledger_id), "owner-a")
        assert [item.version for item in history["revisions"]] == [1, 2]
        assert [event["event_type"] for event in history["audit_events"]] == [
            "LEDGER_CREATED",
            "ENTRY_APPENDED",
        ]


def test_serialization_preserves_conflict_supersession_and_review_hash():
    session_local = _database()
    with session_local() as db:
        project_id = _project(db)
        service = OperationalReasoningLedgerService(db)
        ledger, _ = service.create(
            owner="owner-a", project_id=project_id, title="Gate", description=""
        )
        ledger = service.append(
            str(ledger.ledger_id),
            _entry("owner-a", project_id, LedgerEntryKind.CONFLICT),
            owner="owner-a",
            expected_version=ledger.version,
        )
        conflict_id = ledger.entries[-1].entry_id
        ledger = service.resolve_conflict(
            str(ledger.ledger_id),
            conflict_id,
            owner="owner-a",
            expected_version=ledger.version,
            resolution_state="superseded",
            rationale="Better evidence",
        )
        ledger = service.append(
            str(ledger.ledger_id),
            _entry("owner-a", project_id, LedgerEntryKind.CONCLUSION),
            owner="owner-a",
            expected_version=ledger.version,
        )
        ledger = service.review(
            str(ledger.ledger_id),
            ReviewDecision(
                reviewer="owner-a", outcome=ReviewOutcome.APPROVED, rationale="Reviewed"
            ),
            owner="owner-a",
            expected_version=ledger.version,
        )
        assert ledger.has_human_approval
        assert (
            ledger.review_decisions[-1].reviewed_content_hash
            == ledger.review_content_hash
        )
        restored = dict_to_ledger(ledger_to_dict(ledger))
        assert restored.resolved_conflict_ids == {conflict_id}
        assert restored.has_human_approval
        assert ledger_to_canonical_json(restored) == ledger_to_canonical_json(ledger)
        ledger = service.append(
            str(ledger.ledger_id),
            _entry("owner-a", project_id),
            owner="owner-a",
            expected_version=ledger.version,
        )
        assert not ledger.has_human_approval


def test_literature_reference_validation_preserves_roles(tmp_path: Path):
    from app.literature_extraction.models import PaperKnowledge
    from app.literature_extraction.repository import LiteratureResultRepository

    paper_data = {
        "paper_id": "paper-1",
        "source": {
            "content_hash": "a" * 64,
            "media_type": "text/plain",
            "original_filename": "paper.txt",
        },
        "metadata": {},
        "analysis_manifest": {
            "analysis_id": "analysis-1",
            "analysis_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "pipeline_version": "test",
            "status": "completed",
        },
    }
    # Use the canonical model's defaults, then persist the established bundle payload.
    paper = PaperKnowledge.model_validate(paper_data)
    paper_dir = tmp_path / paper.paper_id
    paper_dir.mkdir(parents=True)
    (paper_dir / "paper.json").write_text(paper.model_dump_json(), encoding="utf-8")
    validator = CanonicalLiteratureValidator(
        papers=LiteratureResultRepository(tmp_path)
    )
    validator.validate(
        LedgerProvenance(
            source_kind="literature",
            source_id=paper.paper_id,
            content_hash=paper.source.content_hash,
            extra={"resolution_state": "resolved"},
        )
    )
    validator.validate(
        LedgerProvenance(
            source_kind="literature",
            source_id="not-yet-resolved",
            extra={"resolution_state": "unresolved", "role": "counterevidence"},
        )
    )


@pytest.mark.asyncio
async def test_end_to_end_literature_evidence_to_reviewed_governed_retrieval(
    tmp_path: Path,
):
    from app.literature_extraction.repository import LiteratureResultRepository
    from app.literature_extraction.service import extract_and_persist

    source = tmp_path / "paper.txt"
    source.write_text(
        "Orchid evidence study\n\nResults\nEscherichia coli was characterized by a red flower trait.\n",
        encoding="utf-8",
    )
    papers = LiteratureResultRepository(tmp_path / "literature")
    paper = await extract_and_persist(source, papers)
    assert paper.evidence
    evidence = paper.evidence[0]
    claim_id = evidence.supports_ids[0]

    session_local = _database()
    with session_local() as db:
        project_id = _project(db)
        service = OperationalReasoningLedgerService(
            db,
            literature_validator=CanonicalLiteratureValidator(papers=papers),
        )
        ledger, _ = service.create(
            owner="owner-a",
            project_id=project_id,
            title="Literature synthesis",
            description="",
        )
        for kind, role in (
            (LedgerEntryKind.SUPPORT, "support"),
            (LedgerEntryKind.COUNTEREVIDENCE, "counterevidence"),
        ):
            ledger = service.append(
                str(ledger.ledger_id),
                LedgerEntry(
                    kind=kind,
                    text=f"Reviewable {role} summary",
                    author="owner-a",
                    tenant_id="owner-a",
                    project_id=project_id,
                    provenance=LedgerProvenance(
                        source_kind="literature",
                        source_id=paper.paper_id,
                        literature_record_id=evidence.evidence_id,
                        content_hash=paper.source.content_hash,
                        extra={
                            "resolution_state": "resolved",
                            "claim_id": claim_id,
                            "evidence_id": evidence.evidence_id,
                            "role": role,
                        },
                    ),
                    uncertainty=UncertaintyMarker(confidence=0.8),
                    attributes={"evidence_role": role},
                ),
                owner="owner-a",
                expected_version=ledger.version,
            )
        ledger = service.append(
            str(ledger.ledger_id),
            _entry("owner-a", project_id, LedgerEntryKind.CONCLUSION, 0.85),
            owner="owner-a",
            expected_version=ledger.version,
        )
        ledger = service.review(
            str(ledger.ledger_id),
            ReviewDecision(
                reviewer="owner-a",
                outcome=ReviewOutcome.APPROVED,
                rationale="Evidence and counterevidence reviewed",
            ),
            owner="owner-a",
            expected_version=ledger.version,
        )
        assert service.validate(str(ledger.ledger_id), "owner-a") == []
        retrieved = service.current(str(ledger.ledger_id), "owner-a")
        assert [item.kind for item in retrieved.entries[:2]] == [
            LedgerEntryKind.SUPPORT,
            LedgerEntryKind.COUNTEREVIDENCE,
        ]
        assert all(
            item.provenance.content_hash == paper.source.content_hash
            for item in retrieved.entries[:2]
        )


@pytest.fixture
def api_client():
    session_local = _database()
    with session_local() as db:
        project_id = _project(db)
    app = FastAPI()
    app.include_router(router)
    app.include_router(project_router)

    def db_override():
        with session_local() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    with TestClient(app) as client:
        yield app, client, project_id


def test_authenticated_api_owner_project_isolation_and_no_cot(api_client):
    app, client, project_id = api_client
    payload = {"project_id": project_id, "title": "API ledger", "description": ""}
    assert client.post("/api/reasoning-ledgers", json=payload).status_code == 401
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "owner-a",
        "auth_type": "owner_session",
    }
    created = client.post("/api/reasoning-ledgers", json=payload)
    assert created.status_code == 201
    ledger = created.json()["ledger"]
    ledger_id = ledger["ledger_id"]
    bad = client.post(
        f"/api/reasoning-ledgers/{ledger_id}/entries",
        json={
            "expected_version": 1,
            "kind": "support",
            "text": "public evidence summary",
            "chain_of_thought": "never store this",
        },
    )
    assert bad.status_code == 422
    appended = client.post(
        f"/api/reasoning-ledgers/{ledger_id}/entries",
        json={
            "expected_version": 1,
            "kind": "counterevidence",
            "text": "Contrary observation",
            "attributes": {"evidence_role": "counterevidence"},
        },
    )
    assert appended.status_code == 201
    assert appended.json()["entries"][-1]["author"] == "owner-a"
    conclusion = client.post(
        f"/api/reasoning-ledgers/{ledger_id}/entries",
        json={
            "expected_version": 2,
            "kind": "conclusion",
            "text": "Governed conclusion",
            "uncertainty": {"confidence": 0.9},
        },
    )
    assert conclusion.status_code == 201
    reviewed = client.post(
        f"/api/reasoning-ledgers/{ledger_id}/reviews",
        json={
            "expected_version": 3,
            "outcome": "deferred",
            "rationale": "Await another source",
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["review_decisions"][-1]["reviewer"] == "owner-a"
    history = client.get(f"/api/reasoning-ledgers/{ledger_id}/history")
    assert history.status_code == 200
    assert history.json()["audit_events"][-1]["event_type"] == "REVIEW_RECORDED"
    stale = client.post(
        f"/api/reasoning-ledgers/{ledger_id}/entries",
        json={"expected_version": 1, "kind": "support", "text": "stale"},
    )
    assert stale.status_code == 409
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "owner-b",
        "auth_type": "owner_session",
    }
    assert client.get(f"/api/reasoning-ledgers/{ledger_id}").status_code == 404
    assert (
        client.get(f"/api/research/projects/{project_id}/reasoning-ledgers").status_code
        == 404
    )
