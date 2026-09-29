"""Read-only access to the evidence-aggregation store that serves the operator API.

Evidence aggregates live in the BUILD-086 runtime repository (a JSON snapshot in
``oc_candidate_knowledge.runtime_repository_snapshots`` when a database is configured).
Nothing in the application writes the relational ``aggregate_assertions`` /
``aggregate_versions`` tables created by migration 086b, so cross-module consumers must
resolve aggregates through the same repository instance ``/api/evidence-aggregation``
serves from, never through those tables.
"""

from __future__ import annotations

from typing import Any


class AggregateStoreUnavailable(RuntimeError):
    """The serving aggregate repository could not be reached; callers must fail closed."""


def serving_repository() -> Any:
    """Return the refreshed repository used by ``/api/evidence-aggregation``.

    Raises :class:`AggregateStoreUnavailable` exactly where the serving routes answer 503.
    """
    from . import routes

    repository = routes.REPOSITORY
    if repository is None or routes.SERVICE is None:
        raise AggregateStoreUnavailable(
            routes.REPOSITORY_ERROR or "AGGREGATION_DATABASE_UNAVAILABLE"
        )
    try:
        if hasattr(repository, "refresh"):
            repository.refresh()
    except Exception as exc:  # any store failure is unavailability
        raise AggregateStoreUnavailable("AGGREGATION_DATABASE_UNAVAILABLE") from exc
    return repository
