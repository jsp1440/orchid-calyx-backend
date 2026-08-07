from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .engineering_core import TerminalOutcome
from .executor import (
    PROHIBITED_CAPABILITIES,
    ExecutionReceipt,
    ExecutionState,
    GovernedAssignment,
    canonical_checksum,
)
from .repository_evidence_executor import RepositoryEvidenceExecutor

ISOLATED_PATCH_ROLE = "isolated_workspace_patcher"
ISOLATION_MARKER = ".calyx-isolated-workspace.json"
ISOLATION_SCHEMA = "calyx-isolated-workspace-v1"
ALLOWED_PATH_PREFIXES = ("app/", "tests/", "docs/brain/")
SUPPORTED_CAPABILITIES = frozenset(
    {"validate_input", "produce_receipt", "collect_evidence_uris", "workspace_write"}
)
MAX_PATCH_FILES = 8
MAX_FILE_BYTES = 500_000
MAX_TOTAL_BYTES = 1_500_000
ABSENT_PREIMAGE = "absent"


@dataclass(frozen=True, slots=True)
class PatchSpec:
    path: str
    before_sha256: str
    content_utf8: str


@dataclass(frozen=True, slots=True)
class PreparedPatch:
    spec: PatchSpec
    target: Path
    before_sha256: str
    after_sha256: str
    before_bytes: bytes | None
    after_bytes: bytes


class IsolatedWorkspacePatchExecutor:
    """Bounded local file mutation in an explicitly disposable engineering worktree."""

    executor_key = "isolated_workspace_patcher_v1"

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
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
        if assignment.role_key != ISOLATED_PATCH_ROLE:
            raise PermissionError("ISOLATED_PATCH_ROLE_REQUIRED")
        if assignment.cancelled:
            raise PermissionError("ISOLATED_PATCH_CANCELLED")
        if assignment.timeout_seconds <= 0:
            raise PermissionError("ISOLATED_PATCH_TIMEOUT_INVALID")

        requested = set(assignment.requested_capabilities)
        prohibited = sorted(requested & PROHIBITED_CAPABILITIES)
        unsupported = sorted(requested - SUPPORTED_CAPABILITIES - PROHIBITED_CAPABILITIES)
        if prohibited:
            raise PermissionError(f"ISOLATED_PATCH_PROHIBITED_CAPABILITY:{','.join(prohibited)}")
        if unsupported:
            raise PermissionError(f"ISOLATED_PATCH_UNSUPPORTED_CAPABILITY:{','.join(unsupported)}")
        if "workspace_write" not in requested:
            raise PermissionError("ISOLATED_PATCH_WORKSPACE_WRITE_CAPABILITY_REQUIRED")

        job = assignment.inputs.get("job")
        if not isinstance(job, dict):
            raise TypeError("ISOLATED_PATCH_JOB_INPUT_REQUIRED")
        if not bool(job.get("mutating_intent")):
            raise PermissionError("ISOLATED_PATCH_MUTATING_INTENT_REQUIRED")

        repository = str(job.get("repository") or "").strip()
        branch = str(job.get("branch") or "").strip()
        if repository != self.repository_name:
            raise PermissionError("ISOLATED_PATCH_REPOSITORY_MISMATCH")
        if not branch.startswith("autonomy/"):
            raise PermissionError("ISOLATED_PATCH_AUTONOMY_BRANCH_REQUIRED")

        checkout = self._reader._checkout_identity()
        if checkout.branch != branch:
            raise PermissionError("ISOLATED_PATCH_REVISION_MISMATCH")
        self._verify_isolation_marker(repository=repository, branch=branch)

        raw_patches = job.get("patches")
        if not isinstance(raw_patches, list) or not raw_patches:
            raise TypeError("ISOLATED_PATCH_PATCHES_REQUIRED")
        if len(raw_patches) > MAX_PATCH_FILES:
            raise ValueError("ISOLATED_PATCH_FILE_COUNT_EXCEEDED")

        specs = tuple(self._parse_patch(item) for item in raw_patches)
        paths = [spec.path for spec in specs]
        if len(set(paths)) != len(paths):
            raise ValueError("ISOLATED_PATCH_DUPLICATE_PATH")

        prepared = tuple(self._prepare_patch(spec) for spec in specs)
        total_bytes = sum(len(item.after_bytes) for item in prepared)
        if total_bytes > MAX_TOTAL_BYTES:
            raise ValueError("ISOLATED_PATCH_TOTAL_BYTES_EXCEEDED")

        self._apply_prepared(prepared)

        checkout_after = self._reader._checkout_identity()
        if checkout_after != checkout:
            raise RuntimeError("ISOLATED_PATCH_CHECKOUT_CHANGED_DURING_WRITE")

        input_checksum = assignment.verified_input_checksum()
        changes = [
            {
                "path": item.spec.path,
                "before_sha256": item.before_sha256,
                "after_sha256": item.after_sha256,
                "created": item.before_bytes is None,
                "size_bytes": len(item.after_bytes),
            }
            for item in prepared
        ]
        output: dict[str, object] = {
            "status": "delivered",
            "executed": True,
            "mode": "authoritative_isolated_workspace_patch",
            "repository": repository,
            "branch": branch,
            "checkout_commit_sha": checkout.commit_sha,
            "workspace_isolated": True,
            "workspace_disposable": True,
            "changes": changes,
            "file_count": len(changes),
            "total_written_bytes": total_bytes,
            "commit_created": False,
            "validation_commands_run": False,
            "side_effects": ["isolated_workspace_files_modified"],
        }
        evidence_uris = (
            *assignment.evidence_uris,
            f"repo-commit:{repository}@{checkout.commit_sha}",
            *(f"workspace-file:{change['path']}#{change['after_sha256']}" for change in changes),
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
            raw, size = self._reader._read_workspace_file(ISOLATION_MARKER, 32_768)
        except FileNotFoundError as exc:
            raise PermissionError("ISOLATED_PATCH_MARKER_REQUIRED") from exc
        if size == 0:
            raise PermissionError("ISOLATED_PATCH_MARKER_INVALID")
        try:
            marker = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PermissionError("ISOLATED_PATCH_MARKER_INVALID") from exc
        expected = {
            "schema": ISOLATION_SCHEMA,
            "repository": repository,
            "branch": branch,
            "disposable": True,
            "workspace_write_authorized": True,
        }
        if not isinstance(marker, dict) or any(marker.get(key) != value for key, value in expected.items()):
            raise PermissionError("ISOLATED_PATCH_MARKER_MISMATCH")

    @staticmethod
    def _parse_patch(value: Any) -> PatchSpec:
        if not isinstance(value, dict):
            raise TypeError("ISOLATED_PATCH_SPEC_INVALID")
        path = str(value.get("path") or "").strip()
        before_sha256 = str(value.get("before_sha256") or "").strip().lower()
        content = value.get("content_utf8")
        if not path or not before_sha256 or not isinstance(content, str):
            raise TypeError("ISOLATED_PATCH_SPEC_INVALID")
        if before_sha256 != ABSENT_PREIMAGE and not _is_sha256(before_sha256):
            raise ValueError("ISOLATED_PATCH_PREIMAGE_HASH_INVALID")
        return PatchSpec(path=path, before_sha256=before_sha256, content_utf8=content)

    def _prepare_patch(self, spec: PatchSpec) -> PreparedPatch:
        target = self._validated_target(spec.path)
        after_bytes = spec.content_utf8.encode("utf-8")
        if len(after_bytes) > MAX_FILE_BYTES:
            raise ValueError(f"ISOLATED_PATCH_FILE_TOO_LARGE:{spec.path}")

        try:
            before_bytes, _ = self._reader._read_workspace_file(spec.path, MAX_FILE_BYTES)
        except FileNotFoundError:
            before_bytes = None

        if before_bytes is None:
            if spec.before_sha256 != ABSENT_PREIMAGE:
                raise ValueError(f"ISOLATED_PATCH_PREIMAGE_MISMATCH:{spec.path}")
            before_digest = ABSENT_PREIMAGE
        else:
            try:
                before_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"ISOLATED_PATCH_EXISTING_FILE_NOT_UTF8:{spec.path}") from exc
            before_digest = hashlib.sha256(before_bytes).hexdigest()
            if before_digest != spec.before_sha256:
                raise ValueError(f"ISOLATED_PATCH_PREIMAGE_MISMATCH:{spec.path}")

        return PreparedPatch(
            spec=spec,
            target=target,
            before_sha256=before_digest,
            after_sha256=hashlib.sha256(after_bytes).hexdigest(),
            before_bytes=before_bytes,
            after_bytes=after_bytes,
        )

    def _validated_target(self, relative_path: str) -> Path:
        path = PurePosixPath(relative_path)
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise PermissionError("ISOLATED_PATCH_PATH_ESCAPE")
        normalized = path.as_posix()
        if not normalized.startswith(ALLOWED_PATH_PREFIXES):
            raise PermissionError(f"ISOLATED_PATCH_PATH_NOT_ALLOWED:{normalized}")

        target = self.workspace_root.joinpath(*path.parts)
        parent = target.parent
        if not parent.is_dir():
            raise FileNotFoundError(f"ISOLATED_PATCH_PARENT_MISSING:{normalized}")
        resolved_parent = parent.resolve(strict=True)
        try:
            resolved_parent.relative_to(self.workspace_root)
        except ValueError as exc:
            raise PermissionError("ISOLATED_PATCH_PATH_ESCAPE") from exc
        if target.exists() and target.is_symlink():
            raise PermissionError("ISOLATED_PATCH_SYMLINK_PROHIBITED")
        return target

    def _apply_prepared(self, prepared: tuple[PreparedPatch, ...]) -> None:
        staged: list[tuple[PreparedPatch, str]] = []
        try:
            for item in prepared:
                descriptor, temporary = tempfile.mkstemp(prefix=".calyx-patch-", dir=item.target.parent)
                try:
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(item.after_bytes)
                        handle.flush()
                        os.fsync(handle.fileno())
                except Exception:
                    try:
                        os.unlink(temporary)
                    except FileNotFoundError:
                        pass
                    raise
                staged.append((item, temporary))

            applied: list[PreparedPatch] = []
            try:
                for item, temporary in staged:
                    os.replace(temporary, item.target)
                    applied.append(item)
            except Exception:
                self._rollback(applied)
                raise
        finally:
            for _, temporary in staged:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    @staticmethod
    def _rollback(applied: list[PreparedPatch]) -> None:
        for item in reversed(applied):
            if item.before_bytes is None:
                try:
                    item.target.unlink()
                except FileNotFoundError:
                    pass
            else:
                item.target.write_bytes(item.before_bytes)


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
