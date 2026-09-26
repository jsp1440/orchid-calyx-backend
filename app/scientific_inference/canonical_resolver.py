from __future__ import annotations

from collections.abc import Callable, Iterable
from copy import deepcopy
from typing import Any


class CanonicalAggregateResolutionError(ValueError):
    pass


def _serving_aggregate_repository() -> Any:
    from app.evidence_aggregation.lookup import serving_repository

    return serving_repository()


class CanonicalAggregateResolver:
    """Read immutable evidence aggregate versions from the canonical aggregation store.

    The resolver is intentionally read-only. It accepts only aggregate-version identities
    and reconstructs the evaluator input from the evidence-aggregation runtime repository:
    the same store ``/api/evidence-aggregation`` serves from (a JSON snapshot in
    ``oc_candidate_knowledge.runtime_repository_snapshots`` when a database is configured).
    The relational 086b ``aggregate_*`` tables are never written by the application and
    are therefore not an authority. Caller-supplied evidence, confidence, review,
    verification, or source-anchor payloads are not accepted. An unreachable store fails
    closed.
    """

    def __init__(self, repository: Callable[[], Any] | None = None):
        self._repository = repository or _serving_aggregate_repository

    def _store(self) -> Any:
        try:
            repository = self._repository()
        except Exception as exc:  # unavailable is never resolvable
            raise CanonicalAggregateResolutionError(
                "CANONICAL_AGGREGATE_STORE_UNAVAILABLE"
            ) from exc
        if repository is None:
            raise CanonicalAggregateResolutionError("CANONICAL_AGGREGATE_STORE_UNAVAILABLE")
        return repository

    def resolve_versions(self, aggregate_version_ids: Iterable[int]) -> list[dict[str, Any]]:
        ids = list(aggregate_version_ids)
        if not ids:
            raise CanonicalAggregateResolutionError("AGGREGATE_VERSION_IDS_REQUIRED")
        if len(ids) != len(set(ids)):
            raise CanonicalAggregateResolutionError("DUPLICATE_AGGREGATE_VERSION_ID")
        for version_id in ids:
            self._validate_identity(version_id)
        repository = self._store()
        return [self._resolve(repository, version_id) for version_id in ids]

    def resolve_version(self, aggregate_version_id: int) -> dict[str, Any]:
        self._validate_identity(aggregate_version_id)
        return self._resolve(self._store(), aggregate_version_id)

    @staticmethod
    def _validate_identity(aggregate_version_id: Any) -> None:
        if not isinstance(aggregate_version_id, int) or isinstance(aggregate_version_id, bool):
            raise CanonicalAggregateResolutionError("INVALID_AGGREGATE_VERSION_ID")
        if aggregate_version_id <= 0:
            raise CanonicalAggregateResolutionError("INVALID_AGGREGATE_VERSION_ID")

    @staticmethod
    def _resolve(repository: Any, aggregate_version_id: int) -> dict[str, Any]:
        row = repository.aggregate_version(aggregate_version_id)
        if row is None:
            raise CanonicalAggregateResolutionError("CANONICAL_AGGREGATE_VERSION_NOT_FOUND")
        row = deepcopy(row)
        if not bool(row.get("active")):
            raise CanonicalAggregateResolutionError("CANONICAL_AGGREGATE_VERSION_NOT_ACTIVE")
        if (
            row.get("superseded_by_version_id") is not None
            or row.get("supersession_state") == "SUPERSEDED"
        ):
            raise CanonicalAggregateResolutionError("CANONICAL_AGGREGATE_VERSION_SUPERSEDED")
        if bool(row.get("published")):
            raise CanonicalAggregateResolutionError("INVALID_PUBLISHED_CANDIDATE_AGGREGATE_STATE")

        confidence_dimensions = dict(row.get("confidence_dimensions") or {})
        if bool(confidence_dimensions.get("score_is_truth_probability")):
            raise CanonicalAggregateResolutionError("CANONICAL_CONFIDENCE_TRUTH_PROBABILITY_FORBIDDEN")

        # Preserve the store's deterministic contribution order.
        source_anchor_links = [
            {
                "candidate_id": link.get("candidate_id"),
                "revision_id": link.get("revision_id"),
                "anchor_ids": list(link.get("anchor_ids") or ()),
            }
            for link in row.get("source_anchor_links") or ()
        ]

        return {
            "aggregate_id": row["aggregate_id"],
            "aggregate_version_id": row["aggregate_version_id"],
            "aggregate_type": row.get("aggregate_type"),
            "identity_hash": row.get("identity_hash"),
            "aggregate_status": row.get("aggregate_status"),
            "review_state": row.get("review_state"),
            "verification_state": row.get("verification_state"),
            "published": False,
            "source_anchor_links": source_anchor_links,
            "confidence_dimensions": confidence_dimensions,
            "canonical_contexts": {
                "temporal": row.get("temporal_context") or {},
                "geographic": row.get("geographic_context") or {},
                "taxonomic": row.get("taxonomic_context") or {},
                "measurement": row.get("measurement_summary") or {},
            },
            "canonical_provenance_chain": dict(row.get("provenance_chain") or {}),
            # The aggregation store records multidimensional confidence only; it has no
            # separate scored confidence assessment, so none is fabricated here.
            "canonical_confidence_assessment": None,
        }
