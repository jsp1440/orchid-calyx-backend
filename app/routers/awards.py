from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Award, Entry
from app.schemas import AwardCreate, AwardOut, AwardUpdate
from app.security import verify_api_key
from app.show_lock import ensure_show_unlocked

DbSession = Annotated[Session, Depends(get_db)]

router = APIRouter(
    prefix="/api", tags=["awards"], dependencies=[Depends(verify_api_key)]
)


def _ensure_entry_show_unlocked(db: Session, entry_id: str) -> None:
    """An award belongs to an entry, and the entry to a show."""
    entry = db.get(Entry, entry_id)
    ensure_show_unlocked(db, entry.show_id if entry else None)


@router.post("/awards", response_model=AwardOut)
def create_award(payload: AwardCreate, db: DbSession):
    _ensure_entry_show_unlocked(db, payload.entry_id)
    award = Award(**payload.model_dump())
    db.add(award)
    db.commit()
    db.refresh(award)
    return award


@router.get("/awards", response_model=list[AwardOut])
def list_awards(db: DbSession, entry_id: str | None = Query(default=None)):
    query = select(Award)
    if entry_id:
        query = query.where(Award.entry_id == entry_id)
    return db.execute(query).scalars().all()


@router.get("/awards/{award_id}", response_model=AwardOut)
def get_award(award_id: str, db: DbSession):
    award = db.execute(select(Award).where(Award.id == award_id)).scalar_one_or_none()
    if not award:
        raise HTTPException(status_code=404, detail="Award not found")
    return award


@router.patch("/awards/{award_id}", response_model=AwardOut)
def update_award(award_id: str, payload: AwardUpdate, db: DbSession):
    award = db.execute(select(Award).where(Award.id == award_id)).scalar_one_or_none()
    if not award:
        raise HTTPException(status_code=404, detail="Award not found")
    _ensure_entry_show_unlocked(db, award.entry_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(award, k, v)
    db.commit()
    db.refresh(award)
    return award


@router.delete("/awards/{award_id}")
def delete_award(award_id: str, db: DbSession):
    award = db.execute(select(Award).where(Award.id == award_id)).scalar_one_or_none()
    if not award:
        raise HTTPException(status_code=404, detail="Award not found")
    _ensure_entry_show_unlocked(db, award.entry_id)
    db.delete(award)
    db.commit()
    return {"status": "deleted"}
