from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.mission_control_access import AccessPrincipal, MissionControlRole
from app.review_api.dependencies import authenticated_principal, review_service_dependency
from app.review_tasks.models import ReviewTaskInput
from app.review_tasks.operations import ReviewQueueOperations
from app.review_tasks.repository import MemoryReviewTaskRepository
from app.review_tasks.service import GovernedReviewTaskService

client = TestClient(app)
service = GovernedReviewTaskService(repository=MemoryReviewTaskRepository())


def _principal(*capabilities: str) -> AccessPrincipal:
    return AccessPrincipal(
        principal_id="operator-1",
        roles=(MissionControlRole.ADMINISTRATOR,),
        direct_capabilities=tuple(capabilities),
        authenticated=True,
    )


def setup_function() -> None:
    service.repository.tasks.clear()
    service.repository.decisions.clear()
    service.repository.events.clear()
    app.dependency_overrides[review_service_dependency] = lambda: service


def teardown_function() -> None:
    app.dependency_overrides.clear()


def _task(*, orchestration_id: str = "001h-task", embargoed: bool = False) -> dict:
    return service.create(
        ReviewTaskInput(
            orchestration_id=orchestration_id,
            review_type="HUMAN_REVIEW_REQUIRED",
            risk_class="2",
            routing_outcome="HUMAN_REVIEW_REQUIRED",
            required_capability="review.science",
            priority=90,
            embargoed=embargoed,
        )
    )


def test_reservation_sets_expiration_and_worker_expires_it() -> None:
    reviewer = AccessPrincipal(
        principal_id="reviewer-1",
        roles=(MissionControlRole.VOLUNTEER,),
        qualifications=("qualified.science-reviewer",),
        authenticated=True,
    )
    task = _task()
    reserved = service.reserve_for_principal(task["task_id"], reviewer, reservation_hours=1)
    assert reserved["reservation_expires_at"]

    reserved["reservation_expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    service.repository.save(reserved)
    expired = ReviewQueueOperations(service).expire_reservations()
    assert len(expired) == 1
    assert expired[0]["state"] == "EXPIRED"
    assert expired[0]["assigned_to"] is None


def test_metrics_endpoint_requires_operations_capability() -> None:
    _task()
    app.dependency_overrides[authenticated_principal] = lambda: _principal()
    denied = client.get("/api/mission-control/review/queue/metrics")
    assert denied.status_code == 403

    app.dependency_overrides[authenticated_principal] = lambda: _principal(
        "mission_control.view.operations"
    )
    allowed = client.get("/api/mission-control/review/queue/metrics")
    assert allowed.status_code == 200
    assert allowed.json()["high_priority_open"] == 1


def test_expiration_endpoint_requires_assignment_management() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: _principal(
        "review.assignments.manage"
    )
    response = client.post(
        "/api/mission-control/review/reservations/expire",
        json={"dry_run": True},
    )
    assert response.status_code == 200
    assert response.json()["dry_run"] is True


def test_workforce_export_filters_embargoed_tasks() -> None:
    visible = _task()
    _task(orchestration_id="001h-embargoed", embargoed=True)
    app.dependency_overrides[authenticated_principal] = lambda: _principal(
        "review.external.export", "review.science"
    )
    response = client.get("/api/mission-control/review/workforce/export")
    assert response.status_code == 200
    payload = response.json()
    assert payload["allowed"] is True
    assert len(payload["tasks"]) == 1
    assert payload["tasks"][0]["task_id"] == visible["task_id"]
