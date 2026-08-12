from __future__ import annotations

from app.calyx_conversation import speak_routes
from app.calyx_conversation.provider_readiness import reply_provider_readiness


def auth() -> dict[str, str]:
    return {"subject": "owner-provider-readiness"}


def clear_acceptance(monkeypatch) -> None:
    monkeypatch.delenv("CALYX_CHAT_LIVE_ACCEPTANCE_VERIFIED", raising=False)
    monkeypatch.delenv("CALYX_CHAT_LIVE_ACCEPTANCE_MODEL", raising=False)
    monkeypatch.delenv("CALYX_CHAT_LIVE_ACCEPTANCE_RELEASE", raising=False)


def test_provider_readiness_reports_deterministic_fallback_when_unconfigured(monkeypatch):
    monkeypatch.delenv("CALYX_CHAT_COMPLETIONS_URL", raising=False)
    monkeypatch.delenv("CALYX_CHAT_MODEL", raising=False)
    monkeypatch.delenv("CALYX_CHAT_API_KEY", raising=False)
    clear_acceptance(monkeypatch)

    readiness = reply_provider_readiness()

    assert readiness == {
        "mode": "deterministic-governed",
        "generative_configured": False,
        "model": "calyx-governed-summary-v1",
        "endpoint_configured": False,
        "live_acceptance_verified": False,
        "acceptance_attestation_matches_runtime": False,
        "accepted_speak_release": "CALYX-SPEAK-005-WORKSPACE-OUTPUTS",
        "fallback_mode": "deterministic-governed",
    }


def test_provider_readiness_reports_configured_generative_mode_without_secrets(monkeypatch):
    monkeypatch.setenv("CALYX_CHAT_COMPLETIONS_URL", "https://provider.invalid/v1/chat/completions")
    monkeypatch.setenv("CALYX_CHAT_MODEL", "scientific-model-v1")
    monkeypatch.setenv("CALYX_CHAT_API_KEY", "secret-must-never-appear")
    clear_acceptance(monkeypatch)

    readiness = reply_provider_readiness()

    assert readiness["mode"] == "openai-compatible"
    assert readiness["generative_configured"] is True
    assert readiness["model"] == "scientific-model-v1"
    assert readiness["endpoint_configured"] is True
    assert readiness["live_acceptance_verified"] is False
    assert readiness["acceptance_attestation_matches_runtime"] is False
    serialized = repr(readiness)
    assert "provider.invalid" not in serialized
    assert "secret-must-never-appear" not in serialized


def test_partial_configuration_does_not_claim_generative_or_accepted_readiness(monkeypatch):
    monkeypatch.setenv("CALYX_CHAT_COMPLETIONS_URL", "https://provider.invalid/v1/chat/completions")
    monkeypatch.delenv("CALYX_CHAT_MODEL", raising=False)
    monkeypatch.setenv("CALYX_CHAT_LIVE_ACCEPTANCE_VERIFIED", "true")
    monkeypatch.setenv("CALYX_CHAT_LIVE_ACCEPTANCE_MODEL", "scientific-model-v1")
    monkeypatch.setenv(
        "CALYX_CHAT_LIVE_ACCEPTANCE_RELEASE", "CALYX-SPEAK-005-WORKSPACE-OUTPUTS"
    )

    readiness = reply_provider_readiness()

    assert readiness["generative_configured"] is False
    assert readiness["mode"] == "deterministic-governed"
    assert readiness["endpoint_configured"] is True
    assert readiness["live_acceptance_verified"] is False
    assert readiness["acceptance_attestation_matches_runtime"] is False


def test_live_acceptance_requires_matching_model_and_release(monkeypatch):
    monkeypatch.setenv("CALYX_CHAT_COMPLETIONS_URL", "https://provider.invalid/v1/chat/completions")
    monkeypatch.setenv("CALYX_CHAT_MODEL", "scientific-model-v1")
    monkeypatch.setenv("CALYX_CHAT_LIVE_ACCEPTANCE_VERIFIED", "yes")
    monkeypatch.setenv("CALYX_CHAT_LIVE_ACCEPTANCE_MODEL", "scientific-model-v1")
    monkeypatch.setenv(
        "CALYX_CHAT_LIVE_ACCEPTANCE_RELEASE", "CALYX-SPEAK-005-WORKSPACE-OUTPUTS"
    )

    readiness = reply_provider_readiness()

    assert readiness["generative_configured"] is True
    assert readiness["acceptance_attestation_matches_runtime"] is True
    assert readiness["live_acceptance_verified"] is True


def test_stale_acceptance_does_not_survive_model_or_release_change(monkeypatch):
    monkeypatch.setenv("CALYX_CHAT_COMPLETIONS_URL", "https://provider.invalid/v1/chat/completions")
    monkeypatch.setenv("CALYX_CHAT_MODEL", "scientific-model-v2")
    monkeypatch.setenv("CALYX_CHAT_LIVE_ACCEPTANCE_VERIFIED", "true")
    monkeypatch.setenv("CALYX_CHAT_LIVE_ACCEPTANCE_MODEL", "scientific-model-v1")
    monkeypatch.setenv("CALYX_CHAT_LIVE_ACCEPTANCE_RELEASE", "CALYX-SPEAK-004-CONTEXT")

    readiness = reply_provider_readiness()

    assert readiness["generative_configured"] is True
    assert readiness["acceptance_attestation_matches_runtime"] is False
    assert readiness["live_acceptance_verified"] is False


def test_speak_status_exposes_provider_readiness_without_claiming_live_acceptance(monkeypatch):
    monkeypatch.setenv("CALYX_CHAT_COMPLETIONS_URL", "https://provider.invalid/v1/chat/completions")
    monkeypatch.setenv("CALYX_CHAT_MODEL", "scientific-model-v1")
    clear_acceptance(monkeypatch)

    status = speak_routes.speak_status(auth())

    assert status["release"] == "CALYX-SPEAK-005-WORKSPACE-OUTPUTS"
    assert status["reply_provider"]["generative_configured"] is True
    assert status["reply_provider"]["live_acceptance_verified"] is False
    assert status["automatic_publication"] is False
    assert status["knowledge_graph_mutation"] is False
