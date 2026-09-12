"""Governed readiness-change observation and regression lifecycle.

Compares two canonical ``sci-obs-readiness-v1`` snapshots, emits one stable
``module.readiness.changed`` operational observation for a comparable material
change, and reuses the existing SCI-OBS anomaly/Verification Workbench binding.
It never changes readiness, scientific, publication, or deployment state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import re
from typing import Any
from uuid import UUID

from app.kernel.identity import OCID, OCIDKind

from .models import (
    ObservationEventType,
    PipelineStage,
    SafeStatus,
    SafeStatusState,
    ScientificObservationEvent,
)
from .readiness import CALCULATION_VERSION, COMPONENTS, DIMENSIONS, DimensionState
from .service import ObservabilityService

CHANGE_CONTRACT_VERSION = "sci-obs-readiness-change-v1"
_ALLOWED_STATES = {
    DimensionState.AVAILABLE,
    DimensionState.CONDITIONAL,
    DimensionState.BLOCKED,
    DimensionState.UNAVAILABLE,
    DimensionState.UNKNOWN,
    DimensionState.ERROR,
}
_COMPARABLE_STATE_RANK = {
    DimensionState.BLOCKED: 0,
    DimensionState.CONDITIONAL: 1,
    DimensionState.AVAILABLE: 2,
}
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_PROTECTED_FRAGMENTS = (
    "api_key",
    "authorization",
    "credential",
    "exact_locality",
    "latitude",
    "longitude",
    "password",
    "private_key",
    "raw_prompt",
    "secret",
    "token",
)


class ReadinessChangeError(ValueError):
    """Raised when readiness comparison cannot be performed safely."""


class ReadinessChangeKind(StrEnum):
    UNCHANGED = "unchanged"
    IMPROVED = "improved"
    REGRESSED = "regressed"
    INCOMPARABLE = "incomparable"


@dataclass(frozen=True, slots=True)
class ReadinessSnapshot:
    module_id: str
    project_id: str
    environment: str
    readiness: Mapping[str, Any]
    evidence_refs: tuple[str, ...]
    source_ref: str


@dataclass(frozen=True, slots=True)
class ReadinessChangeResult:
    contract_version: str
    classification: ReadinessChangeKind
    reason_code: str
    created: bool
    event: Mapping[str, Any] | None = None
    anomalies: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    review_bindings: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "classification": self.classification.value,
            "reason_code": self.reason_code,
            "created": self.created,
            "event": dict(self.event) if self.event is not None else None,
            "anomalies": [dict(item) for item in self.anomalies],
            "review_bindings": [dict(item) for item in self.review_bindings],
            "authority": {
                "advisory_only": True,
                "mutates_authoritative_state": False,
                "publication_authority": False,
                "deployment_authority": False,
            },
        }


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode()).hexdigest()


def _event_ocid(value: Any) -> OCID:
    return OCID(kind=OCIDKind.EVENT, value=UUID(hex=_fingerprint(value)[:32]))


def _validate_safe_identifier(name: str, value: str) -> None:
    if not _ID_PATTERN.fullmatch(value):
        raise ReadinessChangeError(f"{name} is invalid")
    lowered = value.casefold()
    if any(fragment in lowered for fragment in _PROTECTED_FRAGMENTS):
        raise ReadinessChangeError(f"{name} contains a protected field")


def _validate_string_list(name: str, value: Any, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > 32:
        raise ReadinessChangeError(f"{name} must be a bounded list")
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or len(item) > 160:
            raise ReadinessChangeError(f"{name} contains an invalid value")
        _validate_safe_identifier(name, item)
        cleaned.append(item)
    if required and not cleaned:
        raise ReadinessChangeError(f"{name} requires evidence")
    return tuple(sorted(set(cleaned)))


def _validate_readiness(payload: Mapping[str, Any]) -> None:
    if payload.get("contract_version") != CALCULATION_VERSION:
        raise ReadinessChangeError("incompatible readiness contract")
    if payload.get("publication_authority") is not False:
        raise ReadinessChangeError("readiness cannot grant publication authority")
    if payload.get("human_approval_required") is not True:
        raise ReadinessChangeError("human approval must remain required")
    if payload.get("overall_state") not in {"ready", "conditional", "blocked"}:
        raise ReadinessChangeError("invalid overall readiness state")

    dimensions = payload.get("dimensions")
    if not isinstance(dimensions, Mapping) or not dimensions or len(dimensions) > len(DIMENSIONS):
        raise ReadinessChangeError("dimensions must be present and bounded")
    if not set(dimensions).issubset(DIMENSIONS):
        raise ReadinessChangeError("unknown readiness dimension")

    for key, raw in dimensions.items():
        if not isinstance(raw, Mapping) or raw.get("key") != key:
            raise ReadinessChangeError("dimension identity mismatch")
        state = raw.get("state")
        if state not in _ALLOWED_STATES:
            raise ReadinessChangeError("invalid dimension state")
        if raw.get("calculation_version") != CALCULATION_VERSION:
            raise ReadinessChangeError("dimension calculation version mismatch")
        numerator, denominator = raw.get("numerator"), raw.get("denominator")
        if (numerator is None) != (denominator is None):
            raise ReadinessChangeError("numerator and denominator must be paired")
        if numerator is not None:
            if (
                isinstance(numerator, bool)
                or isinstance(denominator, bool)
                or not isinstance(numerator, int)
                or not isinstance(denominator, int)
                or denominator <= 0
                or numerator < 0
                or numerator > denominator
                or denominator > 100_000
            ):
                raise ReadinessChangeError("invalid readiness fraction")
        elif state not in {DimensionState.UNAVAILABLE, DimensionState.UNKNOWN, DimensionState.ERROR}:
            raise ReadinessChangeError("available readiness requires a measured fraction")
        _validate_string_list("missing_requirements", raw.get("missing_requirements", []))
        _validate_string_list("upstream_blockers", raw.get("upstream_blockers", []))

    coverage = payload.get("component_coverage")
    if not isinstance(coverage, Mapping) or not set(coverage).issubset(COMPONENTS):
        raise ReadinessChangeError("invalid component coverage")
    for raw in coverage.values():
        if not isinstance(raw, Mapping) or raw.get("state") not in _ALLOWED_STATES:
            raise ReadinessChangeError("invalid component coverage state")
        present = raw.get("present")
        if present not in {True, False, None}:
            raise ReadinessChangeError("invalid component coverage value")


def _validate_snapshot(snapshot: ReadinessSnapshot) -> None:
    _validate_safe_identifier("module_id", snapshot.module_id)
    _validate_safe_identifier("project_id", snapshot.project_id)
    _validate_safe_identifier("environment", snapshot.environment)
    _validate_safe_identifier("source_ref", snapshot.source_ref)
    _validate_string_list("evidence_refs", snapshot.evidence_refs, required=True)
    _validate_readiness(snapshot.readiness)


def _canonical_readiness(payload: Mapping[str, Any]) -> dict[str, Any]:
    dimensions: dict[str, Any] = {}
    for key, raw in sorted((payload.get("dimensions") or {}).items()):
        dimensions[key] = {
            "key": raw.get("key"),
            "state": raw.get("state"),
            "numerator": raw.get("numerator"),
            "denominator": raw.get("denominator"),
            "score": raw.get("score"),
            "missing_requirements": sorted(raw.get("missing_requirements") or []),
            "upstream_blockers": sorted(raw.get("upstream_blockers") or []),
            "limitation": raw.get("limitation"),
            "calculation_version": raw.get("calculation_version"),
        }
    return {
        "contract_version": payload.get("contract_version"),
        "overall_state": payload.get("overall_state"),
        "dimensions": dimensions,
        "component_coverage": {
            key: {
                "state": raw.get("state"),
                "present": raw.get("present"),
            }
            for key, raw in sorted((payload.get("component_coverage") or {}).items())
        },
        "human_approval_required": payload.get("human_approval_required"),
        "publication_authority": payload.get("publication_authority"),
    }


def _direction(previous: Mapping[str, Any], current: Mapping[str, Any]) -> ReadinessChangeKind:
    if previous == current:
        return ReadinessChangeKind.UNCHANGED
    if set(previous["dimensions"]) != set(current["dimensions"]):
        return ReadinessChangeKind.INCOMPARABLE

    improved = False
    regressed = False
    for key in previous["dimensions"]:
        before = previous["dimensions"][key]
        after = current["dimensions"][key]
        states = {before["state"], after["state"]}
        if states & {DimensionState.UNAVAILABLE, DimensionState.UNKNOWN, DimensionState.ERROR}:
            if before != after:
                return ReadinessChangeKind.INCOMPARABLE
            continue
        before_rank = _COMPARABLE_STATE_RANK[before["state"]]
        after_rank = _COMPARABLE_STATE_RANK[after["state"]]
        improved |= after_rank > before_rank
        regressed |= after_rank < before_rank
        if before["numerator"] is not None and after["numerator"] is not None:
            left = after["numerator"] * before["denominator"]
            right = before["numerator"] * after["denominator"]
            improved |= left > right
            regressed |= left < right
        improved |= bool(set(before["missing_requirements"]) - set(after["missing_requirements"]))
        improved |= bool(set(before["upstream_blockers"]) - set(after["upstream_blockers"]))
        regressed |= bool(set(after["missing_requirements"]) - set(before["missing_requirements"]))
        regressed |= bool(set(after["upstream_blockers"]) - set(before["upstream_blockers"]))

    before_coverage = previous["component_coverage"]
    after_coverage = current["component_coverage"]
    if set(before_coverage) != set(after_coverage):
        return ReadinessChangeKind.INCOMPARABLE
    for key in before_coverage:
        before = before_coverage[key]
        after = after_coverage[key]
        if before == after:
            continue
        if before["state"] == DimensionState.UNAVAILABLE or after["state"] == DimensionState.UNAVAILABLE:
            return ReadinessChangeKind.INCOMPARABLE
        improved |= before["present"] is False and after["present"] is True
        regressed |= before["present"] is True and after["present"] is False

    if improved and regressed:
        return ReadinessChangeKind.INCOMPARABLE
    if improved:
        return ReadinessChangeKind.IMPROVED
    if regressed:
        return ReadinessChangeKind.REGRESSED
    return ReadinessChangeKind.INCOMPARABLE


def _binding_dict(binding: Any) -> dict[str, Any]:
    return {
        "review_type": binding.review_type,
        "risk_class": binding.risk_class,
        "batch_key": binding.batch_key,
        "routing_outcome": binding.routing_outcome,
        "required_capability": binding.required_capability,
        "embargoed": binding.embargoed,
        "display_policy": binding.display_policy,
        "authoritative_state_mutated": binding.metadata.get("authoritative_state_mutated"),
    }


class ReadinessChangeLifecycle:
    """Emit deduplicated, evidence-backed readiness-change observations."""

    def __init__(self, service: ObservabilityService) -> None:
        self._service = service

    def compare(
        self,
        previous: ReadinessSnapshot,
        current: ReadinessSnapshot,
    ) -> ReadinessChangeResult:
        _validate_snapshot(previous)
        _validate_snapshot(current)
        if (
            previous.module_id,
            previous.project_id,
            previous.environment,
        ) != (
            current.module_id,
            current.project_id,
            current.environment,
        ):
            raise ReadinessChangeError("cross-identity or cross-environment comparison refused")

        before = _canonical_readiness(previous.readiness)
        after = _canonical_readiness(current.readiness)
        classification = _direction(before, after)
        if classification is ReadinessChangeKind.UNCHANGED:
            return ReadinessChangeResult(
                contract_version=CHANGE_CONTRACT_VERSION,
                classification=classification,
                reason_code="READINESS_UNCHANGED",
                created=False,
            )
        if classification is ReadinessChangeKind.INCOMPARABLE:
            return ReadinessChangeResult(
                contract_version=CHANGE_CONTRACT_VERSION,
                classification=classification,
                reason_code="READINESS_CHANGE_INCOMPARABLE",
                created=False,
            )

        identity = {
            "contract_version": CHANGE_CONTRACT_VERSION,
            "module_id": current.module_id,
            "project_id": current.project_id,
            "environment": current.environment,
            "previous": before,
            "current": after,
            "classification": classification.value,
            "evidence_refs": sorted(current.evidence_refs),
        }
        event_id = _event_ocid({"readiness_change": identity})
        existing = self._service.store.get(str(event_id))
        if existing is not None:
            return ReadinessChangeResult(
                contract_version=CHANGE_CONTRACT_VERSION,
                classification=classification,
                reason_code=(
                    "READINESS_REGRESSED" if classification is ReadinessChangeKind.REGRESSED
                    else "READINESS_IMPROVED"
                ),
                created=False,
                event=existing,
            )

        correlation_id = _event_ocid(
            {
                "readiness_lineage": {
                    "module_id": current.module_id,
                    "project_id": current.project_id,
                    "environment": current.environment,
                }
            }
        )
        reason_code = (
            "READINESS_REGRESSED"
            if classification is ReadinessChangeKind.REGRESSED
            else "READINESS_IMPROVED"
        )
        status = (
            SafeStatusState.DEGRADED
            if classification is ReadinessChangeKind.REGRESSED
            else SafeStatusState.OK
        )
        event = ScientificObservationEvent(
            event_id=event_id,
            correlation_id=correlation_id,
            event_type=ObservationEventType.MODULE_READINESS_CHANGED,
            pipeline_stage=PipelineStage.API_PRODUCER,
            component="app/scientific_observability/readiness_change.py",
            component_version=CHANGE_CONTRACT_VERSION,
            source={
                "source_id": CALCULATION_VERSION,
                "source_record_id": current.source_ref,
                "source_anchor_id": current.evidence_refs[0],
            },
            evidence={
                "verification_state": "verified",
                "evidence_refs": list(current.evidence_refs),
            },
            actor={"actor_type": "service", "actor_id": "scientific-observability"},
            safe_status=SafeStatus(status=status, reason_code=reason_code),
            extensions={
                "readiness_change_contract": CHANGE_CONTRACT_VERSION,
                "module_id": current.module_id,
                "project_id": current.project_id,
                "environment": current.environment,
                "classification": classification.value,
                "previous_fingerprint": _fingerprint(before),
                "current_fingerprint": _fingerprint(after),
                "previous_readiness_state": before["overall_state"],
                "readiness_state": after["overall_state"],
                "evidence_refs": list(current.evidence_refs),
                "advisory_only": True,
                "authoritative_state_mutated": False,
                "publication_authority": False,
                "deployment_authority": False,
            },
        )
        recorded = self._service.record(
            event,
            prior_readiness_state=str(before["overall_state"]),
        )
        return ReadinessChangeResult(
            contract_version=CHANGE_CONTRACT_VERSION,
            classification=classification,
            reason_code=reason_code,
            created=recorded.created,
            event=recorded.event,
            anomalies=tuple(item.to_dict() for item in recorded.anomalies),
            review_bindings=tuple(_binding_dict(item) for item in recorded.review_bindings),
        )
