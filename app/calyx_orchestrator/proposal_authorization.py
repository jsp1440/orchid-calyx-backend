from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from .executor import canonical_checksum
from .sandbox_supervisor_evidence import canonical_sha256

SCHEMA = "calyx-proposal-authorization-v1"
MANIFEST_SCHEMA = "calyx-git-proposal-manifest-v1"
PATCH_EXECUTOR_KEY = "isolated_workspace_patcher_v1"
ALLOWED_REVIEW_CLASSES = frozenset({"operational", "security"})
MAX_RATIONALE = 2_000
MAX_EVIDENCE_URIS = 8


class ProposalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _nonempty(value: Any, *, code: str, maximum: int = 256) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise ValueError(code)
    return normalized


def _manifest_payload(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(snapshot)
    supplied_digest = str(payload.pop("manifest_digest", "") or "").strip().lower()
    if not _is_sha256(supplied_digest):
        raise ValueError("PROPOSAL_AUTH_MANIFEST_DIGEST_INVALID")
    if payload.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("PROPOSAL_AUTH_MANIFEST_SCHEMA_INVALID")
    if canonical_sha256(payload) != supplied_digest:
        raise PermissionError("PROPOSAL_AUTH_MANIFEST_DIGEST_MISMATCH")
    return {**payload, "manifest_digest": supplied_digest}


def _normalize_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("PROPOSAL_AUTH_DECIDED_AT_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class ProposalAuthorizationRecord:
    manifest_digest: str
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
            verified.get("repository"),
            verified.get("base_commit_sha"),
            verified.get("source_autonomy_branch"),
            verified.get("proposed_branch"),
            verified.get("patch_output_checksum"),
        )
        recorded = (
            self.repository,
            self.base_commit_sha,
            self.source_autonomy_branch,
            self.proposed_branch,
            self.patch_output_checksum,
        )
        if identity != recorded:
            raise PermissionError("PROPOSAL_AUTH_MANIFEST_IDENTITY_MISMATCH")


class ProposalAuthorizationBuilder:
    """Create review evidence for an exact 114M manifest without mutation authority."""

    def build(
        self,
        *,
        manifest_snapshot: Mapping[str, Any],
        patch_receipt: Mapping[str, Any],
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
        repository = _nonempty(
            manifest.get("repository"), code="PROPOSAL_AUTH_REPOSITORY_INVALID"
        )
        base_commit = str(manifest.get("base_commit_sha") or "").strip().lower()
        if len(base_commit) != 40 or any(
            character not in "0123456789abcdef" for character in base_commit
        ):
            raise ValueError("PROPOSAL_AUTH_BASE_COMMIT_INVALID")
        source_branch = _nonempty(
            manifest.get("source_autonomy_branch"),
            code="PROPOSAL_AUTH_SOURCE_BRANCH_INVALID",
        )
        proposed_branch = _nonempty(
            manifest.get("proposed_branch"),
            code="PROPOSAL_AUTH_PROPOSED_BRANCH_INVALID",
        )
        patch_checksum = str(manifest.get("patch_output_checksum") or "").strip().lower()
        if not _is_sha256(patch_checksum):
            raise ValueError("PROPOSAL_AUTH_PATCH_CHECKSUM_INVALID")

        producer_id = self._verify_patch_receipt(
            patch_receipt,
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

    @staticmethod
    def _verify_patch_receipt(
        patch_receipt: Mapping[str, Any],
        *,
        repository: str,
        source_branch: str,
        base_commit: str,
        patch_checksum: str,
    ) -> str:
        executor_key = str(patch_receipt.get("executor_key") or "").strip()
        if executor_key != PATCH_EXECUTOR_KEY:
            raise PermissionError("PROPOSAL_AUTH_PATCH_EXECUTOR_INVALID")
        if str(patch_receipt.get("state") or "").strip().lower() != "delivered":
            raise PermissionError("PROPOSAL_AUTH_PATCH_RECEIPT_NOT_DELIVERED")
        if str(patch_receipt.get("outcome") or "").strip().lower() != "delivered":
            raise PermissionError("PROPOSAL_AUTH_PATCH_RECEIPT_NOT_DELIVERED")
        output = patch_receipt.get("output")
        if not isinstance(output, Mapping):
            raise TypeError("PROPOSAL_AUTH_PATCH_OUTPUT_REQUIRED")
        output_checksum = str(patch_receipt.get("output_checksum") or "").strip().lower()
        if (
            not _is_sha256(output_checksum)
            or output_checksum != patch_checksum
            or output_checksum != canonical_checksum(dict(output))
        ):
            raise PermissionError("PROPOSAL_AUTH_PATCH_CHECKSUM_MISMATCH")
        identity = (
            str(output.get("repository") or "").strip(),
            str(output.get("branch") or "").strip(),
            str(output.get("checkout_commit_sha") or "").strip().lower(),
        )
        if identity != (repository, source_branch, base_commit):
            raise PermissionError("PROPOSAL_AUTH_PATCH_IDENTITY_MISMATCH")
        if output.get("mode") != "authoritative_isolated_workspace_patch":
            raise PermissionError("PROPOSAL_AUTH_PATCH_MODE_INVALID")
        return f"executor:{executor_key}"


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
                raise ValueError("PROPOSAL_AUTH_AUTHORITATIVE_DECISION_ALREADY_RECORDED")
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
