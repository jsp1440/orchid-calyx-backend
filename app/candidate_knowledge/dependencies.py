from __future__ import annotations

from fastapi import HTTPException

from app.persistence.state_repository import configured_database_url

from .repository import MemoryCandidateRepository
from .service import CandidateExtractionService


def _build_repository() -> MemoryCandidateRepository:
    # PostgresCandidateRepository is a subclass of MemoryCandidateRepository,
    # so the return type is valid for both branches.
    if configured_database_url():
        from .postgres_repository import PostgresCandidateRepository

        return PostgresCandidateRepository()
    return MemoryCandidateRepository()


try:
    _REPOSITORY: MemoryCandidateRepository | None = _build_repository()
    _REPOSITORY_ERROR: str | None = None
except Exception:  # noqa: BLE001
    _REPOSITORY = None
    _REPOSITORY_ERROR = "CANDIDATE_DATABASE_UNAVAILABLE"

_SERVICE: CandidateExtractionService | None = (
    CandidateExtractionService(_REPOSITORY) if _REPOSITORY is not None else None
)


def get_candidate_components() -> tuple[MemoryCandidateRepository, CandidateExtractionService]:
    """Public FastAPI dependency that returns (repository, service) or raises HTTP 503.

    The repository is always a ``MemoryCandidateRepository`` instance; when a database
    URL is configured it is a ``PostgresCandidateRepository`` subclass of the same.
    """
    if _REPOSITORY is None or _SERVICE is None:
        raise HTTPException(
            503, detail={"code": _REPOSITORY_ERROR or "CANDIDATE_DATABASE_UNAVAILABLE"}
        )
    return _REPOSITORY, _SERVICE
