from fastapi.testclient import TestClient

from app.main import app
from app.mission_control_access import AccessPrincipal, MissionControlRole
from app.review_api.dependencies import authenticated_principal

client = TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def _principal(role: MissionControlRole) -> AccessPrincipal:
    return AccessPrincipal(principal_id=f"001e-{role.value}", roles=(role,), authenticated=True)


def test_frontend_contract_populates_required_intelligence_center_fields() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: _principal(MissionControlRole.PUBLIC)
    response = client.get("/api/executive/frontend-contract")
    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == "MISSION-CONTROL-TELEMETRY-001E"
    required = {
        "id", "title", "category_badges", "status", "narrative_summary",
        "next_action", "metric", "target", "schedule", "freshness",
        "approval_state", "calyx_context", "navigation",
    }
    assert payload["panels"]
    for panel in payload["panels"]:
        assert required.issubset(panel)
        assert panel["status"] != "unknown"
        assert panel["freshness"] != "unknown"
        assert panel["calyx_context"]["recommendation_signal"] != "unknown"


def test_frontend_contract_covers_expected_navigation_without_redesign() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: _principal(MissionControlRole.PUBLIC)
    payload = client.get("/api/executive/frontend-contract").json()
    assert payload["readiness"]["frontend_redesign_required"] is False
    assert payload["readiness"]["direct_field_population_supported"] is True
    assert payload["readiness"]["missing_panel_ids"] == []
    assert payload["navigation_order"] == [
        "recommendations", "health", "completeness", "integrations",
        "inaturalist", "gbif", "world_plants_hassler", "eol_traitbank",
        "globi", "pollinator_datasets",
    ]


def test_public_contract_omits_operational_controls() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: _principal(MissionControlRole.PUBLIC)
    payload = client.get("/api/executive/frontend-contract").json()
    assert payload["governance"]["operational_details_included"] is False
    for panel in payload["panels"]:
        assert panel.get("allowed_actions", {}) == {}


def test_administrator_contract_preserves_governance_boundaries() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: _principal(MissionControlRole.ADMINISTRATOR)
    payload = client.get("/api/executive/frontend-contract").json()
    assert payload["governance"]["operational_details_included"] is True
    assert payload["governance"]["does_not_grant_scientific_authority"] is True
    assert payload["governance"]["does_not_publish"] is True


def test_frontend_contract_requires_authentication() -> None:
    assert client.get("/api/executive/frontend-contract").status_code == 401
