from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Entry
from app.schemas import EntryCreate, EntryOut, EntryUpdate
from app.security import verify_api_key
from app.show_lock import ensure_show_unlocked

DbSession = Annotated[Session, Depends(get_db)]

router = APIRouter(
    prefix="/api", tags=["entries"], dependencies=[Depends(verify_api_key)]
)


@router.post("/entries", response_model=EntryOut)
def create_entry(payload: EntryCreate, db: DbSession):
    ensure_show_unlocked(db, payload.show_id)
    entry = Entry(**payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/entries", response_model=list[EntryOut])
def list_entries(db: DbSession, show_id: str | None = Query(default=None)):
    query = select(Entry)
    if show_id:
        query = query.where(Entry.show_id == show_id)
    return db.execute(query).scalars().all()


@router.get("/entries/{entry_id}", response_model=EntryOut)
def get_entry(entry_id: str, db: DbSession):
    entry = db.execute(select(Entry).where(Entry.id == entry_id)).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@router.patch("/entries/{entry_id}", response_model=EntryOut)
def update_entry(entry_id: str, payload: EntryUpdate, db: DbSession):
    entry = db.execute(select(Entry).where(Entry.id == entry_id)).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    ensure_show_unlocked(db, entry.show_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(entry, k, v)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, db: DbSession):
    entry = db.execute(select(Entry).where(Entry.id == entry_id)).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    ensure_show_unlocked(db, entry.show_id)
    db.delete(entry)
    db.commit()
    return {"status": "deleted"}
