from __future__ import annotations

from app.mission_control_briefing.proposal_executor_status import (
    proposal_executor_mission_control_status,
)
from app.mission_control_briefing.routes import router

REPOSITORY = "jsp1440/orchid-calyx-backend"
OWNER = "principal:owner"


def test_mission_control_status_is_read_only_and_blocked_by_default() -> None:
    status = proposal_executor_mission_control_status({})
    assert status["schema"] == "calyx-mission-control-proposal-executor-status-v1"
    assert status["status"] == "blocked"
    assert status["read_only"] is True
    assert status["mutation_performed"] is False
    assert status["secret_material_exposed"] is False
    assert status["evidence_chain_complete_through_policy"] is True
    assert status["live_credential_registration_active"] is False
    assert status["policy"]["enabled"] is False
    assert status["policy"]["external_side_effects"] is False
    assert "executor_disabled" in status["policy"]["blockers"]


def test_enabled_configuration_remains_blocked_without_credential_readiness() -> None:
    status = proposal_executor_mission_control_status(
        {
            "CALYX_GITHUB_PROPOSAL_EXECUTOR_ENABLED": "true",
            "CALYX_GITHUB_PROPOSAL_EXECUTOR_OWNER": OWNER,
            "CALYX_GITHUB_PROPOSAL_REPOSITORIES": REPOSITORY,
        }
    )
    assert status["status"] == "blocked"
    assert status["policy"]["credential_ready"] is False
    assert status["policy"]["external_side_effects"] is False
    assert "credential_not_ready" in status["policy"]["blockers"]


def test_status_never_widens_authority_even_when_all_readiness_inputs_are_true() -> None:
    status = proposal_executor_mission_control_status(
        {
            "CALYX_GITHUB_PROPOSAL_EXECUTOR_ENABLED": "true",
            "CALYX_GITHUB_PROPOSAL_EXECUTOR_OWNER": OWNER,
            "CALYX_GITHUB_PROPOSAL_REPOSITORIES": REPOSITORY,
        },
        credential_ready=True,
    )
    assert status["status"] == "ready"
    assert status["policy"]["ready_for_owner_authorized_draft_pr"] is True
    assert status["authority"]["draft_pull_request_only"] is True
    for field in (
        "merge_authorized",
        "automatic_merge_authorized",
        "deployment_authorized",
        "publication_authorized",
        "taxonomy_activation_authorized",
        "production_database_mutation_authorized",
        "production_graph_mutation_authorized",
        "credential_disclosure_authorized",
        "spending_authorized",
    ):
        assert status["authority"][field] is False
    assert status["mutation_performed"] is False


def test_invalid_repository_configuration_is_reported_fail_closed() -> None:
    status = proposal_executor_mission_control_status(
        {
            "CALYX_GITHUB_PROPOSAL_EXECUTOR_ENABLED": "true",
            "CALYX_GITHUB_PROPOSAL_EXECUTOR_OWNER": OWNER,
            "CALYX_GITHUB_PROPOSAL_REPOSITORIES": "org/repo name",
        },
        credential_ready=True,
    )
    assert status["status"] == "blocked"
    assert status["policy"]["valid"] is False
    assert status["policy"]["external_side_effects"] is False


def test_authenticated_briefing_router_exposes_proposal_executor_route() -> None:
    paths = {route.path for route in router.routes}
    assert "/api/mission-control/briefing/proposal-executor" in paths
