from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.brain_mission.api import router as mission_router
from app.brain_mission.routes import ExistingBrainMissionAdapter
from app.brain_mission.service import (
    BrainMissionService,
    MemoryMissionRepository,
    MissionComponents,
)
from app.evidence_retrieval.routes import ENGINE
from app.security import verify_owner_or_api_key


def _complete_components() -> MissionComponents:
    return MissionComponents(
        retrieve=lambda context: {"results": [{"result_id": "one"}]},
        aggregate=lambda context: {
            "supporting_evidence": [{"candidate_id": 1}],
            "contradicting_evidence": [],
        },
        analyze=lambda context: {
            "contradicting_evidence": [],
            "missing_evidence": ["mycorrhiza"],
        },
        interpret=lambda context: {
            "confidence": 0.9,
            "conclusions": [{"text": "Provisional conclusion", "claim_ids": ["1"]}],
        },
        create_ledger=lambda context: {"ledger_id": "ledger-1", "version": 1},
        validate=lambda context: {"valid": True, "blockers": []},
        review_state=lambda context: {"status": "HUMAN_REVIEW_REQUIRED"},
        publication_eligibility=lambda context: {"eligible": True, "blockers": []},
    )


def test_mission_never_becomes_publication_eligible_without_human_review():
    service = BrainMissionService(_complete_components(), MemoryMissionRepository())
    mission = service.start(
        question="What is known about Laelia anceps pollination?",
        tenant_id="owner-a",
        project_id="project-a",
        actor="owner-a",
    )

    assert mission["state"] == "AWAITING_HUMAN_REVIEW"
    assert mission["review_status"] == "HUMAN_REVIEW_REQUIRED"
    assert mission["validation"]["valid"] is True
    assert mission["publication_eligibility"]["eligible"] is False
    assert mission["publication_eligibility"]["automatic_publication"] is False


def test_mission_fails_closed_when_adapter_is_unavailable():
    service = BrainMissionService(MissionComponents(), MemoryMissionRepository())
    mission = service.start(
        question="What evidence exists?",
        tenant_id="owner-a",
        project_id="project-a",
        actor="owner-a",
    )

    assert mission["state"] == "BLOCKED"
    assert mission["partial"] is True
    assert mission["blockers"][0]["code"] == "RETRIEVE_COMPONENT_UNAVAILABLE"
    assert mission["publication_eligibility"]["eligible"] is False


def test_canonical_source_reconstruction_requires_exact_active_index_identity():
    original_documents = deepcopy(ENGINE.repo.documents)
    try:
        ENGINE.repo.documents[:] = [
            {
                "index_document_id": 11,
                "source_object_type": "CLAIM",
                "source_object_id": 101,
                "revision_id": 202,
                "extraction_run_id": 303,
                "anchors": (404,),
                "content_hash": "abc123",
                "active": True,
                "metadata": {
                    "candidate_facts": [
                        {
                            "kind": "ECOLOGICAL_RELATIONSHIP",
                            "subject": "Laelia anceps",
                            "predicate": "pollinated_by",
                            "object_value": "Bombus sp.",
                            "confidence": 0.8,
                        }
                    ],
                    "source_class": "PRIMARY",
                    "directness": "DIRECT_OBSERVATION",
                },
            }
        ]
        result = {
            "result_id": "result-1",
            "object_type": "CLAIM",
            "authorized_excerpt": "Laelia anceps is pollinated by Bombus sp.",
            "fused_score": 0.82,
            "display_policy": "FULL_TEXT_ALLOWED",
            "citation": {
                "revision_id": 202,
                "source_anchor_ids": [404],
                "locator": {"page": 7, "char_start": 12, "char_end": 54},
            },
        }

        evidence = ExistingBrainMissionAdapter._canonical_source(result)
        assert evidence.source_object_id == 101
        assert evidence.revision_id == 202
        assert evidence.extraction_run_id == 303
        assert evidence.source_anchors[0].anchor_id == 404
        assert evidence.metadata["content_hash"] == "abc123"

        ENGINE.repo.documents.append({**ENGINE.repo.documents[0], "index_document_id": 12})
        with pytest.raises(ValueError, match="AMBIGUOUS_CANONICAL_SOURCE_IDENTITY"):
            ExistingBrainMissionAdapter._canonical_source(result)
    finally:
        ENGINE.repo.documents[:] = original_documents


def test_mission_api_derives_tenant_from_auth_and_hides_cross_tenant_status(monkeypatch):
    repository = MemoryMissionRepository()
    service = BrainMissionService(_complete_components(), repository)
    monkeypatch.setattr("app.brain_mission.api.SERVICE", service)

    app = FastAPI()
    actor = {"actor": "owner-a", "auth_type": "owner_session"}
    app.dependency_overrides[verify_owner_or_api_key] = lambda: actor
    app.include_router(mission_router, prefix="/brain")
    client = TestClient(app)

    created = client.post(
        "/brain/missions",
        json={
            "question": "What is known about Laelia anceps?",
            "project_id": "project-a",
        },
    )
    assert created.status_code == 201
    mission = created.json()
    assert mission["tenant_id"] == "owner-a"

    actor["actor"] = "owner-b"
    hidden = client.get(f"/brain/missions/{mission['mission_id']}")
    assert hidden.status_code == 404
    assert hidden.json()["detail"]["code"] == "MISSION_NOT_FOUND"


def test_brain_router_mounts_scientific_mission_routes():
    from app.brain.routes import router as brain_router

    paths = {route.path for route in brain_router.routes}
    assert "/brain/missions" in paths
    assert "/brain/missions/{mission_id}" in paths
