from __future__ import annotations

from contextlib import contextmanager
from typing import Any
import re
import secrets
import time


_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID = re.compile(r"^[0-9a-f]{16}$")
_FORBIDDEN_KEYS = ("prompt", "message", "answer", "excerpt", "secret", "token_value", "chain_of_thought", "latitude", "longitude")


def _safe_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in attributes.items():
        normalized = key.casefold()
        if any(forbidden in normalized for forbidden in _FORBIDDEN_KEYS):
            continue
        if value is None or isinstance(value, (str, int, float, bool)):
            safe[key] = value
        elif isinstance(value, list) and all(isinstance(item, (str, int, float, bool)) for item in value):
            safe[key] = list(value)
    return safe


class ScientificTrace:
    """Content-free, vendor-neutral trace for one governed Calyx execution."""

    schema_version = "calyx.scientific-observability.v1"

    def __init__(self, operation: str) -> None:
        self.trace_id = secrets.token_hex(16)
        self.root_span_id = secrets.token_hex(8)
        self.operation = operation
        self._started_ns = time.perf_counter_ns()
        self._spans: list[dict[str, Any]] = []
        self._terminal_error: str | None = None

    @contextmanager
    def span(self, name: str, **attributes: Any):
        started_ns = time.perf_counter_ns()
        span_id = secrets.token_hex(8)
        mutable_attributes = _safe_attributes(attributes)
        status = "ok"
        error_type: str | None = None
        try:
            yield mutable_attributes
        except Exception as exc:
            status = "error"
            error_type = type(exc).__name__
            self._terminal_error = error_type
            raise
        finally:
            span = {
                "name": name,
                "span_id": span_id,
                "parent_span_id": self.root_span_id,
                "status": status,
                "duration_ms": round((time.perf_counter_ns() - started_ns) / 1_000_000, 3),
                "attributes": _safe_attributes(mutable_attributes),
            }
            if error_type is not None:
                span["error_type"] = error_type
            self._spans.append(span)

    def _evaluations(self, retrieval: dict[str, Any] | None) -> list[dict[str, Any]]:
        if retrieval is None:
            return [
                {"name": name, "status": "unknown", "reason": "retrieval_not_completed"}
                for name in (
                    "retrieval_grounding",
                    "provenance_completeness",
                    "citation_support_availability",
                    "counterevidence_visibility",
                    "uncertainty_disclosure",
                    "circular_self_evidence_risk",
                    "locality_protection",
                )
            ]

        results = retrieval.get("results") or []
        if not results:
            grounding = {"name": "retrieval_grounding", "status": "insufficient_evidence", "reason": "no_eligible_evidence"}
            provenance = {"name": "provenance_completeness", "status": "unknown", "reason": "no_evidence_to_evaluate"}
            citation = {"name": "citation_support_availability", "status": "unknown", "reason": "no_evidence_to_evaluate"}
        else:
            grounding = {"name": "retrieval_grounding", "status": "pass", "evidence_objects": len(results)}
            complete = 0
            supported = 0
            for result in results:
                cite = result.get("citation") or {}
                if (cite.get("document_title") or cite.get("source_type")) and (cite.get("locator") or cite.get("revision_id")):
                    complete += 1
                if result.get("authorized_excerpt") or cite.get("locator"):
                    supported += 1
            provenance = {
                "name": "provenance_completeness",
                "status": "pass" if complete == len(results) else "incomplete",
                "complete": complete,
                "total": len(results),
            }
            citation = {
                "name": "citation_support_availability",
                "status": "pass" if supported == len(results) else "incomplete",
                "supported": supported,
                "total": len(results),
            }

        generated_types = {"calyx_answer", "calyx_hypothesis", "conversation", "generated_interpretation"}
        self_generated = sum(1 for result in results if str(result.get("object_type", "")).casefold() in generated_types)
        circular = {
            "name": "circular_self_evidence_risk",
            "status": "pass" if self_generated == 0 else "review_required",
            "self_generated_evidence_objects": self_generated,
        }
        counterevidence_count = retrieval.get("counterevidence_count")
        counterevidence = (
            {"name": "counterevidence_visibility", "status": "unknown", "reason": "retrieval_contract_does_not_report_counterevidence"}
            if counterevidence_count is None
            else {"name": "counterevidence_visibility", "status": "observed", "count": int(counterevidence_count)}
        )
        locality_state = retrieval.get("locality_protection_state")
        locality = (
            {"name": "locality_protection", "status": "unknown", "reason": "retrieval_contract_does_not_report_locality_policy"}
            if locality_state is None
            else {"name": "locality_protection", "status": str(locality_state)}
        )
        uncertainty = {
            "name": "uncertainty_disclosure",
            "status": "unknown",
            "reason": "current_conversation_contract_does_not_emit_claim_uncertainty",
        }
        return [grounding, provenance, citation, counterevidence, uncertainty, circular, locality]

    def finish(self, retrieval: dict[str, Any] | None = None) -> dict[str, Any]:
        assert _TRACE_ID.fullmatch(self.trace_id)
        assert _SPAN_ID.fullmatch(self.root_span_id)
        evidence_ids = []
        for result in (retrieval or {}).get("results") or []:
            identifier = result.get("object_id") or result.get("evidence_id") or result.get("id")
            if identifier is not None:
                evidence_ids.append(str(identifier))
        return {
            "schema_version": self.schema_version,
            "trace_id": self.trace_id,
            "root_span_id": self.root_span_id,
            "operation": self.operation,
            "status": "error" if self._terminal_error else "ok",
            "duration_ms": round((time.perf_counter_ns() - self._started_ns) / 1_000_000, 3),
            "error_type": self._terminal_error,
            "spans": list(self._spans),
            "evidence_identifiers": evidence_ids,
            "provider": {
                "name": None,
                "model": None,
                "fallback_position": None,
                "input_tokens": None,
                "output_tokens": None,
                "estimated_cost_usd": None,
                "measurement_state": "unavailable",
            },
            "scientific_evaluations": self._evaluations(retrieval),
            "governance": {
                "content_recorded": False,
                "private_reasoning_recorded": False,
                "protected_coordinates_recorded": False,
                "knowledge_graph_mutation": False,
                "publication_authority": "none",
            },
        }
