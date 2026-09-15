from fastapi.testclient import TestClient

from app.main import app
from app.mission_control_access import AccessPrincipal, MissionControlRole
from app.review_api.dependencies import authenticated_principal

client = TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_executive_state_returns_truthful_payload_for_authenticated_public_user() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: AccessPrincipal(
        principal_id="public-telemetry-user",
        roles=(MissionControlRole.PUBLIC,),
        authenticated=True,
    )
    response = client.get("/api/executive/state")
    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == "MISSION-CONTROL-TELEMETRY-001A"
    assert payload["governance"]["public_safe"] is True
    assert payload["governance"]["operational_details_included"] is False
    assert "generated_at" in payload
    assert "partial_failures" in payload
    assert "subsystems" in payload


def test_administrator_receives_operational_details_without_scientific_authority() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: AccessPrincipal(
        principal_id="telemetry-admin",
        roles=(MissionControlRole.ADMINISTRATOR,),
        authenticated=True,
    )
    response = client.get("/api/executive/state")
    assert response.status_code == 200
    payload = response.json()
    assert payload["governance"]["operational_details_included"] is True
    assert payload["governance"]["does_not_grant_scientific_authority"] is True
    assert "activation_matrix" in payload


def test_executive_state_requires_authentication() -> None:
    response = client.get("/api/executive/state")
    assert response.status_code == 401

def test_executive_state_exposes_truthful_scientific_readiness() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: AccessPrincipal(
        principal_id="scientific-readiness-user",
        roles=(MissionControlRole.PUBLIC,),
        authenticated=True,
    )
    payload = client.get("/api/executive/state").json()
    readiness = payload["scientific_readiness"]

    assert readiness["contract_version"] == "sci-obs-readiness-v1"
    assert set(readiness["dimensions"]) == {
        "engineering_health",
        "integration_health",
        "data_readiness",
        "scientific_evidence_readiness",
        "product_workflow_readiness",
        "freshness",
    }
    for dimension in readiness["dimensions"].values():
        assert dimension["state"] == "unavailable"
        assert dimension["numerator"] is None
        assert dimension["denominator"] is None
        assert dimension["score"] is None
        assert dimension["missing_requirements"]
    assert readiness["publication_authority"] is False
    assert readiness["human_approval_required"] is True
    assert all(
        component["state"] == "unavailable" and component["present"] is None
        for component in readiness["component_coverage"].values()
    )
