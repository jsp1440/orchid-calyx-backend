from app.mission_control_access import AccessPrincipal, MissionControlRole
from app.mission_control_briefing.service import MissionControlBriefingService


def _service() -> MissionControlBriefingService:
    return MissionControlBriefingService(
        completeness_provider=lambda: [
            {
                "id": "literature",
                "display_name": "Literature System",
                "category": "Science",
                "status": "warning",
                "completion": 45,
                "summary": "Literature telemetry.",
                "telemetry_source": "oc_literature.documents",
                "blockers": ["Coverage gap"],
                "recommended_next_action": "Extract priority papers.",
                "last_update": "2026-07-27T00:00:00+00:00",
            }
        ],
        harvester_provider=lambda: [
            {
                "id": "literature",
                "name": "Literature harvesters",
                "state": "idle",
                "last_run": "2026-07-27T00:00:00+00:00",
                "heartbeat_at": "2026-07-27T00:00:00+00:00",
                "errors": [],
            }
        ],
        metric_provider=lambda: {"database_connected": True, "metrics": {"literature": {"count": 10}}},
    )


def test_public_briefing_excludes_restricted_operations() -> None:
    principal = AccessPrincipal(
        principal_id="public-user",
        roles=(MissionControlRole.PUBLIC,),
        authenticated=True,
    )
    payload = _service().briefing_for_principal(principal)
    assert payload["audience"] == "public"
    assert "operations" not in payload
    assert "expert_focus" not in payload


def test_volunteer_briefing_surfaces_actionable_gaps() -> None:
    principal = AccessPrincipal(
        principal_id="volunteer-1",
        roles=(MissionControlRole.PUBLIC, MissionControlRole.VOLUNTEER),
        authenticated=True,
    )
    payload = _service().briefing_for_principal(principal)
    assert payload["audience"] == "volunteer"
    assert payload["volunteer_focus"][0]["module_id"] == "literature"


def test_expert_briefing_includes_scientific_metrics_and_blockers() -> None:
    principal = AccessPrincipal(
        principal_id="expert-1",
        roles=(MissionControlRole.PUBLIC, MissionControlRole.EXPERT),
        authenticated=True,
    )
    payload = _service().briefing_for_principal(principal)
    assert payload["audience"] == "expert"
    assert payload["expert_focus"][0]["module_id"] == "literature"
    assert payload["scientific_metrics"]["database_connected"] is True


def test_administrator_briefing_includes_operational_feed() -> None:
    principal = AccessPrincipal(
        principal_id="admin-1",
        roles=(MissionControlRole.PUBLIC, MissionControlRole.ADMINISTRATOR),
        authenticated=True,
    )
    payload = _service().briefing_for_principal(principal)
    assert payload["audience"] == "administrator"
    assert payload["operations"]["harvesters"][0]["harvester_id"] == "literature"
