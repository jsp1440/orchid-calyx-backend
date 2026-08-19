from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

import requests

from .evidence_synthesis import build_synthesis_packet, provider_context
from .persona import conversational_system_guidance


@dataclass(frozen=True)
class GeneratedReply:
    text: str
    provider: str
    model: str
    request_hash: str
    provider_response_id: str | None = None


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
    """Evidence-safe fallback that composes from the same semantic packet as the LLM."""

    provider_name = "deterministic-governed"
    model_name = "calyx-semantic-summary-v2"

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

    @staticmethod
    def _evidence_statement(item: dict[str, Any]) -> str:
        return str(item.get("statement") or "").strip()

    def generate(self, *, messages: list[dict[str, str]], governed_context: dict[str, Any]) -> GeneratedReply:
        semantic = semantic_provider_context(messages, governed_context)
        packet = semantic.get("synthesis_packet") or {}
        payload = {"messages": messages, "semantic_context": semantic}
        if governed_context.get("casual"):
            text = "Hello. I’m Calyx, the Orchid Continuum’s governed scientific workspace. I can discuss a question conversationally, connect evidence across the Continuum, and keep inference and uncertainty visible."
            return GeneratedReply(text=text, provider=self.provider_name, model=self.model_name, request_hash=_request_hash(payload))

        mission_error = governed_context.get("mission_error")
        if mission_error:
            text = (
                "I could not complete a governed Brain mission for this turn, so I will not present a scientific conclusion as established.\n\n"
                f"Mission status: {mission_error}\n\n"
                "Evidence vs inference: any available records remain evidence inputs, not an established conclusion."
            )
            return GeneratedReply(text=text, provider=self.provider_name, model=self.model_name, request_hash=_request_hash(payload))

        conclusions = packet.get("candidate_conclusions") or []
        evidence = packet.get("evidence_items") or []
        reconciliation = packet.get("reconciliation") or {}
        supporting_ids = set(reconciliation.get("supporting_evidence_ids") or [])
        contradicting_ids = set(reconciliation.get("contradicting_evidence_ids") or [])
        supporting = [item for item in evidence if item.get("evidence_id") in supporting_ids]
        contradicting = [item for item in evidence if item.get("evidence_id") in contradicting_ids]
        missing = reconciliation.get("missing_evidence") or []
        mission = governed_context.get("mission") or {}
        lines: list[str] = []

        if conclusions:
            lines.append("Scientific conclusion: " + " ".join(str(item.get("text") or "").strip() for item in conclusions[:2] if str(item.get("text") or "").strip()))
        elif evidence:
            strongest = [self._evidence_statement(item) for item in evidence if self._evidence_statement(item)][:3]
            lines.append("Scientific conclusion: the available governed evidence is relevant, but it does not yet justify a stronger integrated conclusion." + ((" The strongest available evidence is: " + "; ".join(strongest) + ".") if strongest else ""))
        else:
            lines.append("Scientific conclusion: no evidence-grounded conclusion could be justified from the governed synthesis packet.")

        if supporting:
            lines.append("Evidence summary: " + "; ".join(self._evidence_statement(item) for item in supporting[:4] if self._evidence_statement(item)))
            lines.append(f"Supporting evidence count: {len(supporting)}.")
        elif not conclusions:
            # Preserve the explicit no-evidence diagnostic when no conclusion exists,
            # but keep successful mission fallbacks compact so follow-up turns retain
            # the preceding user question inside the bounded conversation window.
            lines.append("Evidence summary: the mission did not surface any supporting evidence records that could justify a conclusion.")

        if contradicting:
            lines.append("Disagreements or conflicting evidence: " + "; ".join(self._evidence_statement(item) for item in contradicting[:4] if self._evidence_statement(item)))
        if missing:
            lines.append("Limitations and uncertainty: missing or incomplete evidence for " + "; ".join(str(item) for item in missing[:8]) + ".")
        confidence = mission.get("confidence")
        if confidence is not None and (supporting or contradicting or missing):
            lines.append(f"Strength of evidence: provisional backend confidence {float(confidence):.2f}; this remains an inference pending human scientific review.")
        citations = self._citations(mission)
        if citations:
            lines.append("Supporting sources/citations: " + "; ".join(citations[:5]))
        artifacts = mission.get("artifacts") or {}
        identifiers = []
        if artifacts.get("evidence_packet_id"):
            identifiers.append(f"evidence packet {artifacts['evidence_packet_id']}")
        if artifacts.get("interpretation_id"):
            identifiers.append(f"interpretation {artifacts['interpretation_id']}")
        if identifiers:
            lines.append("Governed provenance: " + ", ".join(identifiers) + ".")
        if supporting or contradicting or missing or citations or identifiers:
            lines.append("Evidence vs inference: source evidence and extracted evidence remain distinct from this provisional synthesis, which is not reviewed or published knowledge.")
        return GeneratedReply(text="\n\n".join(line for line in lines if line), provider=self.provider_name, model=self.model_name, request_hash=_request_hash(payload))


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
