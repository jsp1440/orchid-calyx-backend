from fastapi.testclient import TestClient

from app.main import app
from app.mission_control_access import AccessPrincipal, MissionControlRole
from app.review_api.dependencies import authenticated_principal
from app.executive_telemetry.intelligence import build_dependency_intelligence

client = TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_dependency_intelligence_reports_trait_and_pollinator_impacts() -> None:
    result = build_dependency_intelligence(
        subsystems=[],
        harvesters=[
            {
                "source_id": "eol_traitbank",
                "status": "warning",
                "completion_percentage": 42,
            },
            {"source_id": "globi", "status": "unavailable"},
            {"source_id": "pollinator_datasets", "status": "unavailable"},
        ],
    )
    ids = {item["id"] for item in result["dependencies"]}
    assert "trait-coverage-culture-sheets" in ids
    assert "pollinator-coverage-ecological-completeness" in ids
    recommendation = result["recommendations"][0]
    assert recommendation["reason"]
    assert recommendation["confidence"] > 0
    assert recommendation["expected_scientific_gain"]


def test_intelligence_endpoint_is_authenticated_and_governed() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: AccessPrincipal(
        principal_id="telemetry-admin",
        roles=(MissionControlRole.ADMINISTRATOR,),
        authenticated=True,
    )
    response = client.get("/api/executive/intelligence")
    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == "MISSION-CONTROL-TELEMETRY-001D"
    assert "recommendations" in payload
    assert "dependencies" in payload
    assert payload["governance"]["does_not_publish"] is True
    assert payload["governance"]["does_not_grant_scientific_authority"] is True


def test_intelligence_endpoint_requires_authentication() -> None:
    response = client.get("/api/executive/intelligence")
    assert response.status_code == 401
