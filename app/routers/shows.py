from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.deps import get_db
from app.models import Show
from app.schemas import ShowCreate, ShowUpdate, ShowOut
from app.security import verify_api_key

router = APIRouter(prefix="/api", tags=["shows"], dependencies=[Depends(verify_api_key)])


@router.post("/shows", response_model=ShowOut)
def create_show(payload: ShowCreate, db: Session = Depends(get_db)):
    show = Show(**payload.model_dump())
    db.add(show)
    db.commit()
    db.refresh(show)
    return show


@router.get("/shows", response_model=List[ShowOut])
def list_shows(db: Session = Depends(get_db)):
    return db.execute(select(Show)).scalars().all()


@router.get("/shows/{show_id}", response_model=ShowOut)
def get_show(show_id: str, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    return show


@router.patch("/shows/{show_id}", response_model=ShowOut)
def update_show(show_id: str, payload: ShowUpdate, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(show, k, v)
    db.commit()
    db.refresh(show)
    return show


@router.delete("/shows/{show_id}")
def delete_show(show_id: str, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    db.delete(show)
    db.commit()
    return {"status": "deleted"}
