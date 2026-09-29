from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.member_auth import owner_or_member_read
from app.models import Feedback
from app.schemas import FeedbackCreate, FeedbackOut

router = APIRouter(
    prefix="/api",
    tags=["Feedback"],
)

# Anonymous beta feedback is public to submit, so every string is length-bounded:
# over-long input is rejected with 422 instead of being stored unbounded.
FEEDBACK_LABEL_MAX_CHARS = 200
FEEDBACK_TEXT_MAX_CHARS = 4000

FEEDBACK_LIST_DEFAULT_LIMIT = 200
FEEDBACK_LIST_MAX_LIMIT = 1000

Db = Annotated[Session, Depends(get_db)]


class BoundedFeedbackCreate(FeedbackCreate):
    """``FeedbackCreate`` with the same fields and defaults, plus length limits."""

    module: str = Field(max_length=FEEDBACK_LABEL_MAX_CHARS)
    step: str | None = Field(default=None, max_length=FEEDBACK_LABEL_MAX_CHARS)
    confusion: str | None = Field(default=None, max_length=FEEDBACK_TEXT_MAX_CHARS)
    suggestions: str | None = Field(default=None, max_length=FEEDBACK_TEXT_MAX_CHARS)
    organization_id: str | None = Field(default=None, max_length=FEEDBACK_LABEL_MAX_CHARS)


# Public on purpose: anonymous visitors submit beta feedback.
@router.post("/feedback", response_model=FeedbackOut)
def submit_feedback(data: BoundedFeedbackCreate, db: Db):
    fb = Feedback(**data.model_dump())
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return fb


# Owner-only. Rows hold visitors' free text (which can contain personal information)
# and non-public organization ids. ``owner_or_member_read`` is default-deny and this
# route is not marked ``@member_readable``: owner session or API key are admitted
# exactly as by ``verify_owner_or_api_key``, a verified member gets 403
# OWNER_ACCESS_REQUIRED, anonymous/invalid credentials stay 401. The dependency runs
# before query validation, so unauthenticated callers never see a 422.
@router.get(
    "/feedback",
    response_model=list[FeedbackOut],
    dependencies=[Depends(owner_or_member_read)],
)
def list_feedback(
    db: Db,
    module: str | None = None,
    limit: Annotated[int, Query(ge=1, le=FEEDBACK_LIST_MAX_LIMIT)] = FEEDBACK_LIST_DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    q = select(Feedback)
    if module:
        q = q.where(Feedback.module == module)
    q = q.order_by(Feedback.created_at.desc(), Feedback.id.desc()).offset(offset).limit(limit)
    return db.execute(q).scalars().all()
