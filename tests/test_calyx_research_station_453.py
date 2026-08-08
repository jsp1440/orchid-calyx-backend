from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.calyx_orchestrator.artifact_registry import (
    ArtifactRegistration,
    ImmutableArtifactRegistry,
)
from app.routers import research_station as api
from app.security import verify_owner_or_api_key
from runtime.literature_acquisition import LiteratureAcquisitionService
from runtime.research_station import ResearchStationService

OWNER = "research-owner"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _service(tmp_path: Path) -> tuple[ResearchStationService, LiteratureAcquisitionService, ImmutableArtifactRegistry]:
    literature = LiteratureAcquisitionService(tmp_path / "literature")
    registry = ImmutableArtifactRegistry()
    service = ResearchStationService(
        tmp_path / "research",
        literature=literature,
        artifact_registry=registry,
    )
    return service, literature, registry


def _project(service: ResearchStationService) -> str:
    result = service.create_project(
        OWNER,
        {
            "project_id": "orchid-pollination-pilot",
            "title": "Orchid pollination pilot",
            "objective": "Evaluate a reproducible evidence workflow for orchid pollination observations.",
            "state": "active",
            "created_at": "2026-08-07T20:00:00-07:00",
        },
    )
    return result["project"]["project_id"]


def test_private_project_questions_protocol_samples_and_datasets(tmp_path: Path):
    service, _, _ = _service(tmp_path)
    project_id = _project(service)
    service.add_question(
        OWNER,
        project_id,
        {"text": "Which floral characters are associated with the observed pollinator?", "rationale": "Pilot question"},
    )
    service.add_protocol(
        OWNER,
        project_id,
        {"title": "Observation protocol", "version": "1.0", "methods": "Record flower morphology and visitor observations without intervention."},
    )
    service.add_sample(
        OWNER,
        project_id,
        {"label": "flower-observation-1", "sample_type": "non-destructive observation", "provenance": {"source": "fixture"}},
    )
    service.add_dataset(
        OWNER,
        project_id,
        {"title": "Pilot observations", "checksum_sha256": _sha("dataset-v1"), "schema_ref": "dataset-schema/v1", "provenance": {"protocol": "1.0"}},
    )
    readiness = service.readiness(OWNER, project_id)
    assert readiness["questions"] == 1
    assert readiness["protocols"] == 1
    assert readiness["samples"] == 1
    assert readiness["datasets"] == 1
    assert readiness["private_by_default"] is True
    assert readiness["public_sharing_enabled"] is False


def test_notebook_revisions_are_immutable_linked_and_hashed(tmp_path: Path):
    service, _, _ = _service(tmp_path)
    project_id = _project(service)
    first = service.revise_notebook(
        OWNER,
        project_id,
        "entry-001",
        {"body": "Initial observation: one floral visitor recorded.", "author": OWNER, "authored_at": "2026-08-07T20:10:00-07:00"},
    )["revision"]
    second = service.revise_notebook(
        OWNER,
        project_id,
        "entry-001",
        {"body": "Follow-up observation: visitor contacted the pollinarium.", "author": OWNER, "authored_at": "2026-08-07T20:20:00-07:00"},
    )["revision"]
    assert first["revision_number"] == 1
    assert second["revision_number"] == 2
    assert second["parent_revision_id"] == first["revision_id"]
    assert first["content_sha256"] != second["content_sha256"]
    manifest = service.manifest(OWNER, project_id)
    assert len(manifest["notebook_revisions"]) == 2
    assert manifest["manifest_sha256"]


def test_literature_and_candidate_knowledge_artifacts_attach_with_provenance(tmp_path: Path):
    service, literature, _ = _service(tmp_path)
    project_id = _project(service)
    run = literature.intake_bytes(
        "paper.txt",
        b"Cattleya labiata is reported with a pollinator association in the study population.",
        source_ref="10.1234/research.station.fixture",
    )
    literature_attachment = service.attach(
        OWNER,
        project_id,
        {"kind": "literature_run", "source_id": run["run_id"], "note": "Primary literature extraction"},
    )["attachment"]
    assert literature_attachment["provenance"]["source_sha256"] == run["source_sha256"]

    handoff_id = "handoff-fixture-001"
    run_dir = literature._run_dir(run["run_id"])
    (run_dir / "candidate_handoffs.json").write_text(
        json.dumps(
            [
                {
                    "handoff_id": handoff_id,
                    "candidate_run_id": "candidate-run-fixture",
                    "candidate_ids": ["candidate-fixture-1"],
                    "confidence": 0.75,
                    "review_required": True,
                    "published": False,
                }
            ]
        ),
        encoding="utf-8",
    )
    candidate_attachment = service.attach(
        OWNER,
        project_id,
        {"kind": "candidate_knowledge", "source_id": "candidate-fixture-1", "literature_run_id": run["run_id"]},
    )["attachment"]
    assert candidate_attachment["provenance"]["candidate_handoff"]["handoff_id"] == handoff_id
    assert candidate_attachment["private"] is True


def test_claim_evidence_decision_and_artifact_registry_attachment(tmp_path: Path):
    service, _, registry = _service(tmp_path)
    project_id = _project(service)
    artifact_id = "research-fixture:artifact-1"
    registry.register(
        ArtifactRegistration(
            artifact_id=artifact_id,
            content=b"fixture evidence",
            media_type="text/plain",
            source_uri="fixture://research/evidence-1",
            producer_assignment_id="test-453",
            evidence_uris=("fixture://research/evidence-1",),
        )
    )
    attachment = service.attach(
        OWNER,
        project_id,
        {"kind": "artifact_registry", "source_id": artifact_id},
    )["attachment"]
    claim = service.add_claim(
        OWNER,
        project_id,
        {
            "statement": "The observed visitor contacted the pollinarium.",
            "confidence": 0.7,
            "state": "needs_review",
            "provenance": {"notebook_entry": "entry-001"},
        },
    )["claim"]
    evidence = service.add_evidence(
        OWNER,
        project_id,
        {"attachment_id": attachment["attachment_id"], "claim_id": claim["claim_id"], "relation": "supports", "note": "Fixture evidence"},
    )["evidence"]
    decision = service.add_decision(
        OWNER,
        project_id,
        {
            "subject_id": claim["claim_id"],
            "decision": "needs_review",
            "rationale": "Independent review is required before project acceptance.",
            "decided_by": OWNER,
            "decided_at": "2026-08-07T21:00:00-07:00",
        },
    )["decision"]
    assert evidence["relation"] == "supports"
    assert decision["decision"] == "needs_review"


def test_tasks_milestones_blockers_drive_reproducibility_state(tmp_path: Path):
    service, _, _ = _service(tmp_path)
    project_id = _project(service)
    service.upsert_task(
        OWNER,
        project_id,
        {
            "title": "Verify specimen identity",
            "state": "blocked",
            "milestone": "pilot-review",
            "blockers": ["Awaiting expert taxonomic review"],
            "updated_at": "2026-08-07T21:10:00-07:00",
        },
    )
    readiness = service.readiness(OWNER, project_id)
    assert readiness["decision"] == "BLOCKED"
    assert len(readiness["blockers"]) == 1
    manifest = service.manifest(OWNER, project_id)
    assert manifest["reproducibility_state"] == "blocked"
    assert manifest["file_checksums"]


def test_protected_project_and_readiness_api(tmp_path: Path, monkeypatch):
    service, _, _ = _service(tmp_path)
    monkeypatch.setattr(api, "_service", lambda: service)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": OWNER, "auth_type": "test"}
    client = TestClient(app)

    created = client.post(
        "/brain/mission-control/research/projects",
        json={
            "project_id": "api-project",
            "title": "API project",
            "objective": "Exercise protected Research Station routes.",
            "state": "active",
            "created_at": "2026-08-07T21:20:00-07:00",
        },
    )
    assert created.status_code == 200
    notebook = client.post(
        "/brain/mission-control/research/projects/api-project/notebook/entry-a/revisions",
        json={"body": "Recorded a reproducible fixture observation.", "author": OWNER, "authored_at": "2026-08-07T21:21:00-07:00"},
    )
    assert notebook.status_code == 200
    readiness = client.get("/brain/mission-control/research/projects/api-project/readiness")
    assert readiness.status_code == 200
    payload = readiness.json()
    assert payload["notebook_revisions"] == 1
    assert payload["private_by_default"] is True
    assert payload["scientific_publication_authorized"] is False
    assert payload["live_laboratory_control"] is False
    assert payload["production_deployment_authorized"] is False
    assert payload["knowledge_graph_mutation_authorized"] is False
