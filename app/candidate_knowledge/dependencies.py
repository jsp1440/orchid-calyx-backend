"""Candidate-knowledge repository and service, resolved on first use.

The repository used to be built when this module was imported. With
``DATABASE_URL`` set, *importing* anything that reached this module opened a
database connection and could bootstrap the additive runtime snapshot table
(``PostgresStateMixin._bootstrap_runtime_snapshot_storage_if_missing``) --
including tooling, tests and offline demonstrations that never served a
request (FIL-001B, #1810).

It is now resolved once, on the first call that needs it, under a lock. What it
resolves to is unchanged: the same repository class for the same configuration,
the same ``CANDIDATE_DATABASE_UNAVAILABLE`` code, and the same "a failure is
remembered for the life of the process" behaviour. Only *when* the database is
first contacted moves, from import to first use.
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import HTTPException

from app.persistence.state_repository import configured_database_url

from .repository import MemoryCandidateRepository
from .service import CandidateExtractionService

UNAVAILABLE = "CANDIDATE_DATABASE_UNAVAILABLE"

_LOCK = threading.Lock()
_RESOLVED: (
    tuple[
        MemoryCandidateRepository | None, CandidateExtractionService | None, str | None
    ]
    | None
) = None


def _build_repository() -> MemoryCandidateRepository:
    # PostgresCandidateRepository is a subclass of MemoryCandidateRepository,
    # so the return type is valid for both branches.
    if configured_database_url():
        from .postgres_repository import PostgresCandidateRepository

        return PostgresCandidateRepository()
    return MemoryCandidateRepository()


def resolve_components() -> tuple[
    MemoryCandidateRepository | None, CandidateExtractionService | None, str | None
]:
    """``(repository, service, error)``, built at most once per process.

    A build failure is resolved too -- to ``(None, None, UNAVAILABLE)`` -- and is
    not retried, exactly as the import-time build behaved.
    """
    global _RESOLVED
    resolved = _RESOLVED
    if resolved is not None:
        return resolved
    with _LOCK:
        if _RESOLVED is None:
            try:
                repository: MemoryCandidateRepository | None = _build_repository()
                error: str | None = None
            except Exception:  # noqa: BLE001 - unavailable is unavailable
                repository, error = None, UNAVAILABLE
            service = (
                CandidateExtractionService(repository)
                if repository is not None
                else None
            )
            _RESOLVED = (repository, service, error)
        return _RESOLVED


def get_candidate_components() -> tuple[
    MemoryCandidateRepository, CandidateExtractionService
]:
    """Public FastAPI dependency that returns (repository, service) or raises HTTP 503.

    The repository is always a ``MemoryCandidateRepository`` instance; when a database
    URL is configured it is a ``PostgresCandidateRepository`` subclass of the same.
    """
    repository, service, error = resolve_components()
    if repository is None or service is None:
        raise HTTPException(503, detail={"code": error or UNAVAILABLE})
    return repository, service


def __getattr__(name: str) -> Any:
    """Keep ``_REPOSITORY``, ``_SERVICE`` and ``_REPOSITORY_ERROR`` readable.

    They were module attributes; reading one now resolves the components first.
    """
    index = {"_REPOSITORY": 0, "_SERVICE": 1, "_REPOSITORY_ERROR": 2}.get(name)
    if index is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return resolve_components()[index]
