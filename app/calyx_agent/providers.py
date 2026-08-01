from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

import requests


class ProviderError(RuntimeError):
    """Safe provider failure that never exposes credentials or raw response bodies."""


@dataclass(frozen=True)
class ProviderRequest:
    request_id: str
    user_request: str
    deterministic_summary: str
    intent: str
    approval_required: bool
    approval_reason: str | None
    steps: tuple[dict[str, Any], ...]
    tool_results: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ProviderResponse:
    provider: str
    model: str
    response_id: str | None
    text: str


class AgentProvider(Protocol):
    provider_id: str
    model: str

    def synthesize(self, request: ProviderRequest) -> ProviderResponse: ...


class OpenAIResponsesProvider:
    """OpenAI Responses API adapter used only for governed synthesis.

    This adapter has no tool definitions and receives only sanitized, deterministic
    Calyx output. It cannot change server-side intent, action class, or approvals.
    """

    provider_id = "openai"

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 45.0,
        max_output_chars: int = 12000,
    ) -> None:
        if not model.strip():
            raise ValueError("CALYX_AGENT_MODEL_REQUIRED")
        if not api_key.strip():
            raise ValueError("OPENAI_API_KEY_REQUIRED")
        self.model = model.strip()
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

    def synthesize(self, request: ProviderRequest) -> ProviderResponse:
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You are Calyx, the Orchid Continuum's governed scientific and technical assistant. "
                                "Use only the supplied deterministic evidence. Never claim that an action was executed "
                                "unless its step status says completed. Never alter or bypass approval requirements. "
                                "Do not provide private chain-of-thought. Give a concise answer, evidence-based findings, "
                                "uncertainties, and the next safe action."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": self._render_context(request),
                        }
                    ],
                },
            ],
            "max_output_tokens": 1800,
        }
        try:
            response = requests.post(
                f"{self._base_url}/responses",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ProviderError("CALYX_PROVIDER_REQUEST_FAILED") from exc

        text = self._extract_output_text(data)
        if not text:
            raise ProviderError("CALYX_PROVIDER_EMPTY_RESPONSE")
        if len(text) > self._max_output_chars:
            text = text[: self._max_output_chars].rstrip() + "\n\n[Response truncated by Calyx.]"
        return ProviderResponse(
            provider=self.provider_id,
            model=self.model,
            response_id=str(data.get("id") or "") or None,
            text=text,
        )

    @staticmethod
    def _render_context(request: ProviderRequest) -> str:
        return (
            f"Request ID: {request.request_id}\n"
            f"User request: {request.user_request}\n"
            f"Server-classified intent: {request.intent}\n"
            f"Approval required: {request.approval_required}\n"
            f"Approval reason: {request.approval_reason or 'none'}\n"
            f"Deterministic summary: {request.deterministic_summary}\n"
            f"Governed steps: {list(request.steps)!r}\n"
            f"Read-only tool results: {list(request.tool_results)!r}\n"
        )

    @staticmethod
    def _extract_output_text(data: dict[str, Any]) -> str:
        direct = data.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        parts: list[str] = []
        for item in data.get("output", []):
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if not isinstance(content, dict):
                    continue
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n\n".join(parts)


def provider_from_environment() -> AgentProvider | None:
    provider = os.getenv("CALYX_AGENT_PROVIDER", "").strip().casefold()
    model = os.getenv("CALYX_AGENT_MODEL", "").strip()
    if not provider and not model:
        return None
    if provider != "openai":
        raise ProviderError("CALYX_PROVIDER_UNSUPPORTED")
    return OpenAIResponsesProvider(
        model=model,
        api_key=os.getenv("OPENAI_API_KEY", ""),
        base_url=os.getenv("CALYX_AGENT_BASE_URL", "https://api.openai.com/v1"),
        timeout_seconds=float(os.getenv("CALYX_AGENT_TIMEOUT_SECONDS", "45")),
    )
