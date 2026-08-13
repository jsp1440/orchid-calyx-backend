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
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _scientific_system_prompt() -> str:
    return (
        "You are Calyx, the Orchid Continuum's governed scientific collaborator. "
        "Use only the supplied conversation and governed context for factual scientific claims. "
        "The context may contain local indexed evidence, review-required Europe PMC literature discovery, "
        "Brain mission output, current NOAA CPC seasonal climate products, and canonical read-only Knowledge Graph context. "
        "Integrate these sources when relevant and explicitly distinguish local governed evidence, external unreviewed literature, "
        "time-sensitive climate forecasts, canonical graph facts, horticultural observations, inference, uncertainty, and missing evidence. "
        "Never treat a climate forecast as evidence of orchid physiology. Never treat an external literature discovery record as canonical "
        "Continuum evidence until review/indexing says so. Never claim a capability is implemented unless the governed context says it is. "
        "When comparing several orchid groups, use a compact markdown table when useful. Do not generalize one Dendrobium physiological group "
        "to the entire genus. Give DOI/PMID identifiers when supplied. Do not publish, promote Candidate Knowledge, or mutate the Knowledge Graph."
    )


class DeterministicGovernedReplyProvider:
    """Safe fallback that never invents facts outside supplied governed context."""

    provider_name = "deterministic-governed"
    model_name = "calyx-governed-summary-v1"

    @staticmethod
    def _supporting_evidence_summary(item: Any) -> str:
        if not isinstance(item, dict):
            return str(item)
        parts = [
            str(value)
            for value in (item.get("subject"), item.get("predicate"), item.get("value"))
            if value not in (None, "")
        ]
        return " ".join(parts) if parts else str(item.get("candidate_id") or "unlabeled supporting evidence")

    @staticmethod
    def _contradicting_evidence_summary(item: Any) -> str:
        if not isinstance(item, dict):
            return str(item)
        candidate_id = item.get("candidate_id")
        parts = [
            str(value)
            for value in (item.get("subject"), item.get("predicate"), item.get("value"))
            if value not in (None, "")
        ]
        label = " ".join(parts) if parts else "conflicting evidence"
        return f"{label} (candidate {candidate_id})" if candidate_id is not None else label

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

    @classmethod
    def _format_mission_answer(cls, mission: dict[str, Any]) -> list[str]:
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
                "Canonical Brain mission conclusion: no conclusion was produced from reviewed/indexed evidence for this turn."
            )
        if supporting:
            lines.append(
                "Canonical evidence summary: "
                + "; ".join(cls._supporting_evidence_summary(item) for item in supporting[:5])
            )
            lines.append(f"Supporting evidence count: {len(supporting)}.")
        else:
            lines.append(
                "Canonical evidence status: the Brain mission did not surface supporting indexed evidence records. External literature discovery, when present below, remains a separate review-required evidence tier."
            )
        if contradicting:
            lines.append(
                "Disagreements or conflicting evidence: "
                + "; ".join(cls._contradicting_evidence_summary(item) for item in contradicting[:5])
            )
        if missing:
            lines.append(
                "Limitations and uncertainty: missing or incomplete canonical evidence for "
                + "; ".join(str(item) for item in missing[:8])
                + "."
            )
        confidence = mission.get("confidence")
        if confidence is not None:
            lines.append(
                f"Strength of canonical evidence: provisional backend confidence {float(confidence):.2f}; human scientific review remains required."
            )
        citations = cls._collect_citations(mission)
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
            "Evidence vs inference: canonical source evidence, external discovery records, and provisional synthesis remain distinct and review-bound."
        )
        return lines

    @staticmethod
    def _format_continuum_context(context: dict[str, Any]) -> list[str]:
        taxa = context.get("taxa") or []
        if not taxa:
            return []
        lines = [
            "Orchid Continuum context: canonical Knowledge Graph taxa were resolved automatically for this question."
        ]
        for item in taxa[:12]:
            genus = str(item.get("genus") or "unknown taxon")
            graph = item.get("knowledge_graph") or {}
            brain = item.get("brain_graph") or {}
            environmental = item.get("environmental_facts") or []
            suffix = f"; environmental graph facts={len(environmental)}" if environmental else ""
            lines.append(
                f"- {genus}: Knowledge Graph nodes={len(graph.get('nodes') or [])}, "
                f"edges={len(graph.get('edges') or [])}; Brain graph nodes={len(brain.get('nodes') or [])}{suffix}."
            )
        lines.append(
            "Graph context is read-only supporting context; it does not by itself establish a literature-backed horticultural conclusion."
        )
        return lines

    @staticmethod
    def _format_external_literature(retrieval: dict[str, Any]) -> list[str]:
        external = retrieval.get("external_literature") or {}
        records = external.get("results") or []
        if not records:
            status = external.get("status")
            if status in {"empty", "unavailable"}:
                return [f"External literature discovery status: Europe PMC {status}."]
            return []
        lines = [
            f"External literature discovery: Europe PMC returned {len(records)} review-required records because local indexed coverage was insufficient."
        ]
        for index, record in enumerate(records[:8], start=1):
            title = str(record.get("title") or "Untitled publication")
            authors = str(record.get("authors") or "").strip()
            date = str(record.get("publication_date") or "").strip()
            doi = str(record.get("doi") or "").strip()
            pmid = str(record.get("pmid") or "").strip()
            abstract = str(record.get("abstract") or "").strip().replace("\n", " ")
            ids = ", ".join(value for value in (f"DOI {doi}" if doi else "", f"PMID {pmid}" if pmid else "") if value)
            citation_parts = [value for value in (authors, date, ids) if value]
            citation = "; ".join(citation_parts)
            lines.append(
                f"{index}. {title}" + (f" — {citation}" if citation else "") + (f": {abstract[:650]}" if abstract else "")
            )
        lines.append(
            "These records are external discovery context, not yet reviewed/indexed Orchid Continuum evidence and not automatically promoted to canonical knowledge."
        )
        return lines

    @staticmethod
    def _format_climate_context(climate: dict[str, Any]) -> list[str]:
        products = climate.get("products") or []
        if not products:
            return []
        lines = [
            "Current seasonal climate context: NOAA/NWS Climate Prediction Center products were retrieved for this climate-sensitive question."
        ]
        for product in products[:2]:
            name = str(product.get("product") or "climate discussion")
            issued = str(product.get("issued_text") or "").strip()
            points = product.get("summary_points") or []
            lines.append(f"- {name}" + (f" ({issued})" if issued else "") + ":")
            for point in points[:6]:
                lines.append("  • " + str(point))
        lines.append(
            "Climate products are time-sensitive external context; they describe forecast conditions and do not establish orchid physiological responses by themselves."
        )
        return lines

    def generate(
        self,
        *,
        messages: list[dict[str, str]],
        governed_context: dict[str, Any],
    ) -> GeneratedReply:
        payload = {"messages": messages, "governed_context": governed_context}
        mission = governed_context.get("mission")
        retrieval = governed_context.get("retrieval") or {}
        continuum = governed_context.get("continuum") or {}
        climate = governed_context.get("climate") or {}
        question = next(
            (item["content"] for item in reversed(messages) if item.get("role") == "user"),
            "",
        )
        lines: list[str] = []
        if governed_context.get("casual"):
            lines.append(
                "Hello. I’m Calyx, the Orchid Continuum’s governed scientific workspace. I can retrieve Continuum evidence, discover external literature when local coverage is incomplete, consult NOAA CPC climate context, run governed Brain missions, and keep evidence boundaries visible."
            )
        else:
            # Put useful discovered evidence before the canonical-mission limitation so an
            # empty canonical index no longer hides successful external retrieval.
            lines.extend(self._format_external_literature(retrieval))
            lines.extend(self._format_climate_context(climate))
            lines.extend(self._format_continuum_context(continuum))
            if mission:
                lines.extend(self._format_mission_answer(mission))
            elif governed_context.get("mission_error"):
                lines.append(
                    "Governed Brain mission status: the mission could not complete, so no canonical scientific conclusion is presented."
                )
                lines.append("Mission status: " + str(governed_context["mission_error"]))
            elif retrieval.get("results"):
                lines.append(
                    f"Local indexed retrieval returned {retrieval.get('total_eligible_results', len(retrieval['results']))} eligible evidence objects."
                )
            elif not (retrieval.get("external_literature") or {}).get("results"):
                lines.append(
                    "I do not yet have enough governed or discovered scientific evidence to answer substantively without guessing."
                )
            lines.append("This answer remains review-bound and is not automatically published knowledge.")
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
    """Server-configured OpenAI-compatible chat-completions provider."""

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
        context_text = json.dumps(governed_context, sort_keys=True, default=str)
        provider_messages = [
            {"role": "system", "content": _scientific_system_prompt()},
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
            provider=self.provider_name,
            model=self.model,
            request_hash=_request_hash(payload),
            provider_response_id=str(body.get("id")) if body.get("id") else None,
        )


class OpenAIResponsesReplyProvider:
    """Reuse the existing Calyx Agent OpenAI configuration for Speak with Calyx.

    This removes the accidental requirement for a second set of chat-specific secrets.
    If CALYX_AGENT_PROVIDER=openai, CALYX_AGENT_MODEL and OPENAI_API_KEY are already
    configured for the agent, Speak can use the same governed model boundary.
    """

    provider_name = "openai"

    def __init__(self) -> None:
        provider = os.getenv("CALYX_AGENT_PROVIDER", "").strip().casefold()
        self.model = os.getenv("CALYX_AGENT_MODEL", "").strip()
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.base_url = os.getenv("CALYX_AGENT_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.timeout = max(1.0, min(float(os.getenv("CALYX_AGENT_TIMEOUT_SECONDS", "45")), 120.0))
        self.max_tokens = max(128, min(int(os.getenv("CALYX_CHAT_MAX_TOKENS", "2200")), 6000))
        if provider != "openai" or not self.model or not self.api_key:
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
                if not isinstance(content, dict):
                    continue
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n\n".join(parts)

    def generate(self, *, messages: list[dict[str, str]], governed_context: dict[str, Any]) -> GeneratedReply:
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
                        "content": [{"type": "input_text", "text": str(item.get("content") or "")}],
                    }
                    for item in messages
                    if item.get("role") in {"user", "assistant"}
                ],
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Governed Calyx context for this turn:\n" + json.dumps(governed_context, sort_keys=True, default=str),
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


def configured_reply_provider() -> CalyxReplyProvider:
    if os.getenv("CALYX_CHAT_COMPLETIONS_URL", "").strip() and os.getenv("CALYX_CHAT_MODEL", "").strip():
        return OpenAICompatibleReplyProvider()
    if (
        os.getenv("CALYX_AGENT_PROVIDER", "").strip().casefold() == "openai"
        and os.getenv("CALYX_AGENT_MODEL", "").strip()
        and os.getenv("OPENAI_API_KEY", "").strip()
    ):
        return OpenAIResponsesReplyProvider()
    return DeterministicGovernedReplyProvider()
