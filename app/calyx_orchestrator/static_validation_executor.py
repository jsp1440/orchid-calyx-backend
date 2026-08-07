from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .engineering_core import TerminalOutcome
from .executor import (
    ExecutionReceipt,
    ExecutionState,
    GovernedAssignment,
    canonical_checksum,
)
from .isolated_patch_executor import (
    ALLOWED_PATH_PREFIXES,
    ISOLATION_MARKER,
    ISOLATION_SCHEMA,
)
from .repository_evidence_executor import RepositoryEvidenceExecutor

STATIC_VALIDATION_ROLE = "isolated_workspace_static_validator"
MAX_VALIDATION_FILES = 16
MAX_FILE_BYTES = 500_000
MAX_TOTAL_BYTES = 2_000_000


@dataclass(frozen=True, slots=True)
class ValidationTarget:
    path: str
    sha256: str


class IsolatedWorkspaceStaticValidationExecutor:
    """Read-only validation that never imports or executes repository code."""

    executor_key = "isolated_workspace_static_validator_v1"

    def __init__(
        self,
        *,
        workspace_root=None,
        repository_name: str | None = None,
    ) -> None:
        reader = RepositoryEvidenceExecutor(
            workspace_root=workspace_root,
            repository_name=repository_name,
        )
        self.workspace_root = reader.workspace_root
        self.repository_name = reader.repository_name
        self._reader = reader

    def execute(self, assignment: GovernedAssignment) -> ExecutionReceipt:
        if assignment.role_key != STATIC_VALIDATION_ROLE:
            raise PermissionError("STATIC_VALIDATION_ROLE_REQUIRED")
        if assignment.cancelled:
            raise PermissionError("STATIC_VALIDATION_CANCELLED")
        if assignment.timeout_seconds <= 0:
            raise PermissionError("STATIC_VALIDATION_TIMEOUT_INVALID")
        if assignment.requested_capabilities:
            allowed = {"validate_input", "produce_receipt", "collect_evidence_uris"}
            unsupported = sorted(set(assignment.requested_capabilities) - allowed)
            if unsupported:
                raise PermissionError(
                    f"STATIC_VALIDATION_UNSUPPORTED_CAPABILITY:{','.join(unsupported)}"
                )

        job = assignment.inputs.get("job")
        if not isinstance(job, dict):
            raise TypeError("STATIC_VALIDATION_JOB_INPUT_REQUIRED")
        if bool(job.get("mutating_intent")):
            raise PermissionError("STATIC_VALIDATION_MUTATION_PROHIBITED")

        repository = str(job.get("repository") or "").strip()
        branch = str(job.get("branch") or "").strip()
        if repository != self.repository_name:
            raise PermissionError("STATIC_VALIDATION_REPOSITORY_MISMATCH")
        if not branch.startswith("autonomy/"):
            raise PermissionError("STATIC_VALIDATION_AUTONOMY_BRANCH_REQUIRED")

        checkout = self._reader._checkout_identity()
        if checkout.branch != branch:
            raise PermissionError("STATIC_VALIDATION_REVISION_MISMATCH")
        self._verify_isolation_marker(repository=repository, branch=branch)

        raw_targets = job.get("files")
        if not isinstance(raw_targets, list) or not raw_targets:
            raise TypeError("STATIC_VALIDATION_FILES_REQUIRED")
        if len(raw_targets) > MAX_VALIDATION_FILES:
            raise ValueError("STATIC_VALIDATION_FILE_COUNT_EXCEEDED")
        targets = tuple(self._parse_target(item) for item in raw_targets)
        if len({target.path for target in targets}) != len(targets):
            raise ValueError("STATIC_VALIDATION_DUPLICATE_PATH")

        results: list[dict[str, object]] = []
        total_bytes = 0
        for target in targets:
            self._validate_path(target.path)
            try:
                raw, size = self._reader._read_workspace_file(target.path, MAX_FILE_BYTES)
            except FileNotFoundError as exc:
                raise FileNotFoundError(
                    f"STATIC_VALIDATION_FILE_MISSING:{target.path}"
                ) from exc
            total_bytes += size
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError("STATIC_VALIDATION_TOTAL_BYTES_EXCEEDED")
            digest = hashlib.sha256(raw).hexdigest()
            if digest != target.sha256:
                raise ValueError(f"STATIC_VALIDATION_HASH_MISMATCH:{target.path}")
            try:
                source = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"STATIC_VALIDATION_NOT_UTF8:{target.path}") from exc

            language = "text"
            syntax_state = "not_applicable"
            if target.path.endswith(".py"):
                language = "python"
                try:
                    tree = ast.parse(source, filename=target.path, mode="exec")
                    compile(tree, target.path, "exec", dont_inherit=True, optimize=0)
                except (SyntaxError, ValueError, TypeError, MemoryError) as exc:
                    raise ValueError(
                        f"STATIC_VALIDATION_PYTHON_SYNTAX_INVALID:{target.path}"
                    ) from exc
                syntax_state = "passed"

            results.append(
                {
                    "path": target.path,
                    "sha256": digest,
                    "size_bytes": size,
                    "language": language,
                    "utf8": True,
                    "syntax": syntax_state,
                }
            )

        checkout_after = self._reader._checkout_identity()
        if checkout_after != checkout:
            raise RuntimeError("STATIC_VALIDATION_CHECKOUT_CHANGED_DURING_SCAN")

        input_checksum = assignment.verified_input_checksum()
        output: dict[str, object] = {
            "status": "delivered",
            "executed": True,
            "mode": "authoritative_read_only_static_validation",
            "repository": repository,
            "branch": branch,
            "checkout_commit_sha": checkout.commit_sha,
            "workspace_isolated": True,
            "file_count": len(results),
            "total_bytes": total_bytes,
            "results": results,
            "repository_code_imported": False,
            "repository_code_executed": False,
            "subprocess_invoked": False,
            "shell_invoked": False,
            "network_used": False,
            "files_written": False,
            "side_effects": [],
        }
        evidence_uris = (
                *assignment.evidence_uris,
                f"repo-commit:{repository}@{checkout.commit_sha}",
                *[f"validated-file:{item['path']}#{item['sha256']}" for item in results],
            )
        receipt = ExecutionReceipt(
            assignment_id=assignment.assignment_id,
            program_id=assignment.program_id,
            job_key=assignment.job_key,
            executor_key=self.executor_key,
            state=ExecutionState.DELIVERED,
            outcome=TerminalOutcome.DELIVERED,
            input_checksum=input_checksum,
            output_checksum=canonical_checksum(output),
            output=output,
            evidence_uris=evidence_uris,
        )
        receipt.verify()
        return receipt

    def _verify_isolation_marker(self, *, repository: str, branch: str) -> None:
        try:
            raw, _ = self._reader._read_workspace_file(ISOLATION_MARKER, 32_768)
        except FileNotFoundError as exc:
            raise PermissionError("STATIC_VALIDATION_MARKER_REQUIRED") from exc
        try:
            marker = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PermissionError("STATIC_VALIDATION_MARKER_INVALID") from exc
        expected = {
            "schema": ISOLATION_SCHEMA,
            "repository": repository,
            "branch": branch,
            "disposable": True,
            "workspace_write_authorized": True,
        }
        if not isinstance(marker, dict) or any(
            marker.get(key) != value for key, value in expected.items()
        ):
            raise PermissionError("STATIC_VALIDATION_MARKER_MISMATCH")

    @staticmethod
    def _parse_target(value: Any) -> ValidationTarget:
        if not isinstance(value, dict):
            raise TypeError("STATIC_VALIDATION_TARGET_INVALID")
        path = str(value.get("path") or "").strip()
        sha256 = str(value.get("sha256") or "").strip().lower()
        if not path or not _is_sha256(sha256):
            raise ValueError("STATIC_VALIDATION_TARGET_INVALID")
        return ValidationTarget(path=path, sha256=sha256)

    @staticmethod
    def _validate_path(relative_path: str) -> None:
        path = PurePosixPath(relative_path)
        if path.is_absolute() or not path.parts or any(
            part in {"", ".", ".."} for part in path.parts
        ):
            raise PermissionError("STATIC_VALIDATION_PATH_ESCAPE")
        normalized = path.as_posix()
        if not normalized.startswith(ALLOWED_PATH_PREFIXES):
            raise PermissionError(f"STATIC_VALIDATION_PATH_NOT_ALLOWED:{normalized}")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
