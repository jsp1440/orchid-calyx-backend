"""The show judging lock, shared by every router that writes show-scoped data.

``Show.judging_locked`` freezes a show's judging and its results. Only the
owner's ``PATCH /api/shows/{id}`` sets or clears it, and that route is never
guarded here.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Show


def ensure_show_unlocked(db: Session, show_id: str | None) -> None:
    """Raise 409 when ``show_id`` names a show whose judging is locked."""
    show = db.get(Show, show_id) if show_id else None
    if show and show.judging_locked:
        raise HTTPException(
            status_code=409, detail="Judging is locked for this show. Edits are frozen."
        )
