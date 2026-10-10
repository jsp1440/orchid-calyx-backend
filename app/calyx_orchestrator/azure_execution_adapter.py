"""Optional ExecutorAdapter for one already-admitted durable Calyx job.

Authorization is resolved by a trusted operator/control-plane dependency, never
from mission inputs. A committed reservation precedes the non-idempotent Azure
start call. An ambiguous start is never retried automatically.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .assignment_factory import governed_assignment_from_claimed_job
from .azure_execution_models import AzureExecutionRecord
from .engineering_core import TerminalOutcome
from .execution_bridge import LeaseExecutionBridge
from .executor import (
    ExecutionReceipt,
    ExecutionState,
    GovernedAssignment,
    canonical_checksum,
)
from .program_models import CalyxProgramJob

AZURE_EXECUTOR_KEY = "azure_container_apps_job_v1"
AZURE_ROLE = "azure_bounded_job"


@dataclass(frozen=True, slots=True)
class AzureJobConfig:
    enabled: bool = False
    subscription_id: str = ""
    resource_group: str = ""
    environment_name: str = ""
    job_name: str = ""
    job_identity_resource_id: str = ""
    managed_identity_client_id: str = ""
    container_name: str = ""
    image: str = ""
    max_runtime_seconds: int = 60
    api_timeout_seconds: int = 10
    poll_seconds: int = 2
    max_polls: int = 30
    max_cost_microusd: int = 0

    @classmethod
    def from_environ(cls, env: Mapping[str, str]) -> AzureJobConfig:
        names = {
            field: env.get(f"CALYX_AZURE_{field.upper()}", "")
            for field in (
                "subscription_id",
                "resource_group",
                "environment_name",
                "job_name",
                "job_identity_resource_id",
                "managed_identity_client_id",
                "container_name",
                "image",
            )
        }
        enabled = env.get("CALYX_AZURE_ENABLED", "false").lower()
        if enabled not in {"true", "false", "1", "0"}:
            raise ValueError("AZURE_ENABLED_INVALID")
        integers = {
            name: int(env.get(f"CALYX_AZURE_{name.upper()}", str(default)))
            for name, default in (
                ("max_runtime_seconds", 60),
                ("api_timeout_seconds", 10),
                ("poll_seconds", 2),
                ("max_polls", 30),
                ("max_cost_microusd", 0),
            )
        }
        return cls(enabled=enabled in {"true", "1"}, **names, **integers)

    @property
    def resource_id(self) -> str:
        return (
            f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}"
            f"/providers/Microsoft.App/jobs/{self.job_name}"
        )

    def verify(self) -> None:
        import re

        for value in (
            self.subscription_id,
            self.resource_group,
            self.environment_name,
            self.job_name,
            self.container_name,
        ):
            if not re.fullmatch(r"[A-Za-z0-9_.()-]{1,90}", value):
                raise ValueError("AZURE_RESOURCE_CONFIGURATION_INVALID")
        identity_prefix = (
            f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}"
            "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
        )
        if not self.job_identity_resource_id.startswith(identity_prefix):
            raise ValueError("AZURE_JOB_IDENTITY_REQUIRED")
        if not re.fullmatch(
            r"[A-Za-z0-9_-]+", self.job_identity_resource_id[len(identity_prefix) :]
        ):
            raise ValueError("AZURE_JOB_IDENTITY_INVALID")
        if not self.managed_identity_client_id or "@sha256:" not in self.image:
            raise ValueError("AZURE_MANAGED_AUTH_AND_PINNED_IMAGE_REQUIRED")
        if not re.fullmatch(r"[^\s]+@sha256:[a-f0-9]{64}", self.image):
            raise ValueError("AZURE_IMAGE_DIGEST_INVALID")
        if not (
            1 <= self.max_runtime_seconds <= 3600
            and 1 <= self.api_timeout_seconds <= 30
            and 1 <= self.poll_seconds <= 60
            and 1 <= self.max_polls <= 3600
            and self.max_cost_microusd > 0
        ):
            raise ValueError("AZURE_EXECUTION_BOUNDS_INVALID")


@dataclass(frozen=True, slots=True)
class AzureExecutionGrant:
    """Trusted, externally approved per-lease budget reservation; not self-approval."""

    approval_reference: str
    program_job_id: str
    input_checksum: str
    lease_digest: str
    resource_id: str
    config_checksum: str
    expires_at: datetime
    reserved_cost_microusd: int


@dataclass(frozen=True, slots=True)
class AzureObservation:
    status: str
    execution_reference: str
    evidence_uris: tuple[str, ...] = ()


class AzureApiError(RuntimeError):
    pass


class AzureJobClient(Protocol):
    def verify_job(self, config: AzureJobConfig, timeout: float) -> None: ...

    def start(
        self, config: AzureJobConfig, payload: Mapping[str, object], timeout: float
    ) -> str: ...

    def observe(
        self, config: AzureJobConfig, reference: str, timeout: float
    ) -> AzureObservation: ...

    def stop(self, config: AzureJobConfig, reference: str, timeout: float) -> None: ...

    def result(
        self,
        config: AzureJobConfig,
        reference: str,
        assignment_id: str,
        digest: str,
        timeout: float,
    ) -> ExecutionReceipt: ...


def lease_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _receipt_payload(receipt: ExecutionReceipt) -> dict[str, object]:
    return {
        **asdict(receipt),
        "state": receipt.state.value,
        "outcome": receipt.outcome.value,
    }


def _decode_receipt(payload: str) -> ExecutionReceipt:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise TypeError("AZURE_RECEIPT_OBJECT_REQUIRED")
    required = {
        "assignment_id",
        "program_id",
        "job_key",
        "executor_key",
        "state",
        "outcome",
        "input_checksum",
        "output_checksum",
        "output",
        "evidence_uris",
    }
    if not required.issubset(value):
        raise ValueError("AZURE_RECEIPT_FIELDS_MISSING")
    if not isinstance(value.get("output"), dict):
        raise TypeError("AZURE_RECEIPT_OUTPUT_OBJECT_REQUIRED")
    uris = value.get("evidence_uris")
    if not isinstance(uris, list) or not all(
        isinstance(uri, str) and uri.strip() and ":" in uri for uri in uris
    ):
        raise ValueError("AZURE_RECEIPT_EVIDENCE_INVALID")
    value["state"] = ExecutionState(value["state"])
    value["outcome"] = TerminalOutcome(value["outcome"])
    value["evidence_uris"] = tuple(value["evidence_uris"])
    receipt = ExecutionReceipt(**value)
    receipt.verify()
    return receipt


class AzureContainerAppsExecutor:
    executor_key = AZURE_EXECUTOR_KEY

    def __init__(
        self,
        db: Session,
        *,
        config: AzureJobConfig,
        client: AzureJobClient,
        owner: str,
        worker_id: str,
        lease_token: str,
        grant_resolver: Callable[[GovernedAssignment, str], AzureExecutionGrant | None],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.db, self.config, self.client = db, config, client
        self.owner, self.worker_id, self.lease_token = owner, worker_id, lease_token
        self.grant_resolver = grant_resolver
        self.clock, self.monotonic, self.sleep = clock, monotonic, sleep

    def _live(self, assignment: GovernedAssignment) -> CalyxProgramJob:
        job = self.db.get(CalyxProgramJob, assignment.assignment_id)
        if job is None:
            raise LookupError("AZURE_DURABLE_TASK_REQUIRED")
        self.db.refresh(job)
        if (
            job.status != "running"
            or job.outcome is not None
            or job.lease_owner != self.worker_id
            or not self.lease_token
            or job.lease_token != self.lease_token
            or job.lease_expires_at is None
            or _utc(job.lease_expires_at) <= self.clock()
        ):
            raise PermissionError("AZURE_STALE_OR_EXPIRED_LEASE")
        canonical = governed_assignment_from_claimed_job(
            self.db,
            owner=self.owner,
            job=job,
            timeout_seconds=assignment.timeout_seconds,
        )
        if (
            assignment.program_id != canonical.program_id
            or assignment.job_key != canonical.job_key
            or assignment.role_key != AZURE_ROLE
            or job.mutating
            or assignment.objective != canonical.objective
            or assignment.requested_capabilities != canonical.requested_capabilities
            or assignment.evidence_uris != canonical.evidence_uris
            or assignment.verified_input_checksum()
            != canonical.verified_input_checksum()
        ):
            raise PermissionError("AZURE_ASSIGNMENT_NOT_CANONICAL")
        return job

    def _save(
        self, record: AzureExecutionRecord, state: str, **evidence: object
    ) -> None:
        record.state = state
        record.evidence_json = json.dumps(
            {**json.loads(record.evidence_json or "{}"), **evidence}, sort_keys=True
        )
        self.db.commit()

    def _finish(
        self,
        record: AzureExecutionRecord,
        assignment: GovernedAssignment,
        state: ExecutionState,
        code: str | None,
        result: ExecutionReceipt | None = None,
    ) -> ExecutionReceipt:
        evidence = json.loads(record.evidence_json)
        output = {
            "provider": "azure_container_apps_jobs",
            "execution_reference": record.execution_reference,
            "provider_evidence": evidence,
            "result": dict(result.output) if result else None,
            "dispatch_accepted": record.execution_reference is not None,
            "execution_verified": result is not None,
            "retry_policy": "governed_new_job_revision_only",
        }
        uris = tuple(
            dict.fromkeys(
                (
                    *assignment.evidence_uris,
                    f"calyx:azure-execution/{assignment.assignment_id}",
                    *(result.evidence_uris if result else ()),
                    *evidence.get("evidence_uris", []),
                )
            )
        )
        receipt = ExecutionReceipt(
            assignment.assignment_id,
            assignment.program_id,
            assignment.job_key,
            self.executor_key,
            state,
            TerminalOutcome.DELIVERED
            if state == ExecutionState.DELIVERED
            else TerminalOutcome.CANCELLED
            if state == ExecutionState.CANCELLED
            else TerminalOutcome.BLOCKED,
            assignment.verified_input_checksum(),
            canonical_checksum(output),
            output,
            uris,
            code,
        )
        receipt.verify()
        record.receipt_json = json.dumps(_receipt_payload(receipt), sort_keys=True)
        self._save(record, state.value, blocker_code=code)
        return receipt

    def execute(self, assignment: GovernedAssignment) -> ExecutionReceipt:
        self._live(assignment)
        if not self.config.enabled:
            raise PermissionError("AZURE_PROVIDER_DISABLED")
        self.config.verify()
        record = AzureExecutionRecord(
            program_job_id=assignment.assignment_id,
            lease_digest=lease_digest(self.lease_token),
            input_checksum=assignment.verified_input_checksum(),
            config_checksum=canonical_checksum(asdict(self.config)),
            state="reserved",
            evidence_json=json.dumps({"start_disposition": "not_sent"}),
        )
        self.db.add(record)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise PermissionError("AZURE_DUPLICATE_DISPATCH") from exc
        try:
            try:
                grant = self.grant_resolver(assignment, record.lease_digest)
            except Exception as exc:
                self._save(
                    record, "authorization_failed", exception_type=type(exc).__name__
                )
                raise
        except Exception as exc:
            self._save(
                record, "authorization_failed", exception_type=type(exc).__name__
            )
            raise
        if grant is None or not self._valid_grant(assignment, record, grant):
            return self._finish(
                record, assignment, ExecutionState.BLOCKED, "AZURE_UNAUTHORIZED"
            )
        if grant.reserved_cost_microusd < self.config.max_cost_microusd:
            return self._finish(
                record, assignment, ExecutionState.BLOCKED, "AZURE_BUDGET_REJECTED"
            )
        runtime = min(assignment.timeout_seconds, self.config.max_runtime_seconds)
        self._save(
            record,
            "authorized",
            approval_reference=grant.approval_reference,
            reserved_cost_microusd=grant.reserved_cost_microusd,
            deadline_at=(self.clock() + timedelta(seconds=runtime)).isoformat(),
        )
        deadline = self.monotonic() + runtime
        try:
            self.client.verify_job(
                self.config, self._timeout(assignment, deadline, grant)
            )
            self._live(assignment)
            if assignment.cancelled:
                return self._finish(
                    record, assignment, ExecutionState.CANCELLED, "ASSIGNMENT_CANCELLED"
                )
            # If the process disappears here, the durable disposition is unknown.
            self._save(record, "starting", start_disposition="unknown")
            payload = {
                "assignment_id": assignment.assignment_id,
                "program_id": assignment.program_id,
                "job_key": assignment.job_key,
                "input_checksum": record.input_checksum,
                "lease_digest": record.lease_digest,
                "lease_expires_at": _utc(
                    self._live(assignment).lease_expires_at
                ).isoformat(),
                "timeout_seconds": runtime,
                "inputs": dict(assignment.inputs),
                "requested_capabilities": list(assignment.requested_capabilities),
                "evidence_uris": list(assignment.evidence_uris),
                "approval_reference": grant.approval_reference,
            }
            record.execution_reference = self.client.start(
                self.config, payload, self._timeout(assignment, deadline, grant)
            )
            self._save(
                record,
                "running",
                start_disposition="accepted",
                start_reference=record.execution_reference,
            )
            return self._poll(record, assignment, deadline, grant)
        except AzureApiError as exc:
            self._save(record, "api_failed", api_error=str(exc))
            self._stop(record)
            return self._finish(
                record, assignment, ExecutionState.BLOCKED, "AZURE_API_FAILURE"
            )
        except TimeoutError:
            self._stop(record)
            return self._finish(
                record, assignment, ExecutionState.TIMED_OUT, "AZURE_TIMEOUT"
            )
        except PermissionError as exc:
            self._save(record, "fenced", fencing_reason=str(exc))
            self._stop(record)
            raise
        except Exception as exc:
            self._save(
                record,
                "interrupted",
                exception_type=type(exc).__name__,
                reconciliation_required=True,
            )
            self._stop(record)
            raise

    def _valid_grant(
        self,
        assignment: GovernedAssignment,
        record: AzureExecutionRecord,
        grant: AzureExecutionGrant | None,
    ) -> bool:
        return not (
            grant is None
            or not grant.approval_reference.strip()
            or grant.program_job_id != assignment.assignment_id
            or grant.input_checksum != record.input_checksum
            or grant.lease_digest != record.lease_digest
            or grant.resource_id != self.config.resource_id
            or grant.config_checksum != record.config_checksum
            or _utc(grant.expires_at) <= self.clock()
        )

    def _timeout(
        self,
        assignment: GovernedAssignment,
        deadline: float,
        grant: AzureExecutionGrant,
    ) -> float:
        job = self._live(assignment)
        remaining = min(
            deadline - self.monotonic(),
            (_utc(job.lease_expires_at) - self.clock()).total_seconds(),
            (_utc(grant.expires_at) - self.clock()).total_seconds(),
        )
        if remaining <= 0:
            raise TimeoutError("AZURE_EXECUTION_DEADLINE")
        return min(float(self.config.api_timeout_seconds), remaining)

    def _poll(
        self,
        record: AzureExecutionRecord,
        assignment: GovernedAssignment,
        deadline: float,
        grant: AzureExecutionGrant,
    ) -> ExecutionReceipt:
        for _ in range(self.config.max_polls):
            observation = self.client.observe(
                self.config,
                record.execution_reference,
                self._timeout(assignment, deadline, grant),
            )
            record.execution_reference = observation.execution_reference
            self._save(
                record,
                "running",
                azure_status=observation.status,
                evidence_uris=list(observation.evidence_uris),
            )
            self._timeout(assignment, deadline, grant)
            if observation.status == "Succeeded":
                try:
                    result = self.client.result(
                        self.config,
                        record.execution_reference,
                        assignment.assignment_id,
                        record.lease_digest,
                        self._timeout(assignment, deadline, grant),
                    )
                    result.verify()
                    if (
                        result.assignment_id != assignment.assignment_id
                        or result.program_id != assignment.program_id
                        or result.job_key != assignment.job_key
                        or result.executor_key != self.executor_key
                        or result.input_checksum != record.input_checksum
                        or result.state != ExecutionState.DELIVERED
                        or not result.evidence_uris
                        or result.output.get("lease_digest") != record.lease_digest
                        or result.output.get("execution_reference")
                        != record.execution_reference
                    ):
                        raise ValueError("AZURE_RESULT_IDENTITY_MISMATCH")
                except (ValueError, TypeError) as exc:
                    self._save(record, "invalid_result", verification_error=str(exc))
                    return self._finish(
                        record,
                        assignment,
                        ExecutionState.BLOCKED,
                        "AZURE_RESULT_INVALID",
                    )
                self._timeout(assignment, deadline, grant)
                return self._finish(
                    record, assignment, ExecutionState.DELIVERED, None, result
                )
            if observation.status in {"Failed", "Stopped", "Degraded"}:
                return self._finish(
                    record,
                    assignment,
                    ExecutionState.BLOCKED,
                    f"AZURE_JOB_{observation.status.upper()}",
                )
            if observation.status not in {"Running", "Pending", "Processing"}:
                raise AzureApiError("AZURE_STATUS_UNRECOGNIZED")
            self.sleep(
                min(
                    float(self.config.poll_seconds),
                    self._timeout(assignment, deadline, grant),
                )
            )
        raise TimeoutError("AZURE_POLL_BUDGET_EXHAUSTED")

    def _stop(self, record: AzureExecutionRecord) -> None:
        if not record.execution_reference:
            unknown = (
                json.loads(record.evidence_json).get("start_disposition") == "unknown"
            )
            self._save(record, record.state, reconciliation_required=unknown)
            return
        try:
            self.client.stop(
                self.config,
                record.execution_reference,
                float(self.config.api_timeout_seconds),
            )
        except AzureApiError as exc:
            self._save(
                record, record.state, stop_error=str(exc), reconciliation_required=True
            )
        else:
            self._save(
                record, record.state, stop_requested=True, reconciliation_required=True
            )

    def settle(
        self, assignment: GovernedAssignment, receipt: ExecutionReceipt
    ) -> CalyxProgramJob:
        self._live(assignment)
        record = self.db.get(AzureExecutionRecord, assignment.assignment_id)
        if (
            record is None
            or record.lease_digest != lease_digest(self.lease_token)
            or record.input_checksum != assignment.verified_input_checksum()
            or not record.receipt_json
            or _receipt_payload(_decode_receipt(record.receipt_json))
            != _receipt_payload(receipt)
        ):
            raise PermissionError("AZURE_UNRECORDED_RECEIPT")
        completed = LeaseExecutionBridge(self.db).complete_from_receipt(
            program_job_id=assignment.assignment_id,
            worker_id=self.worker_id,
            lease_token=self.lease_token,
            receipt=receipt,
        )
        self._save(record, "settled", settled_outcome=completed.outcome)
        return completed

    def resume(self, assignment: GovernedAssignment) -> ExecutionReceipt:
        """Read/poll a known dispatch after restart; never sends another start."""
        self._live(assignment)
        if not self.config.enabled:
            raise PermissionError("AZURE_PROVIDER_DISABLED")
        record = self.db.get(AzureExecutionRecord, assignment.assignment_id)
        if (
            record is None
            or record.lease_digest != lease_digest(self.lease_token)
            or record.input_checksum != assignment.verified_input_checksum()
            or record.config_checksum != canonical_checksum(asdict(self.config))
        ):
            raise PermissionError("AZURE_RESUME_IDENTITY_MISMATCH")
        if record.receipt_json:
            return _decode_receipt(record.receipt_json)
        # A crash during start cannot prove whether Azure accepted the request.
        if not record.execution_reference:
            unknown = (
                json.loads(record.evidence_json).get("start_disposition") == "unknown"
            )
            self._save(record, "interrupted", reconciliation_required=unknown)
            return self._finish(
                record,
                assignment,
                ExecutionState.BLOCKED,
                "AZURE_START_OUTCOME_UNKNOWN"
                if unknown
                else "AZURE_PRESTART_INTERRUPTED",
            )
        grant = self.grant_resolver(assignment, record.lease_digest)
        if (
            grant is None
            or not self._valid_grant(assignment, record, grant)
            or grant.reserved_cost_microusd < self.config.max_cost_microusd
        ):
            self._stop(record)
            return self._finish(
                record, assignment, ExecutionState.BLOCKED, "AZURE_GRANT_EXPIRED"
            )
        deadline_at = json.loads(record.evidence_json).get("deadline_at")
        if not isinstance(deadline_at, str):
            raise TypeError("AZURE_DURABLE_DEADLINE_REQUIRED")
        deadline = self.monotonic() + max(
            0, (datetime.fromisoformat(deadline_at) - self.clock()).total_seconds()
        )
        try:
            return self._poll(record, assignment, deadline, grant)
        except (AzureApiError, TimeoutError) as exc:
            self._save(record, "interrupted", recovery_error=str(exc))
            self._stop(record)
            return self._finish(
                record, assignment, ExecutionState.BLOCKED, "AZURE_RECOVERY_FAILED"
            )
        except PermissionError as exc:
            self._save(record, "fenced", fencing_reason=str(exc))
            self._stop(record)
            raise
        except Exception as exc:
            self._save(record, "interrupted", exception_type=type(exc).__name__)
            self._stop(record)
            raise
