"""Provider-free acceptance ledger for Orchid Continuum autonomous cycles.

This module records and evaluates evidence; it grants no execution, merge,
deployment, publication, credential, spending, or production authority.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

TARGET_STREAK = 10


@dataclass(frozen=True)
class CycleEvidence:
    cycle_id: str
    work_identity: str
    lease_identity: str
    pr_number: int
    exact_head_sha: str
    merged_sha: str
    exact_head_ci_green: bool
    landed_verified: bool
    lease_released: bool
    duplicate_ownership: bool = False
    duplicate_lineage: bool = False
    unauthorized_owner_gate_crossing: bool = False
    abandoned_lease: bool = False
    false_green: bool = False
    recoverable_fault_seen: bool = False
    recoverable_fault_healed: bool = False
    manual_intervention: bool = False

    @property
    def accepted(self) -> bool:
        if not all(
            (
                self.cycle_id,
                self.work_identity,
                self.lease_identity,
                self.exact_head_sha,
                self.merged_sha,
            )
        ):
            return False
        if self.pr_number <= 0:
            return False
        if not (
            self.exact_head_ci_green and self.landed_verified and self.lease_released
        ):
            return False
        if any(
            (
                self.duplicate_ownership,
                self.duplicate_lineage,
                self.unauthorized_owner_gate_crossing,
                self.abandoned_lease,
                self.false_green,
                self.manual_intervention,
            )
        ):
            return False
        return not self.recoverable_fault_seen or self.recoverable_fault_healed


@dataclass(frozen=True)
class Certification:
    certified: bool
    accepted_streak: int
    target_streak: int
    recovery_proven: bool
    reason: str


def evaluate(
    cycles: Iterable[CycleEvidence], target: int = TARGET_STREAK
) -> Certification:
    streak = 0
    recovery_proven = False
    for cycle in cycles:
        if not cycle.accepted:
            return Certification(
                False,
                streak,
                target,
                recovery_proven,
                f"cycle {cycle.cycle_id} failed acceptance",
            )
        streak += 1
        recovery_proven = recovery_proven or (
            cycle.recoverable_fault_seen and cycle.recoverable_fault_healed
        )
        if streak == target:
            if not recovery_proven:
                return Certification(
                    False,
                    streak,
                    target,
                    False,
                    (
                        "ten clean cycles completed but no self-healing recovery "
                        "was proven"
                    ),
                )
            return Certification(True, streak, target, True, "certified")
    return Certification(
        False,
        streak,
        target,
        recovery_proven,
        f"need {target - streak} more accepted consecutive cycles",
    )


def write_ledger(path: Path, cycles: list[CycleEvidence]) -> Certification:
    result = evaluate(cycles)
    payload = {
        "schema": "oc.autonomy.certification.v1",
        "target_streak": TARGET_STREAK,
        "cycles": [asdict(c) | {"accepted": c.accepted} for c in cycles],
        "result": asdict(result),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tmp.replace(path)
    return result
