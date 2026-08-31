import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.specialist_service import (
    MissionSpec,
    SpecialistMissionRepository,
    plan_activation,
)
from app.database import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def create_publication_mission(db: Session):
    return SpecialistMissionRepository(db).create(
        owner="owner",
        spec=MissionSpec(
            idempotency_key="phalaenopsis-pilot-v1",
            kind="trait-analysis",
            question="Which traits distinguish cool- and warm-growing Phalaenopsis?",
            scientific=True,
            publication_candidate=True,
            max_specialists=4,
            token_budget=1000,
            cost_budget_microusd=10000,
        ),
    )


def test_activation_is_minimum_sufficient_and_review_gated():
    activation = plan_activation(
        "taxonomy",
        scientific=True,
        publication_candidate=False,
        max_specialists=4,
    )
    assert activation["specialists"] == ["taxonomist-botanist", "data-steward"]
    assert activation["reviewer"] == "scientific-reviewer"
    assert activation["automatic_publication"] is False


def test_create_is_idempotent_but_rejects_key_reuse(db):
    repository = SpecialistMissionRepository(db)
    spec = MissionSpec(
        idempotency_key="taxonomy-0001",
        kind="taxonomy",
        question="Resolve this name.",
    )
    first = repository.create(owner="owner", spec=spec)
    second = repository.create(owner="owner", spec=spec)
    assert first.mission_id == second.mission_id

    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_REUSED"):
        repository.create(
            owner="owner",
            spec=MissionSpec(
                idempotency_key="taxonomy-0001",
                kind="taxonomy",
                question="A different request.",
            ),
        )


def test_artifact_requires_activation_and_provenance_and_tracks_cost(db):
    mission = create_publication_mission(db)
    repository = SpecialistMissionRepository(db)

    with pytest.raises(ValueError, match="SPECIALIST_NOT_ACTIVATED"):
        repository.add_artifact(
            owner="owner",
            mission_id=mission.mission_id,
            artifact_key="design-1",
            specialist_id="experience-designer",
            artifact_type="design",
            content={"result": "not routed"},
            provenance={"source": "test"},
        )
    with pytest.raises(ValueError, match="PROVENANCE_REQUIRED"):
        repository.add_artifact(
            owner="owner",
            mission_id=mission.mission_id,
            artifact_key="evidence-1",
            specialist_id="evidence-scientist",
            artifact_type="evidence-packet",
            content={"claims": []},
            provenance={},
        )

    artifact = repository.add_artifact(
        owner="owner",
        mission_id=mission.mission_id,
        artifact_key="evidence-1",
        specialist_id="evidence-scientist",
        artifact_type="evidence-packet",
        content={"claims": ["cool-growing species tend to occur at higher elevation"]},
        provenance={"source_revision_ids": [1]},
        tokens_used=250,
        cost_microusd=4000,
    )
    assert artifact.artifact_id
    snapshot = repository.snapshot(owner="owner", mission_id=mission.mission_id)
    assert snapshot["budget"]["tokens"] == {"used": 250, "limit": 1000}
    assert snapshot["budget"]["cost_microusd"] == {"used": 4000, "limit": 10000}


def test_budget_excess_fails_closed_without_charging_mission(db):
    mission = create_publication_mission(db)
    repository = SpecialistMissionRepository(db)
    with pytest.raises(ValueError, match="TOKEN_BUDGET_EXCEEDED"):
        repository.add_artifact(
            owner="owner",
            mission_id=mission.mission_id,
            artifact_key="too-large",
            specialist_id="evidence-scientist",
            artifact_type="evidence-packet",
            content={"claims": []},
            provenance={"source": "test"},
            tokens_used=1001,
        )
    snapshot = repository.snapshot(owner="owner", mission_id=mission.mission_id)
    assert snapshot["budget"]["tokens"]["used"] == 0
    assert snapshot["artifact_count"] == 0


def test_publication_requires_independent_review_and_owner_approval(db):
    mission = create_publication_mission(db)
    repository = SpecialistMissionRepository(db)
    assert repository.snapshot(owner="owner", mission_id=mission.mission_id)["promotion"]["eligible"] is False

    with pytest.raises(ValueError, match="INDEPENDENT_SCIENTIFIC_REVIEWER_REQUIRED"):
        repository.record_review(
            owner="owner",
            mission_id=mission.mission_id,
            review_key="review-1",
            reviewer_id="evidence-scientist",
            passed=True,
            findings={},
            provenance={"reviewed_artifact_keys": ["evidence-1"]},
        )

    repository.record_review(
        owner="owner",
        mission_id=mission.mission_id,
        review_key="review-1",
        reviewer_id="scientific-reviewer",
        passed=True,
        findings={"blockers": []},
        provenance={"reviewed_artifact_keys": ["evidence-1"]},
    )
    assert repository.snapshot(owner="owner", mission_id=mission.mission_id)["promotion"]["eligible"] is False

    with pytest.raises(PermissionError, match="OWNER_APPROVAL_ACTOR_MISMATCH"):
        repository.record_approval(
            owner="owner",
            mission_id=mission.mission_id,
            approval_key="approval-1",
            actor="worker",
            decision="approved",
            note=None,
        )

    repository.record_approval(
        owner="owner",
        mission_id=mission.mission_id,
        approval_key="approval-1",
        actor="owner",
        decision="approved",
        note="Reviewed for promotion.",
    )
    promotion = repository.snapshot(owner="owner", mission_id=mission.mission_id)["promotion"]
    assert promotion == {
        "eligible": True,
        "automatic_publication": False,
        "review_passed": True,
        "owner_approved": True,
    }


def test_owner_isolation_hides_missions(db):
    mission = create_publication_mission(db)
    with pytest.raises(LookupError, match="SPECIALIST_MISSION_NOT_FOUND"):
        SpecialistMissionRepository(db).snapshot(owner="different-owner", mission_id=mission.mission_id)
