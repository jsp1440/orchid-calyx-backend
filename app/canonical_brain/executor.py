from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from .orchestration import BuildAssignment, ExecutionReceipt


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionRequest(StrictModel):
    assignment: BuildAssignment
    capability: str = Field(min_length=3)
    input_payload: dict[str, object]
    evidence_uris: list[str] = Field(min_length=1)
    recorded_at: datetime
    timeout_seconds: int = Field(default=300, ge=1, le=3600)


class ExecutionResult(StrictModel):
    receipt: ExecutionReceipt
    input_checksum: str = Field(min_length=64, max_length=64)
    adapter_name: str
    dry_run: bool


class ExecutorAdapter(Protocol):
    name: str

    def execute(self, request: ExecutionRequest) -> ExecutionResult: ...


def _checksum(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DeterministicDryRunExecutor:
    """Candidate-only executor used to validate orchestration without running code."""

    name = "deterministic-dry-run-v1"

    def __init__(self, supported_capabilities: set[str]) -> None:
        self._supported_capabilities = set(supported_capabilities)

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        if request.capability not in self._supported_capabilities:
            raise ValueError(f"unsupported executor capability: {request.capability}")
        if request.assignment.status != "running":
            raise ValueError("assignments must be running before execution")

        input_checksum = _checksum(request.input_payload)
        output_payload = {
            "assignment_id": request.assignment.assignment_id,
            "build_id": request.assignment.build_id,
            "agent_id": request.assignment.agent_id,
            "capability": request.capability,
            "input_checksum": input_checksum,
            "mode": "dry-run",
        }
        output_checksum = _checksum(output_payload)
        receipt_id = hashlib.sha256(
            f"{request.assignment.assignment_id}:completed:dry-run".encode()
        ).hexdigest()
        receipt = ExecutionReceipt(
            receipt_id=receipt_id,
            assignment_id=request.assignment.assignment_id,
            build_id=request.assignment.build_id,
            agent_id=request.assignment.agent_id,
            outcome="completed",
            recorded_at=request.recorded_at,
            evidence_uris=sorted(set(request.evidence_uris)),
            output_checksum=output_checksum,
        )
        return ExecutionResult(
            receipt=receipt,
            input_checksum=input_checksum,
            adapter_name=self.name,
            dry_run=True,
        )
