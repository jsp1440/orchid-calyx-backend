from __future__ import annotations

import os
from typing import Any

from .provider import DeterministicGovernedReplyProvider

_TRUTHY = {"1", "true", "yes", "on"}
_ACCEPTED_SPEAK_RELEASE = "CALYX-SPEAK-005-WORKSPACE-OUTPUTS"


def reply_provider_readiness() -> dict[str, Any]:
    endpoint_configured = bool(os.getenv("CALYX_CHAT_COMPLETIONS_URL", "").strip())
    model = os.getenv("CALYX_CHAT_MODEL", "").strip()
    generative_configured = endpoint_configured and bool(model)
    acceptance_attested = (
        os.getenv("CALYX_CHAT_LIVE_ACCEPTANCE_VERIFIED", "").strip().casefold() in _TRUTHY
    )
    acceptance_model = os.getenv("CALYX_CHAT_LIVE_ACCEPTANCE_MODEL", "").strip()
    acceptance_release = os.getenv("CALYX_CHAT_LIVE_ACCEPTANCE_RELEASE", "").strip()
    acceptance_matches_runtime = (
        generative_configured
        and acceptance_model == model
        and acceptance_release == _ACCEPTED_SPEAK_RELEASE
    )
    live_acceptance_verified = (
        generative_configured and acceptance_attested and acceptance_matches_runtime
    )

    if generative_configured:
        return {
            "mode": "openai-compatible",
            "generative_configured": True,
            "model": model,
            "endpoint_configured": True,
            "live_acceptance_verified": live_acceptance_verified,
            "acceptance_attestation_matches_runtime": acceptance_matches_runtime,
            "accepted_speak_release": _ACCEPTED_SPEAK_RELEASE,
            "fallback_mode": DeterministicGovernedReplyProvider.provider_name,
        }

    return {
        "mode": DeterministicGovernedReplyProvider.provider_name,
        "generative_configured": False,
        "model": DeterministicGovernedReplyProvider.model_name,
        "endpoint_configured": endpoint_configured,
        "live_acceptance_verified": False,
        "acceptance_attestation_matches_runtime": False,
        "accepted_speak_release": _ACCEPTED_SPEAK_RELEASE,
        "fallback_mode": DeterministicGovernedReplyProvider.provider_name,
    }
