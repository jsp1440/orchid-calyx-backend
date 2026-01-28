from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.deps import get_db
from app.models import Award
from app.schemas import AwardCreate, AwardUpdate, AwardOut
from app.security import verify_api_key

router = APIRouter(prefix="/api", tags=["awards"], dependencies=[Depends(verify_api_key)])


@router.post("/awards", response_model=AwardOut)
def create_award(payload: AwardCreate, db: Session = Depends(get_db)):
    award = Award(**payload.model_dump())
    db.add(award)
    db.commit()
    db.refresh(award)
    return award


@router.get("/awards", response_model=List[AwardOut])
def list_awards(entry_id: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    query = select(Award)
    if entry_id:
        query = query.where(Award.entry_id == entry_id)
    return db.execute(query).scalars().all()


@router.get("/awards/{award_id}", response_model=AwardOut)
def get_award(award_id: str, db: Session = Depends(get_db)):
    award = db.execute(select(Award).where(Award.id == award_id)).scalar_one_or_none()
    if not award:
        raise HTTPException(status_code=404, detail="Award not found")
    return award


@router.patch("/awards/{award_id}", response_model=AwardOut)
def update_award(award_id: str, payload: AwardUpdate, db: Session = Depends(get_db)):
    award = db.execute(select(Award).where(Award.id == award_id)).scalar_one_or_none()
    if not award:
        raise HTTPException(status_code=404, detail="Award not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(award, k, v)
    db.commit()
    db.refresh(award)
    return award


@router.delete("/awards/{award_id}")
def delete_award(award_id: str, db: Session = Depends(get_db)):
    award = db.execute(select(Award).where(Award.id == award_id)).scalar_one_or_none()
    if not award:
        raise HTTPException(status_code=404, detail="Award not found")
    db.delete(award)
    db.commit()
    return {"status": "deleted"}
