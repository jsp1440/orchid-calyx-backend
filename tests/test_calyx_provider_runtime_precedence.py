from __future__ import annotations

from app.calyx_conversation import provider
from app.calyx_conversation.provider_runtime import (
    OpenAIRuntimeResponsesProvider,
    configured_runtime_provider,
    runtime_provider_configuration,
)


def _clear_chat(monkeypatch):
    monkeypatch.delenv("CALYX_CHAT_COMPLETIONS_URL", raising=False)
    monkeypatch.delenv("CALYX_CHAT_MODEL", raising=False)
    monkeypatch.delenv("CALYX_CHAT_API_KEY", raising=False)


def test_agent_openai_configuration_uses_hardened_speak_provider(monkeypatch):
    _clear_chat(monkeypatch)
    monkeypatch.setenv("CALYX_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("CALYX_AGENT_MODEL", "gpt-5-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    legacy = provider.configured_reply_provider()
    configured = configured_runtime_provider()
    status = runtime_provider_configuration()

    assert isinstance(legacy, provider.OpenAIResponsesReplyProvider)
    assert isinstance(configured, OpenAIRuntimeResponsesProvider)
    assert configured.model == "gpt-5-mini"
    assert status["selected"] == "calyx-agent-openai-hardened"
    assert status["generative_ready"] is True


def test_explicit_chat_configuration_keeps_priority(monkeypatch):
    monkeypatch.setenv("CALYX_CHAT_COMPLETIONS_URL", "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv("CALYX_CHAT_MODEL", "custom-model")
    monkeypatch.setenv("CALYX_CHAT_API_KEY", "custom-key")
    monkeypatch.setenv("CALYX_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("CALYX_AGENT_MODEL", "gpt-5-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    configured = configured_runtime_provider()
    status = runtime_provider_configuration()

    assert isinstance(configured, provider.OpenAICompatibleReplyProvider)
    assert configured.model == "custom-model"
    assert status["selected"] == "chat-completions"


def test_missing_openai_key_still_falls_back_safely(monkeypatch):
    _clear_chat(monkeypatch)
    monkeypatch.setenv("CALYX_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("CALYX_AGENT_MODEL", "gpt-5-mini")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    configured = configured_runtime_provider()
    status = runtime_provider_configuration()

    assert isinstance(configured, provider.DeterministicGovernedReplyProvider)
    assert status["generative_ready"] is False
