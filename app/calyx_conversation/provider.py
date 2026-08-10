from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

import requests


@dataclass(frozen=True)
class GeneratedReply:
    text: str
    provider: str
    model: str
    request_hash: str
    provider_response_id: str | None = None


class CalyxReplyProvider(Protocol):
    def generate(
        self,
        *,
        messages: list[dict[str, str]],
        governed_context: dict[str, Any],
    ) -> GeneratedReply: ...


def _request_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class DeterministicGovernedReplyProvider:
    """Safe fallback that never invents facts outside supplied governed context."""

    provider_name = "deterministic-governed"
    model_name = "calyx-governed-summary-v1"

    def generate(
        self,
        *,
        messages: list[dict[str, str]],
        governed_context: dict[str, Any],
    ) -> GeneratedReply:
        payload = {"messages": messages, "governed_context": governed_context}
        mission = governed_context.get("mission")
        retrieval = governed_context.get("retrieval") or {}
        question = next(
            (item["content"] for item in reversed(messages) if item.get("role") == "user"),
            "",
        )
        lines: list[str] = []
        if mission:
            conclusions = mission.get("conclusions") or []
            if conclusions:
                lines.extend(str(item.get("text") or "").strip() for item in conclusions if item.get("text"))
            else:
                lines.append("I completed a governed Brain mission, but it did not produce a scientific conclusion.")
            gaps = mission.get("missing_evidence") or []
            if gaps:
                lines.append("Evidence gaps: " + "; ".join(str(item) for item in gaps[:8]))
            confidence = mission.get("confidence")
            if confidence is not None:
                lines.append(f"Backend confidence: {float(confidence):.2f}.")
            lines.append("This answer remains review-bound and is not automatically published knowledge.")
        elif retrieval.get("results"):
            lines.append(
                f"I found {retrieval.get('total_eligible_results', len(retrieval['results']))} eligible Orchid Continuum evidence objects relevant to your question."
            )
            for index, result in enumerate(retrieval["results"][:5], start=1):
                excerpt = str(result.get("authorized_excerpt") or "").strip().replace("\n", " ")
                title = result.get("title") or result.get("object_type") or f"Evidence {index}"
                lines.append(f"{index}. {title}" + (f": {excerpt[:360]}" if excerpt else ""))
            lines.append("I have not promoted these retrieved records into published knowledge.")
        else:
            lines.append(
                "I do not yet have enough governed Orchid Continuum evidence to answer that substantively without guessing."
            )
        if question:
            lines.append(f"Question retained in this thread: {question}")
        text = "\n\n".join(item for item in lines if item)
        return GeneratedReply(
            text=text,
            provider=self.provider_name,
            model=self.model_name,
            request_hash=_request_hash(payload),
        )


class OpenAICompatibleReplyProvider:
    """Optional server-configured provider using an OpenAI-compatible chat-completions contract."""

    def __init__(self) -> None:
        self.url = os.getenv("CALYX_CHAT_COMPLETIONS_URL", "").strip()
        self.api_key = os.getenv("CALYX_CHAT_API_KEY", "").strip()
        self.model = os.getenv("CALYX_CHAT_MODEL", "").strip()
        self.timeout = max(1.0, min(float(os.getenv("CALYX_CHAT_TIMEOUT_SECONDS", "45")), 120.0))
        self.max_tokens = max(128, min(int(os.getenv("CALYX_CHAT_MAX_TOKENS", "1400")), 4000))
        if not self.url or not self.model:
            raise RuntimeError("CALYX_CHAT_PROVIDER_NOT_CONFIGURED")

    def generate(
        self,
        *,
        messages: list[dict[str, str]],
        governed_context: dict[str, Any],
    ) -> GeneratedReply:
        system = (
            "You are Calyx, the Orchid Continuum's governed scientific collaborator. "
            "Use only the supplied conversation and governed context for factual scientific claims. "
            "Explicitly distinguish direct evidence, inference, missing evidence, and proposed design ideas. "
            "Never claim an Orchid Continuum capability is implemented unless the governed context says it is. "
            "Do not publish, promote Candidate Knowledge, or mutate the Knowledge Graph."
        )
        context_text = json.dumps(governed_context, sort_keys=True, default=str)
        provider_messages = [
            {"role": "system", "content": system},
            *messages,
            {"role": "system", "content": "Governed Calyx context for this turn:\n" + context_text},
        ]
        payload = {
            "model": self.model,
            "messages": provider_messages,
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = requests.post(self.url, headers=headers, json=payload, timeout=self.timeout)
        response.raise_for_status()
        body = response.json()
        choices = body.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise RuntimeError("CALYX_CHAT_PROVIDER_INVALID_RESPONSE")
        message = choices[0].get("message") or {}
        text = str(message.get("content") or "").strip()
        if not text:
            raise RuntimeError("CALYX_CHAT_PROVIDER_EMPTY_RESPONSE")
        return GeneratedReply(
            text=text,
            provider="openai-compatible",
            model=self.model,
            request_hash=_request_hash(payload),
            provider_response_id=str(body.get("id")) if body.get("id") else None,
        )


def configured_reply_provider() -> CalyxReplyProvider:
    if os.getenv("CALYX_CHAT_COMPLETIONS_URL", "").strip() and os.getenv("CALYX_CHAT_MODEL", "").strip():
        return OpenAICompatibleReplyProvider()
    return DeterministicGovernedReplyProvider()
