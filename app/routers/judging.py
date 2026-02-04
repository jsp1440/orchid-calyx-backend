import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Show, Entry, Judge, ScoreSubmission
from app.schemas import JudgeCreate, JudgeOut, ScoreSubmissionCreate, ScoreSubmissionOut
from app.security import verify_api_key

router = APIRouter(prefix="/api", tags=["Judging"], dependencies=[Depends(verify_api_key)])


@router.post("/judges", response_model=JudgeOut)
def create_judge(data: JudgeCreate, db: Session = Depends(get_db)):
    show = db.get(Show, data.show_id)
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    
    judge = Judge(
        show_id=data.show_id,
        name=data.name,
        email=data.email
    )
    db.add(judge)
    db.commit()
    db.refresh(judge)
    return judge


@router.get("/judges", response_model=list[JudgeOut])
def list_judges(show_id: str, db: Session = Depends(get_db)):
    judges = db.execute(
        select(Judge).where(Judge.show_id == show_id)
    ).scalars().all()
    return judges


@router.post("/score-submissions", response_model=ScoreSubmissionOut)
def create_score_submission(data: ScoreSubmissionCreate, db: Session = Depends(get_db)):
    show = db.get(Show, data.show_id)
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    
    if show.judging_locked:
        raise HTTPException(status_code=409, detail="Judging is locked for this show.")
    
    entry = db.get(Entry, data.entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    judge = db.get(Judge, data.judge_id)
    if not judge:
        raise HTTPException(status_code=404, detail="Judge not found")
    
    existing = db.execute(
        select(ScoreSubmission).where(
            ScoreSubmission.show_id == data.show_id,
            ScoreSubmission.entry_id == data.entry_id,
            ScoreSubmission.judge_id == data.judge_id
        )
    ).scalar_one_or_none()
    
    if existing:
        raise HTTPException(status_code=409, detail="Score already submitted for this judge and entry.")
    
    breakdown_json = None
    if data.points_breakdown:
        breakdown_json = json.dumps(data.points_breakdown)
    
    submission = ScoreSubmission(
        show_id=data.show_id,
        entry_id=data.entry_id,
        judge_id=data.judge_id,
        total_points=data.total_points,
        points_breakdown=breakdown_json,
        notes=data.notes
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


@router.get("/entries/{entry_id}/scores", response_model=list[ScoreSubmissionOut])
def get_entry_scores(entry_id: str, db: Session = Depends(get_db)):
    entry = db.get(Entry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    scores = db.execute(
        select(ScoreSubmission).where(ScoreSubmission.entry_id == entry_id)
    ).scalars().all()
    return scores
