from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

from .provider import (
    CalyxReplyProvider,
    GeneratedReply,
    _request_hash,
    _scientific_system_prompt,
    configured_reply_provider,
)

LOGGER = logging.getLogger(__name__)

# These are model-budget guards, not word-count limits. The current user turn is
# kept much larger than ordinary chat so formal research briefs can pass intact.
_MAX_CONTEXT_CHARS = 60000
_MAX_MESSAGE_CHARS = 4000
_MAX_CURRENT_MESSAGE_CHARS = 100000
_MAX_HISTORY_CHARS = 20000
_DEFAULT_MAX_OUTPUT_TOKENS = 12000
_MAX_CONFIGURABLE_OUTPUT_TOKENS = 32000


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


def _compact_value(value: Any, *, depth: int = 0) -> Any:
    """Bound retrieved scientific context without changing its epistemic labels."""

    if depth >= 6:
        if isinstance(value, (dict, list, tuple)):
            return "[nested context omitted]"
        return value
    if isinstance(value, str):
        text = " ".join(value.split())
        return text if len(text) <= 2200 else text[:2200] + "…"
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 32:
                compact["_additional_fields_omitted"] = len(value) - 32
                break
            compact[str(key)] = _compact_value(item, depth=depth + 1)
        return compact
    if isinstance(value, (list, tuple)):
        items = list(value)
        compact_items: list[Any] = []
        used_chars = 0
        for item in items[:16]:
            compacted_item = _compact_value(item, depth=depth + 1)
            item_chars = len(json.dumps(compacted_item, default=str))
            if compact_items and used_chars + item_chars > _MAX_HISTORY_CHARS:
                break
            compact_items.append(compacted_item)
            used_chars += item_chars
        omitted = len(items) - len(compact_items)
        if omitted > 0:
            compact_items.append({"_additional_items_omitted": omitted})
        return compact_items
    return value


def compact_governed_context(governed_context: dict[str, Any]) -> dict[str, Any]:
    """Create the model-facing context while retaining source/governance boundaries.

    The full governed objects remain available server-side and in research details.
    The model receives a bounded representation so a large mission, climate product,
    or literature result set cannot knock the generative provider offline.
    """

    preferred_keys = (
        "casual",
        "conversation_id",
        "project_id",
        "interaction_context",
        "retrieval",
        "continuum",
        "climate",
        "mission",
        "mission_error",
        "provider_configuration",
        "epistemic_policy",
        "deliverable_capabilities",
    )
    selected = {key: governed_context[key] for key in preferred_keys if key in governed_context}
    return _compact_value(selected)


def _compact_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep the current research prompt intact while bounding older conversation history."""

    eligible = [
        item
        for item in messages
        if item.get("role") in {"user", "assistant"}
        and str(item.get("content") or "").strip()
    ]
    if not eligible:
        return []

    compact: list[dict[str, str]] = []
    current = eligible[-1]
    current_content = str(current.get("content") or "").strip()
    if len(current_content) > _MAX_CURRENT_MESSAGE_CHARS:
        current_content = current_content[:_MAX_CURRENT_MESSAGE_CHARS]

    remaining = max(0, _MAX_HISTORY_CHARS - len(current_content))
    history: list[dict[str, str]] = []
    for item in reversed(eligible[:-1]):
        if remaining <= 0:
            break
        role = str(item.get("role"))
        content = str(item.get("content") or "").strip()
        clipped = content[-_MAX_MESSAGE_CHARS:]
        if len(clipped) > remaining:
            clipped = clipped[-remaining:]
        if clipped:
            history.append({"role": role, "content": clipped})
            remaining -= len(clipped)
    history.reverse()
    compact.extend(history)
    compact.append({"role": str(current.get("role")), "content": current_content})
    return compact


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
            min(float(os.getenv("CALYX_AGENT_TIMEOUT_SECONDS", "90")), 180.0),
        )
        self.max_tokens = max(
            128,
            min(
                int(os.getenv("CALYX_CHAT_MAX_TOKENS", str(_DEFAULT_MAX_OUTPUT_TOKENS))),
                _MAX_CONFIGURABLE_OUTPUT_TOKENS,
            ),
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
        compact = compact_governed_context(governed_context)
        text = json.dumps(compact, sort_keys=True, default=str)
        if len(text) > _MAX_CONTEXT_CHARS:
            LOGGER.warning(
                "Calyx governed context exceeded model budget; truncating chars=%s limit=%s",
                len(text),
                _MAX_CONTEXT_CHARS,
            )
            text = text[:_MAX_CONTEXT_CHARS] + "\n[additional governed context omitted; full provenance remains server-side]"
        return "Governed Calyx context for this turn:\n" + text

    def _responses_payload(
        self,
        *,
        messages: list[dict[str, str]],
        governed_context: dict[str, Any],
    ) -> dict[str, Any]:
        model_messages = _compact_messages(messages)
        response_messages = []
        for item in model_messages:
            role = item["role"]
            content_type = "output_text" if role == "assistant" else "input_text"
            response_messages.append(
                {
                    "role": role,
                    "content": [{"type": content_type, "text": item["content"]}],
                }
            )
        return {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": _scientific_system_prompt()}],
                },
                *response_messages,
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
            *_compact_messages(messages),
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
            if response.status_code in {400, 404, 405, 409, 415, 422}:
                return self._chat_completion_fallback(
                    messages=messages,
                    governed_context=governed_context,
                    primary_error=primary_error,
                )
            raise primary_error

        try:
            body = response.json()
        except ValueError:
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
        selected = "calyx-agent-openai-hardened"
    elif runtime_model and openai_key:
        selected = "openai-runtime-autodetect"
    else:
        selected = "deterministic-governed"

    configured_output = max(
        128,
        min(
            int(os.getenv("CALYX_CHAT_MAX_TOKENS", str(_DEFAULT_MAX_OUTPUT_TOKENS))),
            _MAX_CONFIGURABLE_OUTPUT_TOKENS,
        ),
    )
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
        "model_context_compaction": True,
        "max_governed_context_chars": _MAX_CONTEXT_CHARS,
        "max_current_message_chars": _MAX_CURRENT_MESSAGE_CHARS,
        "max_conversation_history_chars": _MAX_HISTORY_CHARS,
        "max_output_tokens": configured_output,
        "output_budget_configurable": True,
        "word_count_limit": False,
        "missing_configuration": missing,
        "secrets_exposed": False,
    }


def configured_runtime_provider() -> CalyxReplyProvider:
    """Select Speak's provider with hardened OpenAI precedence."""

    chat_url = os.getenv("CALYX_CHAT_COMPLETIONS_URL", "").strip()
    chat_model = os.getenv("CALYX_CHAT_MODEL", "").strip()
    if chat_url and chat_model:
        return configured_reply_provider()

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = _runtime_model()
    if api_key and model:
        return OpenAIRuntimeResponsesProvider(model=model, api_key=api_key)

    return configured_reply_provider()