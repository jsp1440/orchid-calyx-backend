from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from .git_proposal_manifest import (
    MAX_CHANGES,
    MAX_SUMMARY,
    MAX_TITLE,
    GitProposalManifest,
    GitProposalManifestBuilder,
    ProposedChange,
    VerifiedValidation,
    _bounded_text,
    _is_git_sha,
    _is_sha256,
    _valid_git_branch,
)
from .persisted_patch_execution import PersistedPatchExecutionService
from .sandbox_supervisor_evidence import canonical_sha256

SCHEMA = "calyx-proposal-authorization-v2"
MANIFEST_SCHEMA = "calyx-git-proposal-manifest-v2"
ALLOWED_REVIEW_CLASSES = frozenset({"operational", "security"})
MAX_RATIONALE = 2_000
MAX_EVIDENCE_URIS = 8


class ProposalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


def _nonempty(value: Any, *, code: str, maximum: int = 256) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise ValueError(code)
    return normalized


def _validated_manifest_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Reconstruct and verify canonical 114M manifest invariants before review."""
    supplied = dict(snapshot)
    supplied_digest = str(supplied.get("manifest_digest") or "").strip().lower()
    if not _is_sha256(supplied_digest):
        raise ValueError("PROPOSAL_AUTH_MANIFEST_DIGEST_INVALID")
    payload = {key: value for key, value in supplied.items() if key != "manifest_digest"}
    if payload.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("PROPOSAL_AUTH_MANIFEST_SCHEMA_INVALID")
    if canonical_sha256(payload) != supplied_digest:
        raise PermissionError("PROPOSAL_AUTH_MANIFEST_DIGEST_MISMATCH")

    patch_program_job_id = _nonempty(
        payload.get("patch_program_job_id"),
        code="PROPOSAL_AUTH_PATCH_PROGRAM_JOB_ID_REQUIRED",
    )
    repository = _nonempty(
        payload.get("repository"), code="PROPOSAL_AUTH_REPOSITORY_INVALID"
    )
    if "/" not in repository:
        raise ValueError("PROPOSAL_AUTH_REPOSITORY_INVALID")
    base_commit = str(payload.get("base_commit_sha") or "").strip().lower()
    if not _is_git_sha(base_commit):
        raise ValueError("PROPOSAL_AUTH_BASE_COMMIT_INVALID")
    source_branch = _nonempty(
        payload.get("source_autonomy_branch"),
        code="PROPOSAL_AUTH_SOURCE_BRANCH_INVALID",
    )
    proposed_branch = _nonempty(
        payload.get("proposed_branch"), code="PROPOSAL_AUTH_PROPOSED_BRANCH_INVALID"
    )
    if not source_branch.startswith("autonomy/") or not _valid_git_branch(source_branch):
        raise PermissionError("PROPOSAL_AUTH_SOURCE_BRANCH_INVALID")
    if (
        not proposed_branch.startswith("autonomy/proposal/")
        or proposed_branch == source_branch
        or not _valid_git_branch(proposed_branch)
    ):
        raise PermissionError("PROPOSAL_AUTH_PROPOSED_BRANCH_INVALID")
    patch_checksum = str(payload.get("patch_output_checksum") or "").strip().lower()
    if not _is_sha256(patch_checksum):
        raise ValueError("PROPOSAL_AUTH_PATCH_CHECKSUM_INVALID")

    raw_changes = payload.get("changes")
    if not isinstance(raw_changes, list) or not 1 <= len(raw_changes) <= MAX_CHANGES:
        raise ValueError("PROPOSAL_AUTH_CHANGE_COUNT_INVALID")
    if any(not isinstance(item, Mapping) for item in raw_changes):
        raise TypeError("PROPOSAL_AUTH_CHANGE_INVALID")
    changes = tuple(ProposedChange.from_mapping(item) for item in raw_changes)
    if len({change.path for change in changes}) != len(changes):
        raise ValueError("PROPOSAL_AUTH_DUPLICATE_CHANGE")

    raw_validations = payload.get("validations")
    if not isinstance(raw_validations, list) or not raw_validations:
        raise PermissionError("PROPOSAL_AUTH_VALIDATION_REQUIRED")
    validations: list[VerifiedValidation] = []
    for raw_validation in raw_validations:
        if not isinstance(raw_validation, Mapping):
            raise TypeError("PROPOSAL_AUTH_VALIDATION_INVALID")
        preset = _nonempty(
            raw_validation.get("preset"),
            code="PROPOSAL_AUTH_VALIDATION_PRESET_INVALID",
        )
        request_digest = str(raw_validation.get("request_digest") or "").strip().lower()
        receipt_digest = str(raw_validation.get("receipt_digest") or "").strip().lower()
        policy_digest = str(raw_validation.get("policy_digest") or "").strip().lower()
        if not all(_is_sha256(value) for value in (request_digest, receipt_digest, policy_digest)):
            raise ValueError("PROPOSAL_AUTH_VALIDATION_DIGEST_INVALID")
        raw_targets = raw_validation.get("targets")
        if not isinstance(raw_targets, list) or not raw_targets:
            raise ValueError("PROPOSAL_AUTH_VALIDATION_TARGETS_INVALID")
        target_hashes: list[tuple[str, str]] = []
        for raw_target in raw_targets:
            if not isinstance(raw_target, Mapping):
                raise TypeError("PROPOSAL_AUTH_VALIDATION_TARGET_INVALID")
            path = _nonempty(
                raw_target.get("path"), code="PROPOSAL_AUTH_VALIDATION_TARGET_INVALID"
            )
            digest = str(raw_target.get("sha256") or "").strip().lower()
            if not _is_sha256(digest):
                raise ValueError("PROPOSAL_AUTH_VALIDATION_TARGET_INVALID")
            target_hashes.append((path, digest))
        if len({path for path, _ in target_hashes}) != len(target_hashes):
            raise ValueError("PROPOSAL_AUTH_VALIDATION_DUPLICATE_TARGET")
        validations.append(
            VerifiedValidation(
                preset=preset,
                request_digest=request_digest,
                receipt_digest=receipt_digest,
                policy_digest=policy_digest,
                target_hashes=tuple(sorted(target_hashes)),
            )
        )
    canonical_validations = tuple(
        sorted(validations, key=lambda item: (item.preset, item.request_digest))
    )
    GitProposalManifestBuilder._require_change_coverage(changes, canonical_validations)

    manifest = GitProposalManifest(
        patch_program_job_id=patch_program_job_id,
        repository=repository,
        base_commit_sha=base_commit,
        source_autonomy_branch=source_branch,
        proposed_branch=proposed_branch,
        patch_output_checksum=patch_checksum,
        changes=changes,
        validations=canonical_validations,
        commit_title=_bounded_text(
            payload.get("commit_title"), field="COMMIT_TITLE", maximum=MAX_TITLE
        ),
        pr_title=_bounded_text(
            payload.get("pr_title"), field="PR_TITLE", maximum=MAX_TITLE
        ),
        summary=_bounded_text(
            payload.get("summary"), field="SUMMARY", maximum=MAX_SUMMARY
        ),
    )
    canonical = manifest.snapshot()
    if supplied != canonical:
        raise PermissionError("PROPOSAL_AUTH_NONCANONICAL_MANIFEST")
    return canonical


def _manifest_payload(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return _validated_manifest_snapshot(snapshot)


def _normalize_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("PROPOSAL_AUTH_DECIDED_AT_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class ProposalAuthorizationRecord:
    manifest_digest: str
    patch_program_job_id: str
    repository: str
    base_commit_sha: str
    source_autonomy_branch: str
    proposed_branch: str
    patch_output_checksum: str
    producer_id: str
    requested_by: str
    review_class: str
    reviewer_id: str
    reviewer_roles: tuple[str, ...]
    decision: ProposalDecision
    rationale: str
    evidence_uris: tuple[str, ...]
    decided_at: str

    def payload(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "manifest_digest": self.manifest_digest,
            "patch_program_job_id": self.patch_program_job_id,
            "repository": self.repository,
            "base_commit_sha": self.base_commit_sha,
            "source_autonomy_branch": self.source_autonomy_branch,
            "proposed_branch": self.proposed_branch,
            "patch_output_checksum": self.patch_output_checksum,
            "producer_id": self.producer_id,
            "requested_by": self.requested_by,
            "review_class": self.review_class,
            "reviewer_id": self.reviewer_id,
            "reviewer_roles": list(self.reviewer_roles),
            "decision": self.decision.value,
            "rationale": self.rationale,
            "evidence_uris": list(self.evidence_uris),
            "decided_at": self.decided_at,
            "git_mutation_authorized": False,
            "commit_authorized": False,
            "push_authorized": False,
            "pull_request_creation_authorized": False,
            "automatic_merge_authorized": False,
            "deployment_authorized": False,
            "publication_authorized": False,
            "taxonomy_activation_authorized": False,
            "production_database_mutation_authorized": False,
            "production_graph_mutation_authorized": False,
        }

    @property
    def authorization_digest(self) -> str:
        return canonical_sha256(self.payload())

    def snapshot(self) -> dict[str, Any]:
        return {**self.payload(), "authorization_digest": self.authorization_digest}

    def verify_for_manifest(self, manifest_snapshot: Mapping[str, Any]) -> None:
        verified = _manifest_payload(manifest_snapshot)
        if verified["manifest_digest"] != self.manifest_digest:
            raise PermissionError("PROPOSAL_AUTH_STALE_MANIFEST")
        identity = (
            verified.get("patch_program_job_id"),
            verified.get("repository"),
            verified.get("base_commit_sha"),
            verified.get("source_autonomy_branch"),
            verified.get("proposed_branch"),
            verified.get("patch_output_checksum"),
        )
        recorded = (
            self.patch_program_job_id,
            self.repository,
            self.base_commit_sha,
            self.source_autonomy_branch,
            self.proposed_branch,
            self.patch_output_checksum,
        )
        if identity != recorded:
            raise PermissionError("PROPOSAL_AUTH_MANIFEST_IDENTITY_MISMATCH")


class ProposalAuthorizationBuilder:
    """Create review evidence for an exact persisted-patch proposal without mutation authority."""

    def __init__(self, patch_execution_service: PersistedPatchExecutionService) -> None:
        self._patch_execution_service = patch_execution_service

    def build(
        self,
        *,
        manifest_snapshot: Mapping[str, Any],
        requested_by: str,
        review_class: str,
        reviewer_id: str,
        reviewer_roles: Sequence[str],
        decision: ProposalDecision | str,
        rationale: str,
        evidence_uris: Sequence[str],
        decided_at: datetime,
    ) -> ProposalAuthorizationRecord:
        manifest = _manifest_payload(manifest_snapshot)
        patch_program_job_id = manifest["patch_program_job_id"]
        repository = manifest["repository"]
        base_commit = manifest["base_commit_sha"]
        source_branch = manifest["source_autonomy_branch"]
        proposed_branch = manifest["proposed_branch"]
        patch_checksum = manifest["patch_output_checksum"]

        producer_id = self._verify_persisted_patch(
            program_job_id=patch_program_job_id,
            repository=repository,
            source_branch=source_branch,
            base_commit=base_commit,
            patch_checksum=patch_checksum,
        )
        requester = _nonempty(requested_by, code="PROPOSAL_AUTH_REQUESTER_REQUIRED")
        reviewer = _nonempty(reviewer_id, code="PROPOSAL_AUTH_REVIEWER_REQUIRED")
        normalized_class = str(review_class or "").strip().lower()
        if normalized_class not in ALLOWED_REVIEW_CLASSES:
            raise PermissionError("PROPOSAL_AUTH_REVIEW_CLASS_NOT_ALLOWED")
        roles = tuple(
            sorted(
                {
                    _nonempty(role, code="PROPOSAL_AUTH_REVIEWER_ROLE_INVALID")
                    for role in reviewer_roles
                }
            )
        )
        if normalized_class not in roles:
            raise PermissionError("PROPOSAL_AUTH_REVIEWER_ROLE_REQUIRED")
        if reviewer in {requester, producer_id}:
            raise PermissionError("PROPOSAL_AUTH_SELF_APPROVAL_PROHIBITED")

        try:
            normalized_decision = ProposalDecision(str(decision).strip().lower())
        except ValueError as exc:
            raise ValueError("PROPOSAL_AUTH_DECISION_INVALID") from exc
        normalized_rationale = _nonempty(
            rationale,
            code="PROPOSAL_AUTH_RATIONALE_REQUIRED",
            maximum=MAX_RATIONALE,
        )
        evidence = tuple(
            sorted(
                {
                    _nonempty(
                        uri,
                        code="PROPOSAL_AUTH_EVIDENCE_URI_INVALID",
                        maximum=1_024,
                    )
                    for uri in evidence_uris
                }
            )
        )
        if (
            not evidence
            or len(evidence) > MAX_EVIDENCE_URIS
            or any(":" not in uri for uri in evidence)
        ):
            raise ValueError("PROPOSAL_AUTH_EVIDENCE_INVALID")

        record = ProposalAuthorizationRecord(
            manifest_digest=manifest["manifest_digest"],
            patch_program_job_id=patch_program_job_id,
            repository=repository,
            base_commit_sha=base_commit,
            source_autonomy_branch=source_branch,
            proposed_branch=proposed_branch,
            patch_output_checksum=patch_checksum,
            producer_id=producer_id,
            requested_by=requester,
            review_class=normalized_class,
            reviewer_id=reviewer,
            reviewer_roles=roles,
            decision=normalized_decision,
            rationale=normalized_rationale,
            evidence_uris=evidence,
            decided_at=_normalize_timestamp(decided_at),
        )
        record.verify_for_manifest(manifest_snapshot)
        return record

    def _verify_persisted_patch(
        self,
        *,
        program_job_id: str,
        repository: str,
        source_branch: str,
        base_commit: str,
        patch_checksum: str,
    ) -> str:
        try:
            persisted = self._patch_execution_service.get_completed(
                program_job_id=program_job_id
            )
        except (LookupError, PermissionError, TypeError, ValueError) as exc:
            raise PermissionError("PROPOSAL_AUTH_PERSISTED_PATCH_REQUIRED") from exc
        output = persisted.output
        identity = (
            persisted.repository,
            persisted.branch,
            str(output.get("checkout_commit_sha") or "").strip().lower(),
            persisted.output_checksum,
        )
        if identity != (repository, source_branch, base_commit, patch_checksum):
            raise PermissionError("PROPOSAL_AUTH_PERSISTED_PATCH_MISMATCH")
        return f"executor:{persisted.executor_key}"


@dataclass(slots=True)
class ProposalAuthorizationRegistry:
    records: dict[tuple[str, str], ProposalAuthorizationRecord] = field(
        default_factory=dict
    )

    def record(self, item: ProposalAuthorizationRecord) -> ProposalAuthorizationRecord:
        key = (item.manifest_digest, item.review_class)
        existing = self.records.get(key)
        if existing is not None:
            if existing != item:
                raise ValueError(
                    "PROPOSAL_AUTH_AUTHORITATIVE_DECISION_ALREADY_RECORDED"
                )
            return existing
        self.records[key] = item
        return item

    def require(
        self, *, manifest_digest: str, review_class: str
    ) -> ProposalAuthorizationRecord:
        try:
            return self.records[(manifest_digest, review_class)]
        except KeyError as exc:
            raise LookupError("PROPOSAL_AUTH_RECORD_NOT_FOUND") from exc
