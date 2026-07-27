from fastapi.testclient import TestClient

from app.main import app
from app.mission_control_access import AccessPrincipal, MissionControlRole
from app.review_api.dependencies import authenticated_principal, review_service_dependency
from app.review_tasks.models import ReviewTaskInput
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


def _task(*, embargoed: bool = False) -> dict:
    return service.create(
        ReviewTaskInput(
            orchestration_id="001i-task-embargoed" if embargoed else "001i-task",
            review_type="HUMAN_REVIEW_REQUIRED",
            risk_class="2",
            routing_outcome="HUMAN_REVIEW_REQUIRED",
            required_capability="review.science",
            embargoed=embargoed,
        )
    )


def _importer(*, include_science: bool = True) -> AccessPrincipal:
    capabilities = ["review.external.import"]
    if include_science:
        capabilities.append("review.science")
    return AccessPrincipal(
        principal_id="importer-1",
        roles=(MissionControlRole.ADMINISTRATOR,),
        direct_capabilities=tuple(capabilities),
        authenticated=True,
    )


def test_workforce_import_requires_explicit_import_capability() -> None:
    task = _task()
    app.dependency_overrides[authenticated_principal] = lambda: AccessPrincipal(
        principal_id="admin-only",
        roles=(MissionControlRole.ADMINISTRATOR,),
        authenticated=True,
    )
    response = client.post(
        "/api/mission-control/review/workforce/import",
        json={
            "source": "orchid-zoo",
            "batch_id": "batch-1",
            "results": [{"task_id": task["task_id"], "decision": "ACCEPT"}],
        },
    )
    assert response.status_code == 403


def test_workforce_import_reconciles_valid_result() -> None:
    task = _task()
    app.dependency_overrides[authenticated_principal] = lambda: _importer()
    response = client.post(
        "/api/mission-control/review/workforce/import",
        json={
            "source": "orchid-zoo",
            "batch_id": "batch-2",
            "results": [
                {
                    "task_id": task["task_id"],
                    "external_result_id": "result-1",
                    "reviewer_id": "volunteer-42",
                    "decision": "ACCEPT",
                    "comment": "Validated externally.",
                }
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted_count"] == 1
    assert payload["rejected_count"] == 0
    assert payload["accepted"][0]["authoritative_decision"] == "ACCEPT"
    history = service.repository.history(task["task_id"])
    assert any(event["event_type"] == "WORKFORCE_RESULT_IMPORTED" for event in history)


def test_workforce_import_rejects_embargoed_and_duplicate_results() -> None:
    visible = _task()
    embargoed = _task(embargoed=True)
    app.dependency_overrides[authenticated_principal] = lambda: _importer()
    response = client.post(
        "/api/mission-control/review/workforce/import",
        json={
            "source": "external-classroom",
            "batch_id": "batch-3",
            "dry_run": True,
            "results": [
                {"task_id": embargoed["task_id"], "external_result_id": "x1", "decision": "ACCEPT"},
                {"task_id": visible["task_id"], "external_result_id": "x2", "decision": "DEFER"},
                {"task_id": visible["task_id"], "external_result_id": "x2", "decision": "DEFER"},
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted_count"] == 1
    assert {item["code"] for item in payload["rejected"]} == {"EMBARGOED_TASK", "DUPLICATE_RESULT"}


def test_frontend_contract_is_capability_driven() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: _importer(include_science=False)
    response = client.get("/api/mission-control/review/frontend-contract")
    assert response.status_code == 200
    payload = response.json()
    assert payload["navigation"]["workforce_import"] is True
    assert payload["navigation"]["review_queue"] is False
    assert payload["actions"]["publish"] is False
    assert payload["governance"]["administrator_role_does_not_imply_scientific_authority"] is True
