"""Deterministic homeostasis policy for Orchid Continuum."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class HealthBand(StrEnum):
    HEALTHY = "healthy"
    WATCH = "watch"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"

class InterventionKind(StrEnum):
    OBSERVE = "observe"
    RECONCILE = "reconcile"
    REFILL = "refill"
    CLEANUP = "cleanup"
    REPAIR = "repair"
    REQUEST_EXTERNAL_INTELLIGENCE = "request_external_intelligence"
    REQUEST_OWNER_BUDGET = "request_owner_budget"
    THROTTLE_EXTERNAL_CALLS = "throttle_external_calls"

@dataclass(frozen=True)
class VitalSign:
    name: str
    value: float | int | None
    minimum: float | int | None = None
    maximum: float | int | None = None
    stale: bool = False
    evidence: tuple[str, ...] = ()

    def band(self) -> HealthBand:
        if self.value is None:
            return HealthBand.UNKNOWN
        if self.stale:
            return HealthBand.WATCH
        if self.minimum is not None and self.value < self.minimum:
            return HealthBand.DEGRADED
        if self.maximum is not None and self.value > self.maximum:
            return HealthBand.DEGRADED
        return HealthBand.HEALTHY

@dataclass(frozen=True)
class Intervention:
    kind: InterventionKind
    reason: str
    vital_sign: str
    requires_external_provider: bool = False
    requires_owner_budget: bool = False

@dataclass(frozen=True)
class HomeostasisAssessment:
    status: HealthBand
    interventions: tuple[Intervention, ...]

def _specific_intervention(sign: VitalSign) -> Intervention | None:
    name = sign.name.lower()
    band = sign.band()
    if band is HealthBand.HEALTHY:
        return None
    if band is HealthBand.UNKNOWN:
        return Intervention(InterventionKind.OBSERVE, "Collect authoritative evidence before acting.", sign.name)
    if sign.stale:
        return Intervention(InterventionKind.REFILL, "Refresh stale observation from local or free sources first.", sign.name)
    if "taxonomy" in name or "provenance" in name or "conflict" in name:
        return Intervention(InterventionKind.RECONCILE, "Reconcile scientific evidence.", sign.name)
    if "duplicate" in name or "orphan" in name or "dead_letter" in name:
        return Intervention(InterventionKind.CLEANUP, "Run bounded cleanup or quarantine.", sign.name)
    if "availability" in name or "heartbeat" in name or "failed_job" in name:
        return Intervention(InterventionKind.REPAIR, "Repair or reroute provider-free work first.", sign.name)
    if "budget" in name:
        return Intervention(InterventionKind.THROTTLE_EXTERNAL_CALLS, "Prefer cache, piggyback, free federation and local work.", sign.name)
    if "coverage" in name or "evidence" in name or "freshness" in name:
        return Intervention(
            InterventionKind.REQUEST_EXTERNAL_INTELLIGENCE,
            "Knowledge coverage is outside target after local evidence is exhausted.",
            sign.name,
            requires_external_provider=True,
        )
    return Intervention(InterventionKind.OBSERVE, "Gather evidence for a bounded intervention.", sign.name)

def assess_homeostasis(signs: Iterable[VitalSign]) -> HomeostasisAssessment:
    signs = tuple(signs)
    interventions = tuple(i for sign in signs if (i := _specific_intervention(sign)) is not None)
    bands = [sign.band() for sign in signs]
    if any(b is HealthBand.DEGRADED for b in bands):
        status = HealthBand.DEGRADED
    elif any(b in {HealthBand.WATCH, HealthBand.UNKNOWN} for b in bands):
        status = HealthBand.WATCH
    else:
        status = HealthBand.HEALTHY
    return HomeostasisAssessment(status=status, interventions=interventions)

def escalate_external_request(
    intervention: Intervention,
    *,
    local_evidence_exhausted: bool,
    cache_miss: bool,
    free_source_unavailable: bool,
    estimated_cost_usd: float,
    remaining_authorized_budget_usd: float,
) -> Intervention:
    """Route external need through reuse and budget gates without authorizing spend."""
    if intervention.kind is not InterventionKind.REQUEST_EXTERNAL_INTELLIGENCE:
        return intervention
    if not (local_evidence_exhausted and cache_miss and free_source_unavailable):
        return Intervention(
            InterventionKind.REFILL,
            "Reuse local, cached, piggybacked or free-federation evidence before paid retrieval.",
            intervention.vital_sign,
        )
    if estimated_cost_usd <= remaining_authorized_budget_usd:
        return intervention
    return Intervention(
        InterventionKind.REQUEST_OWNER_BUDGET,
        (
            f"Estimated external cost ${estimated_cost_usd:.2f} exceeds remaining "
            f"authorized budget ${remaining_authorized_budget_usd:.2f}."
        ),
        intervention.vital_sign,
        requires_external_provider=True,
        requires_owner_budget=True,
    )
