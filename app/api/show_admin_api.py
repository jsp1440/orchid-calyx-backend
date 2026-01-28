from __future__ import annotations

from datetime import date, datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database import get_db
from app.security import require_admin
from app.models.orchid_judge_show import Organization, Show

router = APIRouter(tags=["orgs-shows-admin"])


class OrgCreate(BaseModel):
    name: str
    slug: str = Field(min_length=2, max_length=60, pattern="^[a-z0-9-]+$")
    country_code: Optional[str] = Field(default="US", max_length=3)
    website_url: Optional[str] = None


class OrgUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = Field(default=None, min_length=2, max_length=60, pattern="^[a-z0-9-]+$")
    country_code: Optional[str] = Field(default=None, max_length=3)
    website_url: Optional[str] = None


class OrgOut(OrgCreate):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True


class ShowCreate(BaseModel):
    name: str
    start_date: date
    end_date: date
    timezone: str = "America/Los_Angeles"
    venue_name: Optional[str] = None
    venue_address: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    country_code: Optional[str] = Field(default="US", max_length=3)


class ShowUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    timezone: Optional[str] = None
    venue_name: Optional[str] = None
    venue_address: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    country_code: Optional[str] = None


class ShowOut(ShowCreate):
    id: str
    organization_id: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/orgs", response_model=OrgOut, dependencies=[Depends(require_admin)])
def create_org(payload: OrgCreate, db: Session = Depends(get_db)):
    existing = db.execute(select(Organization).where(Organization.slug == payload.slug)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Organization slug already exists.")
    org = Organization(**payload.model_dump())
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@router.get("/orgs", response_model=List[OrgOut], dependencies=[Depends(require_admin)])
def list_orgs(db: Session = Depends(get_db)):
    return db.execute(select(Organization)).scalars().all()


@router.patch("/orgs/{org_id}", response_model=OrgOut, dependencies=[Depends(require_admin)])
def update_org(org_id: str, payload: OrgUpdate, db: Session = Depends(get_db)):
    org = db.execute(select(Organization).where(Organization.id == org_id)).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    data = payload.model_dump(exclude_unset=True)
    if "slug" in data and data["slug"] != org.slug:
        exists = db.execute(select(Organization).where(Organization.slug == data["slug"])).scalar_one_or_none()
        if exists:
            raise HTTPException(status_code=400, detail="Organization slug already exists.")
    for k, v in data.items():
        setattr(org, k, v)
    db.commit()
    db.refresh(org)
    return org


@router.delete("/orgs/{org_id}", dependencies=[Depends(require_admin)])
def delete_org(org_id: str, db: Session = Depends(get_db)):
    org = db.execute(select(Organization).where(Organization.id == org_id)).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    db.delete(org)
    db.commit()
    return {"status": "deleted"}


@router.post("/orgs/{org_id}/shows", response_model=ShowOut, dependencies=[Depends(require_admin)])
def create_show(org_id: str, payload: ShowCreate, db: Session = Depends(get_db)):
    org = db.execute(select(Organization).where(Organization.id == org_id)).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")
    show = Show(organization_id=org_id, **payload.model_dump())
    db.add(show)
    db.commit()
    db.refresh(show)
    return show


@router.get("/orgs/{org_id}/shows", response_model=List[ShowOut], dependencies=[Depends(require_admin)])
def list_shows(org_id: str, db: Session = Depends(get_db)):
    return db.execute(select(Show).where(Show.organization_id == org_id)).scalars().all()


@router.patch("/shows/{show_id}", response_model=ShowOut, dependencies=[Depends(require_admin)])
def update_show(show_id: str, payload: ShowUpdate, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(show, k, v)
    db.commit()
    db.refresh(show)
    return show


@router.delete("/shows/{show_id}", dependencies=[Depends(require_admin)])
def delete_show(show_id: str, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found.")
    db.delete(show)
    db.commit()
    return {"status": "deleted"}
