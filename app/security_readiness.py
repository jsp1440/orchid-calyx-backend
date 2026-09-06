"""Context-aware zero-day readiness contracts for Orchid Continuum.

This module is deliberately side-effect free. It calculates exposure and closure
state; containment remains behind the existing owner-approval boundary.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from math import prod
from typing import Iterable


class Severity(str, Enum):
    SEV1 = "sev1"
    SEV2 = "sev2"
    SEV3 = "sev3"
    SEV4 = "sev4"


@dataclass(frozen=True)
class Exposure:
    affected_assets: int
    internet_exposure: int
    privilege: int
    connectivity: int
    data_sensitivity: int
    runtime_reachable: bool = True
    known_exploit: bool = False
    compensating_control: bool = False

    def __post_init__(self) -> None:
        for name in ("internet_exposure", "privilege", "connectivity", "data_sensitivity"):
            value = getattr(self, name)
            if not 1 <= value <= 5:
                raise ValueError(f"{name} must be between 1 and 5")
        if self.affected_assets < 0:
            raise ValueError("affected_assets cannot be negative")

    @property
    def blast_radius(self) -> int:
        base = prod((
            self.affected_assets,
            self.internet_exposure,
            self.privilege,
            self.connectivity,
            self.data_sensitivity,
        ))
        if not self.runtime_reachable:
            base = round(base * 0.2)
        if self.compensating_control:
            base = round(base * 0.5)
        if self.known_exploit:
            base = round(base * 1.5)
        return base

    @property
    def severity(self) -> Severity:
        if self.known_exploit and self.internet_exposure >= 4:
            return Severity.SEV1
        if self.blast_radius >= 500:
            return Severity.SEV1
        if self.blast_radius >= 150:
            return Severity.SEV2
        if self.blast_radius >= 25:
            return Severity.SEV3
        return Severity.SEV4

    def payload(self) -> dict:
        return {**asdict(self), "blast_radius": self.blast_radius, "severity": self.severity.value}


CLOSURE_EVIDENCE = frozenset({
    "affected_assets_identified",
    "containment_verified",
    "patched_artifacts_rebuilt",
    "vulnerable_artifacts_unreachable",
    "regression_tests_passed",
    "security_rescan_passed",
    "rollback_available",
    "production_reverified",
})


def closure_gate(evidence: Iterable[str]) -> dict:
    supplied = frozenset(evidence)
    missing = sorted(CLOSURE_EVIDENCE - supplied)
    return {
        "status": "verified_closed" if not missing else "open",
        "close_allowed": not missing,
        "missing_evidence": missing,
        "required_evidence": sorted(CLOSURE_EVIDENCE),
    }


READINESS_TARGETS_MINUTES = {
    "identify_affected_systems": 15,
    "determine_exploitability": 60,
    "deploy_compensating_control": 60,
    "sev1_full_mitigation": 480,
    "post_incident_review": 4320,
}
