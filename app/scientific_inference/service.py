from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from .models import InferenceDomain, InferenceState, ScientificInferenceEnvelope

SCHEMA = "calyx-scientific-inference/v1"
ALGORITHM_VERSION = "scian-confidence-1"


class ScientificInferenceService:
    """Build review-required scientific inferences from canonical evidence aggregates.

    The service is deliberately non-persistent. Aggregate records remain authoritative in
    the Brain/evidence-aggregation layer. This service only evaluates the evidence envelope
    supplied to it and cannot publish, review, or mutate the Knowledge Graph.
    """

    def build(
        self,
        *,
        domain: InferenceDomain | str,
        statement: str,
        aggregates: Iterable[dict[str, Any]],
        assumptions: Iterable[str] = (),
        limitations: Iterable[str] = (),
    ) -> ScientificInferenceEnvelope:
        statement = " ".join(statement.split())
        if not statement:
            raise ValueError("INFERENCE_STATEMENT_REQUIRED")
        aggregate_list = list(aggregates)
        if not aggregate_list:
            raise ValueError("CANONICAL_EVIDENCE_AGGREGATES_REQUIRED")

        domain_value = InferenceDomain(domain)
        refs = tuple(self._aggregate_ref(item) for item in aggregate_list)
        anchors = tuple(self._source_anchor_refs(aggregate_list))
        components, conflicts, derived_limitations = self._confidence(aggregate_list)
        score = self._weighted_confidence(components, conflicts)
        state = self._state(aggregate_list, score, conflicts, anchors)
        confidence_band = self._band(score)
        normalized_assumptions = tuple(sorted({" ".join(x.split()) for x in assumptions if x.strip()}))
        normalized_limitations = tuple(
            sorted(
                {
                    *[" ".join(x.split()) for x in limitations if x.strip()],
                    *derived_limitations,
                }
            )
        )
        identity_payload = {
            "schema": SCHEMA,
            "algorithm_version": ALGORITHM_VERSION,
            "domain": domain_value.value,
            "statement": statement,
            "aggregate_refs": refs,
            "assumptions": normalized_assumptions,
        }
        inference_id = "sciinf_" + hashlib.sha256(
            json.dumps(identity_payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()

        return ScientificInferenceEnvelope(
            schema=SCHEMA,
            inference_id=inference_id,
            domain=domain_value,
            statement=statement,
            state=state,
            aggregate_refs=refs,
            source_anchor_refs=anchors,
            confidence_score=score,
            confidence_band=confidence_band,
            confidence_components=components,
            conflict_summary=conflicts,
            assumptions=normalized_assumptions,
            known_limitations=normalized_limitations,
            provenance={
                "authority": "canonical_evidence_aggregates",
                "algorithm_version": ALGORITHM_VERSION,
                "aggregate_identity_fields": ["aggregate_id", "aggregate_version_id", "identity_hash"],
                "evidence_not_rewritten": True,
                "inference_is_not_source_evidence": True,
            },
        )

    @staticmethod
    def _aggregate_ref(aggregate: dict[str, Any]) -> dict[str, Any]:
        required = ("aggregate_id", "aggregate_version_id", "aggregate_type", "identity_hash")
        missing = [key for key in required if aggregate.get(key) in (None, "")]
        if missing:
            raise ValueError(f"AGGREGATE_IDENTITY_REQUIRED:{','.join(missing)}")
        return {
            "aggregate_id": aggregate["aggregate_id"],
            "aggregate_version_id": aggregate["aggregate_version_id"],
            "aggregate_type": aggregate["aggregate_type"],
            "identity_hash": aggregate["identity_hash"],
            "aggregate_status": aggregate.get("aggregate_status"),
            "review_state": aggregate.get("review_state"),
            "verification_state": aggregate.get("verification_state"),
            "published": bool(aggregate.get("published", False)),
        }

    @staticmethod
    def _source_anchor_refs(aggregates: list[dict[str, Any]]) -> Iterable[dict[str, Any]]:
        seen: set[tuple[Any, Any, tuple[Any, ...]]] = set()
        for aggregate in aggregates:
            for link in aggregate.get("source_anchor_links", ()):
                anchor_ids = tuple(link.get("anchor_ids") or ())
                key = (link.get("candidate_id"), link.get("revision_id"), anchor_ids)
                if key in seen:
                    continue
                seen.add(key)
                yield {
                    "candidate_id": link.get("candidate_id"),
                    "source_revision_id": link.get("revision_id"),
                    "source_anchor_ids": anchor_ids,
                }

    def _confidence(
        self, aggregates: list[dict[str, Any]]
    ) -> tuple[dict[str, float | None], dict[str, int], set[str]]:
        summaries = [item.get("confidence_dimensions") or {} for item in aggregates]
        components: dict[str, float | None] = {
            "source_confidence": self._mean(
                min(1.0, 0.35 + 0.15 * float(summary.get("independent_sources", 0)))
                for summary in summaries
            ),
            "anchor_completeness": self._mean_optional(
                summary.get("anchor_completeness") for summary in summaries
            ),
            "identity_resolution_confidence": self._mean_optional(
                summary.get("taxon_link_certainty") for summary in summaries
            ),
            "methodological_confidence": self._mean_optional(
                summary.get("method_compatibility") for summary in summaries
            ),
            "context_compatibility": self._mean_optional(
                self._context_compatibility(summary) for summary in summaries
            ),
            "independent_corroboration": self._mean(self._corroboration(summary) for summary in summaries),
            "review_confidence": self._mean_optional(
                summary.get("review_completeness") for summary in summaries
            ),
        }
        conflicts = {
            "contradicting_assertions": sum(int(x.get("contradicting_assertions", 0)) for x in summaries),
            "unresolved_assertions": sum(int(x.get("unresolved_assertions", 0)) for x in summaries),
            "supporting_assertions": sum(int(x.get("supporting_assertions", 0)) for x in summaries),
        }
        limitations: set[str] = set()
        if components["identity_resolution_confidence"] is None:
            limitations.add("IDENTITY_RESOLUTION_CONFIDENCE_UNAVAILABLE")
        if components["methodological_confidence"] is None:
            limitations.add("METHODOLOGICAL_CONFIDENCE_UNAVAILABLE")
        if components["review_confidence"] in (None, 0.0):
            limitations.add("HUMAN_REVIEW_INCOMPLETE")
        if conflicts["contradicting_assertions"]:
            limitations.add("CONTRADICTORY_EVIDENCE_PRESENT")
        if conflicts["unresolved_assertions"]:
            limitations.add("UNRESOLVED_EVIDENCE_RELATIONSHIPS_PRESENT")
        return components, conflicts, limitations

    @staticmethod
    def _context_compatibility(summary: dict[str, Any]) -> float | None:
        values = [
            summary.get("temporal_compatibility"),
            summary.get("geographic_compatibility"),
        ]
        present = [float(value) for value in values if isinstance(value, (int, float))]
        return sum(present) / len(present) if present else None

    @staticmethod
    def _corroboration(summary: dict[str, Any]) -> float:
        support = int(summary.get("supporting_assertions", 0))
        contradict = int(summary.get("contradicting_assertions", 0))
        unresolved = int(summary.get("unresolved_assertions", 0))
        independent = int(summary.get("independent_sources", 0))
        relationship_score = (support + 1.0) / (support + contradict + unresolved + 1.0)
        independence_score = min(1.0, independent / 3.0)
        return 0.6 * relationship_score + 0.4 * independence_score

    @staticmethod
    def _mean(values: Iterable[float]) -> float:
        values = list(values)
        return sum(values) / len(values)

    @staticmethod
    def _mean_optional(values: Iterable[Any]) -> float | None:
        present = [float(value) for value in values if isinstance(value, (int, float))]
        if not present:
            return None
        return sum(present) / len(present)

    @staticmethod
    def _weighted_confidence(
        components: dict[str, float | None], conflicts: dict[str, int]
    ) -> float:
        weights = {
            "source_confidence": 0.20,
            "anchor_completeness": 0.15,
            "identity_resolution_confidence": 0.15,
            "methodological_confidence": 0.15,
            "context_compatibility": 0.10,
            "independent_corroboration": 0.15,
            "review_confidence": 0.10,
        }
        available = [(key, value) for key, value in components.items() if value is not None]
        numerator = sum(weights[key] * float(value) for key, value in available)
        denominator = sum(weights[key] for key, _ in available)
        base = numerator / denominator if denominator else 0.0
        adverse = 2 * conflicts["contradicting_assertions"] + conflicts["unresolved_assertions"]
        total = adverse + conflicts["supporting_assertions"]
        conflict_penalty = min(0.8, adverse / total) if total else 0.0
        return round(max(0.0, min(1.0, base * (1.0 - 0.5 * conflict_penalty))), 4)

    @staticmethod
    def _state(
        aggregates: list[dict[str, Any]],
        score: float,
        conflicts: dict[str, int],
        anchors: tuple[dict[str, Any], ...],
    ) -> InferenceState:
        if not anchors or score < 0.4:
            return InferenceState.INSUFFICIENT_EVIDENCE
        if conflicts["contradicting_assertions"] or conflicts["unresolved_assertions"]:
            return InferenceState.CONFLICT_REVIEW_REQUIRED
        if any(
            item.get("review_state") != "APPROVED"
            or item.get("verification_state") != "VERIFIED"
            for item in aggregates
        ):
            return InferenceState.REVIEW_REQUIRED
        return InferenceState.CANDIDATE

    @staticmethod
    def _band(score: float) -> str:
        if score >= 0.8:
            return "HIGH"
        if score >= 0.6:
            return "MODERATE"
        if score >= 0.4:
            return "LIMITED"
        return "LOW"
