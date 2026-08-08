from __future__ import annotations

import json
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .proposal_authorization import (
    ALLOWED_REVIEW_CLASSES,
    SCHEMA,
    ProposalAuthorizationRecord,
    ProposalAuthorizationRegistry,
    ProposalDecision,
)
from .proposal_authorization_models import ProposalAuthorizationDecisionRecord
from .sandbox_supervisor_evidence import canonical_sha256


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


class DurableProposalAuthorizationStore:
    """Persist immutable 114N review decisions and verify them on every read."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self, item: ProposalAuthorizationRecord
    ) -> ProposalAuthorizationRecord:
        snapshot = item.snapshot()
        self._validate_snapshot(snapshot)
        existing = self._find(
            manifest_digest=item.manifest_digest,
            review_class=item.review_class,
        )
        if existing is not None:
            persisted = self._decode(existing)
            if persisted != item:
                raise ValueError(
                    "PROPOSAL_AUTH_DURABLE_DECISION_ALREADY_RECORDED"
                )
            return persisted

        row = ProposalAuthorizationDecisionRecord(
            manifest_digest=item.manifest_digest,
            review_class=item.review_class,
            authorization_digest=item.authorization_digest,
            payload_json=json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
        )
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            winner = self._find(
                manifest_digest=item.manifest_digest,
                review_class=item.review_class,
            )
            if winner is None:
                raise
            persisted = self._decode(winner)
            if persisted != item:
                raise ValueError(
                    "PROPOSAL_AUTH_DURABLE_DECISION_ALREADY_RECORDED"
                )
            return persisted
        self.db.refresh(row)
        return self._decode(row)

    def require(
        self, *, manifest_digest: str, review_class: str
    ) -> ProposalAuthorizationRecord:
        digest = manifest_digest.strip().lower()
        normalized_class = review_class.strip().lower()
        if not _is_sha256(digest):
            raise ValueError("PROPOSAL_AUTH_DURABLE_MANIFEST_DIGEST_INVALID")
        if normalized_class not in ALLOWED_REVIEW_CLASSES:
            raise ValueError("PROPOSAL_AUTH_DURABLE_REVIEW_CLASS_INVALID")
        row = self._find(
            manifest_digest=digest,
            review_class=normalized_class,
        )
        if row is None:
            raise LookupError("PROPOSAL_AUTH_DURABLE_RECORD_NOT_FOUND")
        return self._decode(row)

    def materialize_registry(
        self, *, manifest_digest: str
    ) -> ProposalAuthorizationRegistry:
        digest = manifest_digest.strip().lower()
        if not _is_sha256(digest):
            raise ValueError("PROPOSAL_AUTH_DURABLE_MANIFEST_DIGEST_INVALID")
        rows = self.db.scalars(
            select(ProposalAuthorizationDecisionRecord)
            .where(ProposalAuthorizationDecisionRecord.manifest_digest == digest)
            .order_by(ProposalAuthorizationDecisionRecord.review_class.asc())
        ).all()
        registry = ProposalAuthorizationRegistry()
        for row in rows:
            registry.record(self._decode(row))
        return registry

    def _find(
        self, *, manifest_digest: str, review_class: str
    ) -> ProposalAuthorizationDecisionRecord | None:
        return self.db.scalar(
            select(ProposalAuthorizationDecisionRecord).where(
                ProposalAuthorizationDecisionRecord.manifest_digest == manifest_digest,
                ProposalAuthorizationDecisionRecord.review_class == review_class,
            )
        )

    @staticmethod
    def _validate_snapshot(snapshot: Mapping[str, object]) -> None:
        payload = dict(snapshot)
        supplied = str(payload.pop("authorization_digest", "") or "").strip().lower()
        if not _is_sha256(supplied):
            raise ValueError("PROPOSAL_AUTH_DURABLE_AUTHORIZATION_DIGEST_INVALID")
        if payload.get("schema") != SCHEMA:
            raise ValueError("PROPOSAL_AUTH_DURABLE_SCHEMA_INVALID")
        if canonical_sha256(payload) != supplied:
            raise PermissionError("PROPOSAL_AUTH_DURABLE_AUTHORIZATION_DIGEST_MISMATCH")

    @classmethod
    def _decode(
        cls, row: ProposalAuthorizationDecisionRecord
    ) -> ProposalAuthorizationRecord:
        try:
            raw = json.loads(row.payload_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise PermissionError("PROPOSAL_AUTH_DURABLE_PAYLOAD_INVALID") from exc
        if not isinstance(raw, dict):
            raise PermissionError("PROPOSAL_AUTH_DURABLE_PAYLOAD_INVALID")
        cls._validate_snapshot(raw)
        supplied = str(raw.get("authorization_digest") or "").strip().lower()
        if supplied != row.authorization_digest:
            raise PermissionError("PROPOSAL_AUTH_DURABLE_ROW_DIGEST_MISMATCH")
        if raw.get("manifest_digest") != row.manifest_digest:
            raise PermissionError("PROPOSAL_AUTH_DURABLE_ROW_IDENTITY_MISMATCH")
        if raw.get("review_class") != row.review_class:
            raise PermissionError("PROPOSAL_AUTH_DURABLE_ROW_IDENTITY_MISMATCH")

        try:
            record = ProposalAuthorizationRecord(
                manifest_digest=str(raw["manifest_digest"]),
                repository=str(raw["repository"]),
                base_commit_sha=str(raw["base_commit_sha"]),
                source_autonomy_branch=str(raw["source_autonomy_branch"]),
                proposed_branch=str(raw["proposed_branch"]),
                patch_output_checksum=str(raw["patch_output_checksum"]),
                producer_id=str(raw["producer_id"]),
                requested_by=str(raw["requested_by"]),
                review_class=str(raw["review_class"]),
                reviewer_id=str(raw["reviewer_id"]),
                reviewer_roles=tuple(str(role) for role in raw["reviewer_roles"]),
                decision=ProposalDecision(str(raw["decision"])),
                rationale=str(raw["rationale"]),
                evidence_uris=tuple(str(uri) for uri in raw["evidence_uris"]),
                decided_at=str(raw["decided_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PermissionError("PROPOSAL_AUTH_DURABLE_PAYLOAD_INVALID") from exc

        if record.snapshot() != raw:
            raise PermissionError("PROPOSAL_AUTH_DURABLE_PAYLOAD_SHAPE_MISMATCH")
        return record
