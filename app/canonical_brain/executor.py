from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.calyx_orchestrator.executor import (
    DeterministicDryRunExecutor as CalyxDryRunExecutor,
)
from app.calyx_orchestrator.executor import ExecutorCapability, GovernedAssignment

from .orchestration import BuildAssignment


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
    input_checksum: str = Field(min_length=64, max_length=64)
    output_checksum: str = Field(min_length=64, max_length=64)
    adapter_name: str
    dry_run: bool
    authoritative: bool
    state: str
    outcome: str
    evidence_uris: list[str]
    output: dict[str, object]
    blocker_code: str | None = None


class ExecutorAdapter(Protocol):
    name: str

    def execute(self, request: ExecutionRequest) -> ExecutionResult: ...


class DeterministicDryRunExecutor:
    """Non-authoritative preflight wrapper over the current Calyx dry-run executor."""

    name = "calyx-deterministic-preflight-v1"

    def __init__(self, supported_capabilities: set[str]) -> None:
        self._supported_capabilities = set(supported_capabilities)

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        if request.capability not in self._supported_capabilities:
            raise ValueError(f"unsupported executor capability: {request.capability}")
        if request.assignment.status != "running":
            raise ValueError("assignments must be running before execution")

        assignment = GovernedAssignment(
            assignment_id=request.assignment.assignment_id,
            program_id="canonical-brain-preflight",
            job_key=request.assignment.build_id,
            role_key=request.assignment.agent_id,
            objective=f"Validate candidate build {request.assignment.build_id}",
            inputs={
                "architecture_id": request.assignment.architecture_id,
                "capability": request.capability,
                "payload": request.input_payload,
                "recorded_at": request.recorded_at.isoformat(),
            },
            requested_capabilities=tuple(item.value for item in ExecutorCapability),
            evidence_uris=tuple(request.evidence_uris),
            timeout_seconds=request.timeout_seconds,
        )
        receipt = CalyxDryRunExecutor().execute(assignment)
        receipt.verify()
        return ExecutionResult(
            input_checksum=receipt.input_checksum,
            output_checksum=receipt.output_checksum,
            adapter_name=self.name,
            dry_run=True,
            authoritative=False,
            state=receipt.state.value,
            outcome=receipt.outcome.value,
            evidence_uris=list(receipt.evidence_uris),
            output=dict(receipt.output),
            blocker_code=receipt.blocker_code,
        )
