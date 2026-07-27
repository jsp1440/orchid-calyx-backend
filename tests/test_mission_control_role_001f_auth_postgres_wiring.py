from fastapi.testclient import TestClient

from app.main import app
from app.mission_control_access import AccessPrincipal, MissionControlRole
from app.review_api.dependencies import authenticated_principal, review_service_dependency
from app.review_tasks.models import ReviewTaskInput
from app.review_tasks.service import GovernedReviewTaskService

client = TestClient(app)


def _principal() -> AccessPrincipal:
    return AccessPrincipal(
        principal_id="reviewer-001f",
        roles=(MissionControlRole.VOLUNTEER,),
        qualifications=("qualified.science-reviewer",),
        authenticated=True,
    )


def test_review_api_rejects_unauthenticated_requests() -> None:
    response = client.get("/api/mission-control/review/queue")
    assert response.status_code == 401


def test_review_api_requires_database_when_not_overridden(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MISSION_CONTROL_REVIEW_ALLOW_MEMORY", raising=False)
    app.dependency_overrides[authenticated_principal] = _principal
    try:
        response = client.get("/api/mission-control/review/queue")
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "REVIEW_DATABASE_NOT_CONFIGURED"
    finally:
        app.dependency_overrides.clear()


def test_review_api_uses_injected_persistent_service_contract() -> None:
    service = GovernedReviewTaskService()
    task = service.create(
        ReviewTaskInput(
            orchestration_id="001f-human",
            review_type="HUMAN_REVIEW_REQUIRED",
            risk_class="2",
            routing_outcome="HUMAN_REVIEW_REQUIRED",
            required_capability="review.science",
        )
    )
    app.dependency_overrides[authenticated_principal] = _principal
    app.dependency_overrides[review_service_dependency] = lambda: service
    try:
        response = client.get("/api/mission-control/review/queue")
        assert response.status_code == 200
        assert any(item["task_id"] == task["task_id"] for item in response.json()["tasks"])
    finally:
        app.dependency_overrides.clear()


def test_administrator_authentication_does_not_imply_scientific_review() -> None:
    principal = AccessPrincipal(
        principal_id="owner",
        roles=(MissionControlRole.ADMINISTRATOR,),
        authenticated=True,
    )
    service = GovernedReviewTaskService()
    service.create(
        ReviewTaskInput(
            orchestration_id="001f-expert",
            review_type="EXPERT_REVIEW_REQUIRED",
            risk_class="3",
            routing_outcome="EXPERT_REVIEW_REQUIRED",
            required_capability="review.expert",
        )
    )
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.dependency_overrides[review_service_dependency] = lambda: service
    try:
        response = client.get("/api/mission-control/review/queue")
        assert response.status_code == 200
        assert response.json()["tasks"] == []
    finally:
        app.dependency_overrides.clear()
