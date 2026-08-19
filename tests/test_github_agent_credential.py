from __future__ import annotations

import pytest

from app.calyx_orchestrator.github_agent_credential import (
    CODING_AGENT_TOKEN_ENV_VAR,
    GitHubCodingAgentCredentialError,
    load_coding_agent_transport,
)
from app.calyx_orchestrator.github_proposal_mutation_adapter import (
    RequestsGitHubTransport,
)


def test_missing_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(GitHubCodingAgentCredentialError, match=CODING_AGENT_TOKEN_ENV_VAR):
        load_coding_agent_transport(environ={})


def test_blank_token_fails_closed() -> None:
    with pytest.raises(GitHubCodingAgentCredentialError):
        load_coding_agent_transport(environ={CODING_AGENT_TOKEN_ENV_VAR: "   "})


def test_generic_github_token_cannot_substitute() -> None:
    """A broad or differently-scoped credential present under a generic name
    must never silently authorize the coding-agent mutation path."""
    environ = {
        "GITHUB_TOKEN": "a-real-looking-generic-token-value",
        "GH_TOKEN": "another-real-looking-value",
    }
    with pytest.raises(GitHubCodingAgentCredentialError):
        load_coding_agent_transport(environ=environ)


def test_calyx_github_token_cannot_substitute() -> None:
    """The Brain-config read-only credential must never become the
    coding-agent mutation credential, even though both names start with
    CALYX_GITHUB_."""
    environ = {"CALYX_GITHUB_TOKEN": "brain-read-only-credential-value"}
    with pytest.raises(GitHubCodingAgentCredentialError):
        load_coding_agent_transport(environ=environ)


def test_calyx_engineering_provider_token_cannot_substitute() -> None:
    """The separate, pre-existing calyx_engineering structured-patch
    provider credential must never become the coding-agent mutation
    credential either - they are unrelated automation pathways."""
    environ = {"CALYX_ENGINEERING_PROVIDER_TOKEN": "structured-patch-provider-value"}
    with pytest.raises(GitHubCodingAgentCredentialError):
        load_coding_agent_transport(environ=environ)


def test_valid_token_constructs_the_transport() -> None:
    transport = load_coding_agent_transport(
        environ={CODING_AGENT_TOKEN_ENV_VAR: "a-distinctive-fake-coding-agent-token-xyz"}
    )
    assert isinstance(transport, RequestsGitHubTransport)


def test_token_value_never_appears_in_transport_repr() -> None:
    distinctive_token = "distinctive-marker-should-never-leak-99887766"
    transport = load_coding_agent_transport(environ={CODING_AGENT_TOKEN_ENV_VAR: distinctive_token})
    assert distinctive_token not in repr(transport)
    assert distinctive_token not in str(transport)


def test_error_message_never_contains_secret_shaped_content() -> None:
    """Fires exactly when there is no usable value - there is nothing to
    leak by construction, but assert it explicitly so a future refactor
    that adds an interim variable cannot accidentally start leaking one."""
    with pytest.raises(GitHubCodingAgentCredentialError) as exc_info:
        load_coding_agent_transport(environ={CODING_AGENT_TOKEN_ENV_VAR: ""})
    message = str(exc_info.value)
    assert "ghp_" not in message
    assert "github_pat_" not in message
    assert CODING_AGENT_TOKEN_ENV_VAR in message  # names the missing variable, not a value
