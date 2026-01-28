from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.deps import get_db
from app.models import VolunteerTask
from app.schemas import VolunteerTaskCreate, VolunteerTaskUpdate, VolunteerTaskOut
from app.security import verify_api_key

router = APIRouter(prefix="/api", tags=["volunteers"], dependencies=[Depends(verify_api_key)])


@router.post("/volunteer-tasks", response_model=VolunteerTaskOut)
def create_task(payload: VolunteerTaskCreate, db: Session = Depends(get_db)):
    task = VolunteerTask(**payload.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("/volunteer-tasks", response_model=List[VolunteerTaskOut])
def list_tasks(show_id: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    query = select(VolunteerTask)
    if show_id:
        query = query.where(VolunteerTask.show_id == show_id)
    return db.execute(query).scalars().all()


@router.get("/volunteer-tasks/{task_id}", response_model=VolunteerTaskOut)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.execute(select(VolunteerTask).where(VolunteerTask.id == task_id)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.patch("/volunteer-tasks/{task_id}", response_model=VolunteerTaskOut)
def update_task(task_id: str, payload: VolunteerTaskUpdate, db: Session = Depends(get_db)):
    task = db.execute(select(VolunteerTask).where(VolunteerTask.id == task_id)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(task, k, v)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/volunteer-tasks/{task_id}")
def delete_task(task_id: str, db: Session = Depends(get_db)):
    task = db.execute(select(VolunteerTask).where(VolunteerTask.id == task_id)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    return {"status": "deleted"}
