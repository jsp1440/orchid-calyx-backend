from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .engineering_core import TerminalOutcome


class ExecutionState(StrEnum):
    DELIVERED = "delivered"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class ExecutorCapability(StrEnum):
    VALIDATE_INPUT = "validate_input"
    PRODUCE_RECEIPT = "produce_receipt"
    COLLECT_EVIDENCE_URIS = "collect_evidence_uris"


PROHIBITED_CAPABILITIES = frozenset(
    {
        "shell",
        "network",
        "merge",
        "deploy",
        "publish",
        "credential_access",
        "production_graph_mutation",
    }
)


def canonical_checksum(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class GovernedAssignment:
    assignment_id: str
    program_id: str
    job_key: str
    role_key: str
    objective: str
    inputs: Mapping[str, object]
    requested_capabilities: tuple[str, ...] = ()
    evidence_uris: tuple[str, ...] = ()
    timeout_seconds: int = 60
    cancelled: bool = False
    input_checksum: str | None = None

    def verified_input_checksum(self) -> str:
        calculated = canonical_checksum(self.inputs)
        if self.input_checksum is not None and self.input_checksum != calculated:
            raise ValueError("ASSIGNMENT_INPUT_CHECKSUM_MISMATCH")
        return calculated


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    assignment_id: str
    program_id: str
    job_key: str
    executor_key: str
    state: ExecutionState
    outcome: TerminalOutcome
    input_checksum: str
    output_checksum: str
    output: Mapping[str, object]
    evidence_uris: tuple[str, ...]
    blocker_code: str | None = None

    def verify(self) -> None:
        if self.output_checksum != canonical_checksum(self.output):
            raise ValueError("RECEIPT_OUTPUT_CHECKSUM_MISMATCH")
        if self.state == ExecutionState.DELIVERED and self.outcome != TerminalOutcome.DELIVERED:
            raise ValueError("RECEIPT_STATE_OUTCOME_MISMATCH")
        if self.state == ExecutionState.CANCELLED and self.outcome != TerminalOutcome.CANCELLED:
            raise ValueError("RECEIPT_STATE_OUTCOME_MISMATCH")
        if self.state in {ExecutionState.BLOCKED, ExecutionState.TIMED_OUT} and self.outcome != TerminalOutcome.BLOCKED:
            raise ValueError("RECEIPT_STATE_OUTCOME_MISMATCH")


class ExecutorAdapter(Protocol):
    executor_key: str

    def execute(self, assignment: GovernedAssignment) -> ExecutionReceipt: ...


class DeterministicDryRunExecutor:
    """A fail-closed executor that performs no shell, network, or production actions."""

    executor_key = "deterministic_dry_run_v1"
    supported_capabilities = frozenset(item.value for item in ExecutorCapability)

    def execute(self, assignment: GovernedAssignment) -> ExecutionReceipt:
        input_checksum = assignment.verified_input_checksum()
        evidence_uris = _normalize_evidence_uris(assignment.evidence_uris)

        if assignment.cancelled:
            return self._receipt(
                assignment=assignment,
                state=ExecutionState.CANCELLED,
                outcome=TerminalOutcome.CANCELLED,
                input_checksum=input_checksum,
                output={"status": "cancelled", "executed": False},
                evidence_uris=evidence_uris,
                blocker_code="ASSIGNMENT_CANCELLED",
            )
        if assignment.timeout_seconds <= 0:
            return self._receipt(
                assignment=assignment,
                state=ExecutionState.TIMED_OUT,
                outcome=TerminalOutcome.BLOCKED,
                input_checksum=input_checksum,
                output={"status": "timed_out", "executed": False},
                evidence_uris=evidence_uris,
                blocker_code="INVALID_OR_EXPIRED_TIMEOUT",
            )

        requested = set(assignment.requested_capabilities)
        prohibited = sorted(requested & PROHIBITED_CAPABILITIES)
        unsupported = sorted(requested - self.supported_capabilities - PROHIBITED_CAPABILITIES)
        if prohibited or unsupported:
            code = "PROHIBITED_CAPABILITY" if prohibited else "UNSUPPORTED_CAPABILITY"
            return self._receipt(
                assignment=assignment,
                state=ExecutionState.BLOCKED,
                outcome=TerminalOutcome.BLOCKED,
                input_checksum=input_checksum,
                output={
                    "status": "blocked",
                    "executed": False,
                    "prohibited_capabilities": prohibited,
                    "unsupported_capabilities": unsupported,
                },
                evidence_uris=evidence_uris,
                blocker_code=code,
            )

        output = {
            "status": "delivered",
            "executed": True,
            "mode": "dry_run",
            "objective": assignment.objective,
            "input_keys": sorted(str(key) for key in assignment.inputs),
            "capabilities": sorted(requested),
            "side_effects": [],
        }
        return self._receipt(
            assignment=assignment,
            state=ExecutionState.DELIVERED,
            outcome=TerminalOutcome.DELIVERED,
            input_checksum=input_checksum,
            output=output,
            evidence_uris=evidence_uris,
        )

    def _receipt(
        self,
        *,
        assignment: GovernedAssignment,
        state: ExecutionState,
        outcome: TerminalOutcome,
        input_checksum: str,
        output: Mapping[str, object],
        evidence_uris: tuple[str, ...],
        blocker_code: str | None = None,
    ) -> ExecutionReceipt:
        receipt = ExecutionReceipt(
            assignment_id=assignment.assignment_id,
            program_id=assignment.program_id,
            job_key=assignment.job_key,
            executor_key=self.executor_key,
            state=state,
            outcome=outcome,
            input_checksum=input_checksum,
            output_checksum=canonical_checksum(output),
            output=output,
            evidence_uris=evidence_uris,
            blocker_code=blocker_code,
        )
        receipt.verify()
        return receipt


def _normalize_evidence_uris(values: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        item = value.strip()
        if not item:
            raise ValueError("EMPTY_EVIDENCE_URI")
        if ":" not in item:
            raise ValueError("INVALID_EVIDENCE_URI")
        if item not in normalized:
            normalized.append(item)
    return tuple(normalized)
