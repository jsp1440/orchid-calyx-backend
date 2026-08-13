from __future__ import annotations

import json
import os
from typing import Any

import requests

from .provider import (
    CalyxReplyProvider,
    DeterministicGovernedReplyProvider,
    GeneratedReply,
    _request_hash,
    _scientific_system_prompt,
    configured_reply_provider,
)


def _runtime_model() -> str:
    return (
        os.getenv("CALYX_AGENT_MODEL", "").strip()
        or os.getenv("OPENAI_MODEL", "").strip()
        or (
            os.getenv("CALYX_CHAT_MODEL", "").strip()
            if not os.getenv("CALYX_CHAT_COMPLETIONS_URL", "").strip()
            else ""
        )
    )


class OpenAIRuntimeResponsesProvider:
    """Use an existing OpenAI key/model even when Calyx-specific selector vars are absent."""

    provider_name = "openai"

    def __init__(self, *, model: str, api_key: str) -> None:
        self.model = model.strip()
        self.api_key = api_key.strip()
        self.base_url = os.getenv(
            "CALYX_AGENT_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/")
        self.timeout = max(
            1.0,
            min(float(os.getenv("CALYX_AGENT_TIMEOUT_SECONDS", "45")), 120.0),
        )
        self.max_tokens = max(
            128,
            min(int(os.getenv("CALYX_CHAT_MAX_TOKENS", "2200")), 6000),
        )
        if not self.model or not self.api_key:
            raise RuntimeError("CALYX_RUNTIME_OPENAI_PROVIDER_NOT_CONFIGURED")

    @staticmethod
    def _extract_text(body: dict[str, Any]) -> str:
        direct = body.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        parts: list[str] = []
        for item in body.get("output") or []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n\n".join(parts)

    def generate(
        self,
        *,
        messages: list[dict[str, str]],
        governed_context: dict[str, Any],
    ) -> GeneratedReply:
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": _scientific_system_prompt()}],
                },
                *[
                    {
                        "role": "assistant" if item.get("role") == "assistant" else "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": str(item.get("content") or ""),
                            }
                        ],
                    }
                    for item in messages
                    if item.get("role") in {"user", "assistant"}
                ],
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Governed Calyx context for this turn:\n"
                            + json.dumps(governed_context, sort_keys=True, default=str),
                        }
                    ],
                },
            ],
            "max_output_tokens": self.max_tokens,
        }
        response = requests.post(
            f"{self.base_url}/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        text = self._extract_text(body)
        if not text:
            raise RuntimeError("CALYX_CHAT_PROVIDER_EMPTY_RESPONSE")
        return GeneratedReply(
            text=text,
            provider=self.provider_name,
            model=self.model,
            request_hash=_request_hash(payload),
            provider_response_id=str(body.get("id")) if body.get("id") else None,
        )


def runtime_provider_configuration() -> dict[str, Any]:
    chat_url = bool(os.getenv("CALYX_CHAT_COMPLETIONS_URL", "").strip())
    chat_model = bool(os.getenv("CALYX_CHAT_MODEL", "").strip())
    agent_provider = os.getenv("CALYX_AGENT_PROVIDER", "").strip().casefold()
    agent_model = bool(os.getenv("CALYX_AGENT_MODEL", "").strip())
    openai_model = bool(os.getenv("OPENAI_MODEL", "").strip())
    openai_key = bool(os.getenv("OPENAI_API_KEY", "").strip())
    runtime_model = _runtime_model()

    missing: list[str] = []
    if not openai_key and not (chat_url and chat_model):
        missing.append("OPENAI_API_KEY or CALYX_CHAT_COMPLETIONS_URL")
    if not runtime_model and not (chat_url and chat_model):
        missing.append("CALYX_AGENT_MODEL or OPENAI_MODEL")

    if chat_url and chat_model:
        selected = "chat-completions"
    elif agent_provider == "openai" and agent_model and openai_key:
        selected = "calyx-agent-openai"
    elif runtime_model and openai_key:
        selected = "openai-runtime-autodetect"
    else:
        selected = "deterministic-governed"

    return {
        "selected": selected,
        "generative_ready": selected != "deterministic-governed",
        "openai_key_present": openai_key,
        "calyx_agent_provider": agent_provider or None,
        "calyx_agent_model_present": agent_model,
        "openai_model_present": openai_model,
        "chat_url_present": chat_url,
        "chat_model_present": chat_model,
        "resolved_model": runtime_model or None,
        "missing_configuration": missing,
        "secrets_exposed": False,
    }


def configured_runtime_provider() -> CalyxReplyProvider:
    legacy = configured_reply_provider()
    if not isinstance(legacy, DeterministicGovernedReplyProvider):
        return legacy

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = _runtime_model()
    if api_key and model:
        return OpenAIRuntimeResponsesProvider(model=model, api_key=api_key)
    return legacy
