from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .persisted_patch_execution import PersistedPatchExecutionService
from .sandbox_supervisor_evidence import (
    SupervisorValidationReceipt,
    ValidationRequestEnvelope,
    canonical_sha256,
)
from .sandbox_supervisor_service import SandboxSupervisorService

SCHEMA = "calyx-git-proposal-manifest-v2"
MAX_CHANGES = 8
MAX_TITLE = 120
MAX_SUMMARY = 4_000
ALLOWED_CHANGE_PREFIXES = ("app/", "tests/", "docs/brain/")
FORBIDDEN_REF_CHARS = frozenset(" ~^:?*[\\")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _is_git_sha(value: str) -> bool:
    return len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


def _valid_git_branch(value: str) -> bool:
    """Apply Git ref-name rules without invoking Git or a shell."""
    if (
        not value
        or value == "@"
        or value.startswith("/")
        or value.endswith(("/", "."))
        or "//" in value
        or ".." in value
        or "@{" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or any(character in FORBIDDEN_REF_CHARS for character in value)
    ):
        return False
    for component in value.split("/"):
        if (
            not component
            or component.startswith(".")
            or component.endswith((".", ".lock"))
        ):
            return False
    return True


def _bounded_text(value: Any, *, field: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum or "\x00" in text:
        raise ValueError(f"GIT_PROPOSAL_{field}_INVALID")
    return text


@dataclass(frozen=True, slots=True)
class ProposedChange:
    path: str
    before_sha256: str
    after_sha256: str
    created: bool
    size_bytes: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ProposedChange:
        path = str(value.get("path") or "").strip()
        before = str(value.get("before_sha256") or "").strip().lower()
        after = str(value.get("after_sha256") or "").strip().lower()
        created = bool(value.get("created"))
        try:
            size_bytes = int(value.get("size_bytes"))
        except (TypeError, ValueError) as exc:
            raise ValueError("GIT_PROPOSAL_CHANGE_SIZE_INVALID") from exc
        if (
            not path
            or path.startswith("/")
            or ".." in path.split("/")
            or not path.startswith(ALLOWED_CHANGE_PREFIXES)
        ):
            raise PermissionError("GIT_PROPOSAL_CHANGE_PATH_NOT_ALLOWED")
        if created:
            if before != "absent":
                raise ValueError("GIT_PROPOSAL_CREATED_PREIMAGE_INVALID")
        elif not _is_sha256(before):
            raise ValueError("GIT_PROPOSAL_PREIMAGE_HASH_INVALID")
        if not _is_sha256(after):
            raise ValueError("GIT_PROPOSAL_POSTIMAGE_HASH_INVALID")
        if not 0 <= size_bytes <= 500_000:
            raise ValueError("GIT_PROPOSAL_CHANGE_SIZE_INVALID")
        return cls(
            path=path,
            before_sha256=before,
            after_sha256=after,
            created=created,
            size_bytes=size_bytes,
        )

    def payload(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
            "created": self.created,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class VerifiedValidation:
    preset: str
    request_digest: str
    receipt_digest: str
    policy_digest: str
    target_hashes: tuple[tuple[str, str], ...]

    def payload(self) -> dict[str, Any]:
        return {
            "preset": self.preset,
            "request_digest": self.request_digest,
            "receipt_digest": self.receipt_digest,
            "policy_digest": self.policy_digest,
            "targets": [
                {"path": path, "sha256": digest} for path, digest in self.target_hashes
            ],
        }


@dataclass(frozen=True, slots=True)
class GitProposalManifest:
    patch_program_job_id: str
    repository: str
    base_commit_sha: str
    source_autonomy_branch: str
    proposed_branch: str
    patch_output_checksum: str
    changes: tuple[ProposedChange, ...]
    validations: tuple[VerifiedValidation, ...]
    commit_title: str
    pr_title: str
    summary: str

    def payload(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "patch_program_job_id": self.patch_program_job_id,
            "repository": self.repository,
            "base_commit_sha": self.base_commit_sha,
            "source_autonomy_branch": self.source_autonomy_branch,
            "proposed_branch": self.proposed_branch,
            "patch_output_checksum": self.patch_output_checksum,
            "changes": [change.payload() for change in self.changes],
            "validations": [validation.payload() for validation in self.validations],
            "commit_title": self.commit_title,
            "pr_title": self.pr_title,
            "summary": self.summary,
            "git_mutation_performed": False,
            "commit_created": False,
            "push_performed": False,
            "pull_request_created": False,
            "automatic_merge_authorized": False,
            "deployment_authorized": False,
            "publication_authorized": False,
            "production_database_mutation_authorized": False,
            "production_graph_mutation_authorized": False,
        }

    @property
    def manifest_digest(self) -> str:
        return canonical_sha256(self.payload())

    def snapshot(self) -> dict[str, Any]:
        return {**self.payload(), "manifest_digest": self.manifest_digest}


class GitProposalManifestBuilder:
    """Build a proposal only from persisted patch and supervisor evidence."""

    def __init__(
        self,
        supervisor_service: SandboxSupervisorService,
        patch_execution_service: PersistedPatchExecutionService,
        *,
        allowed_policy_digests: Sequence[str],
    ) -> None:
        normalized = frozenset(
            str(value or "").strip().lower() for value in allowed_policy_digests
        )
        if not normalized or any(not _is_sha256(value) for value in normalized):
            raise ValueError("GIT_PROPOSAL_ALLOWED_POLICY_DIGESTS_INVALID")
        self._supervisor_service = supervisor_service
        self._patch_execution_service = patch_execution_service
        self._allowed_policy_digests = normalized

    def build(
        self,
        *,
        patch_program_job_id: str,
        validations: Sequence[Mapping[str, Any]],
        proposed_branch: str,
        commit_title: str,
        pr_title: str,
        summary: str,
    ) -> GitProposalManifest:
        try:
            patch_execution = self._patch_execution_service.get_completed(
                program_job_id=patch_program_job_id
            )
        except (LookupError, PermissionError, TypeError, ValueError) as exc:
            raise PermissionError("GIT_PROPOSAL_PERSISTED_PATCH_REQUIRED") from exc

        output = patch_execution.output
        repository = patch_execution.repository
        source_branch = patch_execution.branch
        base_commit = str(output.get("checkout_commit_sha") or "").strip().lower()
        if not repository or "/" not in repository:
            raise ValueError("GIT_PROPOSAL_REPOSITORY_INVALID")
        if not source_branch.startswith("autonomy/"):
            raise PermissionError("GIT_PROPOSAL_SOURCE_AUTONOMY_BRANCH_REQUIRED")
        if not _is_git_sha(base_commit):
            raise ValueError("GIT_PROPOSAL_BASE_COMMIT_INVALID")

        proposal_branch = proposed_branch.strip()
        if (
            not proposal_branch.startswith("autonomy/proposal/")
            or proposal_branch == source_branch
            or not _valid_git_branch(proposal_branch)
        ):
            raise PermissionError("GIT_PROPOSAL_BRANCH_INVALID")

        raw_changes = output.get("changes")
        if (
            not isinstance(raw_changes, list)
            or not 1 <= len(raw_changes) <= MAX_CHANGES
        ):
            raise ValueError("GIT_PROPOSAL_CHANGE_COUNT_INVALID")
        changes = tuple(ProposedChange.from_mapping(item) for item in raw_changes)
        if len({change.path for change in changes}) != len(changes):
            raise ValueError("GIT_PROPOSAL_DUPLICATE_CHANGE")

        verified = tuple(
            self._verify_validation(
                entry,
                repository=repository,
                branch=source_branch,
                commit_sha=base_commit,
            )
            for entry in validations
        )
        if not verified:
            raise PermissionError("GIT_PROPOSAL_VALIDATION_REQUIRED")
        self._require_change_coverage(changes, verified)

        return GitProposalManifest(
            patch_program_job_id=patch_execution.program_job_id,
            repository=repository,
            base_commit_sha=base_commit,
            source_autonomy_branch=source_branch,
            proposed_branch=proposal_branch,
            patch_output_checksum=patch_execution.output_checksum,
            changes=changes,
            validations=tuple(
                sorted(verified, key=lambda item: (item.preset, item.request_digest))
            ),
            commit_title=_bounded_text(
                commit_title, field="COMMIT_TITLE", maximum=MAX_TITLE
            ),
            pr_title=_bounded_text(pr_title, field="PR_TITLE", maximum=MAX_TITLE),
            summary=_bounded_text(summary, field="SUMMARY", maximum=MAX_SUMMARY),
        )

    def _verify_validation(
        self,
        entry: Mapping[str, Any],
        *,
        repository: str,
        branch: str,
        commit_sha: str,
    ) -> VerifiedValidation:
        raw_request = entry.get("request")
        raw_receipt = entry.get("receipt")
        if not isinstance(raw_request, Mapping) or not isinstance(raw_receipt, Mapping):
            raise TypeError("GIT_PROPOSAL_VALIDATION_EVIDENCE_INVALID")
        raw_targets = raw_request.get("targets")
        if not isinstance(raw_targets, list):
            raise TypeError("GIT_PROPOSAL_VALIDATION_TARGETS_INVALID")
        request = ValidationRequestEnvelope.build(
            repository=str(raw_request.get("repository") or ""),
            branch=str(raw_request.get("branch") or ""),
            checkout_commit_sha=str(raw_request.get("checkout_commit_sha") or ""),
            preset=str(raw_request.get("preset") or ""),
            targets=[dict(item) for item in raw_targets if isinstance(item, Mapping)],
            timeout_seconds=int(raw_request.get("timeout_seconds") or 0),
        )
        if len(request.targets) != len(raw_targets):
            raise TypeError("GIT_PROPOSAL_VALIDATION_TARGETS_INVALID")
        if (
            request.repository != repository
            or request.branch != branch
            or request.checkout_commit_sha != commit_sha
        ):
            raise PermissionError("GIT_PROPOSAL_VALIDATION_IDENTITY_MISMATCH")

        receipt = SupervisorValidationReceipt.from_mapping(raw_receipt)
        receipt.verify_for(request)
        if receipt.outcome != "delivered" or receipt.return_code != 0:
            raise PermissionError("GIT_PROPOSAL_SUCCESSFUL_VALIDATION_REQUIRED")
        if receipt.policy_digest not in self._allowed_policy_digests:
            raise PermissionError("GIT_PROPOSAL_VALIDATION_POLICY_NOT_ALLOWED")

        try:
            persisted = self._supervisor_service.get_completed_by_digest(
                request_digest=request.request_digest
            )
        except (LookupError, PermissionError, ValueError) as exc:
            raise PermissionError("GIT_PROPOSAL_PERSISTED_VALIDATION_REQUIRED") from exc

        expected_targets = [
            target.as_dict()
            for target in sorted(request.targets, key=lambda item: item.path)
        ]
        persisted_targets = json.loads(persisted.targets_json)
        if (
            persisted.request_digest != request.request_digest
            or persisted.repository != request.repository
            or persisted.branch != request.branch
            or persisted.checkout_commit_sha != request.checkout_commit_sha
            or persisted.preset != request.preset
            or int(persisted.timeout_seconds) != request.timeout_seconds
            or sorted(persisted_targets, key=lambda item: item["path"])
            != expected_targets
            or persisted.status != "completed"
            or persisted.outcome != "delivered"
            or persisted.receipt_digest != receipt.receipt_digest
            or persisted.policy_digest != receipt.policy_digest
            or persisted.authorization_id != receipt.authorization_id
            or persisted.evidence_uri != receipt.evidence_uri
        ):
            raise PermissionError("GIT_PROPOSAL_PERSISTED_VALIDATION_MISMATCH")

        return VerifiedValidation(
            preset=request.preset,
            request_digest=request.request_digest,
            receipt_digest=receipt.receipt_digest,
            policy_digest=receipt.policy_digest,
            target_hashes=tuple(
                sorted((target.path, target.sha256) for target in request.targets)
            ),
        )

    @staticmethod
    def _require_change_coverage(
        changes: Sequence[ProposedChange],
        validations: Sequence[VerifiedValidation],
    ) -> None:
        ruff_targets = {
            (path, digest)
            for validation in validations
            if validation.preset == "ruff"
            for path, digest in validation.target_hashes
        }
        pytest_targets = {
            (path, digest)
            for validation in validations
            if validation.preset == "pytest"
            for path, digest in validation.target_hashes
        }
        python_changes = {
            (change.path, change.after_sha256)
            for change in changes
            if change.path.endswith(".py")
        }
        if python_changes - ruff_targets:
            raise PermissionError("GIT_PROPOSAL_RUFF_COVERAGE_INCOMPLETE")
        changed_tests = {
            (change.path, change.after_sha256)
            for change in changes
            if change.path.startswith("tests/") and change.path.endswith(".py")
        }
        if changed_tests - pytest_targets:
            raise PermissionError("GIT_PROPOSAL_PYTEST_COVERAGE_INCOMPLETE")
