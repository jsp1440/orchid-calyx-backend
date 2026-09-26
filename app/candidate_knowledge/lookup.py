"""Read-only access to the candidate-knowledge store that serves the operator API.

Candidates live in the BUILD-086 runtime repository (a JSON snapshot in
``oc_candidate_knowledge.runtime_repository_snapshots`` when a database is configured).
Nothing in the application writes the relational ``oc_candidate_knowledge.candidates``
table created by migration 086a, so cross-module consumers must resolve candidates
through the same repository instance ``/api/candidate-knowledge`` serves from.
"""

from __future__ import annotations

from typing import Any


class CandidateStoreUnavailable(RuntimeError):
    """The serving candidate repository could not be reached; callers must fail closed."""


def serving_repository() -> Any:
    """Return the refreshed repository used by ``/api/candidate-knowledge``.

    Raises :class:`CandidateStoreUnavailable` exactly where the serving routes answer 503.
    """
    from . import routes

    repository = routes.REPOSITORY
    if repository is None or routes.SERVICE is None:
        raise CandidateStoreUnavailable(
            routes.REPOSITORY_ERROR or "CANDIDATE_DATABASE_UNAVAILABLE"
        )
    try:
        if hasattr(repository, "refresh"):
            repository.refresh()
    except Exception as exc:  # any store failure is unavailability
        raise CandidateStoreUnavailable("CANDIDATE_DATABASE_UNAVAILABLE") from exc
    return repository
