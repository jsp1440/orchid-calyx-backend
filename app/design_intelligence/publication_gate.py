"""Fail-closed publication gate for design-intelligence retrieval.

A semantic unit may be retrieved only while the exact document version it came
from is the latest version of its logical key, has an APPROVED review decision as
its most recent review, and has a PUBLISHED publication status as its most recent
publication event. Anything else, including a missing document, a superseded
version, a later rejection, a retirement, a retraction or an unreadable
repository, is treated as not retrievable.

Indexing and retrieval are separate steps, so the index alone cannot be the
authority on what may be shown: a unit that was indexed by mistake, or whose
document was later rejected, retired or superseded, must stay invisible.
"""

from __future__ import annotations

from collections.abc import Callable

from .models import PublicationStatus, ReviewState

#: ``(document_id, version) -> may this version be retrieved right now``.
PublicationGate = Callable[[int, int], bool]


class DesignPublicationStateUnavailable(ValueError):
    """Publication state could not be read, so nothing may be returned."""

    def __init__(self) -> None:
        super().__init__("DESIGN_PUBLICATION_STATE_UNAVAILABLE")


class DesignPublicationGateRequired(ValueError):
    """A consumer that must not return unreviewed guidance has no gate."""

    def __init__(self) -> None:
        super().__init__("DESIGN_PUBLICATION_GATE_REQUIRED")


def is_retrievable(repository, document_id: int, version: int) -> bool:
    """Whether the exact document version is approved, published and current."""
    document = repository.document(document_id)
    if document is None or document.version != version:
        return False
    latest = repository.latest(document.logical_key)
    if latest is None or latest.document_id != document.document_id:
        return False
    return (
        repository.review_state(document_id) is ReviewState.APPROVED
        and repository.publication_status(document_id) is PublicationStatus.PUBLISHED
    )


def corpus_publication_gate(repository) -> PublicationGate:
    """Bind the gate to a corpus repository (in-memory or PostgreSQL).

    A repository failure raises :class:`DesignPublicationStateUnavailable`. A
    partial answer would silently hide or show the wrong units, so the search
    refuses outright instead.
    """

    def gate(document_id: int, version: int) -> bool:
        try:
            return is_retrievable(repository, document_id, version)
        except Exception as exc:
            raise DesignPublicationStateUnavailable() from exc

    return gate
