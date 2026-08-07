from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from .engineering_core import TerminalOutcome
from .executor import ExecutionReceipt, ExecutionState, GovernedAssignment, canonical_checksum

REPOSITORY_EVIDENCE_ROLE = "repository_evidence_reader"
DEFAULT_REPOSITORY = "jsp1440/orchid-calyx-backend"
MAX_FILE_BYTES = 2_000_000
MAX_TOTAL_BYTES = 5_000_000


@dataclass(frozen=True, slots=True)
class EvidenceTarget:
    path: str
    required: bool = False


DEFAULT_TARGETS = (
    EvidenceTarget("AGENTS.md", required=True),
    EvidenceTarget("requirements.txt", required=True),
    EvidenceTarget("pyproject.toml"),
    EvidenceTarget("README.md"),
    EvidenceTarget(".github/workflows/build-brain-114a.yml"),
    EvidenceTarget("docs/brain/BUILD-BRAIN-114A-AUTONOMOUS-WORKER-CYCLE.md"),
)


class RepositoryEvidenceExecutor:
    """Read-only metadata/hash evidence from an explicitly configured local checkout."""

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
        if not self.workspace_root.is_dir():
            raise RuntimeError("REPOSITORY_EVIDENCE_WORKSPACE_NOT_FOUND")

        files: list[dict[str, object]] = []
        missing_optional: list[str] = []
        total_bytes = 0
        for target in self.targets:
            candidate = self.workspace_root / target.path
            resolved = candidate.resolve(strict=False)
            if not resolved.is_relative_to(self.workspace_root):
                raise PermissionError("REPOSITORY_EVIDENCE_PATH_ESCAPE")
            if not candidate.exists():
                if target.required:
                    raise RuntimeError(f"REPOSITORY_EVIDENCE_REQUIRED_FILE_MISSING:{target.path}")
                missing_optional.append(target.path)
                continue
            if candidate.is_symlink():
                raise PermissionError("REPOSITORY_EVIDENCE_SYMLINK_PROHIBITED")
            if not candidate.is_file():
                raise PermissionError("REPOSITORY_EVIDENCE_NON_REGULAR_FILE")
            size = candidate.stat().st_size
            if size > MAX_FILE_BYTES:
                raise RuntimeError(f"REPOSITORY_EVIDENCE_FILE_TOO_LARGE:{target.path}")
            total_bytes += size
            if total_bytes > MAX_TOTAL_BYTES:
                raise RuntimeError("REPOSITORY_EVIDENCE_TOTAL_BYTES_EXCEEDED")
            data = candidate.read_bytes()
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
                [*assignment.evidence_uris, *[f"repo-file:{item['path']}#{item['sha256']}" for item in files]]
            ),
        )
        receipt.verify()
        return receipt
