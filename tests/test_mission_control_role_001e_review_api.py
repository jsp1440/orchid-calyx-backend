from fastapi.testclient import TestClient

from app.main import app
from app.mission_control_access import AccessPrincipal, MissionControlRole
from app.review_api.dependencies import authenticated_principal, review_service_dependency
from app.review_tasks.models import ReviewTaskInput
from app.review_tasks.repository import MemoryReviewTaskRepository
from app.review_tasks.service import GovernedReviewTaskService


client = TestClient(app)
service = GovernedReviewTaskService(repository=MemoryReviewTaskRepository())


def _principal(*, expert: bool = False) -> AccessPrincipal:
    return AccessPrincipal(
        principal_id="reviewer-1",
        roles=(MissionControlRole.PUBLIC, MissionControlRole.EXPERT if expert else MissionControlRole.VOLUNTEER),
        qualifications=(
            "qualified.expert-reviewer" if expert else "qualified.science-reviewer",
        ),
        authenticated=True,
    )


def setup_function() -> None:
    service.repository.tasks.clear()
    service.repository.decisions.clear()
    service.repository.events.clear()
    app.dependency_overrides[review_service_dependency] = lambda: service


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_anonymous_queue_requires_authentication() -> None:
    response = client.get("/api/mission-control/review/queue")
    assert response.status_code == 401


def test_capabilities_resolve_for_authenticated_reviewer() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: _principal()
    response = client.get("/api/mission-control/review/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert payload["principal_id"] == "reviewer-1"
    assert "review.science" in payload["effective_capabilities"]


def test_queue_and_task_detail_are_capability_filtered() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: _principal()
    task = service.create(
        ReviewTaskInput(
            orchestration_id="001e-human",
            review_type="HUMAN_REVIEW_REQUIRED",
            risk_class="2",
            routing_outcome="HUMAN_REVIEW_REQUIRED",
            required_capability="review.science",
        )
    )
    response = client.get("/api/mission-control/review/queue")
    assert response.status_code == 200
    assert any(item["task_id"] == task["task_id"] for item in response.json()["tasks"])

    detail = client.get(f"/api/mission-control/review/tasks/{task['task_id']}")
    assert detail.status_code == 200
    assert detail.json()["task_id"] == task["task_id"]


def test_volunteer_cannot_read_expert_task() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: _principal()
    task = service.create(
        ReviewTaskInput(
            orchestration_id="001e-expert",
            review_type="EXPERT_REVIEW_REQUIRED",
            risk_class="3",
            routing_outcome="EXPERT_REVIEW_REQUIRED",
            required_capability="review.expert",
        )
    )
    response = client.get(f"/api/mission-control/review/tasks/{task['task_id']}")
    assert response.status_code == 403


def test_reserve_and_decide_bind_authenticated_principal() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: _principal()
    task = service.create(
        ReviewTaskInput(
            orchestration_id="001e-decision",
            review_type="HUMAN_REVIEW_REQUIRED",
            risk_class="2",
            routing_outcome="HUMAN_REVIEW_REQUIRED",
            required_capability="review.science",
        )
    )
    reserve = client.post(f"/api/mission-control/review/tasks/{task['task_id']}/reserve")
    assert reserve.status_code == 200
    assert reserve.json()["assigned_to"] == "reviewer-1"

    decision = client.post(
        f"/api/mission-control/review/tasks/{task['task_id']}/decisions",
        json={"decision": "ACCEPT", "comment": "Evidence supports the candidate."},
    )
    assert decision.status_code == 200
    assert decision.json()["authoritative_decision"] == "ACCEPT"
