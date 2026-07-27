from fastapi.testclient import TestClient

from app.executive_telemetry.release_readiness import build_release_readiness
from app.main import app
from app.mission_control_access import AccessPrincipal, MissionControlRole
from app.review_api.dependencies import authenticated_principal

client = TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def _principal(role: MissionControlRole) -> AccessPrincipal:
    return AccessPrincipal(principal_id=f"001f-{role.value}", roles=(role,), authenticated=True)


def test_release_readiness_endpoint_verifies_all_contracts() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: _principal(MissionControlRole.PUBLIC)
    response = client.get("/api/executive/release-readiness")
    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == "MISSION-CONTROL-TELEMETRY-001F"
    assert payload["release_ready"] is True
    assert payload["deployment_state"] == "ready"
    assert payload["blocking_checks"] == []
    assert all(check["status"] == "passed" for check in payload["checks"])


def test_release_readiness_manifest_covers_production_smoke_endpoints() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: _principal(MissionControlRole.PUBLIC)
    payload = client.get("/api/executive/release-readiness").json()
    manifest = payload["smoke_test_manifest"]
    assert manifest["health"] == "/health"
    assert manifest["authenticated_endpoints"] == [
        "/api/executive/state",
        "/api/executive/harvesters",
        "/api/executive/intelligence",
        "/api/executive/frontend-contract",
        "/api/executive/release-readiness",
    ]
    assert manifest["authentication_token_env"] == "MISSION_CONTROL_SMOKE_TOKEN"


def test_release_readiness_distinguishes_runtime_advisories_from_contract_blockers() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: _principal(MissionControlRole.PUBLIC)
    payload = client.get("/api/executive/release-readiness").json()
    assert payload["runtime_advisories"]["advisories_do_not_override_contract_readiness"] is True
    assert isinstance(payload["runtime_advisories"]["degraded_sources"], list)


def test_release_readiness_blocks_on_contract_mismatch() -> None:
    governance = {"does_not_publish": True, "does_not_grant_scientific_authority": True}
    payload = build_release_readiness(
        {"contract_version": "wrong", "governance": governance},
        {"contract_version": "MISSION-CONTROL-TELEMETRY-001B", "harvesters": [], "governance": governance},
        {"contract_version": "MISSION-CONTROL-TELEMETRY-001D", "governance": governance},
        {
            "contract_version": "MISSION-CONTROL-TELEMETRY-001E",
            "readiness": {"direct_field_population_supported": True},
            "governance": governance,
        },
    )
    assert payload["release_ready"] is False
    assert payload["deployment_state"] == "blocked"
    assert "executive_state_contract" in payload["blocking_checks"]


def test_public_release_readiness_omits_operational_authority() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: _principal(MissionControlRole.PUBLIC)
    payload = client.get("/api/executive/release-readiness").json()
    assert payload["governance"]["operational_details_included"] is False
    assert payload["governance"]["does_not_publish"] is True
    assert payload["governance"]["does_not_grant_scientific_authority"] is True


def test_release_readiness_requires_authentication() -> None:
    assert client.get("/api/executive/release-readiness").status_code == 401
