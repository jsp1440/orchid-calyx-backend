import pytest

from app.calyx_orchestrator.github_agent_autonomy_policy import (
    GitHubCodingAgentAutonomyPolicy,
    github_coding_agent_autonomy_status,
)


def test_defaults_are_disabled_and_unauthorized() -> None:
    policy = GitHubCodingAgentAutonomyPolicy()
    assert policy.enabled is False
    status = policy.status()
    assert status["authorized"] is False
    assert status["automatic_execute"] is False


def test_enabling_without_an_owner_fails_closed() -> None:
    with pytest.raises(ValueError, match="CALYX_GITHUB_CODING_AUTONOMY_OWNER_REQUIRED"):
        GitHubCodingAgentAutonomyPolicy(enabled=True, owner="").validated()


def test_enabled_with_owner_is_authorized_but_never_marks_automatic_execute() -> None:
    policy = GitHubCodingAgentAutonomyPolicy(enabled=True, owner="jsp1440").validated()
    status = policy.status()
    assert status["authorized"] is True
    assert status["automatic_preflight"] is True
    # No field, environment variable, or combination of settings on this
    # policy ever produces automatic_execute=True - that is a structural
    # guarantee, not a default that happens to be off.
    assert status["automatic_execute"] is False
    assert status["external_execution"] is False
    assert status["credential_access"] is False


def test_from_environ_reads_configured_values() -> None:
    environ = {
        "CALYX_GITHUB_CODING_AUTONOMY_ENABLED": "true",
        "CALYX_GITHUB_CODING_AUTONOMY_OWNER": "jsp1440",
        "CALYX_GITHUB_CODING_AUTONOMY_POLL_SECONDS": "120",
    }
    policy = GitHubCodingAgentAutonomyPolicy.from_environ(environ)
    assert policy.enabled is True
    assert policy.owner == "jsp1440"
    assert policy.poll_seconds == 120


def test_from_environ_defaults_to_disabled_when_unset() -> None:
    policy = GitHubCodingAgentAutonomyPolicy.from_environ({})
    assert policy.enabled is False
    assert policy.owner == ""


def test_status_helper_reports_invalid_configuration_without_raising() -> None:
    result = github_coding_agent_autonomy_status({"CALYX_GITHUB_CODING_AUTONOMY_ENABLED": "true"})
    assert result["valid"] is False
    assert result["authorized"] is False
    assert "OWNER_REQUIRED" in str(result["error"])
