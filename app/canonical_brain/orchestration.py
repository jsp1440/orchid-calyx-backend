from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.calyx_orchestrator.engineering_core import TerminalOutcome
from app.calyx_orchestrator.execution_bridge import decode_receipt_evidence
from app.calyx_orchestrator.executor import ExecutionState, canonical_checksum
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.program_models import CalyxProgramJob

from .build_queue import GovernedBuildQueue


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentDescriptor(StrictModel):
    agent_id: str = Field(min_length=3)
    title: str = Field(min_length=3)
    architecture_ids: list[str] = Field(min_length=1)
    enabled: bool = True


class BuildAssignment(StrictModel):
    assignment_id: str = Field(min_length=16)
    build_id: str = Field(min_length=3)
    agent_id: str = Field(min_length=3)
    architecture_id: str = Field(min_length=3)
    assigned_at: datetime
    status: Literal["scheduled", "running", "completed", "cancelled"] = "scheduled"


class ExecutionReceipt(StrictModel):
    receipt_id: str = Field(min_length=16)
    assignment_id: str = Field(min_length=16)
    build_id: str = Field(min_length=3)
    agent_id: str = Field(min_length=3)
    outcome: Literal["started", "completed", "cancelled"]
    recorded_at: datetime
    evidence_uris: list[str] = Field(default_factory=list)
    output_checksum: str | None = None
    executor_key: str | None = None
    authoritative: bool = False


class GovernedOrchestrator:
    """Assigns admitted builds and records governed state without launching agents."""

    def __init__(self, queue: GovernedBuildQueue, agents: list[AgentDescriptor]) -> None:
        self._queue = queue
        self._agents = {agent.agent_id: agent for agent in agents}
        self._assignments: dict[str, BuildAssignment] = {}
        self._receipts: dict[str, ExecutionReceipt] = {}

    @staticmethod
    def _stable_id(*parts: str) -> str:
        return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()

    @staticmethod
    def _role_key(agent_id: str) -> str:
        normalized = agent_id.strip().removeprefix("agent:").replace("-", "_")
        if not normalized:
            raise ValueError("CANONICAL_AGENT_ROLE_INVALID")
        return normalized

    def eligible_agents(self, architecture_id: str) -> list[AgentDescriptor]:
        return sorted(
            [
                agent
                for agent in self._agents.values()
                if agent.enabled and architecture_id in agent.architecture_ids
            ],
            key=lambda agent: agent.agent_id,
        )

    def assign(self, build_id: str, assigned_at: datetime) -> BuildAssignment:
        existing = next(
            (assignment for assignment in self._assignments.values() if assignment.build_id == build_id),
            None,
        )
        if existing is not None:
            return existing

        item = self._queue.get(build_id)
        if item is None:
            raise KeyError(build_id)
        if item.status != "admitted":
            raise ValueError("only admitted builds may be assigned")
        agents = self.eligible_agents(item.architecture_id)
        if not agents:
            raise ValueError(f"no enabled agent supports {item.architecture_id}")
        agent = agents[0]
        assignment_id = self._stable_id(build_id, agent.agent_id, item.architecture_id)
        self._queue.transition(build_id, "scheduled")
        assignment = BuildAssignment(
            assignment_id=assignment_id,
            build_id=build_id,
            agent_id=agent.agent_id,
            architecture_id=item.architecture_id,
            assigned_at=assigned_at,
        )
        self._assignments[assignment_id] = assignment
        return assignment

    def record_started(self, assignment_id: str, recorded_at: datetime) -> ExecutionReceipt:
        assignment = self._assignments.get(assignment_id)
        if assignment is None:
            raise KeyError(assignment_id)
        if assignment.status != "scheduled":
            raise ValueError("only scheduled assignments may start")
        self._queue.transition(assignment.build_id, "running")
        updated = assignment.model_copy(update={"status": "running"})
        self._assignments[assignment_id] = updated
        return self._record(updated, "started", recorded_at, [], None)

    def record_completed(
        self,
        assignment_id: str,
        recorded_at: datetime,
        db: Session,
        *,
        program_job_id: str,
        executor_role_key: str,
    ) -> ExecutionReceipt:
        """Complete only from receipt evidence durably recorded by Calyx's lease bridge."""
        assignment = self._assignments.get(assignment_id)
        if assignment is None:
            raise KeyError(assignment_id)
        if assignment.status != "running":
            raise ValueError("only running assignments may complete")

        job = db.get(CalyxProgramJob, program_job_id)
        if job is None:
            raise LookupError("PROGRAM_JOB_NOT_FOUND")
        if job.job_key != assignment.build_id:
            raise ValueError("COMPLETION_BUILD_MISMATCH")
        if job.role_key != executor_role_key:
            raise ValueError("COMPLETION_ROLE_MISMATCH")
        if job.status != "completed" or job.outcome != TerminalOutcome.DELIVERED.value:
            raise ValueError("ONLY_DURABLY_DELIVERED_JOBS_MAY_COMPLETE")
        if job.completed_at is None:
            raise ValueError("DURABLE_COMPLETION_TIMESTAMP_REQUIRED")

        evidence = decode_receipt_evidence(job)
        if evidence.get("receipt_type") != "execution":
            raise ValueError("DURABLE_EXECUTION_RECEIPT_REQUIRED")
        if evidence.get("state") != ExecutionState.DELIVERED.value:
            raise ValueError("ONLY_DURABLY_DELIVERED_JOBS_MAY_COMPLETE")

        registered = AuthoritativeExecutorRegistry().require_authoritative(executor_role_key)
        if registered.external_side_effects:
            raise PermissionError("EXTERNAL_SIDE_EFFECT_EXECUTOR_COMPLETION_PROHIBITED")
        executor_key = str(evidence.get("executor_key") or "")
        if executor_key != registered.executor.executor_key:
            raise ValueError("COMPLETION_EXECUTOR_MISMATCH")
        if self._role_key(assignment.agent_id) != registered.role_key:
            raise PermissionError("COMPLETION_AGENT_ROLE_MISMATCH")

        output = evidence.get("output")
        output_checksum = str(evidence.get("output_checksum") or "")
        input_checksum = str(evidence.get("input_checksum") or "")
        evidence_uris = evidence.get("evidence_uris")
        if not isinstance(output, dict):
            raise TypeError("DURABLE_EXECUTION_OUTPUT_INVALID")
        if len(output_checksum) != 64 or canonical_checksum(output) != output_checksum:
            raise ValueError("DURABLE_EXECUTION_OUTPUT_CHECKSUM_INVALID")
        if len(input_checksum) != 64:
            raise ValueError("DURABLE_EXECUTION_INPUT_CHECKSUM_INVALID")
        if not isinstance(evidence_uris, list) or not all(
            isinstance(uri, str) and uri.strip() for uri in evidence_uris
        ):
            raise ValueError("DURABLE_EXECUTION_EVIDENCE_REQUIRED")
        if not evidence_uris:
            raise ValueError("DURABLE_EXECUTION_EVIDENCE_REQUIRED")
        durable_job_uri = f"calyx:program-job/{job.program_job_id}"
        if durable_job_uri not in evidence_uris:
            raise ValueError("DURABLE_PROGRAM_JOB_EVIDENCE_REQUIRED")

        self._queue.transition(assignment.build_id, "completed")
        updated = assignment.model_copy(update={"status": "completed"})
        self._assignments[assignment_id] = updated
        return self._record(
            updated,
            "completed",
            recorded_at,
            list(evidence_uris),
            output_checksum,
            executor_key=executor_key,
            authoritative=True,
        )

    def _record(
        self,
        assignment: BuildAssignment,
        outcome: Literal["started", "completed", "cancelled"],
        recorded_at: datetime,
        evidence_uris: list[str],
        output_checksum: str | None,
        *,
        executor_key: str | None = None,
        authoritative: bool = False,
    ) -> ExecutionReceipt:
        receipt_id = self._stable_id(assignment.assignment_id, outcome)
        candidate = ExecutionReceipt(
            receipt_id=receipt_id,
            assignment_id=assignment.assignment_id,
            build_id=assignment.build_id,
            agent_id=assignment.agent_id,
            outcome=outcome,
            recorded_at=recorded_at,
            evidence_uris=evidence_uris,
            output_checksum=output_checksum,
            executor_key=executor_key,
            authoritative=authoritative,
        )
        existing = self._receipts.get(receipt_id)
        if existing and existing != candidate:
            raise ValueError(f"conflicting execution receipt identity: {receipt_id}")
        self._receipts[receipt_id] = candidate
        return candidate

    def assignments(self) -> list[BuildAssignment]:
        return sorted(self._assignments.values(), key=lambda item: item.assignment_id)

    def receipts(self) -> list[ExecutionReceipt]:
        return sorted(self._receipts.values(), key=lambda item: item.receipt_id)
