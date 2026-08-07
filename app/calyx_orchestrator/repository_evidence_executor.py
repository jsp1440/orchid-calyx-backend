from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .engineering_core import TerminalOutcome
from .executor import ExecutionReceipt, ExecutionState, GovernedAssignment, canonical_checksum

REPOSITORY_EVIDENCE_ROLE = "repository_evidence_reader"
DEFAULT_REPOSITORY = "jsp1440/orchid-calyx-backend"
MAX_FILE_BYTES = 2_000_000
MAX_TOTAL_BYTES = 5_000_000
MAX_GIT_METADATA_BYTES = 256_000


@dataclass(frozen=True, slots=True)
class EvidenceTarget:
    path: str
    required: bool = False


@dataclass(frozen=True, slots=True)
class CheckoutIdentity:
    branch: str | None
    commit_sha: str


DEFAULT_TARGETS = (
    EvidenceTarget("AGENTS.md", required=True),
    EvidenceTarget("requirements.txt", required=True),
    EvidenceTarget("pyproject.toml"),
    EvidenceTarget("README.md"),
    EvidenceTarget(".github/workflows/build-brain-114a.yml"),
    EvidenceTarget("docs/brain/BUILD-BRAIN-114A-AUTONOMOUS-WORKER-CYCLE.md"),
)


class RepositoryEvidenceExecutor:
    """Read-only metadata/hash evidence from a verified local Git checkout."""

    executor_key = "repository_evidence_reader_v1"

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        repository_name: str | None = None,
        targets: tuple[EvidenceTarget, ...] = DEFAULT_TARGETS,
    ) -> None:
        root = workspace_root or Path(os.environ.get("GITHUB_WORKSPACE") or Path.cwd())
        self.workspace_root = root.resolve()
        self.repository_name = (
            repository_name or os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPOSITORY
        ).strip()
        self.targets = tuple(sorted(targets, key=lambda item: item.path))
        if not self.repository_name:
            raise ValueError("REPOSITORY_EVIDENCE_REPOSITORY_REQUIRED")

    def execute(self, assignment: GovernedAssignment) -> ExecutionReceipt:
        if assignment.role_key != REPOSITORY_EVIDENCE_ROLE:
            raise PermissionError("REPOSITORY_EVIDENCE_ROLE_REQUIRED")
        job = assignment.inputs.get("job")
        if not isinstance(job, dict):
            raise TypeError("REPOSITORY_EVIDENCE_JOB_INPUT_REQUIRED")
        if bool(job.get("mutating_intent")):
            raise PermissionError("REPOSITORY_EVIDENCE_MUTATION_PROHIBITED")
        repository = str(job.get("repository") or "").strip()
        if repository != self.repository_name:
            raise PermissionError("REPOSITORY_EVIDENCE_REPOSITORY_MISMATCH")
        requested_branch = str(job.get("branch") or "").strip()
        if not requested_branch:
            raise ValueError("REPOSITORY_EVIDENCE_BRANCH_REQUIRED")
        if not self.workspace_root.is_dir():
            raise RuntimeError("REPOSITORY_EVIDENCE_WORKSPACE_NOT_FOUND")

        checkout = self._checkout_identity()
        if checkout.branch != requested_branch:
            raise PermissionError("REPOSITORY_EVIDENCE_REVISION_MISMATCH")

        files: list[dict[str, object]] = []
        missing_optional: list[str] = []
        total_bytes = 0
        for target in self.targets:
            try:
                data, size = self._read_workspace_file(target.path, MAX_FILE_BYTES)
            except FileNotFoundError:
                if target.required:
                    raise RuntimeError(
                        f"REPOSITORY_EVIDENCE_REQUIRED_FILE_MISSING:{target.path}"
                    ) from None
                missing_optional.append(target.path)
                continue
            total_bytes += size
            if total_bytes > MAX_TOTAL_BYTES:
                raise RuntimeError("REPOSITORY_EVIDENCE_TOTAL_BYTES_EXCEEDED")
            try:
                data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RuntimeError(f"REPOSITORY_EVIDENCE_NOT_UTF8:{target.path}") from exc
            files.append(
                {
                    "path": target.path,
                    "size_bytes": size,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "required": target.required,
                }
            )

        input_checksum = assignment.verified_input_checksum()
        output = {
            "status": "delivered",
            "executed": True,
            "mode": "authoritative_read_only_repository_evidence",
            "repository": self.repository_name,
            "requested_branch": requested_branch,
            "checkout_branch": checkout.branch,
            "checkout_commit_sha": checkout.commit_sha,
            "files": files,
            "missing_optional": missing_optional,
            "file_count": len(files),
            "total_bytes": total_bytes,
            "contents_included": False,
            "side_effects": [],
        }
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
            evidence_uris=tuple(
                [
                    *assignment.evidence_uris,
                    f"repo-commit:{self.repository_name}@{checkout.commit_sha}",
                    *[f"repo-file:{item['path']}#{item['sha256']}" for item in files],
                ]
            ),
        )
        receipt.verify()
        return receipt

    def _checkout_identity(self) -> CheckoutIdentity:
        try:
            head_bytes, _ = self._read_workspace_file(".git/HEAD", MAX_GIT_METADATA_BYTES)
        except FileNotFoundError as exc:
            raise RuntimeError("REPOSITORY_EVIDENCE_GIT_HEAD_MISSING") from exc
        try:
            head = head_bytes.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise RuntimeError("REPOSITORY_EVIDENCE_GIT_HEAD_INVALID") from exc
        if head.startswith("ref: "):
            ref_name = head[5:].strip()
            prefix = "refs/heads/"
            if not ref_name.startswith(prefix):
                raise RuntimeError("REPOSITORY_EVIDENCE_NON_BRANCH_CHECKOUT")
            branch = ref_name[len(prefix) :]
            commit_sha = self._resolve_git_ref(ref_name)
            return CheckoutIdentity(branch=branch, commit_sha=commit_sha)
        return CheckoutIdentity(branch=None, commit_sha=self._validate_commit_sha(head))

    def _resolve_git_ref(self, ref_name: str) -> str:
        try:
            ref_bytes, _ = self._read_workspace_file(f".git/{ref_name}", MAX_GIT_METADATA_BYTES)
        except FileNotFoundError:
            try:
                packed_bytes, _ = self._read_workspace_file(
                    ".git/packed-refs", MAX_GIT_METADATA_BYTES
                )
            except FileNotFoundError as exc:
                raise RuntimeError("REPOSITORY_EVIDENCE_GIT_REF_MISSING") from exc
            for raw_line in packed_bytes.decode("ascii", errors="strict").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or line.startswith("^"):
                    continue
                sha, separator, name = line.partition(" ")
                if separator and name == ref_name:
                    return self._validate_commit_sha(sha)
            raise RuntimeError("REPOSITORY_EVIDENCE_GIT_REF_MISSING")
        try:
            return self._validate_commit_sha(ref_bytes.decode("ascii").strip())
        except UnicodeDecodeError as exc:
            raise RuntimeError("REPOSITORY_EVIDENCE_GIT_REF_INVALID") from exc

    @staticmethod
    def _validate_commit_sha(value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 40 or any(character not in "0123456789abcdef" for character in normalized):
            raise RuntimeError("REPOSITORY_EVIDENCE_GIT_SHA_INVALID")
        return normalized

    def _read_workspace_file(self, relative_path: str, max_bytes: int) -> tuple[bytes, int]:
        path = PurePosixPath(relative_path)
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise PermissionError("REPOSITORY_EVIDENCE_PATH_ESCAPE")

        nofollow = getattr(os, "O_NOFOLLOW", 0)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
        file_flags = os.O_RDONLY | nofollow
        root_fd = os.open(self.workspace_root, directory_flags)
        current_fd = root_fd
        opened_directories: list[int] = []
        try:
            for component in path.parts[:-1]:
                try:
                    next_fd = os.open(component, directory_flags, dir_fd=current_fd)
                except OSError as exc:
                    if isinstance(exc, FileNotFoundError):
                        raise
                    raise PermissionError("REPOSITORY_EVIDENCE_PATH_ESCAPE") from exc
                opened_directories.append(next_fd)
                current_fd = next_fd
            try:
                file_fd = os.open(path.parts[-1], file_flags, dir_fd=current_fd)
            except OSError as exc:
                if isinstance(exc, FileNotFoundError):
                    raise
                raise PermissionError("REPOSITORY_EVIDENCE_SYMLINK_PROHIBITED") from exc
            try:
                descriptor_stat = os.fstat(file_fd)
                if not stat.S_ISREG(descriptor_stat.st_mode):
                    raise PermissionError("REPOSITORY_EVIDENCE_NON_REGULAR_FILE")
                if descriptor_stat.st_size > max_bytes:
                    raise RuntimeError(f"REPOSITORY_EVIDENCE_FILE_TOO_LARGE:{relative_path}")
                chunks: list[bytes] = []
                remaining = max_bytes + 1
                while remaining > 0:
                    chunk = os.read(file_fd, min(65_536, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                data = b"".join(chunks)
                if len(data) > max_bytes:
                    raise RuntimeError(f"REPOSITORY_EVIDENCE_FILE_TOO_LARGE:{relative_path}")
                return data, len(data)
            finally:
                os.close(file_fd)
        finally:
            for descriptor in reversed(opened_directories):
                os.close(descriptor)
            os.close(root_fd)
