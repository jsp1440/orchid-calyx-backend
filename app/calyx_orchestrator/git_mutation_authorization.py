from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .proposal_authorization import ProposalAuthorizationRecord, ProposalDecision
from .proposal_authorization_status import proposal_review_status
from .proposal_authorization_store import DurableProposalAuthorizationStore
from .sandbox_supervisor_evidence import canonical_sha256

REQUEST_SCHEMA = "calyx-git-mutation-authorization-request-v2"
GRANT_SCHEMA = "calyx-git-mutation-authorization-grant-v1"
MANIFEST_SCHEMA = "calyx-git-proposal-manifest-v2"
REQUIRED_REVIEW_CLASSES = ("operational", "security")
ALLOWED_ACTIONS = (
    "create_branch",
    "create_commit",
    "push_branch",
    "open_pull_request",
)
MAX_TTL_SECONDS = 1800
MAX_SIGNATURE_CHARS = 8192
FORBIDDEN_REF_CHARS = frozenset(" ~^:?*[\\")


class OwnerGrantSignatureVerifier(Protocol):
    """Externally supplied verification capability; runtime holds no signing secret."""

    def verify(self, *, payload: Mapping[str, Any], signature: str) -> bool: ...


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _is_git_sha(value: str) -> bool:
    return len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


def _valid_git_branch(value: str) -> bool:
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


def _nonempty(value: object, *, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized or "\x00" in normalized or len(normalized) > 256:
        raise ValueError(code)
    return normalized


def _bounded_signature(value: object) -> str:
    signature = str(value or "").strip()
    if not signature or "\x00" in signature or len(signature) > MAX_SIGNATURE_CHARS:
        raise ValueError("GIT_AUTHORIZATION_GRANT_SIGNATURE_INVALID")
    return signature


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("GIT_AUTHORIZATION_TIME_INVALID") from exc
    if parsed.tzinfo is None:
        raise ValueError("GIT_AUTHORIZATION_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


def _trusted_now(clock: Callable[[], datetime]) -> datetime:
    current = clock()
    if current.tzinfo is None:
        raise ValueError("GIT_AUTHORIZATION_CLOCK_TIMEZONE_REQUIRED")
    return current.astimezone(timezone.utc)


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


def _require_authoritative_reviews(
    manifest_snapshot: Mapping[str, Any],
    store: DurableProposalAuthorizationStore,
) -> tuple[ProposalAuthorizationRecord, ...]:
    manifest_digest = _manifest_digest(manifest_snapshot)
    registry = store.materialize_registry(manifest_digest=manifest_digest)
    status = proposal_review_status(registry, manifest_digest=manifest_digest)
    if not status.review_evidence_complete:
        raise PermissionError(status.code)
    records: list[ProposalAuthorizationRecord] = []
    for review_class in REQUIRED_REVIEW_CLASSES:
        try:
            record = store.require(
                manifest_digest=manifest_digest, review_class=review_class
            )
        except LookupError as exc:
            raise PermissionError("GIT_AUTHORIZATION_REQUIRED_REVIEWS_MISSING") from exc
        record.verify_for_manifest(manifest_snapshot)
        if record.decision is not ProposalDecision.APPROVED:
            raise PermissionError("GIT_AUTHORIZATION_REVIEW_NOT_APPROVED")
        if review_class not in record.reviewer_roles:
            raise PermissionError("GIT_AUTHORIZATION_REVIEWER_ROLE_REQUIRED")
        records.append(record)
    reviewer_ids = {record.reviewer_id for record in records}
    if len(reviewer_ids) != len(REQUIRED_REVIEW_CLASSES):
        raise PermissionError("GIT_AUTHORIZATION_REVIEWER_SEPARATION_REQUIRED")
    patch_job_ids = {record.patch_program_job_id for record in records}
    if len(patch_job_ids) != 1:
        raise PermissionError("GIT_AUTHORIZATION_PATCH_JOB_REVIEW_MISMATCH")
    return tuple(records)


@dataclass(frozen=True, slots=True)
class GitMutationAuthorizationRequest:
    manifest_digest: str
    patch_program_job_id: str
    repository: str
    base_commit_sha: str
    base_ref: str
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
            "patch_program_job_id": self.patch_program_job_id,
            "repository": self.repository,
            "base_commit_sha": self.base_commit_sha,
            "base_ref": self.base_ref,
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
            "automatic_merge_authorized": False,
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
            signature=_bounded_signature(value.get("signature")),
        )
        if not _is_sha256(grant.request_digest):
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
    """Verify durable reviewed owner authorization; never mutate Git or hold signing secrets."""

    def __init__(
        self,
        *,
        owner_principal: str,
        signature_verifier: OwnerGrantSignatureVerifier,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        principal = owner_principal.strip()
        if not principal:
            raise ValueError("GIT_AUTHORIZATION_OWNER_PRINCIPAL_REQUIRED")
        if signature_verifier is None:
            raise ValueError("GIT_AUTHORIZATION_SIGNATURE_VERIFIER_REQUIRED")
        self._owner_principal = principal
        self._signature_verifier = signature_verifier
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def build_request(
        manifest_snapshot: Mapping[str, Any],
        *,
        review_store: DurableProposalAuthorizationStore,
        actions: Sequence[str],
        base_ref: str,
        expires_at: str,
        now: datetime | None = None,
    ) -> GitMutationAuthorizationRequest:
        _verify_manifest_non_authority(manifest_snapshot)
        digest = _manifest_digest(manifest_snapshot)
        reviews = _require_authoritative_reviews(manifest_snapshot, review_store)
        normalized_actions = tuple(
            dict.fromkeys(str(action).strip() for action in actions)
        )
        if not normalized_actions or any(
            action not in ALLOWED_ACTIONS for action in normalized_actions
        ):
            raise PermissionError("GIT_AUTHORIZATION_ACTION_NOT_ALLOWED")
        patch_program_job_id = _nonempty(
            manifest_snapshot.get("patch_program_job_id"),
            code="GIT_AUTHORIZATION_PATCH_PROGRAM_JOB_ID_REQUIRED",
        )
        if any(
            record.patch_program_job_id != patch_program_job_id for record in reviews
        ):
            raise PermissionError("GIT_AUTHORIZATION_PATCH_JOB_REVIEW_MISMATCH")
        repository = str(manifest_snapshot.get("repository") or "").strip()
        base_commit = (
            str(manifest_snapshot.get("base_commit_sha") or "").strip().lower()
        )
        target_base_ref = str(base_ref or "").strip()
        proposed_branch = str(manifest_snapshot.get("proposed_branch") or "").strip()
        if not repository or "/" not in repository:
            raise ValueError("GIT_AUTHORIZATION_REPOSITORY_INVALID")
        if not _is_git_sha(base_commit):
            raise ValueError("GIT_AUTHORIZATION_BASE_COMMIT_INVALID")
        if not _valid_git_branch(target_base_ref):
            raise ValueError("GIT_AUTHORIZATION_BASE_REF_INVALID")
        if target_base_ref == proposed_branch:
            raise PermissionError("GIT_AUTHORIZATION_BASE_REF_CONFLICT")
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
            patch_program_job_id=patch_program_job_id,
            repository=repository,
            base_commit_sha=base_commit,
            base_ref=target_base_ref,
            proposed_branch=proposed_branch,
            change_hashes=tuple(sorted(changes)),
            validation_receipt_digests=tuple(sorted(receipts)),
            review_authorization_digests=tuple(
                record.authorization_digest for record in reviews
            ),
            actions=normalized_actions,
            expires_at=expiry.isoformat(),
        )

    def verify_grant(
        self,
        request: GitMutationAuthorizationRequest,
        grant_mapping: Mapping[str, Any],
    ) -> GitMutationAuthorizationGrant:
        grant = GitMutationAuthorizationGrant.from_mapping(grant_mapping)
        if grant.request_digest != request.request_digest:
            raise PermissionError("GIT_AUTHORIZATION_REQUEST_MISMATCH")
        if grant.approved_by != self._owner_principal:
            raise PermissionError("GIT_AUTHORIZATION_APPROVER_MISMATCH")
        issued = _parse_utc(grant.issued_at)
        expiry = _parse_utc(grant.expires_at)
        request_expiry = _parse_utc(request.expires_at)
        current = _trusted_now(self._clock)
        grant_ttl = (expiry - issued).total_seconds()
        if (
            expiry != request_expiry
            or grant_ttl <= 0
            or grant_ttl > MAX_TTL_SECONDS
            or issued > current
            or current >= expiry
        ):
            raise PermissionError("GIT_AUTHORIZATION_GRANT_EXPIRED_OR_INVALID")
        if not self._signature_verifier.verify(
            payload=grant.signing_payload(), signature=grant.signature
        ):
            raise PermissionError("GIT_AUTHORIZATION_SIGNATURE_INVALID")
        if grant.decision != "approved":
            raise PermissionError("GIT_AUTHORIZATION_NOT_APPROVED")
        return grant
