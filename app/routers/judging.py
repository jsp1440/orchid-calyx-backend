import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import (
    Entry,
    Exhibitor,
    Judge,
    JudgeAssignment,
    JudgingAward,
    JudgingCriterion,
    JudgingEvent,
    Plant,
    PlantCategory,
    Score,
    Scorecard,
    ScorecardAuditLog,
    ScoreSubmission,
    Show,
)
from app.routers.show_day import _exhibitor_name, new_qr_token
from app.schemas import (
    ExhibitorCreate,
    ExhibitorOut,
    JudgeAssignmentCreate,
    JudgeAssignmentOut,
    JudgeCreate,
    JudgeOut,
    JudgingAwardOut,
    JudgingCriterionCreate,
    JudgingCriterionOut,
    JudgingEventCreate,
    JudgingEventOut,
    JudgingEventUpdate,
    PlantCategoryCreate,
    PlantCategoryOut,
    PlantCreate,
    PlantOut,
    ScoreBatchCreate,
    ScorecardAuditOut,
    ScorecardOut,
    ScorecardSaveRequest,
    ScorecardSubmitRequest,
    ScoreOut,
    ScoreSubmissionCreate,
    ScoreSubmissionOut,
)
from app.security import require_judge, verify_api_key
from app.show_lock import ensure_show_unlocked as _ensure_show_unlocked

router = APIRouter(
    prefix="/api",
    tags=["Judging"],
    dependencies=[Depends(verify_api_key)],
)

# FastAPI dependency marker singletons keep dependency injection explicit while
# avoiding a function call in every route signature.
DB_DEPENDENCY = Depends(get_db)
JUDGE_DEPENDENCY = Depends(require_judge)


def _utcnow() -> datetime:
    """Return naive UTC for the existing timezone-naive SQLAlchemy columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def _parse_points_breakdown(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
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


def _generate_qr_code(plant_id: str) -> str:
    """A new plant's tag token. Random, never derived from ``plant_id``."""
    return new_qr_token()


# A judging event only moves forward: draft -> published -> closed (the publish
# and close routes, and the model's "draft" default). A status outside this
# order is not one the model defines.
EVENT_STATUS_ORDER = {"draft": 0, "published": 1, "closed": 2}


def _check_event_status_change(event: JudgingEvent, new_status: Any) -> bool:
    """Validate a PATCHed status; return True when it actually changes.

    Closed is terminal, and no event moves backwards, so results cannot be
    reopened for edits by an ordinary update.
    """
    current = event.status
    if current == "closed" and new_status != "closed":
        raise HTTPException(status_code=409, detail="Closed events cannot be reopened.")
    if new_status not in EVENT_STATUS_ORDER:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown judging event status: {new_status!r}. "
            f"Expected one of {sorted(EVENT_STATUS_ORDER)}.",
        )
    if new_status == current:
        return False
    if EVENT_STATUS_ORDER[new_status] < EVENT_STATUS_ORDER.get(current, 0):
        raise HTTPException(
            status_code=409,
            detail=f"Judging event status cannot move from {current!r} back to "
            f"{new_status!r}.",
        )
    return True


def _get_scorable_criterion(
    db: Session, criterion_id: str, value: float | None
) -> JudgingCriterion:
    criterion = db.get(JudgingCriterion, criterion_id)
    if not criterion:
        raise HTTPException(
            status_code=404, detail=f"Criterion {criterion_id} not found"
        )
    if value is not None:
        if criterion.points_min is not None and value < criterion.points_min:
            raise HTTPException(
                status_code=422,
                detail=f"{criterion.criteria_name}: {value} is below the minimum of {criterion.points_min}",
            )
        if criterion.points_max is not None and value > criterion.points_max:
            raise HTTPException(
                status_code=422,
                detail=f"{criterion.criteria_name}: {value} is above the maximum of {criterion.points_max}",
            )
    return criterion


# ── Judging Events ────────────────────────────────────────────────


@router.post("/shows/{show_id}/judging/events", response_model=JudgingEventOut)
def create_judging_event(
    show_id: str, data: JudgingEventCreate, db: Session = DB_DEPENDENCY
):
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    _ensure_show_unlocked(db, show_id)

    event = JudgingEvent(
        show_id=show_id,
        name=data.name,
        judging_type=data.judging_type,
        is_blind=data.is_blind,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("/shows/{show_id}/judging/events", response_model=list[JudgingEventOut])
def list_judging_events(show_id: str, db: Session = DB_DEPENDENCY):
    events = (
        db.execute(select(JudgingEvent).where(JudgingEvent.show_id == show_id))
        .scalars()
        .all()
    )
    return events


@router.get("/judging/events/{event_id}", response_model=JudgingEventOut)
def get_judging_event(event_id: str, db: Session = DB_DEPENDENCY):
    event = db.get(JudgingEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Judging event not found")
    return event


@router.patch("/judging/events/{event_id}", response_model=JudgingEventOut)
def update_judging_event(
    event_id: str, data: JudgingEventUpdate, db: Session = DB_DEPENDENCY
):
    event = db.get(JudgingEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Judging event not found")

    _ensure_show_unlocked(db, event.show_id)

    changes = data.model_dump(exclude_unset=True)
    if "status" in changes and _check_event_status_change(event, changes["status"]):
        now = _utcnow()
        if changes["status"] == "published":
            event.published_at = now
        elif changes["status"] == "closed":
            event.closed_at = now
    for field, val in changes.items():
        setattr(event, field, val)

    db.commit()
    db.refresh(event)
    return event


@router.post("/judging/events/{event_id}/publish", response_model=JudgingEventOut)
def publish_judging_event(event_id: str, db: Session = DB_DEPENDENCY):
    event = db.get(JudgingEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Judging event not found")
    _ensure_show_unlocked(db, event.show_id)
    if event.status == "closed":
        raise HTTPException(
            status_code=409, detail="Closed events cannot be re-published"
        )
    if event.status == "published":
        return event

    event.status = "published"
    event.published_at = _utcnow()
    db.commit()
    db.refresh(event)
    return event


@router.post("/judging/events/{event_id}/close", response_model=JudgingEventOut)
def close_judging_event(event_id: str, db: Session = DB_DEPENDENCY):
    event = db.get(JudgingEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Judging event not found")
    _ensure_show_unlocked(db, event.show_id)
    if event.status == "closed":
        return event

    event.status = "closed"
    event.closed_at = _utcnow()
    db.commit()
    db.refresh(event)
    return event


# ── Plant Categories ──────────────────────────────────────────────


@router.post("/judging/events/{event_id}/categories", response_model=PlantCategoryOut)
def create_category(
    event_id: str, data: PlantCategoryCreate, db: Session = DB_DEPENDENCY
):
    event = db.get(JudgingEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Judging event not found")
    _ensure_show_unlocked(db, event.show_id)

    cat = PlantCategory(
        judging_event_id=event_id,
        name=data.name,
        description=data.description,
        sort_order=data.sort_order if data.sort_order is not None else 0,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.get(
    "/judging/events/{event_id}/categories", response_model=list[PlantCategoryOut]
)
def list_categories(event_id: str, db: Session = DB_DEPENDENCY):
    cats = (
        db.execute(
            select(PlantCategory).where(PlantCategory.judging_event_id == event_id)
        )
        .scalars()
        .all()
    )
    return cats


# ── Judging Awards (read-only from Orchid Continuum) ─────────────


@router.get("/judging/awards", response_model=list[JudgingAwardOut])
def list_awards(system_id: str | None = Query(None), db: Session = DB_DEPENDENCY):
    q = select(JudgingAward)
    if system_id:
        q = q.where(JudgingAward.system_id == system_id)
    return db.execute(q).scalars().all()


@router.get("/judging/awards/{award_id}", response_model=JudgingAwardOut)
def get_award(award_id: str, db: Session = DB_DEPENDENCY):
    award = db.get(JudgingAward, award_id)
    if not award:
        raise HTTPException(status_code=404, detail="Award not found")
    return award


# ── Judging Criteria (per award) ─────────────────────────────────


@router.post("/judging/awards/{award_id}/criteria", response_model=JudgingCriterionOut)
def create_criterion(
    award_id: str, data: JudgingCriterionCreate, db: Session = DB_DEPENDENCY
):
    award = db.get(JudgingAward, award_id)
    if not award:
        raise HTTPException(status_code=404, detail="Award not found")

    criterion = JudgingCriterion(
        award_id=award_id,
        criteria_name=data.criteria_name,
        criteria_description=data.criteria_description,
        points_min=data.points_min,
        points_max=data.points_max,
        weighting=data.weighting,
        rubric_json=data.rubric_json,
        scoring_type=data.scoring_type or "numeric",
        min_value=data.min_value,
        max_value=data.max_value,
        choices_json=data.choices_json,
    )
    db.add(criterion)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Criterion with this name already exists for this award.",
        )
    db.refresh(criterion)
    return criterion


@router.get(
    "/judging/awards/{award_id}/criteria", response_model=list[JudgingCriterionOut]
)
def list_criteria(award_id: str, db: Session = DB_DEPENDENCY):
    criteria = (
        db.execute(
            select(JudgingCriterion).where(JudgingCriterion.award_id == award_id)
        )
        .scalars()
        .all()
    )
    return criteria


# ── Exhibitors ────────────────────────────────────────────────────


@router.post("/exhibitors", response_model=ExhibitorOut)
def create_exhibitor(data: ExhibitorCreate, db: Session = DB_DEPENDENCY):
    exhibitor = Exhibitor(
        name=data.name,
        email=data.email,
        phone=data.phone,
    )
    db.add(exhibitor)
    db.commit()
    db.refresh(exhibitor)
    return exhibitor


@router.get("/exhibitors", response_model=list[ExhibitorOut])
def list_exhibitors(db: Session = DB_DEPENDENCY):
    return db.execute(select(Exhibitor)).scalars().all()


@router.get("/exhibitors/{exhibitor_id}", response_model=ExhibitorOut)
def get_exhibitor(exhibitor_id: str, db: Session = DB_DEPENDENCY):
    ex = db.get(Exhibitor, exhibitor_id)
    if not ex:
        raise HTTPException(status_code=404, detail="Exhibitor not found")
    return ex


# ── Plants ────────────────────────────────────────────────────────


@router.post("/judging/events/{event_id}/plants", response_model=PlantOut)
def create_plant(event_id: str, data: PlantCreate, db: Session = DB_DEPENDENCY):
    event = db.get(JudgingEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Judging event not found")
    _ensure_show_unlocked(db, event.show_id)

    exhibitor = db.get(Exhibitor, data.exhibitor_id)
    if not exhibitor:
        raise HTTPException(status_code=404, detail="Exhibitor not found")

    cat = db.get(PlantCategory, data.category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    if cat.judging_event_id != event_id:
        raise HTTPException(
            status_code=409, detail="Category does not belong to this judging event"
        )

    plant_id = str(uuid.uuid4())
    plant = Plant(
        id=plant_id,
        exhibitor_id=data.exhibitor_id,
        judging_event_id=event_id,
        category_id=data.category_id,
        name=data.name,
        notes=data.notes,
        qr_code=_generate_qr_code(plant_id),
    )
    db.add(plant)
    db.commit()
    db.refresh(plant)
    return plant


@router.get("/judging/events/{event_id}/plants", response_model=list[PlantOut])
def list_plants(
    event_id: str, category_id: str | None = Query(None), db: Session = DB_DEPENDENCY
):
    q = select(Plant).where(Plant.judging_event_id == event_id)
    if category_id:
        q = q.where(Plant.category_id == category_id)
    return db.execute(q).scalars().all()


@router.get("/judging/plants/{plant_id}", response_model=PlantOut)
def get_plant(plant_id: str, db: Session = DB_DEPENDENCY):
    plant = db.get(Plant, plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")
    return plant


# ── Scores (per-criterion) ───────────────────────────────────────


@router.post(
    "/judging/plants/{plant_id}/scores/{judge_id}", response_model=list[ScoreOut]
)
def submit_scores(
    plant_id: str, judge_id: str, data: ScoreBatchCreate, db: Session = DB_DEPENDENCY
):
    plant = db.get(Plant, plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")

    judge = db.get(Judge, judge_id)
    if not judge:
        raise HTTPException(status_code=404, detail="Judge not found")

    event = db.get(JudgingEvent, plant.judging_event_id)
    if event and event.status == "closed":
        raise HTTPException(
            status_code=409, detail="Judging event is closed. Edits are frozen."
        )
    _ensure_show_unlocked(db, event.show_id if event else None)

    results = []
    for sc in data.scores:
        _get_scorable_criterion(db, sc.criterion_id, sc.value)

        existing = db.execute(
            select(Score).where(
                Score.plant_id == plant_id,
                Score.judge_id == judge_id,
                Score.criterion_id == sc.criterion_id,
            )
        ).scalar_one_or_none()

        if existing:
            existing.value = sc.value
            existing.choice = sc.choice
            results.append(existing)
        else:
            score = Score(
                plant_id=plant_id,
                judge_id=judge_id,
                criterion_id=sc.criterion_id,
                value=sc.value,
                choice=sc.choice,
            )
            db.add(score)
            results.append(score)

    db.commit()
    for r in results:
        db.refresh(r)
    return results


@router.get("/judging/plants/{plant_id}/scores", response_model=list[ScoreOut])
def get_plant_scores(
    plant_id: str, judge_id: str | None = Query(None), db: Session = DB_DEPENDENCY
):
    q = select(Score).where(Score.plant_id == plant_id)
    if judge_id:
        q = q.where(Score.judge_id == judge_id)
    return db.execute(q).scalars().all()


# ── Results / Leaderboard ────────────────────────────────────────


@router.get("/judging/events/{event_id}/results")
def get_event_results(event_id: str, db: Session = DB_DEPENDENCY):
    event = db.get(JudgingEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Judging event not found")

    plants = (
        db.execute(select(Plant).where(Plant.judging_event_id == event_id))
        .scalars()
        .all()
    )

    results = []
    for plant in plants:
        scores = (
            db.execute(select(Score).where(Score.plant_id == plant.id)).scalars().all()
        )

        if not scores:
            continue

        judge_ids = {s.judge_id for s in scores}
        total_by_judge = {}
        for s in scores:
            total_by_judge.setdefault(s.judge_id, 0)
            if s.value is not None:
                criterion = db.execute(
                    select(JudgingCriterion).where(
                        JudgingCriterion.criteria_id == s.criterion_id
                    )
                ).scalar_one_or_none()
                weight = (
                    criterion.weighting if criterion and criterion.weighting else 1.0
                )
                total_by_judge[s.judge_id] += s.value * weight

        avg_total = (
            sum(total_by_judge.values()) / len(total_by_judge) if total_by_judge else 0
        )

        category = db.get(PlantCategory, plant.category_id)

        results.append(
            {
                "plant_id": plant.id,
                "plant_name": plant.name,
                # Same rule as the scan, tag and class-results routes: blind
                # judging withholds who grew the plant.
                "exhibitor_name": _exhibitor_name(db, event, plant.exhibitor_id),
                "category_name": category.name if category else None,
                "avg_weighted_score": round(avg_total, 2),
                "num_judges": len(judge_ids),
                "scores_by_judge": {
                    jid: round(total_by_judge.get(jid, 0), 2) for jid in judge_ids
                },
            }
        )

    results.sort(key=lambda r: r["avg_weighted_score"], reverse=True)

    return {
        "event_id": event_id,
        "event_name": event.name,
        "status": event.status,
        "results": results,
    }


# ── Judges (existing + updated) ─────────────────────────────────


@router.post("/judges", response_model=JudgeOut)
def create_judge(data: JudgeCreate, db: Session = DB_DEPENDENCY):
    show = db.get(Show, data.show_id)
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    _ensure_show_unlocked(db, data.show_id)

    judge = Judge(
        show_id=data.show_id,
        name=data.name,
        email=data.email,
        role=data.role,
    )
    db.add(judge)
    db.commit()
    db.refresh(judge)
    return judge


@router.get("/judges", response_model=list[JudgeOut])
def list_judges(
    show_id: str = Query(..., description="Show ID"),
    db: Session = DB_DEPENDENCY,
):
    judges = db.execute(select(Judge).where(Judge.show_id == show_id)).scalars().all()
    return judges


# ── Score Submissions (legacy/simple) ────────────────────────────


@router.post("/score-submissions", response_model=ScoreSubmissionOut)
def create_score_submission(data: ScoreSubmissionCreate, db: Session = DB_DEPENDENCY):
    show = db.get(Show, data.show_id)
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")

    if getattr(show, "judging_locked", False):
        raise HTTPException(status_code=409, detail="Judging is locked for this show.")

    entry = db.get(Entry, data.entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    if entry.show_id != data.show_id:
        raise HTTPException(
            status_code=409, detail="Entry does not belong to this show."
        )

    judge = db.get(Judge, data.judge_id)
    if not judge:
        raise HTTPException(status_code=404, detail="Judge not found")

    if judge.show_id != data.show_id:
        raise HTTPException(
            status_code=409, detail="Judge is not registered for this show."
        )

    existing = db.execute(
        select(ScoreSubmission).where(
            ScoreSubmission.show_id == data.show_id,
            ScoreSubmission.entry_id == data.entry_id,
            ScoreSubmission.judge_id == data.judge_id,
        )
    ).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Score already submitted for this judge and entry.",
        )

    breakdown_json = (
        json.dumps(data.points_breakdown) if data.points_breakdown else None
    )

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
        raise HTTPException(
            status_code=409,
            detail="Duplicate score submission (already exists).",
        )

    db.refresh(submission)
    return _score_to_out(submission)


@router.get("/entries/{entry_id}/scores", response_model=list[ScoreSubmissionOut])
def get_entry_scores(entry_id: str, db: Session = DB_DEPENDENCY):
    entry = db.get(Entry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    scores = (
        db.execute(select(ScoreSubmission).where(ScoreSubmission.entry_id == entry_id))
        .scalars()
        .all()
    )

    return [_score_to_out(s) for s in scores]


@router.get("/shows/{show_id}/leaderboard")
def show_leaderboard(show_id: str, db: Session = DB_DEPENDENCY):
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
        entries.append(
            {
                "entry_id": row.entry_id,
                "exhibitor_name": entry.exhibitor_name if entry else None,
                "plant_name": entry.plant_name if entry else None,
                "avg_score": round(float(row.avg_score), 2),
                "total_score": int(row.total_score),
                "num_scores": row.num_scores,
            }
        )

    return {"show_id": show_id, "leaderboard": entries}


# ── Judging Widget (plug-in stubs) ─────────────────────────────────


@router.get("/judging/criteria")
def get_judging_criteria(show_id: str = Query(None), db: Session = DB_DEPENDENCY):
    return {
        "criteria": [
            {"name": "form", "max_points": 35, "description": "Overall form and shape"},
            {
                "name": "color",
                "max_points": 35,
                "description": "Color quality and intensity",
            },
            {
                "name": "size",
                "max_points": 30,
                "description": "Size relative to species norms",
            },
        ],
        "total_max_points": 100,
        "note": "Default AOS-style criteria. Configurable per show in future release.",
    }


@router.post("/judging/evaluate")
def evaluate_entry(body: dict, db: Session = DB_DEPENDENCY):
    entry_id = body.get("entry_id")
    judge_id = body.get("judge_id")
    scores = body.get("scores", {})

    if not entry_id or not judge_id:
        raise HTTPException(
            status_code=422, detail="entry_id and judge_id are required"
        )

    total = sum(int(v) for v in scores.values() if isinstance(v, (int, float)))

    return {
        "entry_id": entry_id,
        "judge_id": judge_id,
        "scores": scores,
        "total_points": total,
        "status": "evaluated",
        "note": "Preview only. Call POST /judging/submit to persist.",
    }


@router.post("/judging/submit")
def submit_judging(body: dict, db: Session = DB_DEPENDENCY):
    show_id = body.get("show_id")
    entry_id = body.get("entry_id")
    judge_id = body.get("judge_id")
    scores = body.get("scores", {})

    if not show_id or not entry_id or not judge_id:
        raise HTTPException(
            status_code=422, detail="show_id, entry_id, and judge_id are required"
        )

    total = sum(int(v) for v in scores.values() if isinstance(v, (int, float)))

    data = ScoreSubmissionCreate(
        show_id=show_id,
        entry_id=entry_id,
        judge_id=judge_id,
        total_points=total,
        points_breakdown=scores if scores else None,
        notes=body.get("notes"),
    )
    return create_score_submission(data, db)


# ── Judge Assignments (admin) ─────────────────────────────────────


@router.post(
    "/judging/events/{event_id}/assignments", response_model=JudgeAssignmentOut
)
def create_judge_assignment(
    event_id: str, data: JudgeAssignmentCreate, db: Session = DB_DEPENDENCY
):
    event = db.get(JudgingEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Judging event not found")
    _ensure_show_unlocked(db, event.show_id)

    judge = db.get(Judge, data.judge_id)
    if not judge:
        raise HTTPException(status_code=404, detail="Judge not found")
    if judge.show_id != event.show_id:
        raise HTTPException(
            status_code=422, detail="Judge is not registered for this event's show."
        )

    if data.category_id:
        cat = db.get(PlantCategory, data.category_id)
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found")
        if cat.judging_event_id != event_id:
            raise HTTPException(
                status_code=422,
                detail="Category does not belong to this judging event.",
            )

    assignment = JudgeAssignment(
        judging_event_id=event_id,
        judge_id=data.judge_id,
        category_id=data.category_id,
        active=data.active if data.active is not None else True,
    )
    db.add(assignment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Judge already assigned to this event/category combination.",
        )
    db.refresh(assignment)
    return assignment


@router.get(
    "/judging/events/{event_id}/assignments", response_model=list[JudgeAssignmentOut]
)
def list_judge_assignments(event_id: str, db: Session = DB_DEPENDENCY):
    rows = (
        db.execute(
            select(JudgeAssignment).where(JudgeAssignment.judging_event_id == event_id)
        )
        .scalars()
        .all()
    )
    return rows


# ── Admin: Generate Scorecards ────────────────────────────────────


@router.post(
    "/admin/judging_events/{event_id}/generate_scorecards",
    response_model=list[ScorecardOut],
)
def generate_scorecards(event_id: str, db: Session = DB_DEPENDENCY):
    event = db.get(JudgingEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Judging event not found")
    _ensure_show_unlocked(db, event.show_id)

    assignments = (
        db.execute(
            select(JudgeAssignment).where(
                JudgeAssignment.judging_event_id == event_id,
                JudgeAssignment.active == True,
            )
        )
        .scalars()
        .all()
    )

    if not assignments:
        raise HTTPException(
            status_code=409, detail="No active judge assignments for this event."
        )

    plants = (
        db.execute(select(Plant).where(Plant.judging_event_id == event_id))
        .scalars()
        .all()
    )

    if not plants:
        raise HTTPException(
            status_code=409, detail="No plants registered for this event."
        )

    created = []
    for assignment in assignments:
        relevant_plants = plants
        if assignment.category_id:
            relevant_plants = [
                p for p in plants if p.category_id == assignment.category_id
            ]

        for plant in relevant_plants:
            existing = db.execute(
                select(Scorecard).where(
                    Scorecard.judging_event_id == event_id,
                    Scorecard.plant_id == plant.id,
                    Scorecard.judge_id == assignment.judge_id,
                )
            ).scalar_one_or_none()

            if existing:
                continue

            sc = Scorecard(
                judging_event_id=event_id,
                plant_id=plant.id,
                judge_id=assignment.judge_id,
                status="draft",
            )
            db.add(sc)
            created.append(sc)

    db.commit()
    for sc in created:
        db.refresh(sc)

    return created


# ── Owner judge tooling (X-Judge-Id) ──────────────────────────────
#
# These ``/api/judge/*`` routes sit behind the router-level ``verify_api_key``,
# so only a holder of the owner key reaches them, and ``X-Judge-Id`` names the
# judge the OWNER is acting for (admin correction, rehearsal tooling). They are
# not a judge credential and are never served to a judge device: judges use
# ``/api/judge-portal/*`` with their own bearer token (app/judge_auth.py),
# where the judge is taken from the verified token and X-Judge-Id is ignored.


def _verify_judge_exists(judge_id: str, db: Session) -> Judge:
    judge = db.get(Judge, judge_id)
    if not judge:
        raise HTTPException(
            status_code=404,
            detail="Judge not found. Ensure X-Judge-Id is a valid judge ID.",
        )
    return judge


@router.get("/judge/me", response_model=JudgeOut)
def judge_me(judge_id: str = JUDGE_DEPENDENCY, db: Session = DB_DEPENDENCY):
    return _verify_judge_exists(judge_id, db)


@router.get("/judge/events", response_model=list[JudgingEventOut])
def judge_events(judge_id: str = JUDGE_DEPENDENCY, db: Session = DB_DEPENDENCY):
    _verify_judge_exists(judge_id, db)

    event_ids_q = (
        select(JudgeAssignment.judging_event_id)
        .where(
            JudgeAssignment.judge_id == judge_id,
            JudgeAssignment.active == True,
        )
        .distinct()
    )

    events = (
        db.execute(select(JudgingEvent).where(JudgingEvent.id.in_(event_ids_q)))
        .scalars()
        .all()
    )
    return events


@router.get(
    "/judge/events/{judging_event_id}/scorecards", response_model=list[ScorecardOut]
)
def judge_event_scorecards(
    judging_event_id: str,
    judge_id: str = JUDGE_DEPENDENCY,
    db: Session = DB_DEPENDENCY,
):
    _verify_judge_exists(judge_id, db)

    scorecards = (
        db.execute(
            select(Scorecard).where(
                Scorecard.judging_event_id == judging_event_id,
                Scorecard.judge_id == judge_id,
            )
        )
        .scalars()
        .all()
    )
    return scorecards


@router.get("/judge/scorecards/{scorecard_id}", response_model=ScorecardOut)
def judge_get_scorecard(
    scorecard_id: str,
    judge_id: str = JUDGE_DEPENDENCY,
    db: Session = DB_DEPENDENCY,
):
    _verify_judge_exists(judge_id, db)
    scorecard = db.get(Scorecard, scorecard_id)
    if not scorecard:
        raise HTTPException(status_code=404, detail="Scorecard not found")
    if scorecard.judge_id != judge_id:
        raise HTTPException(
            status_code=403, detail="Access denied: scorecard belongs to another judge."
        )
    return scorecard


def apply_scorecard_autosave(
    db: Session, scorecard: Scorecard, judge_id: str, data: ScorecardSaveRequest
) -> Scorecard:
    """Save a judge's draft scores on ``scorecard``; the caller checked ownership.

    Shared by the owner's ``/api/judge/*`` tooling and the per-judge
    credential routes in ``app/routers/judge_portal.py`` so the two cannot
    drift: submitted cards, closed events and locked shows refuse (409).
    """
    if scorecard.status == "submitted":
        raise HTTPException(
            status_code=409, detail="Scorecard already submitted. Cannot edit."
        )

    event = db.get(JudgingEvent, scorecard.judging_event_id)
    if event and event.status == "closed":
        raise HTTPException(
            status_code=409, detail="Judging event is closed. Edits are frozen."
        )
    _ensure_show_unlocked(db, event.show_id if event else None)

    changed_scores = []
    for item in data.scores:
        _get_scorable_criterion(db, item.criterion_id, item.value)
        existing = db.execute(
            select(Score).where(
                Score.plant_id == scorecard.plant_id,
                Score.judge_id == judge_id,
                Score.criterion_id == item.criterion_id,
            )
        ).scalar_one_or_none()

        if existing:
            old_val = {
                "value": existing.value,
                "choice": existing.choice,
                "value_rank": existing.value_rank,
            }
            existing.value = item.value
            existing.choice = item.choice
            existing.value_rank = item.value_rank
            new_val = {
                "value": item.value,
                "choice": item.choice,
                "value_rank": item.value_rank,
            }
            if old_val != new_val:
                changed_scores.append(
                    {"criterion_id": item.criterion_id, "old": old_val, "new": new_val}
                )
        else:
            score = Score(
                plant_id=scorecard.plant_id,
                judge_id=judge_id,
                criterion_id=item.criterion_id,
                value=item.value,
                choice=item.choice,
                value_rank=item.value_rank,
            )
            db.add(score)
            changed_scores.append(
                {
                    "criterion_id": item.criterion_id,
                    "old": None,
                    "new": {
                        "value": item.value,
                        "choice": item.choice,
                        "value_rank": item.value_rank,
                    },
                }
            )

    scorecard.status = "draft"
    scorecard.updated_at = _utcnow()

    audit = ScorecardAuditLog(
        scorecard_id=scorecard.id,
        actor_judge_id=judge_id,
        action="autosave",
        diff_json=json.dumps({"scores": changed_scores, "notes": data.notes})
        if changed_scores
        else None,
    )
    db.add(audit)

    db.commit()
    db.refresh(scorecard)
    return scorecard


@router.put("/judge/scorecards/{scorecard_id}", response_model=ScorecardOut)
def judge_autosave_scorecard(
    scorecard_id: str,
    data: ScorecardSaveRequest,
    judge_id: str = JUDGE_DEPENDENCY,
    db: Session = DB_DEPENDENCY,
):
    _verify_judge_exists(judge_id, db)

    scorecard = db.get(Scorecard, scorecard_id)
    if not scorecard:
        raise HTTPException(status_code=404, detail="Scorecard not found")
    if scorecard.judge_id != judge_id:
        raise HTTPException(
            status_code=403, detail="Access denied: scorecard belongs to another judge."
        )
    return apply_scorecard_autosave(db, scorecard, judge_id, data)


def apply_scorecard_submit(
    db: Session, scorecard: Scorecard, judge_id: str, data: ScorecardSubmitRequest
) -> Scorecard:
    """Submit ``scorecard`` with its weighted total; the caller checked ownership."""
    if scorecard.status == "submitted":
        raise HTTPException(status_code=409, detail="Scorecard already submitted.")

    event = db.get(JudgingEvent, scorecard.judging_event_id)
    if event and event.status == "closed":
        raise HTTPException(status_code=409, detail="Judging event is closed.")
    _ensure_show_unlocked(db, event.show_id if event else None)

    all_scores = (
        db.execute(
            select(Score).where(
                Score.plant_id == scorecard.plant_id,
                Score.judge_id == judge_id,
            )
        )
        .scalars()
        .all()
    )

    total = 0.0
    for s in all_scores:
        if s.value is not None:
            criterion = db.execute(
                select(JudgingCriterion).where(
                    JudgingCriterion.criteria_id == s.criterion_id
                )
            ).scalar_one_or_none()
            weight = criterion.weighting if criterion and criterion.weighting else 1.0
            total += float(s.value) * float(weight)

    now = _utcnow()
    scorecard.status = "submitted"
    scorecard.submitted_at = now
    scorecard.total = round(total, 2)
    scorecard.version = (scorecard.version or 1) + 1 if scorecard.version else 1
    scorecard.updated_at = now

    audit = ScorecardAuditLog(
        scorecard_id=scorecard.id,
        actor_judge_id=judge_id,
        action="submit",
        diff_json=json.dumps(
            {"final_comment": data.final_comment, "total": round(total, 2)}
        )
        if data.final_comment
        else None,
    )
    db.add(audit)

    db.commit()
    db.refresh(scorecard)
    return scorecard


@router.post("/judge/scorecards/{scorecard_id}/submit", response_model=ScorecardOut)
def judge_submit_scorecard(
    scorecard_id: str,
    data: ScorecardSubmitRequest,
    judge_id: str = JUDGE_DEPENDENCY,
    db: Session = DB_DEPENDENCY,
):
    _verify_judge_exists(judge_id, db)

    scorecard = db.get(Scorecard, scorecard_id)
    if not scorecard:
        raise HTTPException(status_code=404, detail="Scorecard not found")
    if scorecard.judge_id != judge_id:
        raise HTTPException(
            status_code=403, detail="Access denied: scorecard belongs to another judge."
        )
    return apply_scorecard_submit(db, scorecard, judge_id, data)


@router.get(
    "/judge/scorecards/{scorecard_id}/audit", response_model=list[ScorecardAuditOut]
)
def judge_scorecard_audit(
    scorecard_id: str,
    judge_id: str = JUDGE_DEPENDENCY,
    db: Session = DB_DEPENDENCY,
):
    _verify_judge_exists(judge_id, db)
    scorecard = db.get(Scorecard, scorecard_id)
    if not scorecard:
        raise HTTPException(status_code=404, detail="Scorecard not found")
    if scorecard.judge_id != judge_id:
        raise HTTPException(
            status_code=403, detail="Access denied: scorecard belongs to another judge."
        )

    logs = (
        db.execute(
            select(ScorecardAuditLog)
            .where(ScorecardAuditLog.scorecard_id == scorecard_id)
            .order_by(ScorecardAuditLog.created_at.desc())
        )
        .scalars()
        .all()
    )
    return logs
