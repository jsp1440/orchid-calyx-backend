from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.deps import get_db
from app.models import Entry
from app.schemas import EntryCreate, EntryUpdate, EntryOut
from app.security import verify_api_key

router = APIRouter(prefix="/api", tags=["entries"], dependencies=[Depends(verify_api_key)])


@router.post("/entries", response_model=EntryOut)
def create_entry(payload: EntryCreate, db: Session = Depends(get_db)):
    entry = Entry(**payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/entries", response_model=List[EntryOut])
def list_entries(show_id: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    query = select(Entry)
    if show_id:
        query = query.where(Entry.show_id == show_id)
    return db.execute(query).scalars().all()


@router.get("/entries/{entry_id}", response_model=EntryOut)
def get_entry(entry_id: str, db: Session = Depends(get_db)):
    entry = db.execute(select(Entry).where(Entry.id == entry_id)).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@router.patch("/entries/{entry_id}", response_model=EntryOut)
def update_entry(entry_id: str, payload: EntryUpdate, db: Session = Depends(get_db)):
    entry = db.execute(select(Entry).where(Entry.id == entry_id)).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(entry, k, v)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, db: Session = Depends(get_db)):
    entry = db.execute(select(Entry).where(Entry.id == entry_id)).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    db.delete(entry)
    db.commit()
    return {"status": "deleted"}
