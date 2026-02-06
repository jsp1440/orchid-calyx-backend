from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Feedback
from app.schemas import FeedbackCreate, FeedbackOut

router = APIRouter(
    prefix="/api",
    tags=["Feedback"],
)


@router.post("/feedback", response_model=FeedbackOut)
def submit_feedback(data: FeedbackCreate, db: Session = Depends(get_db)):
    fb = Feedback(**data.model_dump())
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return fb


@router.get("/feedback", response_model=List[FeedbackOut])
def list_feedback(module: str = None, db: Session = Depends(get_db)):
    q = select(Feedback)
    if module:
        q = q.where(Feedback.module == module)
    q = q.order_by(Feedback.created_at.desc())
    return db.execute(q).scalars().all()
