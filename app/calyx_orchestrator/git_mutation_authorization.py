from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .proposal_authorization import ProposalAuthorizationRecord, ProposalDecision
from .sandbox_supervisor_evidence import canonical_sha256

REQUEST_SCHEMA = "calyx-git-mutation-authorization-request-v1"
GRANT_SCHEMA = "calyx-git-mutation-authorization-grant-v1"
MANIFEST_SCHEMA = "calyx-git-proposal-manifest-v1"
REQUIRED_REVIEW_CLASSES = ("operational", "security")
ALLOWED_ACTIONS = (
    "create_branch",
    "create_commit",
    "push_branch",
    "open_pull_request",
)
MAX_TTL_SECONDS = 1800


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _is_git_sha(value: str) -> bool:
    return len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("GIT_AUTHORIZATION_TIME_INVALID") from exc
    if parsed.tzinfo is None:
        raise ValueError("GIT_AUTHORIZATION_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def _manifest_digest(snapshot: Mapping[str, Any]) -> str:
    payload = dict(snapshot)
    supplied = str(payload.pop("manifest_digest", "")).strip().lower()
    if not _is_sha256(supplied):
        raise ValueError("GIT_AUTHORIZATION_MANIFEST_DIGEST_INVALID")
    if payload.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("GIT_AUTHORIZATION_MANIFEST_SCHEMA_INVALID")
    if canonical_sha256(payload) != supplied:
        raise PermissionError("GIT_AUTHORIZATION_MANIFEST_DIGEST_MISMATCH")
    return supplied


def _verify_manifest_non_authority(snapshot: Mapping[str, Any]) -> None:
    required_false = (
        "git_mutation_performed",
        "commit_created",
        "push_performed",
        "pull_request_created",
        "automatic_merge_authorized",
        "deployment_authorized",
        "publication_authorized",
        "production_database_mutation_authorized",
        "production_graph_mutation_authorized",
    )
    if any(snapshot.get(field) is not False for field in required_false):
        raise PermissionError("GIT_AUTHORIZATION_MANIFEST_AUTHORITY_CONTAMINATED")


def _verify_reviews(
    manifest_snapshot: Mapping[str, Any],
    reviews: Sequence[ProposalAuthorizationRecord],
) -> tuple[str, ...]:
    by_class: dict[str, ProposalAuthorizationRecord] = {}
    for review in reviews:
        review.verify_for_manifest(manifest_snapshot)
        if review.decision is not ProposalDecision.APPROVED:
            raise PermissionError("GIT_AUTHORIZATION_REVIEW_NOT_APPROVED")
        if review.review_class in by_class:
            raise ValueError("GIT_AUTHORIZATION_DUPLICATE_REVIEW_CLASS")
        by_class[review.review_class] = review
    if tuple(sorted(by_class)) != tuple(sorted(REQUIRED_REVIEW_CLASSES)):
        raise PermissionError("GIT_AUTHORIZATION_REQUIRED_REVIEWS_MISSING")
    reviewer_ids = {review.reviewer_id for review in by_class.values()}
    if len(reviewer_ids) != len(REQUIRED_REVIEW_CLASSES):
        raise PermissionError("GIT_AUTHORIZATION_REVIEWER_SEPARATION_REQUIRED")
    return tuple(
        by_class[review_class].authorization_digest
        for review_class in REQUIRED_REVIEW_CLASSES
    )


@dataclass(frozen=True, slots=True)
class GitMutationAuthorizationRequest:
    manifest_digest: str
    repository: str
    base_commit_sha: str
    proposed_branch: str
    change_hashes: tuple[tuple[str, str], ...]
    validation_receipt_digests: tuple[str, ...]
    review_authorization_digests: tuple[str, ...]
    actions: tuple[str, ...]
    expires_at: str

    def payload(self) -> dict[str, Any]:
        return {
            "schema": REQUEST_SCHEMA,
            "manifest_digest": self.manifest_digest,
            "repository": self.repository,
            "base_commit_sha": self.base_commit_sha,
            "proposed_branch": self.proposed_branch,
            "change_hashes": [
                {"path": path, "after_sha256": digest}
                for path, digest in self.change_hashes
            ],
            "validation_receipt_digests": list(self.validation_receipt_digests),
            "review_authorization_digests": list(self.review_authorization_digests),
            "actions": list(self.actions),
            "expires_at": self.expires_at,
            "merge_authorized": False,
            "deployment_authorized": False,
            "publication_authorized": False,
            "taxonomy_activation_authorized": False,
            "production_database_mutation_authorized": False,
            "production_graph_mutation_authorized": False,
        }

    @property
    def request_digest(self) -> str:
        return canonical_sha256(self.payload())

    def snapshot(self) -> dict[str, Any]:
        return {**self.payload(), "request_digest": self.request_digest}


@dataclass(frozen=True, slots=True)
class GitMutationAuthorizationGrant:
    request_digest: str
    decision: str
    approved_by: str
    issued_at: str
    expires_at: str
    signature: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> GitMutationAuthorizationGrant:
        grant = cls(
            request_digest=str(value.get("request_digest") or "").strip().lower(),
            decision=str(value.get("decision") or "").strip().lower(),
            approved_by=str(value.get("approved_by") or "").strip(),
            issued_at=str(value.get("issued_at") or "").strip(),
            expires_at=str(value.get("expires_at") or "").strip(),
            signature=str(value.get("signature") or "").strip().lower(),
        )
        if not _is_sha256(grant.request_digest) or not _is_sha256(grant.signature):
            raise ValueError("GIT_AUTHORIZATION_GRANT_DIGEST_INVALID")
        if grant.decision not in {"approved", "denied"}:
            raise ValueError("GIT_AUTHORIZATION_GRANT_DECISION_INVALID")
        if not grant.approved_by:
            raise ValueError("GIT_AUTHORIZATION_APPROVER_REQUIRED")
        return grant

    def signing_payload(self) -> dict[str, Any]:
        return {
            "schema": GRANT_SCHEMA,
            "request_digest": self.request_digest,
            "decision": self.decision,
            "approved_by": self.approved_by,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }


class GitMutationAuthorizationGate:
    """Require two-role proposal review plus exact owner authorization; never mutate Git."""

    def __init__(self, *, owner_principal: str, hmac_secret: bytes) -> None:
        principal = owner_principal.strip()
        if not principal:
            raise ValueError("GIT_AUTHORIZATION_OWNER_PRINCIPAL_REQUIRED")
        if len(hmac_secret) < 32:
            raise ValueError("GIT_AUTHORIZATION_SECRET_TOO_SHORT")
        self._owner_principal = principal
        self._secret = bytes(hmac_secret)

    @staticmethod
    def build_request(
        manifest_snapshot: Mapping[str, Any],
        *,
        review_authorizations: Sequence[ProposalAuthorizationRecord],
        actions: Sequence[str],
        expires_at: str,
        now: datetime | None = None,
    ) -> GitMutationAuthorizationRequest:
        _verify_manifest_non_authority(manifest_snapshot)
        digest = _manifest_digest(manifest_snapshot)
        review_digests = _verify_reviews(manifest_snapshot, review_authorizations)

        normalized_actions = tuple(
            dict.fromkeys(str(action).strip() for action in actions)
        )
        if not normalized_actions or any(
            action not in ALLOWED_ACTIONS for action in normalized_actions
        ):
            raise PermissionError("GIT_AUTHORIZATION_ACTION_NOT_ALLOWED")

        repository = str(manifest_snapshot.get("repository") or "").strip()
        base_commit = (
            str(manifest_snapshot.get("base_commit_sha") or "").strip().lower()
        )
        proposed_branch = str(manifest_snapshot.get("proposed_branch") or "").strip()
        if not repository or "/" not in repository:
            raise ValueError("GIT_AUTHORIZATION_REPOSITORY_INVALID")
        if not _is_git_sha(base_commit):
            raise ValueError("GIT_AUTHORIZATION_BASE_COMMIT_INVALID")
        if not proposed_branch.startswith("autonomy/proposal/"):
            raise PermissionError("GIT_AUTHORIZATION_PROPOSAL_BRANCH_INVALID")

        raw_changes = manifest_snapshot.get("changes")
        raw_validations = manifest_snapshot.get("validations")
        if not isinstance(raw_changes, list) or not raw_changes:
            raise ValueError("GIT_AUTHORIZATION_CHANGES_REQUIRED")
        if not isinstance(raw_validations, list) or not raw_validations:
            raise ValueError("GIT_AUTHORIZATION_VALIDATIONS_REQUIRED")

        changes: list[tuple[str, str]] = []
        for item in raw_changes:
            if not isinstance(item, Mapping):
                raise TypeError("GIT_AUTHORIZATION_CHANGE_INVALID")
            path = str(item.get("path") or "").strip()
            after = str(item.get("after_sha256") or "").strip().lower()
            if not path or not _is_sha256(after):
                raise ValueError("GIT_AUTHORIZATION_CHANGE_INVALID")
            changes.append((path, after))

        receipts: list[str] = []
        for item in raw_validations:
            if not isinstance(item, Mapping):
                raise TypeError("GIT_AUTHORIZATION_VALIDATION_INVALID")
            receipt = str(item.get("receipt_digest") or "").strip().lower()
            if not _is_sha256(receipt):
                raise ValueError("GIT_AUTHORIZATION_VALIDATION_RECEIPT_INVALID")
            receipts.append(receipt)

        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        expiry = _parse_utc(expires_at)
        ttl = (expiry - current).total_seconds()
        if ttl <= 0 or ttl > MAX_TTL_SECONDS:
            raise PermissionError("GIT_AUTHORIZATION_EXPIRY_INVALID")

        return GitMutationAuthorizationRequest(
            manifest_digest=digest,
            repository=repository,
            base_commit_sha=base_commit,
            proposed_branch=proposed_branch,
            change_hashes=tuple(sorted(changes)),
            validation_receipt_digests=tuple(sorted(receipts)),
            review_authorization_digests=review_digests,
            actions=normalized_actions,
            expires_at=expiry.isoformat(),
        )

    def verify_grant(
        self,
        request: GitMutationAuthorizationRequest,
        grant_mapping: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> GitMutationAuthorizationGrant:
        grant = GitMutationAuthorizationGrant.from_mapping(grant_mapping)
        if grant.request_digest != request.request_digest:
            raise PermissionError("GIT_AUTHORIZATION_REQUEST_MISMATCH")
        if grant.approved_by != self._owner_principal:
            raise PermissionError("GIT_AUTHORIZATION_APPROVER_MISMATCH")
        issued = _parse_utc(grant.issued_at)
        expiry = _parse_utc(grant.expires_at)
        request_expiry = _parse_utc(request.expires_at)
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if expiry != request_expiry or issued > current or current >= expiry:
            raise PermissionError("GIT_AUTHORIZATION_GRANT_EXPIRED_OR_INVALID")
        expected = hmac.new(
            self._secret,
            canonical_sha256(grant.signing_payload()).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, grant.signature):
            raise PermissionError("GIT_AUTHORIZATION_SIGNATURE_INVALID")
        if grant.decision != "approved":
            raise PermissionError("GIT_AUTHORIZATION_NOT_APPROVED")
        return grant

    def sign_for_test_or_operator(
        self,
        *,
        request_digest: str,
        decision: str,
        issued_at: str,
        expires_at: str,
    ) -> dict[str, Any]:
        unsigned = {
            "schema": GRANT_SCHEMA,
            "request_digest": request_digest,
            "decision": decision,
            "approved_by": self._owner_principal,
            "issued_at": issued_at,
            "expires_at": expires_at,
        }
        signature = hmac.new(
            self._secret,
            canonical_sha256(unsigned).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        return {**unsigned, "signature": signature}
