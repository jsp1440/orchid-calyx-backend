from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.service import extract_and_persist
from app.reasoning_ledger.models import (
    LedgerEntry,
    LedgerEntryKind,
    LedgerProvenance,
    LedgerValidationError,
    ReviewDecision,
    ReviewOutcome,
    UncertaintyMarker,
)
from app.reasoning_ledger.operational_service import (
    CanonicalLiteratureValidator,
    OperationalReasoningLedgerService,
)
from app.reasoning_ledger.persistence import TABLES as LEDGER_TABLES
from app.reasoning_publication.repository import (
    ReasoningPublicationArtifactRow,
    ReasoningPublicationAttemptRow,
)
from app.reasoning_publication.service import ReasoningLedgerPublicationService
from app.research_workspace.models import Project


class RecordingGate:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def publish(self, artifact: dict) -> dict:
        self.calls.append(artifact)
        return {
            "publication_id": 701,
            "graph": {
                "outcome": "PUBLISHED",
                "graph_version_id": 88,
                "mutation_count": 1,
            },
        }


def _session_factory():
    url = os.getenv("CALYX_BRAIN_INTEGRATION_TEST_DATABASE_URL")
    if url:
        engine = create_engine(url)
        with engine.begin() as connection:
            for schema in (
                "research_station",
                "reasoning_ledger",
                "reasoning_publication",
            ):
                connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
    else:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            execution_options={
                "schema_translate_map": {
                    "research_station": None,
                    "reasoning_ledger": None,
                    "reasoning_publication": None,
                }
            },
        )

    Base.metadata.create_all(
        engine,
        tables=[
            Project.__table__,
            *LEDGER_TABLES,
            ReasoningPublicationArtifactRow.__table__,
            ReasoningPublicationAttemptRow.__table__,
        ],
    )
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _provenance(paper, evidence, *, role: str) -> LedgerProvenance:
    return LedgerProvenance(
        source_kind="literature",
        source_id=paper.paper_id,
        literature_record_id=evidence.evidence_id,
        content_hash=paper.source.content_hash,
        retrieved_at=datetime.now(timezone.utc),
        extra={
            "resolution_state": "resolved",
            "evidence_id": evidence.evidence_id,
            "role": role,
        },
    )


@pytest.mark.asyncio
async def test_literature_to_reviewed_publication_is_persistent_and_idempotent(
    tmp_path,
):
    source = tmp_path / "orchid-study.txt"
    source.write_text(
        "Orchid pollination study\n\nResults\n"
        "Masdevallia veitchiana was visited by a pollinating fly.\n",
        encoding="utf-8",
    )
    papers = LiteratureResultRepository(tmp_path / "literature")
    paper = await extract_and_persist(source, papers)
    assert paper.evidence
    evidence = paper.evidence[0]

    session_local = _session_factory()
    with session_local() as db:
        project = Project(
            owner_subject="owner-a",
            title="Orchid evidence acceptance",
            description="",
        )
        db.add(project)
        db.commit()
        project_id = str(project.project_id)

        ledgers = OperationalReasoningLedgerService(
            db,
            literature_validator=CanonicalLiteratureValidator(papers=papers),
        )
        ledger, created = ledgers.create(
            owner="owner-a",
            project_id=project_id,
            title="Pollinator inference",
            description="Governed end-to-end acceptance fixture",
        )
        assert created is True

        for kind, role, confidence in (
            (LedgerEntryKind.SUPPORT, "support", 0.91),
            (LedgerEntryKind.COUNTEREVIDENCE, "counterevidence", 0.65),
            (LedgerEntryKind.CONFLICT, "conflict", 0.7),
        ):
            ledger = ledgers.append(
                str(ledger.ledger_id),
                LedgerEntry(
                    kind=kind,
                    text=f"Reviewable {role} evidence",
                    author="owner-a",
                    tenant_id="owner-a",
                    project_id=project_id,
                    provenance=_provenance(paper, evidence, role=role),
                    uncertainty=UncertaintyMarker(
                        confidence=confidence,
                        rationale="Explicitly retained for human review",
                    ),
                    attributes={"evidence_role": role},
                ),
                owner="owner-a",
                expected_version=ledger.version,
            )

        conflict_id = ledger.entries[-1].entry_id
        ledger = ledgers.resolve_conflict(
            str(ledger.ledger_id),
            conflict_id,
            owner="owner-a",
            expected_version=ledger.version,
            resolution_state="superseded",
            rationale="The directly anchored observation is more specific.",
        )
        assert not ledger.unresolved_conflicts

        attributes = {
            "graph_operation_type": "CREATE_EDGE",
            "subject_canonical_node_id": 11,
            "subject_canonical_key": "Masdevallia veitchiana",
            "object_canonical_node_id": 12,
            "object_canonical_key": "pollinating fly",
            "predicate": "pollinated_by",
            "supporting_evidence_references": [evidence.evidence_id],
            "counterevidence_references": [evidence.evidence_id],
            "literature_evidence_ids": [evidence.evidence_id],
            "source_document_hashes": [paper.source.content_hash],
            "inference_family": "pollinator",
            "inference_rule_id": "calyx.acceptance.pollinator",
            "inference_rule_version": "1.0.0",
            "originating_candidate_ids": ["acceptance-candidate-1"],
            "originating_inference_hash": "b" * 64,
            "provenance_chain": [
                {
                    "paper_id": paper.paper_id,
                    "evidence_id": evidence.evidence_id,
                    "source_hash": paper.source.content_hash,
                }
            ],
            "canonical_assertion_id": 41,
            "canonical_assertion_version": 1,
            "publication_policy_id": "scientific-human-review",
            "publication_policy_version": 1,
        }
        ledger = ledgers.append(
            str(ledger.ledger_id),
            LedgerEntry(
                kind=LedgerEntryKind.CONCLUSION,
                text="The reviewed evidence supports a pollination relationship.",
                author="owner-a",
                tenant_id="owner-a",
                project_id=project_id,
                provenance=_provenance(paper, evidence, role="conclusion"),
                uncertainty=UncertaintyMarker(
                    confidence=0.84,
                    rationale="Support outweighs retained counterevidence.",
                ),
                attributes=attributes,
            ),
            owner="owner-a",
            expected_version=ledger.version,
        )
        ledger = ledgers.review(
            str(ledger.ledger_id),
            ReviewDecision(
                reviewer="owner-a",
                outcome=ReviewOutcome.APPROVED,
                rationale="Current evidence, conflict disposition, and uncertainty reviewed.",
            ),
            owner="owner-a",
            expected_version=ledger.version,
        )
        assert ledgers.validate(str(ledger.ledger_id), "owner-a") == []

        gate = RecordingGate()
        publication = ReasoningLedgerPublicationService(db, gate)
        publication.ledgers = ledgers
        first, first_created = publication.publish(
            str(ledger.ledger_id),
            owner="owner-a",
            expected_version=ledger.version,
            expected_review_content_hash=ledger.review_content_hash,
        )
        second, second_created = publication.publish(
            str(ledger.ledger_id),
            owner="owner-a",
            expected_version=ledger.version,
            expected_review_content_hash=ledger.review_content_hash,
        )

        assert first_created is True
        assert second_created is False
        assert first["publication_status"] == "published"
        assert second["artifact_hash"] == first["artifact_hash"]
        assert first["canonical_graph_ids"] == ["graph_version:88"]
        assert evidence.evidence_id in first["literature_evidence_ids"]
        assert len(gate.calls) == 1
        assert (
            publication.history(str(ledger.ledger_id), "owner-a")[0]["artifact_hash"]
            == first["artifact_hash"]
        )

        changed = ledgers.append(
            str(ledger.ledger_id),
            LedgerEntry(
                kind=LedgerEntryKind.SUPPORT,
                text="Later evidence requires renewed review.",
                author="owner-a",
                tenant_id="owner-a",
                project_id=project_id,
                provenance=_provenance(paper, evidence, role="later_support"),
                uncertainty=UncertaintyMarker(confidence=0.8),
            ),
            owner="owner-a",
            expected_version=ledger.version,
        )
        assert not changed.has_human_approval
        with pytest.raises(LedgerValidationError, match="MISSING_HUMAN_APPROVAL"):
            publication.publish(
                str(changed.ledger_id),
                owner="owner-a",
                expected_version=changed.version,
                expected_review_content_hash=changed.review_content_hash,
            )

        with pytest.raises(Exception, match="ledger not found"):
            ledgers.current(str(ledger.ledger_id), "owner-b")
