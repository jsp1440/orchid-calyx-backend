from __future__ import annotations

import pytest

from runtime.config_loader import BrainConfigSource


def test_calyx_github_token_is_preferred_over_generic_github_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CALYX_GITHUB_TOKEN", "narrow-brain-read-token")
    monkeypatch.setenv("GITHUB_TOKEN", "broad-generic-token")
    source = BrainConfigSource.from_env()
    assert source.token == "narrow-brain-read-token"


def test_falls_back_to_generic_github_token_when_calyx_specific_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CALYX_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "broad-generic-token")
    source = BrainConfigSource.from_env()
    assert source.token == "broad-generic-token"


def test_token_is_none_when_neither_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CALYX_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    source = BrainConfigSource.from_env()
    assert source.token is None


def test_coding_agent_mutation_credential_is_never_read_by_the_brain_config_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dedicated GitHub coding-agent mutation credential
    (CALYX_GITHUB_CODING_AGENT_TOKEN) must never leak into this unrelated,
    read-only Brain-config fetch path, even if it is the only credential
    present in the environment."""
    monkeypatch.delenv("CALYX_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("CALYX_GITHUB_CODING_AGENT_TOKEN", "coding-agent-mutation-only-token")
    source = BrainConfigSource.from_env()
    assert source.token is None
