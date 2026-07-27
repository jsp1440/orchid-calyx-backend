from fastapi.testclient import TestClient

from app.main import app
from app.mission_control_access import AccessPrincipal, MissionControlRole
from app.review_api.dependencies import authenticated_principal, review_service_dependency
from app.review_tasks.repository import MemoryReviewTaskRepository
from app.review_tasks.service import GovernedReviewTaskService

client = TestClient(app)
service = GovernedReviewTaskService(repository=MemoryReviewTaskRepository())


def setup_function() -> None:
    service.repository.tasks.clear()
    service.repository.decisions.clear()
    service.repository.events.clear()
    app.dependency_overrides[review_service_dependency] = lambda: service


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_release_readiness_requires_authentication() -> None:
    response = client.get("/api/mission-control/release-readiness")
    assert response.status_code == 401


def test_release_readiness_preserves_administrator_science_separation() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: AccessPrincipal(
        principal_id="admin-1",
        roles=(MissionControlRole.ADMINISTRATOR,),
        authenticated=True,
    )
    response = client.get("/api/mission-control/release-readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["controls"]["administrator_science_separation"] is True
    assert payload["frontend_contract"]["actions"]["publish"] is False
    assert payload["governance"]["does_not_publish"] is True


def test_memory_persistence_is_reported_as_release_blocker() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: AccessPrincipal(
        principal_id="expert-1",
        roles=(MissionControlRole.EXPERT,),
        qualifications=("qualified.expert-reviewer",),
        authenticated=True,
    )
    response = client.get("/api/mission-control/release-readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["release_ready"] is False
    assert payload["controls"]["review_persistence_configured"] is False
    assert "Durable review persistence is not configured for this runtime." in payload["blockers"]


def test_required_dependency_slices_are_declared() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: AccessPrincipal(
        principal_id="reviewer-1",
        roles=(MissionControlRole.VOLUNTEER,),
        qualifications=("qualified.science-reviewer",),
        authenticated=True,
    )
    response = client.get("/api/mission-control/release-readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["required_slices"] == [
        "MISSION-CONTROL-ROLE-001A",
        "MISSION-CONTROL-ROLE-001B",
        "MISSION-CONTROL-ROLE-001C",
        "MISSION-CONTROL-ROLE-001D",
        "MISSION-CONTROL-ROLE-001E",
        "MISSION-CONTROL-ROLE-001F",
        "MISSION-CONTROL-ROLE-001G",
        "MISSION-CONTROL-ROLE-001H",
        "MISSION-CONTROL-ROLE-001I",
    ]
