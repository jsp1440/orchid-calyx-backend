from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import volunteer_service as routes
from app.security import verify_owner_or_api_key
from runtime.volunteer_service import VolunteerService


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    service = VolunteerService(workspace=tmp_path / "volunteers")
    monkeypatch.setattr(routes, "_service_instance", service)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"subject": "owner-a"}
    return TestClient(app)


def test_nonprofit_volunteer_hours_require_supervisor_verification(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    profile = client.put(
        "/brain/mission-control/volunteers/profiles/vol-1",
        json={
            "volunteer_id": "ignored",
            "display_name": "Volunteer One",
            "roles": ["event support"],
            "skills": ["registration"],
            "contact": {"email": "private@example.org"},
            "privacy_level": "private",
        },
    )
    assert profile.status_code == 200
    assert profile.json()["public_profile_authorized"] is False

    assignment = client.post(
        "/brain/mission-control/volunteers/assignments",
        json={
            "assignment_id": "assign-1",
            "volunteer_id": "vol-1",
            "title": "Nonprofit registration desk",
            "role": "event support",
            "required_skills": ["registration"],
            "supervisor_id": "supervisor-1",
        },
    )
    assert assignment.status_code == 200
    assert assignment.json()["readiness"] == "assignment_ready"
    assert assignment.json()["binding_commitment_authorized"] is False

    logged = client.post(
        "/brain/mission-control/volunteers/hours",
        json={
            "log_id": "hours-1",
            "volunteer_id": "vol-1",
            "assignment_id": "assign-1",
            "service_date": "2026-08-08",
            "hours": 3.5,
            "activity": "Check-in and guest support",
        },
    )
    assert logged.status_code == 200
    assert logged.json()["state"] == "submitted"
    assert logged.json()["autonomous_verification_authorized"] is False

    export_before = client.get(
        "/brain/mission-control/volunteers/profiles/vol-1/export"
    ).json()
    assert export_before["verified_hours"] == 0
    assert export_before["contains_private_contact"] is False
    assert export_before["profile"]["contact"] == {}

    verified = client.post(
        "/brain/mission-control/volunteers/hours/hours-1/verify",
        json={
            "supervisor_id": "supervisor-1",
            "decision": "verified",
            "rationale": "Matched the event shift record.",
        },
    )
    assert verified.status_code == 200
    assert verified.json()["verification"]["disciplinary_action"] is False
    assert client.get(
        "/brain/mission-control/volunteers/profiles/vol-1/export"
    ).json()["verified_hours"] == 3.5


def test_orchid_society_training_certificate_and_recognition_are_private(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.put(
        "/brain/mission-control/volunteers/profiles/orchid-vol-1",
        json={
            "volunteer_id": "orchid-vol-1",
            "display_name": "Orchid Society Volunteer",
            "roles": ["show table", "education"],
            "skills": ["orchid handling"],
            "availability": ["Saturday"],
        },
    )
    training = client.post(
        "/brain/mission-control/volunteers/training",
        json={
            "training_id": "training-1",
            "volunteer_id": "orchid-vol-1",
            "title": "Orchid show-table handling",
            "skills_awarded": ["show table stewardship"],
            "evidence": ["fcoss://training/2026/show-table"],
            "reviewed": True,
        },
    )
    assert training.status_code == 200
    assert training.json()["reviewed"] is True

    certificate = client.post(
        "/brain/mission-control/volunteers/certificates",
        json={
            "certificate_id": "cert-1",
            "volunteer_id": "orchid-vol-1",
            "title": "Orchid Society Service Training",
            "issuer": "Five Cities Orchid Society",
            "evidence_uris": ["fcoss://training/2026/show-table"],
        },
    )
    assert certificate.status_code == 200
    payload = certificate.json()
    assert payload["public_display_authorized"] is False
    assert payload["artifact"]["artifact_id"] == "volunteer-certificate:cert-1"
    assert len(payload["artifact"]["checksum"]) == 64

    recognition = client.post(
        "/brain/mission-control/volunteers/recognition",
        json={
            "recognition_id": "recognition-1",
            "volunteer_id": "orchid-vol-1",
            "category": "education service",
            "citation": "Helped members learn safe orchid handling.",
            "basis": ["cert-1"],
            "approved_by": "board-review",
        },
    )
    assert recognition.status_code == 200
    assert recognition.json()["public_display_authorized"] is False
    assert recognition.json()["binding_commitment_authorized"] is False


def test_conflict_disclosure_requires_human_review_and_is_not_disciplinary(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.put(
        "/brain/mission-control/volunteers/profiles/vol-2",
        json={"volunteer_id": "vol-2", "display_name": "Volunteer Two"},
    )
    response = client.post(
        "/brain/mission-control/volunteers/conflicts",
        json={
            "conflict_id": "conflict-1",
            "volunteer_id": "vol-2",
            "type": "vendor relationship",
            "description": "Volunteer has a relationship with a participating vendor.",
            "mitigation": "Board review before procurement-related assignment.",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["review_state"] == "human_review_required"
    assert payload["disciplinary_decision_authorized"] is False


def test_owner_scope_prevents_cross_owner_profile_access(tmp_path, monkeypatch):
    service = VolunteerService(workspace=tmp_path / "volunteers")
    service.save_profile("owner-a", {"volunteer_id": "same-id", "display_name": "Owner A Person"})
    service.save_profile("owner-b", {"volunteer_id": "same-id", "display_name": "Owner B Person"})
    assert service.get_profile("owner-a", "same-id")["display_name"] == "Owner A Person"
    assert service.get_profile("owner-b", "same-id")["display_name"] == "Owner B Person"


def test_readiness_is_private_and_non_authoritative(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    response = client.get("/brain/mission-control/volunteers/readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["public_personal_data_authorized"] is False
    assert payload["autonomous_disciplinary_decisions_authorized"] is False
    assert payload["binding_commitments_authorized"] is False
