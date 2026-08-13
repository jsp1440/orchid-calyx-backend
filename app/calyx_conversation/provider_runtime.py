from __future__ import annotations

import json
import logging
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

LOGGER = logging.getLogger(__name__)


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


def _provider_http_error(response: requests.Response, *, endpoint: str) -> RuntimeError:
    """Return a useful provider error without ever exposing the API key."""

    request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                detail = str(error.get("message") or error.get("code") or "")
            elif error:
                detail = str(error)
    except ValueError:
        detail = response.text
    detail = " ".join(detail.split())[:600]
    message = f"OPENAI_{endpoint.upper()}_HTTP_{response.status_code}"
    if request_id:
        message += f" request_id={request_id}"
    if detail:
        message += f" detail={detail}"
    return RuntimeError(message)


class OpenAIRuntimeResponsesProvider:
    """Use an existing OpenAI key/model even when Calyx-specific selector vars are absent."""

    provider_name = "openai"

    def __init__(self, *, model: str, api_key: str) -> None:
        self.model = model.strip()
        self.model_name = self.model
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

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

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

    @staticmethod
    def _extract_chat_text(body: dict[str, Any]) -> str:
        choices = body.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return ""
        message = choices[0].get("message") or {}
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
            return "\n\n".join(parts)
        return ""

    def _governed_context_text(self, governed_context: dict[str, Any]) -> str:
        return "Governed Calyx context for this turn:\n" + json.dumps(
            governed_context, sort_keys=True, default=str
        )

    def _responses_payload(
        self,
        *,
        messages: list[dict[str, str]],
        governed_context: dict[str, Any],
    ) -> dict[str, Any]:
        return {
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
                            "text": self._governed_context_text(governed_context),
                        }
                    ],
                },
            ],
            "max_output_tokens": self.max_tokens,
        }

    def _chat_payload(
        self,
        *,
        messages: list[dict[str, str]],
        governed_context: dict[str, Any],
    ) -> dict[str, Any]:
        chat_messages = [
            {"role": "system", "content": _scientific_system_prompt()},
            *[
                {
                    "role": "assistant" if item.get("role") == "assistant" else "user",
                    "content": str(item.get("content") or ""),
                }
                for item in messages
                if item.get("role") in {"user", "assistant"}
            ],
            {"role": "user", "content": self._governed_context_text(governed_context)},
        ]
        return {
            "model": self.model,
            "messages": chat_messages,
            "max_completion_tokens": self.max_tokens,
        }

    def _chat_completion_fallback(
        self,
        *,
        messages: list[dict[str, str]],
        governed_context: dict[str, Any],
        primary_error: Exception,
    ) -> GeneratedReply:
        payload = self._chat_payload(messages=messages, governed_context=governed_context)
        LOGGER.warning(
            "Calyx OpenAI Responses path failed; trying Chat Completions with the same model=%s primary_error=%s",
            self.model,
            primary_error,
        )
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers,
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            LOGGER.exception(
                "Calyx OpenAI Chat Completions fallback failed before an HTTP response model=%s error=%s",
                self.model,
                type(exc).__name__,
            )
            raise RuntimeError(
                f"OPENAI_GENERATIVE_PATHS_FAILED primary={primary_error} chat={type(exc).__name__}"
            ) from exc
        if not response.ok:
            chat_error = _provider_http_error(response, endpoint="chat_completions")
            LOGGER.error(
                "Calyx OpenAI Chat Completions fallback failed model=%s primary=%s chat=%s",
                self.model,
                primary_error,
                chat_error,
            )
            raise RuntimeError(
                f"OPENAI_GENERATIVE_PATHS_FAILED primary={primary_error} chat={chat_error}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"OPENAI_GENERATIVE_PATHS_FAILED primary={primary_error} chat=INVALID_JSON"
            ) from exc
        text = self._extract_chat_text(body)
        if not text:
            raise RuntimeError(
                f"OPENAI_GENERATIVE_PATHS_FAILED primary={primary_error} chat=EMPTY_RESPONSE"
            )
        return GeneratedReply(
            text=text,
            provider="openai-chat-fallback",
            model=self.model,
            request_hash=_request_hash(payload),
            provider_response_id=str(body.get("id")) if body.get("id") else None,
        )

    def generate(
        self,
        *,
        messages: list[dict[str, str]],
        governed_context: dict[str, Any],
    ) -> GeneratedReply:
        payload = self._responses_payload(messages=messages, governed_context=governed_context)
        try:
            response = requests.post(
                f"{self.base_url}/responses",
                headers=self._headers,
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            LOGGER.exception(
                "Calyx OpenAI Responses request failed before an HTTP response model=%s error=%s",
                self.model,
                type(exc).__name__,
            )
            primary_error = RuntimeError(f"OPENAI_RESPONSES_REQUEST_FAILED:{type(exc).__name__}")
            return self._chat_completion_fallback(
                messages=messages,
                governed_context=governed_context,
                primary_error=primary_error,
            )

        if not response.ok:
            primary_error = _provider_http_error(response, endpoint="responses")
            LOGGER.error("Calyx OpenAI Responses path failed model=%s %s", self.model, primary_error)
            # Retry only when the model/API accepted authentication but the endpoint or
            # request shape may be incompatible. Authentication/quota failures should
            # remain explicit rather than doubling a doomed provider request.
            if response.status_code in {400, 404, 405, 409, 415, 422}:
                return self._chat_completion_fallback(
                    messages=messages,
                    governed_context=governed_context,
                    primary_error=primary_error,
                )
            raise primary_error

        try:
            body = response.json()
        except ValueError as exc:
            primary_error = RuntimeError("OPENAI_RESPONSES_INVALID_JSON")
            LOGGER.error(
                "Calyx OpenAI provider returned non-JSON content model=%s status=%s",
                self.model,
                response.status_code,
            )
            return self._chat_completion_fallback(
                messages=messages,
                governed_context=governed_context,
                primary_error=primary_error,
            )

        text = self._extract_text(body)
        if not text:
            status = str(body.get("status") or "unknown")
            incomplete = body.get("incomplete_details")
            primary_error = RuntimeError(
                f"CALYX_CHAT_PROVIDER_EMPTY_RESPONSE status={status} incomplete={incomplete}"
            )
            LOGGER.error(
                "Calyx OpenAI provider returned no text model=%s response_status=%s incomplete=%s",
                self.model,
                status,
                incomplete,
            )
            return self._chat_completion_fallback(
                messages=messages,
                governed_context=governed_context,
                primary_error=primary_error,
            )

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
        "responses_primary": True,
        "chat_completions_fallback": True,
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
