"""Provider-free acceptance ledger for Orchid Continuum autonomous cycles.

This module records and evaluates evidence; it grants no execution, merge,
deployment, publication, credential, spending, or production authority.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from pathlib import Path

TARGET_STREAK = 10
FULL_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
LEDGER_SCHEMA = "oc.autonomy.certification.v1"


def _is_full_sha(value: str) -> bool:
    return bool(FULL_SHA_PATTERN.fullmatch(value))


def _is_canonical_identity(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and value.isprintable()
    )


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
    verification_base_sha: str = ""

    @property
    def accepted(self) -> bool:
        if not all(
            _is_canonical_identity(value)
            for value in (self.cycle_id, self.work_identity, self.lease_identity)
        ):
            return False
        if isinstance(self.pr_number, bool) or not isinstance(self.pr_number, int):
            return False
        if self.pr_number <= 0:
            return False
        if not isinstance(self.exact_head_sha, str) or not isinstance(self.merged_sha, str):
            return False
        if not isinstance(self.verification_base_sha, str):
            return False
        gate_fields = (
            self.exact_head_ci_green,
            self.landed_verified,
            self.lease_released,
            self.duplicate_ownership,
            self.duplicate_lineage,
            self.unauthorized_owner_gate_crossing,
            self.abandoned_lease,
            self.false_green,
            self.recoverable_fault_seen,
            self.recoverable_fault_healed,
            self.manual_intervention,
        )
        if not all(isinstance(value, bool) for value in gate_fields):
            return False
        if not _is_full_sha(self.exact_head_sha) or not _is_full_sha(self.merged_sha):
            return False
        if not _is_full_sha(self.verification_base_sha):
            return False
        if self.verification_base_sha in {self.exact_head_sha, self.merged_sha}:
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
    if isinstance(target, bool) or not isinstance(target, int) or target <= 0:
        return Certification(
            False, 0, target, False, "target must be a positive integer"
        )

    cycle_list = list(cycles)
    if len(cycle_list) > target:
        return Certification(False, 0, target, False, "evidence exceeds target")

    streak = 0
    recovery_proven = False
    seen_cycle_ids: set[str] = set()
    seen_work_identities: set[str] = set()
    seen_lease_identities: set[str] = set()
    seen_pr_numbers: set[int] = set()
    seen_exact_heads: set[str] = set()
    seen_merge_shas: set[str] = set()
    seen_verification_bases: set[str] = set()
    for cycle in cycle_list:
        expected_cycle_id = str(streak + 1)
        if cycle.cycle_id != expected_cycle_id:
            return Certification(
                False,
                streak,
                target,
                recovery_proven,
                f"cycle identity must be {expected_cycle_id}",
            )
        if not cycle.accepted:
            return Certification(
                False,
                streak,
                target,
                recovery_proven,
                f"cycle {cycle.cycle_id} failed acceptance",
            )
        identities = (
            ("cycle identity", cycle.cycle_id, seen_cycle_ids),
            ("work identity", cycle.work_identity, seen_work_identities),
            ("lease identity", cycle.lease_identity, seen_lease_identities),
            ("PR identity", cycle.pr_number, seen_pr_numbers),
            ("exact head", cycle.exact_head_sha, seen_exact_heads),
            ("merge identity", cycle.merged_sha, seen_merge_shas),
            ("verification base", cycle.verification_base_sha, seen_verification_bases),
        )
        for name, value, seen in identities:
            if value in seen:
                return Certification(
                    False,
                    streak,
                    target,
                    recovery_proven,
                    f"cycle {cycle.cycle_id} reused {name}",
                )
            seen.add(value)
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


def _require_valid_aggregate(
    cycles: list[CycleEvidence], result: Certification
) -> None:
    if len(cycles) > result.target_streak:
        raise ValueError("certification ledger exceeds the target streak")
    if result.accepted_streak != len(cycles):
        raise ValueError("certification ledger contains a failed aggregate streak")


def write_ledger(path: Path, cycles: list[CycleEvidence]) -> Certification:
    result = evaluate(cycles)
    _require_valid_aggregate(cycles, result)
    payload = {
        "schema": LEDGER_SCHEMA,
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


def read_ledger(path: Path) -> list[CycleEvidence]:
    """Load only a complete, internally consistent certification ledger."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("certification ledger is unavailable or corrupt") from exc
    if not isinstance(payload, dict):
        raise TypeError("certification ledger root must be an object")
    if payload.get("schema") != LEDGER_SCHEMA:
        raise ValueError("certification ledger schema is unknown")
    if payload.get("target_streak") != TARGET_STREAK:
        raise ValueError("certification ledger target does not match runtime")

    raw_cycles = payload.get("cycles")
    if not isinstance(raw_cycles, list):
        raise TypeError("certification ledger cycles must be a list")
    field_names = {field.name for field in fields(CycleEvidence)}
    expected_keys = field_names | {"accepted"}
    cycles: list[CycleEvidence] = []
    for index, raw_cycle in enumerate(raw_cycles):
        if not isinstance(raw_cycle, dict) or set(raw_cycle) != expected_keys:
            raise ValueError(f"cycle {index} has an invalid evidence shape")
        accepted = raw_cycle["accepted"]
        if not isinstance(accepted, bool):
            raise TypeError(f"cycle {index} has a non-boolean acceptance result")
        values = {name: raw_cycle[name] for name in field_names}
        try:
            cycle = CycleEvidence(**values)
            acceptance_matches = accepted is cycle.accepted
        except (TypeError, ValueError) as exc:
            raise ValueError(f"cycle {index} cannot be reconstructed") from exc
        if not acceptance_matches or not cycle.accepted:
            raise ValueError(f"cycle {index} acceptance evidence is inconsistent")
        cycles.append(cycle)

    result = evaluate(cycles)
    _require_valid_aggregate(cycles, result)
    raw_result = payload.get("result")
    if raw_result != asdict(result):
        raise ValueError("certification result does not match cycle evidence")
    return cycles


def append_cycle(path: Path, cycle: CycleEvidence) -> Certification:
    """Append one cycle atomically, making identical replay a no-op."""

    cycles = read_ledger(path) if path.exists() else []
    if cycle in cycles:
        return evaluate(cycles)
    identity_fields = (
        "cycle_id",
        "work_identity",
        "lease_identity",
        "pr_number",
        "exact_head_sha",
        "merged_sha",
        "verification_base_sha",
    )
    for existing in cycles:
        for name in identity_fields:
            if getattr(existing, name) == getattr(cycle, name):
                raise ValueError(f"new cycle reuses {name}")
    if not cycle.accepted:
        raise ValueError("new cycle fails acceptance")
    return write_ledger(path, [*cycles, cycle])
