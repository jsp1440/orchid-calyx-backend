from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class CanonicalAggregateResolutionError(ValueError):
    pass


class CanonicalAggregateResolver:
    """Read immutable evidence aggregates from the canonical Brain-backed store.

    The resolver is intentionally read-only. It accepts only aggregate-version identities
    and reconstructs the evaluator input from oc_candidate_knowledge tables. Caller-supplied
    evidence, confidence, review, verification, or source-anchor payloads are not accepted.
    """

    def __init__(self, db: Session):
        self.db = db

    def resolve_versions(self, aggregate_version_ids: Iterable[int]) -> list[dict[str, Any]]:
        ids = list(aggregate_version_ids)
        if not ids:
            raise CanonicalAggregateResolutionError("AGGREGATE_VERSION_IDS_REQUIRED")
        if len(ids) != len(set(ids)):
            raise CanonicalAggregateResolutionError("DUPLICATE_AGGREGATE_VERSION_ID")
        return [self.resolve_version(version_id) for version_id in ids]

    def resolve_version(self, aggregate_version_id: int) -> dict[str, Any]:
        if not isinstance(aggregate_version_id, int) or isinstance(aggregate_version_id, bool):
            raise CanonicalAggregateResolutionError("INVALID_AGGREGATE_VERSION_ID")
        if aggregate_version_id <= 0:
            raise CanonicalAggregateResolutionError("INVALID_AGGREGATE_VERSION_ID")

        row = self.db.execute(
            text(
                """
                SELECT
                    av.aggregate_version_id,
                    av.aggregate_id,
                    aa.aggregate_type,
                    av.identity_hash,
                    aa.status AS aggregate_status,
                    aa.review_state,
                    aa.verification_state,
                    aa.published,
                    aa.active AS aggregate_active,
                    av.active AS version_active,
                    av.superseded_by_version_id,
                    av.summary,
                    av.contexts,
                    av.provenance_chain
                FROM oc_candidate_knowledge.aggregate_versions av
                JOIN oc_candidate_knowledge.aggregate_assertions aa
                  ON aa.aggregate_id = av.aggregate_id
                WHERE av.aggregate_version_id = :aggregate_version_id
                """
            ),
            {"aggregate_version_id": aggregate_version_id},
        ).mappings().one_or_none()
        if row is None:
            raise CanonicalAggregateResolutionError("CANONICAL_AGGREGATE_VERSION_NOT_FOUND")
        if not bool(row["aggregate_active"]) or not bool(row["version_active"]):
            raise CanonicalAggregateResolutionError("CANONICAL_AGGREGATE_VERSION_NOT_ACTIVE")
        if row["superseded_by_version_id"] is not None:
            raise CanonicalAggregateResolutionError("CANONICAL_AGGREGATE_VERSION_SUPERSEDED")
        if bool(row["published"]):
            raise CanonicalAggregateResolutionError("INVALID_PUBLISHED_CANDIDATE_AGGREGATE_STATE")

        confidence_row = self.db.execute(
            text(
                """
                SELECT formula_version, components, uncertainty, score,
                       score_is_truth_probability
                FROM oc_candidate_knowledge.aggregate_confidence_assessments
                WHERE aggregate_version_id = :aggregate_version_id
                ORDER BY assessment_id DESC
                LIMIT 1
                """
            ),
            {"aggregate_version_id": aggregate_version_id},
        ).mappings().one_or_none()
        if confidence_row is not None and bool(confidence_row["score_is_truth_probability"]):
            raise CanonicalAggregateResolutionError("CANONICAL_CONFIDENCE_TRUTH_PROBABILITY_FORBIDDEN")

        evidence_rows = self.db.execute(
            text(
                """
                SELECT candidate_id, source_revision_id, anchor_id
                FROM oc_candidate_knowledge.aggregate_evidence_links
                WHERE aggregate_version_id = :aggregate_version_id
                ORDER BY candidate_id, source_revision_id, anchor_id
                """
            ),
            {"aggregate_version_id": aggregate_version_id},
        ).mappings().all()

        summary = dict(row["summary"] or {})
        confidence_components = (
            dict(confidence_row["components"] or {}) if confidence_row is not None else {}
        )
        confidence_dimensions = {**summary, **confidence_components}
        source_anchor_links = [
            {
                "candidate_id": item["candidate_id"],
                "revision_id": item["source_revision_id"],
                "anchor_ids": [item["anchor_id"]],
            }
            for item in evidence_rows
        ]

        return {
            "aggregate_id": row["aggregate_id"],
            "aggregate_version_id": row["aggregate_version_id"],
            "aggregate_type": row["aggregate_type"],
            "identity_hash": row["identity_hash"],
            "aggregate_status": row["aggregate_status"],
            "review_state": row["review_state"],
            "verification_state": row["verification_state"],
            "published": False,
            "source_anchor_links": source_anchor_links,
            "confidence_dimensions": confidence_dimensions,
            "canonical_contexts": dict(row["contexts"] or {}),
            "canonical_provenance_chain": dict(row["provenance_chain"] or {}),
            "canonical_confidence_assessment": (
                {
                    "formula_version": confidence_row["formula_version"],
                    "score": confidence_row["score"],
                    "score_is_truth_probability": False,
                    "uncertainty": dict(confidence_row["uncertainty"] or {}),
                }
                if confidence_row is not None
                else None
            ),
        }
