from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from .conversational_synthesis import compose_conversational_answer
from .evidence_synthesis import build_synthesis_packet, provider_context
from .persona import conversational_system_guidance


@dataclass(frozen=True)
class GeneratedReply:
    text: str
    provider: str
    model: str
    request_hash: str
    provider_response_id: str | None = None
    # Claim coverage, contradictions, gaps and provenance for the inspectable
    # secondary surface. Never rendered into the conversational prose.
    synthesis_structure: dict[str, Any] | None = None


class CalyxReplyProvider(Protocol):
    def generate(self, *, messages: list[dict[str, str]], governed_context: dict[str, Any]) -> GeneratedReply: ...


def _request_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _scientific_system_prompt() -> str:
    scientific_governance = (
        "You are Calyx, the Orchid Continuum's governed scientific collaborator. "
        "Use only the supplied conversation and governed semantic synthesis context for factual scientific claims. "
        "Reason claim-by-claim across linked evidence rather than narrating source systems sequentially. "
        "Distinguish canonical evidence, review-required external literature, time-sensitive context, inference, contradiction, uncertainty, and missing evidence. "
        "Do not generalize beyond the evidence, convert correlation into causation, publish Candidate Knowledge, or mutate the Knowledge Graph."
    )
    return scientific_governance + "\n\n" + conversational_system_guidance()


def _current_question(messages: list[dict[str, str]], governed_context: dict[str, Any]) -> str:
    # A follow-up turn's literal words ("Why?") decompose into no scientific
    # claim at all. Claim decomposition therefore runs on the investigation
    # subject the turn continues, resolved server-side from conversation state.
    resolved_subject = str(governed_context.get("resolved_subject") or "").strip()
    if resolved_subject:
        return resolved_subject
    interaction = governed_context.get("interaction_context") or {}
    preserved = str(interaction.get("current_question") or "").strip()
    if preserved:
        return preserved
    for item in reversed(messages):
        if item.get("role") == "user" and str(item.get("content") or "").strip():
            return str(item["content"]).strip()
    mission = governed_context.get("mission") or {}
    return str(mission.get("question") or "").strip()


def semantic_provider_context(messages: list[dict[str, str]], governed_context: dict[str, Any]) -> dict[str, Any]:
    semantic = dict(governed_context)
    packet = semantic.get("synthesis_packet")
    if not isinstance(packet, dict) or not packet:
        packet = build_synthesis_packet(
            question=_current_question(messages, governed_context),
            retrieval=governed_context.get("retrieval") or {},
            continuum=governed_context.get("continuum") or {},
            climate=governed_context.get("climate") or {},
            mission=governed_context.get("mission"),
            mission_error=governed_context.get("mission_error"),
            interaction_context=governed_context.get("interaction_context") or {},
        )
    semantic["synthesis_packet"] = packet
    return provider_context(semantic)


class DeterministicGovernedReplyProvider:
    """Degraded composer used when no generative provider is available.

    It renders the SAME governed synthesis packet the LLM path receives, via
    ``conversational_synthesis`` -- claim-by-claim, integrated across source
    families, with machinery kept out of the prose. It previously emitted one
    labelled block per source family, which is exactly the source-inventory
    behaviour ``CALYX-EVIDENCE-SYNTHESIS-002`` exists to prevent.

    It composes; it does not reason generatively, and it says so.
    """

    provider_name = "deterministic-governed"
    model_name = "calyx-conversational-composer-v3"

    @staticmethod
    def _citations(mission: dict[str, Any] | None) -> list[str]:
        citations: list[str] = []
        seen: set[str] = set()
        for source in (mission or {}).get("sources") or []:
            if not isinstance(source, dict):
                continue
            citation = source.get("citation") or {}
            title = citation.get("document_title") or source.get("title") or source.get("object_type")
            locator = citation.get("locator")
            revision = citation.get("revision_id")
            parts = [str(title).strip()] if title else []
            if locator:
                parts.append(f"locator={locator}")
            if revision:
                parts.append(f"revision={revision}")
            rendered = "; ".join(parts)
            if rendered and rendered not in seen:
                seen.add(rendered)
                citations.append(rendered)
        return citations

    def generate(self, *, messages: list[dict[str, str]], governed_context: dict[str, Any]) -> GeneratedReply:
        semantic = semantic_provider_context(messages, governed_context)
        packet = semantic.get("synthesis_packet") or {}
        payload = {"messages": messages, "semantic_context": semantic}

        composed = compose_conversational_answer(
            packet=packet,
            history=messages,
            casual=bool(governed_context.get("casual")),
            mission_error=governed_context.get("mission_error"),
            generative=False,
            resolved_subject=governed_context.get("resolved_subject"),
            follow_up=bool(str(governed_context.get("resolved_subject") or "").strip()),
        )

        mission = governed_context.get("mission") or {}
        # Machinery stays OUT of the prose and inspectable alongside it: the
        # conversational constitution keeps identifiers, counts and confidence
        # in research details rather than the human-facing answer.
        composed.structure["citations"] = self._citations(mission)
        artifacts = mission.get("artifacts") or {}
        composed.structure["governed_provenance"] = {
            "mission_id": mission.get("mission_id"),
            "evidence_packet_id": artifacts.get("evidence_packet_id"),
            "interpretation_id": artifacts.get("interpretation_id"),
            "confidence": mission.get("confidence"),
            "review_status": mission.get("review_status"),
        }

        return GeneratedReply(
            text=composed.text,
            provider=self.provider_name,
            model=self.model_name,
            request_hash=_request_hash(payload),
            synthesis_structure=composed.structure,
        )


class OpenAICompatibleReplyProvider:
    provider_name = "openai-compatible"

    def __init__(self) -> None:
        self.url = os.getenv("CALYX_CHAT_COMPLETIONS_URL", "").strip()
        self.api_key = os.getenv("CALYX_CHAT_API_KEY", "").strip()
        self.model = os.getenv("CALYX_CHAT_MODEL", "").strip()
        self.timeout = max(1.0, min(float(os.getenv("CALYX_CHAT_TIMEOUT_SECONDS", "45")), 120.0))
        self.max_tokens = max(128, min(int(os.getenv("CALYX_CHAT_MAX_TOKENS", "2200")), 6000))
        if not self.url or not self.model:
            raise RuntimeError("CALYX_CHAT_PROVIDER_NOT_CONFIGURED")

    def generate(self, *, messages: list[dict[str, str]], governed_context: dict[str, Any]) -> GeneratedReply:
        semantic = semantic_provider_context(messages, governed_context)
        context_text = json.dumps(semantic, sort_keys=True, default=str)
        provider_messages = [{"role": "system", "content": _scientific_system_prompt()}, *messages, {"role": "system", "content": "Governed Calyx semantic synthesis context for this turn:\n" + context_text}]
        payload = {"model": self.model, "messages": provider_messages, "temperature": 0.2, "max_tokens": self.max_tokens}
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
        return GeneratedReply(text=text, provider=self.provider_name, model=self.model, request_hash=_request_hash(payload), provider_response_id=str(body.get("id")) if body.get("id") else None)


class OpenAIResponsesReplyProvider:
    provider_name = "openai"

    def __init__(self) -> None:
        configured = os.getenv("CALYX_AGENT_PROVIDER", "").strip().casefold()
        self.model = os.getenv("CALYX_AGENT_MODEL", "").strip()
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.base_url = os.getenv("CALYX_AGENT_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.timeout = max(1.0, min(float(os.getenv("CALYX_AGENT_TIMEOUT_SECONDS", "45")), 120.0))
        self.max_tokens = max(128, min(int(os.getenv("CALYX_CHAT_MAX_TOKENS", "2200")), 6000))
        if configured != "openai" or not self.model or not self.api_key:
            raise RuntimeError("CALYX_AGENT_OPENAI_PROVIDER_NOT_CONFIGURED")

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
                if isinstance(content, dict) and isinstance(content.get("text"), str) and content["text"].strip():
                    parts.append(content["text"].strip())
        return "\n\n".join(parts)

    def generate(self, *, messages: list[dict[str, str]], governed_context: dict[str, Any]) -> GeneratedReply:
        semantic = semantic_provider_context(messages, governed_context)
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": _scientific_system_prompt()}]},
                *[{"role": "assistant" if item.get("role") == "assistant" else "user", "content": [{"type": "input_text", "text": str(item.get("content") or "")}]} for item in messages if item.get("role") in {"user", "assistant"}],
                {"role": "user", "content": [{"type": "input_text", "text": "Governed Calyx semantic synthesis context for this turn:\n" + json.dumps(semantic, sort_keys=True, default=str)}]},
            ],
            "max_output_tokens": self.max_tokens,
        }
        response = requests.post(f"{self.base_url}/responses", headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, json=payload, timeout=self.timeout)
        response.raise_for_status()
        body = response.json()
        text = self._extract_text(body)
        if not text:
            raise RuntimeError("CALYX_CHAT_PROVIDER_EMPTY_RESPONSE")
        return GeneratedReply(text=text, provider=self.provider_name, model=self.model, request_hash=_request_hash(payload), provider_response_id=str(body.get("id")) if body.get("id") else None)


def configured_reply_provider() -> CalyxReplyProvider:
    if os.getenv("CALYX_CHAT_COMPLETIONS_URL", "").strip() and os.getenv("CALYX_CHAT_MODEL", "").strip():
        return OpenAICompatibleReplyProvider()
    if os.getenv("CALYX_AGENT_PROVIDER", "").strip().casefold() == "openai" and os.getenv("CALYX_AGENT_MODEL", "").strip() and os.getenv("OPENAI_API_KEY", "").strip():
        return OpenAIResponsesReplyProvider()
    return DeterministicGovernedReplyProvider()
