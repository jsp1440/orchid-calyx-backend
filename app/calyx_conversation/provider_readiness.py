from __future__ import annotations

import os
from typing import Any

from .provider import DeterministicGovernedReplyProvider

_TRUTHY = {"1", "true", "yes", "on"}


def reply_provider_readiness() -> dict[str, Any]:
    endpoint_configured = bool(os.getenv("CALYX_CHAT_COMPLETIONS_URL", "").strip())
    model = os.getenv("CALYX_CHAT_MODEL", "").strip()
    generative_configured = endpoint_configured and bool(model)
    acceptance_attested = (
        os.getenv("CALYX_CHAT_LIVE_ACCEPTANCE_VERIFIED", "").strip().casefold() in _TRUTHY
    )
    live_acceptance_verified = generative_configured and acceptance_attested

    if generative_configured:
        return {
            "mode": "openai-compatible",
            "generative_configured": True,
            "model": model,
            "endpoint_configured": True,
            "live_acceptance_verified": live_acceptance_verified,
            "fallback_mode": DeterministicGovernedReplyProvider.provider_name,
        }

    return {
        "mode": DeterministicGovernedReplyProvider.provider_name,
        "generative_configured": False,
        "model": DeterministicGovernedReplyProvider.model_name,
        "endpoint_configured": endpoint_configured,
        "live_acceptance_verified": False,
        "fallback_mode": DeterministicGovernedReplyProvider.provider_name,
    }
