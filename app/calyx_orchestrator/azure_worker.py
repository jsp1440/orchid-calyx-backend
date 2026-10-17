"""One bounded input-verification worker; no queue, DB, shell, or AI execution."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from .azure_execution_contract import AZURE_EXECUTOR_KEY, AZURE_ROLE
from .engineering_core import TerminalOutcome
from .executor import (
    ExecutionReceipt,
    ExecutionState,
    ExecutorCapability,
    GovernedAssignment,
    canonical_checksum,
)

MAX_PAYLOAD_BYTES = 16384
MAX_RUNTIME_SECONDS = 60
SAFE_CAPABILITIES = tuple(item.value for item in ExecutorCapability)


class WorkerContractError(ValueError):
    pass


class WorkerInterrupted(RuntimeError):
    pass


def receipt_json(receipt: ExecutionReceipt) -> str:
    receipt.verify()
    return json.dumps(
        {
            **asdict(receipt),
            "state": receipt.state.value,
            "outcome": receipt.outcome.value,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise WorkerContractError("WORKER_DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def _nonfinite(_: str) -> object:
    raise WorkerContractError("WORKER_NONFINITE_JSON")


@dataclass(frozen=True, slots=True)
class WorkerEnvelope:
    assignment: GovernedAssignment
    lease_digest: str
    expires_at: datetime
    execution_reference: str
    deadline: datetime
    fake: bool

    @classmethod
    def parse(
        cls,
        encoded: str,
        *,
        execution_reference: str,
        fake: bool,
        now: datetime | None = None,
    ) -> WorkerEnvelope:
        now = now or datetime.now(UTC)
        if not encoded or len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise WorkerContractError("WORKER_PAYLOAD_SIZE_INVALID")
        value = json.loads(
            encoded, object_pairs_hook=_object, parse_constant=_nonfinite
        )
        required = {
            "assignment_id",
            "program_id",
            "job_key",
            "input_checksum",
            "lease_digest",
            "lease_expires_at",
            "timeout_seconds",
            "inputs",
            "requested_capabilities",
            "evidence_uris",
            "approval_reference",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise WorkerContractError("WORKER_PAYLOAD_FIELDS_INVALID")
        for field in ("assignment_id", "program_id"):
            if (
                not isinstance(value[field], str)
                or str(UUID(value[field])) != value[field]
            ):
                raise WorkerContractError("WORKER_DURABLE_ID_INVALID")
        for field in ("input_checksum", "lease_digest"):
            if not isinstance(value[field], str) or not re.fullmatch(
                r"[a-f0-9]{64}", value[field]
            ):
                raise WorkerContractError("WORKER_CHECKSUM_INVALID")
        timeout = value["timeout_seconds"]
        if type(timeout) is not int or not 1 <= timeout <= MAX_RUNTIME_SECONDS:
            raise WorkerContractError("WORKER_TIMEOUT_INVALID")
        expiry = datetime.fromisoformat(value["lease_expires_at"])
        if expiry.tzinfo is None or expiry <= now:
            raise WorkerContractError("WORKER_LEASE_EXPIRED_OR_UNVERIFIABLE")
        approval = value["approval_reference"]
        if not isinstance(approval, str) or not approval.strip() or len(approval) > 500:
            raise WorkerContractError("WORKER_APPROVAL_REFERENCE_REQUIRED")
        inputs = value["inputs"]
        if not isinstance(inputs, dict) or set(inputs) != {
            "program",
            "job",
            "governance",
        }:
            raise WorkerContractError("WORKER_CANONICAL_INPUTS_REQUIRED")
        program, job, governance = (
            inputs["program"],
            inputs["job"],
            inputs["governance"],
        )
        if not all(isinstance(item, dict) for item in (program, job, governance)):
            raise WorkerContractError("WORKER_CANONICAL_INPUTS_REQUIRED")
        if (
            program.get("program_id") != value["program_id"]
            or job.get("program_job_id") != value["assignment_id"]
            or job.get("job_key") != value["job_key"]
            or job.get("role_key") != AZURE_ROLE
            or job.get("mutating_intent") is not False
            or type(job.get("attempt_count")) is not int
            or not 1 <= job["attempt_count"] <= 3
            or not isinstance(job.get("title"), str)
            or not job["title"].strip()
            or job.get("operation", "validate_input") != "validate_input"
        ):
            raise WorkerContractError("WORKER_JOB_IDENTITY_OR_OPERATION_INVALID")
        expected_governance = {
            "mode": "bounded_dry_run",
            "external_execution_authorized": False,
            "repository_code_execution_authorized": False,
            "automatic_merge_authorized": False,
            "deployment_authorized": False,
            "publication_authorized": False,
            "production_graph_mutation_authorized": False,
        }
        if governance != expected_governance:
            raise WorkerContractError("WORKER_GOVERNANCE_MISMATCH")
        if value["requested_capabilities"] != list(SAFE_CAPABILITIES):
            raise WorkerContractError("WORKER_CAPABILITIES_REFUSED")
        evidence = value["evidence_uris"]
        if not isinstance(evidence, list) or evidence != [
            f"calyx:program/{value['program_id']}",
            f"calyx:program-job/{value['assignment_id']}",
        ]:
            raise WorkerContractError("WORKER_PROVENANCE_MISMATCH")
        if not re.fullmatch(
            r"/subscriptions/[A-Za-z0-9-]+/resourceGroups/[A-Za-z0-9_.()-]+"
            r"/providers/Microsoft.App/jobs/[A-Za-z0-9_.()-]+/executions/[A-Za-z0-9_-]+",
            execution_reference,
        ):
            raise WorkerContractError("WORKER_EXECUTION_REFERENCE_REQUIRED")
        assignment = GovernedAssignment(
            value["assignment_id"],
            value["program_id"],
            value["job_key"],
            AZURE_ROLE,
            job["title"],
            inputs,
            tuple(value["requested_capabilities"]),
            tuple(evidence),
            timeout_seconds=timeout,
            input_checksum=value["input_checksum"],
        )
        assignment.verified_input_checksum()
        return cls(
            assignment,
            value["lease_digest"],
            expiry,
            execution_reference,
            min(expiry, now + timedelta(seconds=timeout)),
            fake,
        )

    def check_deadline(self, now: datetime | None = None) -> None:
        if (now or datetime.now(UTC)) >= self.deadline:
            raise TimeoutError("WORKER_DEADLINE_EXCEEDED")


def execute_envelope(
    envelope: WorkerEnvelope,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ExecutionReceipt:
    """Execute only canonical checksum/provenance preflight, not arbitrary missions."""
    envelope.check_deadline(clock())
    assignment = envelope.assignment
    checksum = assignment.verified_input_checksum()
    output = {
        "status": "delivered",
        "mode": "provider_free_container"
        if envelope.fake
        else "bounded_input_verification",
        "operation": "validate_input",
        "lease_digest": envelope.lease_digest,
        "execution_reference": envelope.execution_reference,
        "verified_input_checksum": checksum,
        "canonical_identity_verified": True,
        "publication_authorized": False,
        "production_access": False,
    }
    envelope.check_deadline(clock())
    receipt = ExecutionReceipt(
        assignment.assignment_id,
        assignment.program_id,
        assignment.job_key,
        AZURE_EXECUTOR_KEY,
        ExecutionState.DELIVERED,
        TerminalOutcome.DELIVERED,
        checksum,
        canonical_checksum(output),
        output,
        assignment.evidence_uris,
    )
    receipt.verify()
    return receipt


def failure_receipt(envelope: WorkerEnvelope, code: str) -> ExecutionReceipt:
    assignment = envelope.assignment
    output = {
        "status": "blocked",
        "lease_digest": envelope.lease_digest,
        "execution_reference": envelope.execution_reference,
        "failure_code": code,
        "production_access": False,
    }
    return ExecutionReceipt(
        assignment.assignment_id,
        assignment.program_id,
        assignment.job_key,
        AZURE_EXECUTOR_KEY,
        ExecutionState.BLOCKED,
        TerminalOutcome.BLOCKED,
        assignment.verified_input_checksum(),
        canonical_checksum(output),
        output,
        assignment.evidence_uris,
        code,
    )


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("WORKER_ARTIFACT_DEADLINE_EXCEEDED")
    return min(10.0, remaining)


class ManagedBlobReceiptWriter:
    """Conditional-create immutable receipts; duplicate conflict is never success."""

    def __init__(self, env: Mapping[str, str], *, credential=None) -> None:
        self.account = env.get("CALYX_RECEIPT_STORAGE_ACCOUNT", "")
        self.container = env.get("CALYX_RECEIPT_CONTAINER", "")
        client_id = env.get("CALYX_WORKER_IDENTITY_CLIENT_ID", "")
        if not (
            re.fullmatch(r"[a-z0-9]{3,24}", self.account)
            and re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", self.container)
            and re.fullmatch(r"[a-fA-F0-9-]{36}", client_id)
        ):
            raise WorkerContractError("WORKER_MANAGED_RECEIPT_CONFIGURATION_REQUIRED")
        if credential is None:
            from azure.identity import ManagedIdentityCredential

            credential = ManagedIdentityCredential(
                client_id=client_id,
                connection_timeout=5,
                read_timeout=5,
                retry_total=0,
            )
        self.credential = credential

    def write(self, envelope: WorkerEnvelope, receipt: ExecutionReceipt) -> str:
        import requests

        envelope.check_deadline()
        deadline = time.monotonic() + min(
            10, (envelope.deadline - datetime.now(UTC)).total_seconds()
        )
        url = (
            f"https://{self.account}.blob.core.windows.net/{self.container}"
            f"/{receipt.assignment_id}/{envelope.lease_digest}/receipt.json"
        )
        uri = (
            f"azure-blob:{self.account}/{self.container}"
            f"/{receipt.assignment_id}/{envelope.lease_digest}/receipt.json"
        )
        # The immutable evidence URI participates in the receipt, not the output hash.
        receipt = ExecutionReceipt(
            **{**asdict(receipt), "evidence_uris": (*receipt.evidence_uris, uri)}
        )
        encoded = receipt_json(receipt).encode("utf-8")
        token = self.credential.get_token("https://storage.azure.com/.default")
        envelope.check_deadline()
        headers = {
            "Authorization": f"Bearer {token.token}",
            "x-ms-version": "2024-08-04",
            "x-ms-blob-type": "BlockBlob",
            "If-None-Match": "*",
            "Content-Type": "application/json",
        }
        with requests.put(
            url,
            data=encoded,
            headers=headers,
            timeout=_remaining(deadline),
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code != 201:
                raise WorkerContractError(
                    f"WORKER_RECEIPT_WRITE_HTTP_{response.status_code}"
                )
        envelope.check_deadline()
        return uri


def _reference(env: Mapping[str, str], fake: bool) -> str:
    if fake:
        if env.get("CALYX_AZURE_WORKER_TEST_MODE") != "provider-free":
            raise WorkerContractError("WORKER_TEST_MODE_REQUIRED")
        return env.get("CALYX_WORKER_EXECUTION_REFERENCE", "")
    resource = env.get("CALYX_WORKER_JOB_RESOURCE_ID", "")
    name = env.get("CONTAINER_APP_JOB_EXECUTION_NAME", "")
    if not name:
        raise WorkerContractError("WORKER_PLATFORM_EXECUTION_NAME_REQUIRED")
    return f"{resource}/executions/{name}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fake", action="store_true", help="Network-free stdout receipt test"
    )
    args = parser.parse_args(argv)
    envelope: WorkerEnvelope | None = None
    previous: dict[int, object] = {}

    def interrupted(signum: int, _: object) -> None:
        raise WorkerInterrupted(f"WORKER_INTERRUPTED_{signum}")

    try:
        if args.fake:
            if os.environ.get("CALYX_AZURE_WORKER_ENABLED", "false") != "false":
                raise WorkerContractError("WORKER_FAKE_LIVE_MODE_CONFLICT")
        elif os.environ.get("CALYX_AZURE_WORKER_ENABLED", "false") != "true":
            raise WorkerContractError("WORKER_DISABLED")
        envelope = WorkerEnvelope.parse(
            os.environ.get("CALYX_EXECUTION_PAYLOAD", ""),
            execution_reference=_reference(os.environ, args.fake),
            fake=args.fake,
        )
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, interrupted)
        if hasattr(signal, "SIGALRM"):
            previous[signal.SIGALRM] = signal.signal(signal.SIGALRM, interrupted)
            signal.alarm(envelope.assignment.timeout_seconds)
        receipt = execute_envelope(envelope)
        if args.fake:
            print(receipt_json(receipt))
        else:
            uri = ManagedBlobReceiptWriter(os.environ).write(envelope, receipt)
            print(
                json.dumps(
                    {
                        "assignment_id": receipt.assignment_id,
                        "state": receipt.state.value,
                        "evidence_uri": uri,
                        "executor_key": receipt.executor_key,
                    },
                    sort_keys=True,
                )
            )
        return 0
    except Exception as exc:  # noqa: BLE001 - process boundary: emit sanitized failure, exit nonzero
        # Error messages/provider payloads can contain private mission inputs or tokens.
        # The provider journal records ARM failure; do not emit arbitrary exception text.
        code = str(exc) if isinstance(exc, WorkerContractError) else type(exc).__name__
        print(json.dumps({"state": "blocked", "code": code}), file=sys.stderr)
        if envelope is not None:
            try:
                envelope.check_deadline()
                failed = failure_receipt(envelope, code)
                if args.fake:
                    print(receipt_json(failed))
                else:
                    ManagedBlobReceiptWriter(os.environ).write(envelope, failed)
            except Exception as evidence_error:  # noqa: BLE001 - report failed evidence persistence
                print(
                    json.dumps(
                        {
                            "state": "blocked",
                            "code": "WORKER_FAILURE_EVIDENCE_UNAVAILABLE",
                            "error_type": type(evidence_error).__name__,
                        }
                    ),
                    file=sys.stderr,
                )
        return 2
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
