from __future__ import annotations

import base64
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
ROLLBACK_JOURNAL_SCHEMA = "calyx-isolated-rollback-v1"
ROLLBACK_JOURNAL_PREFIX = ".calyx-isolated-rollback-"
ROLLBACK_JOURNAL_SUFFIX = ".json"
ALLOWED_PATH_PREFIXES = ("app/", "tests/", "docs/brain/")
SUPPORTED_CAPABILITIES = frozenset(
    {"validate_input", "produce_receipt", "collect_evidence_uris", "workspace_write"}
)
MAX_PATCH_FILES = 8
MAX_FILE_BYTES = 500_000
MAX_TOTAL_BYTES = 1_500_000
MAX_JOURNAL_BYTES = 2_500_000
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
    """Bounded, crash-recoverable mutation in a disposable engineering worktree."""

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
        unsupported = sorted(
            requested - SUPPORTED_CAPABILITIES - PROHIBITED_CAPABILITIES
        )
        if prohibited:
            raise PermissionError(
                f"ISOLATED_PATCH_PROHIBITED_CAPABILITY:{','.join(prohibited)}"
            )
        if unsupported:
            raise PermissionError(
                f"ISOLATED_PATCH_UNSUPPORTED_CAPABILITY:{','.join(unsupported)}"
            )
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
        self._recover_for_retry(
            assignment_id=assignment.assignment_id,
            repository=repository,
            branch=branch,
            checkout_commit_sha=checkout.commit_sha,
        )

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

        self._persist_rollback_journal(
            assignment_id=assignment.assignment_id,
            repository=repository,
            branch=branch,
            checkout_commit_sha=checkout.commit_sha,
            prepared=prepared,
        )
        try:
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
                "crash_recovery_journal": True,
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
                *(
                    f"workspace-file:{change['path']}#{change['after_sha256']}"
                    for change in changes
                ),
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
        except Exception:
            self.rollback(assignment.assignment_id)
            raise

    def finalize(self, assignment_id: str) -> None:
        """Delete rollback material only after durable lease completion succeeds."""
        self._delete_journal(self._journal_path(assignment_id))

    def rollback(self, assignment_id: str) -> bool:
        """Restore an interrupted patch from its durable rollback journal."""
        journal_path = self._journal_path(assignment_id)
        if not journal_path.exists():
            return False
        journal = self._load_journal(journal_path)
        self._restore_journal(journal)
        self._delete_journal(journal_path)
        return True

    def _recover_for_retry(
        self,
        *,
        assignment_id: str,
        repository: str,
        branch: str,
        checkout_commit_sha: str,
    ) -> None:
        journals = sorted(
            self.workspace_root.glob(
                f"{ROLLBACK_JOURNAL_PREFIX}*{ROLLBACK_JOURNAL_SUFFIX}"
            )
        )
        expected_path = self._journal_path(assignment_id)
        unexpected = [path for path in journals if path != expected_path]
        if unexpected:
            raise RuntimeError("ISOLATED_PATCH_PENDING_RECOVERY_CONFLICT")
        if not expected_path.exists():
            return
        journal = self._load_journal(expected_path)
        if (
            journal["assignment_id"] != assignment_id
            or journal["repository"] != repository
            or journal["branch"] != branch
            or journal["checkout_commit_sha"] != checkout_commit_sha
        ):
            raise RuntimeError("ISOLATED_PATCH_RECOVERY_IDENTITY_MISMATCH")
        self._restore_journal(journal)
        self._delete_journal(expected_path)

    def _journal_path(self, assignment_id: str) -> Path:
        token = hashlib.sha256(assignment_id.encode("utf-8")).hexdigest()[:32]
        return self.workspace_root / (
            f"{ROLLBACK_JOURNAL_PREFIX}{token}{ROLLBACK_JOURNAL_SUFFIX}"
        )

    def _persist_rollback_journal(
        self,
        *,
        assignment_id: str,
        repository: str,
        branch: str,
        checkout_commit_sha: str,
        prepared: tuple[PreparedPatch, ...],
    ) -> None:
        entries = [
            {
                "path": item.spec.path,
                "before_sha256": item.before_sha256,
                "after_sha256": item.after_sha256,
                "before_content_b64": (
                    base64.b64encode(item.before_bytes).decode("ascii")
                    if item.before_bytes is not None
                    else None
                ),
            }
            for item in prepared
        ]
        core = {
            "schema": ROLLBACK_JOURNAL_SCHEMA,
            "assignment_id": assignment_id,
            "repository": repository,
            "branch": branch,
            "checkout_commit_sha": checkout_commit_sha,
            "entries": entries,
        }
        payload = {**core, "journal_checksum": canonical_checksum(core)}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        if len(encoded) > MAX_JOURNAL_BYTES:
            raise ValueError("ISOLATED_PATCH_ROLLBACK_JOURNAL_TOO_LARGE")
        target = self._journal_path(assignment_id)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".calyx-rollback-stage-", dir=self.workspace_root
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
            self._fsync_directory(self.workspace_root)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _load_journal(self, path: Path) -> dict[str, Any]:
        raw = path.read_bytes()
        if not raw or len(raw) > MAX_JOURNAL_BYTES:
            raise RuntimeError("ISOLATED_PATCH_ROLLBACK_JOURNAL_INVALID")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("ISOLATED_PATCH_ROLLBACK_JOURNAL_INVALID") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != ROLLBACK_JOURNAL_SCHEMA
        ):
            raise RuntimeError("ISOLATED_PATCH_ROLLBACK_JOURNAL_INVALID")
        checksum = str(payload.get("journal_checksum") or "")
        core = {
            key: value for key, value in payload.items() if key != "journal_checksum"
        }
        if checksum != canonical_checksum(core):
            raise RuntimeError("ISOLATED_PATCH_ROLLBACK_JOURNAL_CHECKSUM_MISMATCH")
        entries = payload.get("entries")
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_PATCH_FILES:
            raise RuntimeError("ISOLATED_PATCH_ROLLBACK_JOURNAL_INVALID")
        return payload

    def _restore_journal(self, journal: dict[str, Any]) -> None:
        entries = journal["entries"]
        prepared: list[PreparedPatch] = []
        for raw_entry in entries:
            if not isinstance(raw_entry, dict):
                raise TypeError("ISOLATED_PATCH_ROLLBACK_JOURNAL_INVALID")
            path = str(raw_entry.get("path") or "").strip()
            before_sha = str(raw_entry.get("before_sha256") or "").strip().lower()
            after_sha = str(raw_entry.get("after_sha256") or "").strip().lower()
            encoded_before = raw_entry.get("before_content_b64")
            target = self._validated_target(path)
            if not _is_sha256(after_sha):
                raise RuntimeError("ISOLATED_PATCH_ROLLBACK_JOURNAL_INVALID")
            if before_sha == ABSENT_PREIMAGE:
                if encoded_before is not None:
                    raise RuntimeError("ISOLATED_PATCH_ROLLBACK_JOURNAL_INVALID")
                before_bytes = None
            else:
                if not _is_sha256(before_sha) or not isinstance(encoded_before, str):
                    raise RuntimeError("ISOLATED_PATCH_ROLLBACK_JOURNAL_INVALID")
                try:
                    before_bytes = base64.b64decode(encoded_before, validate=True)
                except (ValueError, TypeError) as exc:
                    raise RuntimeError(
                        "ISOLATED_PATCH_ROLLBACK_JOURNAL_INVALID"
                    ) from exc
                if hashlib.sha256(before_bytes).hexdigest() != before_sha:
                    raise RuntimeError(
                        "ISOLATED_PATCH_ROLLBACK_PREIMAGE_CHECKSUM_MISMATCH"
                    )
            current = target.read_bytes() if target.exists() else None
            current_sha = (
                hashlib.sha256(current).hexdigest()
                if current is not None
                else ABSENT_PREIMAGE
            )
            if current_sha not in {before_sha, after_sha}:
                raise RuntimeError(f"ISOLATED_PATCH_ROLLBACK_STATE_DIVERGED:{path}")
            prepared.append(
                PreparedPatch(
                    spec=PatchSpec(
                        path=path, before_sha256=before_sha, content_utf8=""
                    ),
                    target=target,
                    before_sha256=before_sha,
                    after_sha256=after_sha,
                    before_bytes=before_bytes,
                    after_bytes=b"",
                )
            )
        self._rollback(prepared)

    @staticmethod
    def _delete_journal(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            return
        IsolatedWorkspacePatchExecutor._fsync_directory(path.parent)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

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
        if not isinstance(marker, dict) or any(
            marker.get(key) != value for key, value in expected.items()
        ):
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
        return PatchSpec(
            path=path,
            before_sha256=before_sha256,
            content_utf8=content,
        )

    def _prepare_patch(self, spec: PatchSpec) -> PreparedPatch:
        target = self._validated_target(spec.path)
        after_bytes = spec.content_utf8.encode("utf-8")
        if len(after_bytes) > MAX_FILE_BYTES:
            raise ValueError(f"ISOLATED_PATCH_FILE_TOO_LARGE:{spec.path}")

        try:
            before_bytes, _ = self._reader._read_workspace_file(
                spec.path, MAX_FILE_BYTES
            )
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
                raise ValueError(
                    f"ISOLATED_PATCH_EXISTING_FILE_NOT_UTF8:{spec.path}"
                ) from exc
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
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
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
                descriptor, temporary = tempfile.mkstemp(
                    prefix=".calyx-patch-", dir=item.target.parent
                )
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
                    self._fsync_directory(item.target.parent)
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
                descriptor, temporary = tempfile.mkstemp(
                    prefix=".calyx-rollback-", dir=item.target.parent
                )
                try:
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(item.before_bytes)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, item.target)
                    IsolatedWorkspacePatchExecutor._fsync_directory(item.target.parent)
                finally:
                    try:
                        os.unlink(temporary)
                    except FileNotFoundError:
                        pass


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )
