from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from .models import (
    CONTEXT_DIMENSIONS,
    AssertionRequest,
    CompletenessState,
    ContextForm,
    InterpretationRequest,
    PromotionPath,
    RoutingPolicy,
    SourceEvidenceReference,
)
from .repository import InterpretationRepository


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class ScientificInterpretationService:
    def __init__(self, repository: InterpretationRepository) -> None:
        self.repository = repository

    def construct_packet(
        self,
        *,
        packet_key: str,
        context_form: ContextForm,
        sources: tuple[SourceEvidenceReference, ...],
        context_dimensions: dict[str, CompletenessState],
        material_dimensions: tuple[str, ...],
        structural_relationships: tuple[dict[str, Any], ...],
        construction_policy_version: str,
        boundary_analyzer_version: str,
        construction_rationale: str,
    ) -> dict[str, Any]:
        if not packet_key.strip() or not sources or not construction_rationale.strip():
            raise ValueError("INCOMPLETE_EVIDENCE_PACKET")
        unknown_dimensions = set(context_dimensions) - set(CONTEXT_DIMENSIONS)
        if unknown_dimensions:
            raise ValueError("UNKNOWN_CONTEXT_DIMENSION")
        if set(material_dimensions) - set(context_dimensions):
            raise ValueError("MATERIAL_CONTEXT_DIMENSION_UNASSESSED")
        if context_form in {ContextForm.LINKED_SENTENCES, ContextForm.METHODS_RESULTS} and not structural_relationships:
            raise ValueError("LINKED_CONTEXT_RELATIONSHIP_REQUIRED")
        if context_form is ContextForm.TABLE_WITH_HEADERS:
            relationships = {item.get("relationship") for item in structural_relationships}
            if not {"ROW_HEADER", "COLUMN_HEADER"}.issubset(relationships):
                raise ValueError("TABLE_HEADERS_REQUIRED")
        if context_form is ContextForm.FIGURE_WITH_CAPTION and "CAPTION" not in {item.get("relationship") for item in structural_relationships}:
            raise ValueError("FIGURE_CAPTION_REQUIRED")

        ordered_sources = sorted(
            (asdict(source) for source in sources),
            key=lambda value: (value["source_object_type"], value["source_object_id"], value["source_revision_id"]),
        )
        payload = {
            "packet_key": packet_key,
            "context_form": context_form.value,
            "sources": ordered_sources,
            "context_dimensions": {key: value.value for key, value in sorted(context_dimensions.items())},
            "material_dimensions": sorted(material_dimensions),
            "structural_relationships": list(structural_relationships),
            "construction_policy_version": construction_policy_version,
            "boundary_analyzer_version": boundary_analyzer_version,
            "construction_rationale": construction_rationale,
        }
        payload["fingerprint"] = fingerprint(payload)
        existing = self.repository.packet_by_fingerprint(payload["fingerprint"])
        if existing:
            return existing
        material_states = [context_dimensions[name] for name in material_dimensions]
        payload["state"] = (
            "PACKET_INCOMPLETE"
            if any(value in {CompletenessState.AMBIGUOUS, CompletenessState.UNKNOWN} for value in material_states)
            else "PACKET_RESTRICTED"
            if any(source.copyright_policy in {"METADATA_ONLY", "UNKNOWN_REQUIRES_REVIEW"} for source in sources)
            else "PACKET_COMPLETE"
        )
        saved = self.repository.save_packet(payload)
        self.repository.audit("EVIDENCE_PACKET_CREATED", "EVIDENCE_PACKET", saved["packet_id"], {"fingerprint": saved["fingerprint"], "version": saved["version"]}, "packet-builder")
        return saved

    def interpret(self, request: InterpretationRequest, *, supersedes_interpretation_id: int | None = None, actor: str = "interpretation-engine") -> dict[str, Any]:
        packets = self.repository.packets_by_ids(request.packet_ids)
        if len(packets) != len(set(request.packet_ids)):
            raise ValueError("EVIDENCE_PACKET_NOT_FOUND")
        if any(packet["state"] == "PACKET_INCOMPLETE" for packet in packets):
            raise ValueError("INCOMPLETE_PACKET_CANNOT_BE_INTERPRETED")
        payload = asdict(request)
        payload["packet_ids"] = sorted(request.packet_ids)
        payload["input_packet_fingerprints"] = sorted(packet["fingerprint"] for packet in packets)
        payload["supersedes_interpretation_id"] = supersedes_interpretation_id
        payload["reproducibility_manifest"] = {
            "model_version": request.model_version,
            "ruleset_version": request.ruleset_version,
            "vocabulary_versions": request.vocabulary_versions,
            "configuration_hash": fingerprint(request.configuration),
            "packet_fingerprints": payload["input_packet_fingerprints"],
        }
        payload["fingerprint"] = fingerprint(payload)
        existing = self.repository.interpretation_by_fingerprint(payload["fingerprint"])
        if existing:
            return existing
        saved = self.repository.save_interpretation(payload)
        self.repository.audit("MACHINE_INTERPRETATION_CREATED", "MACHINE_INTERPRETATION", saved["interpretation_id"], {"fingerprint": saved["fingerprint"], "version": saved["version"], "supersedes": supersedes_interpretation_id}, actor)
        return saved

    def evaluate_routing(
        self,
        *,
        interpretation_id: int,
        policy: RoutingPolicy,
        independent_source_count: int,
        taxon_unambiguous: bool,
        measurement_compatible: bool,
        unresolved_contradiction: bool,
        impact_class: str,
        copyright_eligible: bool,
        provenance_complete: bool,
    ) -> dict[str, Any]:
        interpretation = self.repository.interpretation(interpretation_id)
        if not interpretation:
            raise ValueError("INTERPRETATION_NOT_FOUND")
        packets = self.repository.packets_by_ids(tuple(interpretation["packet_ids"]))
        confidence = min(interpretation["confidence_factors"].values())
        context_complete = all(packet["state"] == "PACKET_COMPLETE" for packet in packets)
        model_allowed = not policy.allowed_model_versions or interpretation["model_version"] in policy.allowed_model_versions
        gates = {
            "provenance_complete": provenance_complete,
            "copyright_eligible": copyright_eligible,
            "context_complete": context_complete,
            "model_allowed": model_allowed,
            "taxon_unambiguous": taxon_unambiguous,
            "measurement_compatible": measurement_compatible,
            "no_unresolved_contradiction": not unresolved_contradiction,
            "no_material_alternative": not bool(interpretation["alternatives"]),
            "not_mandatory_review_impact": impact_class not in policy.mandatory_review_impact_classes,
            "policy_healthy": policy.healthy,
        }
        hard_failures = sorted(name for name, passed in gates.items() if not passed)
        if confidence < policy.provisional_confidence:
            gates["minimum_provisional_confidence"] = False
            hard_failures.append("minimum_provisional_confidence")
            hard_failures.sort()
        if hard_failures:
            path = PromotionPath.EXCEPTION_REVIEW
        elif confidence >= policy.minimum_confidence and independent_source_count >= policy.minimum_independent_sources:
            path = PromotionPath.AUTOMATIC_PROMOTION
        else:
            path = PromotionPath.PROVISIONAL_SCIENTIFIC_ASSERTION
        record = {
            "interpretation_id": interpretation_id,
            "policy_name": policy.policy_name,
            "policy_version": policy.version,
            "path": path.value,
            "gates": gates,
            "hard_failures": hard_failures,
            "factors": {
                "minimum_confidence_factor": confidence,
                "independent_source_count": independent_source_count,
                "impact_class": impact_class,
                "calibration_cohort": policy.calibration_cohort,
                "automatic_confidence_threshold": policy.minimum_confidence,
                "provisional_confidence_threshold": policy.provisional_confidence,
                "independent_source_threshold": policy.minimum_independent_sources,
            },
            "explanation": hard_failures or (["all_hard_gates_passed", "automatic_thresholds_passed"] if path is PromotionPath.AUTOMATIC_PROMOTION else ["all_hard_gates_passed", "automatic_thresholds_not_met"]),
        }
        record["fingerprint"] = fingerprint(record)
        existing = self.repository.routing_by_fingerprint(record["fingerprint"])
        if existing:
            return existing
        saved = self.repository.save_routing_decision(record)
        self.repository.audit("PROMOTION_PATH_EVALUATED", "ROUTING_DECISION", saved["routing_decision_id"], {"path": saved["path"], "policy_version": policy.version, "gates": gates}, "promotion-policy")
        return saved

    def create_assertion(self, request: AssertionRequest, routing_decision_id: int) -> dict[str, Any]:
        routing_decision = self.repository.routing_decision(routing_decision_id)
        if not routing_decision:
            raise ValueError("ROUTING_DECISION_NOT_FOUND")
        interpretation_ids = request.supporting_interpretation_ids + request.conflicting_interpretation_ids
        if any(self.repository.interpretation(value) is None for value in interpretation_ids):
            raise ValueError("ASSERTION_INTERPRETATION_NOT_FOUND")
        if routing_decision["interpretation_id"] not in request.supporting_interpretation_ids:
            raise ValueError("ROUTING_DECISION_SUPPORT_MISMATCH")
        payload = asdict(request)
        payload["supporting_interpretation_ids"] = sorted(request.supporting_interpretation_ids)
        payload["conflicting_interpretation_ids"] = sorted(request.conflicting_interpretation_ids)
        payload["routing_decision_id"] = routing_decision_id
        payload["promotion_path"] = routing_decision["path"]
        payload["policy_version"] = routing_decision["policy_version"]
        payload["publication_eligible"] = routing_decision["path"] == PromotionPath.AUTOMATIC_PROMOTION.value
        payload["published"] = False
        payload["fingerprint"] = fingerprint(payload)
        existing = self.repository.assertion_by_fingerprint(payload["fingerprint"])
        if existing:
            return existing
        saved = self.repository.save_assertion(payload)
        self.repository.audit("CANONICAL_ASSERTION_CREATED", "CANONICAL_ASSERTION", saved["assertion_id"], {"version": saved["version"], "promotion_path": saved["promotion_path"], "published": False}, "assertion-registry")
        return saved

    def correct_interpretation(
        self,
        *,
        interpretation_id: int,
        correction_key: str,
        error_category: str,
        affected_field: str,
        corrected_value: Any,
        rationale: str,
        reviewer: str,
        reviewer_specialty: str,
        applicability: dict[str, Any],
        permitted_use: str,
    ) -> dict[str, Any]:
        original = self.repository.interpretation(interpretation_id)
        if not original:
            raise ValueError("INTERPRETATION_NOT_FOUND")
        if not all(value.strip() for value in (correction_key, error_category, affected_field, rationale, reviewer, reviewer_specialty, permitted_use)):
            raise ValueError("INCOMPLETE_CORRECTION_RECORD")
        statement = dict(original["statement"])
        original_value = statement.get(affected_field)
        statement[affected_field] = corrected_value
        request = InterpretationRequest(
            packet_ids=tuple(original["packet_ids"]),
            interpretation_key=original["interpretation_key"],
            statement=statement,
            reasoning={**original["reasoning"], "reviewer_correction": rationale},
            confidence_factors=dict(original["confidence_factors"]),
            ambiguities=tuple(original["ambiguities"]),
            alternatives=tuple(original["alternatives"]),
            model_version=original["model_version"],
            ruleset_version=original["ruleset_version"],
            vocabulary_versions=dict(original["vocabulary_versions"]),
            configuration=dict(original["configuration"]),
        )
        corrected = self.interpret(request, supersedes_interpretation_id=interpretation_id, actor=reviewer)
        record = {
            "correction_key": correction_key,
            "source_interpretation_id": interpretation_id,
            "corrected_interpretation_id": corrected["interpretation_id"],
            "error_category": error_category,
            "affected_field": affected_field,
            "original_value": original_value,
            "corrected_value": corrected_value,
            "rationale": rationale,
            "reviewer": reviewer,
            "reviewer_specialty": reviewer_specialty,
            "applicability": applicability,
            "permitted_use": permitted_use,
            "feedback_state": "CAPTURED",
        }
        saved = self.repository.save_correction(record)
        self.repository.audit("CORRECTION_RECORDED", "CORRECTION_RECORD", saved["correction_id"], {"version": saved["version"], "source_interpretation_id": interpretation_id, "corrected_interpretation_id": corrected["interpretation_id"]}, reviewer)
        return {"correction": saved, "corrected_interpretation": corrected}
