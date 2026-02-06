import json
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Show, Entry, Judge, ScoreSubmission
from app.schemas import (
    JudgeCreate,
    JudgeOut,
    ScoreSubmissionCreate,
    ScoreSubmissionOut,
)
from app.security import verify_api_key

router = APIRouter(
    prefix="/api",
    tags=["Judging"],
    dependencies=[Depends(verify_api_key)],
)


def _parse_points_breakdown(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        # If something weird got stored, don't crash the API—just omit
        return None


def _score_to_out(s: ScoreSubmission) -> dict:
    return {
        "id": s.id,
        "show_id": s.show_id,
        "entry_id": s.entry_id,
        "judge_id": s.judge_id,
        "total_points": s.total_points,
        "points_breakdown": _parse_points_breakdown(s.points_breakdown),
        "notes": s.notes,
        "created_at": s.created_at,
    }


@router.post("/judges", response_model=JudgeOut)
def create_judge(data: JudgeCreate, db: Session = Depends(get_db)):
    show = db.get(Show, data.show_id)
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")

    judge = Judge(
        show_id=data.show_id,
        name=data.name,
        email=data.email,
    )
    db.add(judge)
    db.commit()
    db.refresh(judge)
    return judge


@router.get("/judges", response_model=List[JudgeOut])
def list_judges(
        show_id: str = Query(..., description="Show ID"),
        db: Session = Depends(get_db),
):
    judges = db.execute(
        select(Judge).where(Judge.show_id == show_id)).scalars().all()
    return judges


@router.post("/score-submissions", response_model=ScoreSubmissionOut)
def create_score_submission(data: ScoreSubmissionCreate,
                            db: Session = Depends(get_db)):
    show = db.get(Show, data.show_id)
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")

    if getattr(show, "judging_locked", False):
        raise HTTPException(status_code=409,
                            detail="Judging is locked for this show.")

    entry = db.get(Entry, data.entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    # Safety: ensure entry belongs to the same show
    if entry.show_id != data.show_id:
        raise HTTPException(status_code=409,
                            detail="Entry does not belong to this show.")

    judge = db.get(Judge, data.judge_id)
    if not judge:
        raise HTTPException(status_code=404, detail="Judge not found")

    # Safety: ensure judge belongs to the same show
    if judge.show_id != data.show_id:
        raise HTTPException(status_code=409,
                            detail="Judge is not registered for this show.")

    # Fast pre-check (nice error msg). DB unique constraint is the real guard.
    existing = db.execute(
        select(ScoreSubmission).where(
            ScoreSubmission.show_id == data.show_id,
            ScoreSubmission.entry_id == data.entry_id,
            ScoreSubmission.judge_id == data.judge_id,
        )).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Score already submitted for this judge and entry.",
        )

    breakdown_json = json.dumps(
        data.points_breakdown) if data.points_breakdown else None

    submission = ScoreSubmission(
        show_id=data.show_id,
        entry_id=data.entry_id,
        judge_id=data.judge_id,
        total_points=data.total_points,
        points_breakdown=breakdown_json,
        notes=data.notes,
    )

    db.add(submission)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Handles race conditions; the unique constraint wins
        raise HTTPException(
            status_code=409,
            detail="Duplicate score submission (already exists).",
        )

    db.refresh(submission)
    return _score_to_out(submission)


@router.get("/entries/{entry_id}/scores",
            response_model=List[ScoreSubmissionOut])
def get_entry_scores(entry_id: str, db: Session = Depends(get_db)):
    entry = db.get(Entry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    scores = db.execute(
        select(ScoreSubmission).where(
            ScoreSubmission.entry_id == entry_id)).scalars().all()

    return [_score_to_out(s) for s in scores]


@router.get("/shows/{show_id}/leaderboard")
def show_leaderboard(show_id: str, db: Session = Depends(get_db)):
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")

    rows = db.execute(
        select(
            ScoreSubmission.entry_id,
            func.avg(ScoreSubmission.total_points).label("avg_score"),
            func.sum(ScoreSubmission.total_points).label("total_score"),
            func.count(ScoreSubmission.id).label("num_scores"),
        )
        .where(ScoreSubmission.show_id == show_id)
        .group_by(ScoreSubmission.entry_id)
        .order_by(func.avg(ScoreSubmission.total_points).desc())
    ).all()

    entries = []
    for row in rows:
        entry = db.get(Entry, row.entry_id)
        entries.append({
            "entry_id": row.entry_id,
            "exhibitor_name": entry.exhibitor_name if entry else None,
            "plant_name": entry.plant_name if entry else None,
            "avg_score": round(float(row.avg_score), 2),
            "total_score": int(row.total_score),
            "num_scores": row.num_scores,
        })

    return {"show_id": show_id, "leaderboard": entries}
