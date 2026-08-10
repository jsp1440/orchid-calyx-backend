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
    """Safe fallback that never invents facts outside supplied governed context.

    This provider also makes server-side conversation usable when no external model
    provider has been configured, while keeping the limitation explicit in metadata.
    Its identity is persisted on each reply so a fallback can never masquerade as a
    configured generative model.
    """

    provider_name = "deterministic-governed"
    model_name = "calyx-governed-summary-v1"

    @staticmethod
    def _format_mission_answer(mission: dict[str, Any]) -> list[str]:
        lines: list[str] = []
        conclusions = mission.get("conclusions") or []
        supporting = mission.get("supporting_evidence") or []
        contradicting = mission.get("contradicting_evidence") or []
        missing = mission.get("missing_evidence") or []
        artifacts = mission.get("artifacts") or {}

        conclusion_texts = [
            str(item.get("text") or "").strip()
            for item in conclusions
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
        if conclusion_texts:
            lines.append("Scientific conclusion: " + " ".join(conclusion_texts))
        else:
            lines.append(
                "Scientific conclusion: no evidence-grounded conclusion could be justified from the governed mission output."
            )

        if supporting:
            lines.append(
                "Evidence summary: "
                + "; ".join(
                    DeterministicGovernedReplyProvider._supporting_evidence_summary(item)
                    for item in supporting[:5]
                )
            )
            lines.append(
                f"Supporting evidence count: {len(supporting)}."
            )
        else:
            lines.append(
                "Evidence summary: the mission did not surface any supporting evidence records that could justify a conclusion."
            )

        if contradicting:
            lines.append(
                "Disagreements or conflicting evidence: "
                + "; ".join(
                    DeterministicGovernedReplyProvider._contradicting_evidence_summary(item)
                    for item in contradicting[:5]
                )
            )

        if missing:
            lines.append(
                "Limitations and uncertainty: missing or incomplete evidence for "
                + "; ".join(str(item) for item in missing[:8])
                + "."
            )

        confidence = mission.get("confidence")
        if confidence is not None:
            lines.append(
                f"Strength of evidence: provisional backend confidence {float(confidence):.2f}; this remains an inference pending human scientific review."
            )

        citations = DeterministicGovernedReplyProvider._collect_citations(mission)
        if citations:
            lines.append("Supporting sources/citations: " + "; ".join(citations[:5]))

        evidence_packet_id = artifacts.get("evidence_packet_id")
        interpretation_id = artifacts.get("interpretation_id")
        if evidence_packet_id or interpretation_id:
            identifiers: list[str] = []
            if evidence_packet_id:
                identifiers.append(f"evidence packet {evidence_packet_id}")
            if interpretation_id:
                identifiers.append(f"interpretation {interpretation_id}")
            lines.append("Governed provenance: " + ", ".join(identifiers) + ".")

        lines.append(
            "Evidence vs inference: source evidence and extracted evidence remain distinct from this provisional synthesis, which is not reviewed or published knowledge."
        )
        lines.append(
            "Relevant terminology: supporting evidence, contradicting evidence, missing evidence, provisional synthesis, human review required."
        )
        return lines

    @staticmethod
    def _supporting_evidence_summary(item: Any) -> str:
        if not isinstance(item, dict):
            return str(item)
        subject = item.get("subject")
        predicate = item.get("predicate")
        value = item.get("value")
        parts = [str(value) for value in (subject, predicate, value) if value not in (None, "")]
        if parts:
            return " ".join(parts)
        return str(item.get("candidate_id") or "unlabeled supporting evidence")

    @staticmethod
    def _contradicting_evidence_summary(item: Any) -> str:
        if not isinstance(item, dict):
            return str(item)
        candidate_id = item.get("candidate_id")
        subject = item.get("subject")
        predicate = item.get("predicate")
        value = item.get("value")
        parts = [str(value) for value in (subject, predicate, value) if value not in (None, "")]
        label = " ".join(parts) if parts else "conflicting evidence"
        if candidate_id is not None:
            return f"{label} (candidate {candidate_id})"
        return label

    @staticmethod
    def _collect_citations(mission: dict[str, Any]) -> list[str]:
        citations: list[str] = []
        seen: set[str] = set()
        for result in mission.get("sources") or []:
            if not isinstance(result, dict):
                continue
            citation = result.get("citation") or {}
            title = citation.get("document_title") or result.get("title") or result.get("object_type")
            locator = citation.get("locator")
            revision = citation.get("revision_id")
            parts = [str(title).strip()] if title else []
            if locator:
                parts.append(f"locator={locator}")
            if revision:
                parts.append(f"revision={revision}")
            summary = "; ".join(parts).strip()
            if summary and summary not in seen:
                seen.add(summary)
                citations.append(summary)
        return citations

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
        if governed_context.get("casual"):
            lines.append(
                "Hello. I’m Calyx, the Orchid Continuum’s governed scientific workspace. "
                "I can discuss a question conversationally, retrieve Continuum evidence, run a governed Brain mission when a scientific question needs it, and keep the evidence and publication boundaries visible."
            )
        elif mission:
            lines.extend(self._format_mission_answer(mission))
            lines.append("This answer remains review-bound and is not automatically published knowledge.")
        elif governed_context.get("mission_error"):
            lines.append(
                "I could not complete a governed Brain mission for this turn, so I will not present a scientific conclusion as established."
            )
            lines.append("Mission status: " + str(governed_context["mission_error"]))
            if retrieval.get("results"):
                lines.append(
                    f"I did retrieve {retrieval.get('total_eligible_results', len(retrieval['results']))} eligible evidence objects that can be inspected while the mission gap is repaired."
                )
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
        if question and not governed_context.get("casual"):
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
            "For casual conversation, be natural and concise. For scientific questions, explain what is supported and what remains uncertain. "
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
