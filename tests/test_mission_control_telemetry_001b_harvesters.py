from fastapi.testclient import TestClient

from app.main import app
from app.mission_control_access import AccessPrincipal, MissionControlRole
from app.review_api.dependencies import authenticated_principal
from app.executive_telemetry.harvesters import normalize_harvester

client = TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_normalizer_preserves_counts_and_marks_unavailable_truthfully() -> None:
    payload = normalize_harvester(
        {
            "id": "gbif",
            "name": "GBIF",
            "source": "GBIF occurrence backbone",
            "enabled": False,
            "state": "unknown",
            "rows_processed": 0,
            "rows_inserted": 0,
            "errors": ["database unavailable"],
            "warning_count": 1,
            "checkpoint": "audit_ecological_relationship_graph_gaps",
            "logSummary": "Database telemetry is unavailable.",
        }
    )
    assert payload["status"] == "unavailable"
    assert payload["records_processed"] == 0
    assert payload["failures"] == ["database unavailable"]
    assert payload["calyx_context"]["recommendation_signal"] == "unavailable"


def test_normalizer_calculates_completion_and_duplicate_rate() -> None:
    payload = normalize_harvester(
        {
            "id": "inaturalist",
            "name": "iNaturalist",
            "source": "observations",
            "enabled": True,
            "state": "running",
            "rows_processed": 80,
            "rows_inserted": 75,
            "target_records": 100,
            "checkpoint": "audit_image_species_evidence_coverage",
        }
    )
    assert payload["completion_percentage"] == 80.0
    assert payload["duplicate_count"] == 5
    assert payload["duplicate_rate"] == 6.25


def test_public_harvester_endpoint_omits_operational_actions() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: AccessPrincipal(
        principal_id="public-harvester-user",
        roles=(MissionControlRole.PUBLIC,),
        authenticated=True,
    )
    response = client.get("/api/executive/harvesters")
    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == "MISSION-CONTROL-TELEMETRY-001B"
    assert payload["governance"]["operational_details_included"] is False
    assert all(item["allowed_actions"] == {} for item in payload["harvesters"])


def test_administrator_receives_action_contract_without_scientific_authority() -> None:
    app.dependency_overrides[authenticated_principal] = lambda: AccessPrincipal(
        principal_id="telemetry-admin",
        roles=(MissionControlRole.ADMINISTRATOR,),
        authenticated=True,
    )
    response = client.get("/api/executive/harvesters/gbif")
    assert response.status_code == 200
    payload = response.json()
    assert payload["governance"]["operational_details_included"] is True
    assert payload["governance"]["does_not_grant_scientific_authority"] is True
    assert "allowed_actions" in payload["harvester"]
