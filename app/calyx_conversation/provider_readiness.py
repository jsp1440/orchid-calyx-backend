from __future__ import annotations

import os
from typing import Any

from .provider import DeterministicGovernedReplyProvider


def reply_provider_readiness() -> dict[str, Any]:
    endpoint_configured = bool(os.getenv("CALYX_CHAT_COMPLETIONS_URL", "").strip())
    model = os.getenv("CALYX_CHAT_MODEL", "").strip()
    generative_configured = endpoint_configured and bool(model)

    if generative_configured:
        return {
            "mode": "openai-compatible",
            "generative_configured": True,
            "model": model,
            "endpoint_configured": True,
            "live_acceptance_verified": False,
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
