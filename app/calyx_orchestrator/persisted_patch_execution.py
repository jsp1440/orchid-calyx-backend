from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from .execution_bridge import decode_receipt_evidence
from .executor import canonical_checksum
from .isolated_patch_executor import ISOLATED_PATCH_ROLE, IsolatedWorkspacePatchExecutor
from .program_models import CalyxProgramJob


@dataclass(frozen=True, slots=True)
class PersistedPatchExecution:
    program_job_id: str
    program_id: str
    job_key: str
    repository: str
    branch: str
    executor_key: str
    output_checksum: str
    output: dict[str, object]
    evidence_uris: tuple[str, ...]


class PersistedPatchExecutionService:
    """Resolve authoritative isolated-patch evidence from a durable program-job row."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_completed(self, *, program_job_id: str) -> PersistedPatchExecution:
        normalized_id = str(program_job_id or "").strip()
        if not normalized_id:
            raise ValueError("PATCH_PROGRAM_JOB_ID_REQUIRED")

        job = self.db.get(CalyxProgramJob, normalized_id)
        if job is None:
            raise LookupError("PATCH_PROGRAM_JOB_NOT_FOUND")
        if not sa_inspect(job).persistent:
            raise PermissionError("PATCH_PROGRAM_JOB_NOT_PERSISTENT")
        if job.status != "completed" or job.outcome != "DELIVERED":
            raise PermissionError("PATCH_PROGRAM_JOB_NOT_DELIVERED")
        if job.role_key != ISOLATED_PATCH_ROLE or not bool(job.mutating):
            raise PermissionError("PATCH_PROGRAM_JOB_ROLE_INVALID")
        if not job.repository.strip() or not str(job.branch or "").strip():
            raise PermissionError("PATCH_PROGRAM_JOB_IDENTITY_INVALID")

        evidence = decode_receipt_evidence(job)
        if evidence.get("receipt_type") != "execution":
            raise PermissionError("PATCH_PROGRAM_JOB_RECEIPT_INVALID")
        executor_key = str(evidence.get("executor_key") or "").strip()
        if executor_key != IsolatedWorkspacePatchExecutor.executor_key:
            raise PermissionError("PATCH_PROGRAM_JOB_EXECUTOR_INVALID")
        if str(evidence.get("state") or "").strip().lower() != "delivered":
            raise PermissionError("PATCH_PROGRAM_JOB_RECEIPT_NOT_DELIVERED")
        if evidence.get("blocker_code") not in {None, ""}:
            raise PermissionError("PATCH_PROGRAM_JOB_BLOCKED")

        output = evidence.get("output")
        if not isinstance(output, Mapping):
            raise TypeError("PATCH_PROGRAM_JOB_OUTPUT_REQUIRED")
        output_dict = dict(output)
        output_checksum = str(evidence.get("output_checksum") or "").strip().lower()
        if len(output_checksum) != 64 or any(
            character not in "0123456789abcdef" for character in output_checksum
        ):
            raise ValueError("PATCH_PROGRAM_JOB_OUTPUT_CHECKSUM_INVALID")
        if output_checksum != canonical_checksum(output_dict):
            raise PermissionError("PATCH_PROGRAM_JOB_OUTPUT_CHECKSUM_MISMATCH")

        repository = str(output_dict.get("repository") or "").strip()
        branch = str(output_dict.get("branch") or "").strip()
        if repository != job.repository or branch != str(job.branch):
            raise PermissionError("PATCH_PROGRAM_JOB_IDENTITY_MISMATCH")
        if output_dict.get("mode") != "authoritative_isolated_workspace_patch":
            raise PermissionError("PATCH_PROGRAM_JOB_MODE_INVALID")
        if not bool(output_dict.get("executed")):
            raise PermissionError("PATCH_PROGRAM_JOB_NOT_EXECUTED")
        if not bool(output_dict.get("workspace_isolated")) or not bool(
            output_dict.get("workspace_disposable")
        ):
            raise PermissionError("PATCH_PROGRAM_JOB_WORKSPACE_INVALID")
        if bool(output_dict.get("commit_created")):
            raise PermissionError("PATCH_PROGRAM_JOB_PREEXISTING_COMMIT_PROHIBITED")

        raw_uris = evidence.get("evidence_uris")
        if not isinstance(raw_uris, list):
            raise TypeError("PATCH_PROGRAM_JOB_EVIDENCE_URIS_INVALID")
        evidence_uris = tuple(str(uri) for uri in raw_uris)

        return PersistedPatchExecution(
            program_job_id=job.program_job_id,
            program_id=job.program_id,
            job_key=job.job_key,
            repository=job.repository,
            branch=str(job.branch),
            executor_key=executor_key,
            output_checksum=output_checksum,
            output=output_dict,
            evidence_uris=evidence_uris,
        )
