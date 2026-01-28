from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.database import get_db
from app.security import require_admin
from app.models.orchid_judge_show import Show
from app.models.show_ops import (
    ShowZone,
    Vendor,
    TrainingAsset,
    VolunteerRole,
    VolunteerShift,
    VolunteerSignup,
)

router = APIRouter(tags=["show-ops-volunteers"])


def get_show(db: Session, show_id: str) -> Show:
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found.")
    return show


# ─────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────
class ZoneCreate(BaseModel):
    zone_type: str
    name: str
    notes: Optional[str] = None
    capacity_hint: Optional[int] = None


class ZoneUpdate(BaseModel):
    zone_type: Optional[str] = None
    name: Optional[str] = None
    notes: Optional[str] = None
    capacity_hint: Optional[int] = None


class ZoneOut(ZoneCreate):
    id: str
    show_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class VendorCreate(BaseModel):
    vendor_type: str = Field(default="PLANT", pattern="^(PLANT|FOOD|OTHER)$")
    name: str
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    zone_id: Optional[str] = None
    setup_notes: Optional[str] = None


class VendorUpdate(BaseModel):
    vendor_type: Optional[str] = Field(default=None, pattern="^(PLANT|FOOD|OTHER)$")
    name: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    zone_id: Optional[str] = None
    setup_notes: Optional[str] = None


class VendorOut(VendorCreate):
    id: str
    show_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class TrainingAssetCreate(BaseModel):
    asset_type: str = Field(pattern="^(PDF|LINK|VIDEO|TEXT)$")
    title: str
    content_text: Optional[str] = None
    url: Optional[str] = None
    file_url: Optional[str] = None
    tags: Optional[str] = None


class TrainingAssetUpdate(BaseModel):
    asset_type: Optional[str] = Field(default=None, pattern="^(PDF|LINK|VIDEO|TEXT)$")
    title: Optional[str] = None
    content_text: Optional[str] = None
    url: Optional[str] = None
    file_url: Optional[str] = None
    tags: Optional[str] = None


class TrainingAssetOut(TrainingAssetCreate):
    id: str
    show_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class VolunteerRoleCreate(BaseModel):
    role_key: str
    display_name: str
    description: Optional[str] = None
    default_zone_type: Optional[str] = None
    requires_training: bool = False
    training_asset_id: Optional[str] = None
    min_people_per_shift: Optional[int] = None


class VolunteerRoleUpdate(BaseModel):
    role_key: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    default_zone_type: Optional[str] = None
    requires_training: Optional[bool] = None
    training_asset_id: Optional[str] = None
    min_people_per_shift: Optional[int] = None


class VolunteerRoleOut(VolunteerRoleCreate):
    id: str
    show_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class ShiftCreate(BaseModel):
    role_id: str
    zone_id: Optional[str] = None
    start_time: datetime
    end_time: datetime
    capacity: int = 1
    notes: Optional[str] = None


class ShiftUpdate(BaseModel):
    role_id: Optional[str] = None
    zone_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    capacity: Optional[int] = None
    notes: Optional[str] = None


class ShiftOut(ShiftCreate):
    id: str
    show_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class PublicSignupIn(BaseModel):
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None


class SignupOut(BaseModel):
    id: str
    shift_id: str
    full_name: str
    email: Optional[str]
    phone: Optional[str]
    status: str
    checked_in_at: Optional[datetime]
    checked_out_at: Optional[datetime]
    checkin_method: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class CheckinOutIn(BaseModel):
    status: str = Field(pattern="^(CHECKED_IN|CHECKED_OUT|NO_SHOW|CANCELLED)$")
    method: str = Field(default="MANUAL", pattern="^(QR|CODE|MANUAL)$")


# ─────────────────────────────────────────────
# Zones
# ─────────────────────────────────────────────
@router.post("/shows/{show_id}/zones", response_model=ZoneOut, dependencies=[Depends(require_admin)])
def create_zone(show_id: str, payload: ZoneCreate, db: Session = Depends(get_db)):
    get_show(db, show_id)
    z = ShowZone(show_id=show_id, **payload.model_dump())
    db.add(z)
    db.commit()
    db.refresh(z)
    return z


@router.get("/shows/{show_id}/zones", response_model=List[ZoneOut])
def list_zones(show_id: str, db: Session = Depends(get_db)):
    get_show(db, show_id)
    return db.execute(select(ShowZone).where(ShowZone.show_id == show_id)).scalars().all()


@router.patch("/shows/{show_id}/zones/{zone_id}", response_model=ZoneOut, dependencies=[Depends(require_admin)])
def update_zone(show_id: str, zone_id: str, payload: ZoneUpdate, db: Session = Depends(get_db)):
    get_show(db, show_id)
    z = db.execute(select(ShowZone).where(ShowZone.id == zone_id, ShowZone.show_id == show_id)).scalar_one_or_none()
    if not z:
        raise HTTPException(status_code=404, detail="Zone not found.")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(z, k, v)
    db.commit()
    db.refresh(z)
    return z


@router.delete("/shows/{show_id}/zones/{zone_id}", dependencies=[Depends(require_admin)])
def delete_zone(show_id: str, zone_id: str, db: Session = Depends(get_db)):
    get_show(db, show_id)
    z = db.execute(select(ShowZone).where(ShowZone.id == zone_id, ShowZone.show_id == show_id)).scalar_one_or_none()
    if not z:
        raise HTTPException(status_code=404, detail="Zone not found.")
    db.delete(z)
    db.commit()
    return {"status": "deleted"}


# ─────────────────────────────────────────────
# Vendors (no payments)
# ─────────────────────────────────────────────
@router.post("/shows/{show_id}/vendors", response_model=VendorOut, dependencies=[Depends(require_admin)])
def create_vendor(show_id: str, payload: VendorCreate, db: Session = Depends(get_db)):
    get_show(db, show_id)
    v = Vendor(show_id=show_id, **payload.model_dump())
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


@router.get("/shows/{show_id}/vendors", response_model=List[VendorOut])
def list_vendors(show_id: str, db: Session = Depends(get_db)):
    get_show(db, show_id)
    return db.execute(select(Vendor).where(Vendor.show_id == show_id)).scalars().all()


@router.patch("/shows/{show_id}/vendors/{vendor_id}", response_model=VendorOut, dependencies=[Depends(require_admin)])
def update_vendor(show_id: str, vendor_id: str, payload: VendorUpdate, db: Session = Depends(get_db)):
    get_show(db, show_id)
    v = db.execute(select(Vendor).where(Vendor.id == vendor_id, Vendor.show_id == show_id)).scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found.")
    for k, val in payload.model_dump(exclude_unset=True).items():
        setattr(v, k, val)
    db.commit()
    db.refresh(v)
    return v


@router.delete("/shows/{show_id}/vendors/{vendor_id}", dependencies=[Depends(require_admin)])
def delete_vendor(show_id: str, vendor_id: str, db: Session = Depends(get_db)):
    get_show(db, show_id)
    v = db.execute(select(Vendor).where(Vendor.id == vendor_id, Vendor.show_id == show_id)).scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found.")
    db.delete(v)
    db.commit()
    return {"status": "deleted"}


# ─────────────────────────────────────────────
# Training assets
# ─────────────────────────────────────────────
@router.post("/shows/{show_id}/training-assets", response_model=TrainingAssetOut, dependencies=[Depends(require_admin)])
def create_training_asset(show_id: str, payload: TrainingAssetCreate, db: Session = Depends(get_db)):
    get_show(db, show_id)
    a = TrainingAsset(show_id=show_id, **payload.model_dump())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.get("/shows/{show_id}/training-assets", response_model=List[TrainingAssetOut])
def list_training_assets(show_id: str, db: Session = Depends(get_db)):
    get_show(db, show_id)
    return db.execute(select(TrainingAsset).where(TrainingAsset.show_id == show_id)).scalars().all()


@router.patch("/shows/{show_id}/training-assets/{asset_id}", response_model=TrainingAssetOut, dependencies=[Depends(require_admin)])
def update_training_asset(show_id: str, asset_id: str, payload: TrainingAssetUpdate, db: Session = Depends(get_db)):
    get_show(db, show_id)
    a = db.execute(select(TrainingAsset).where(TrainingAsset.id == asset_id, TrainingAsset.show_id == show_id)).scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Training asset not found.")
    for k, val in payload.model_dump(exclude_unset=True).items():
        setattr(a, k, val)
    db.commit()
    db.refresh(a)
    return a


@router.delete("/shows/{show_id}/training-assets/{asset_id}", dependencies=[Depends(require_admin)])
def delete_training_asset(show_id: str, asset_id: str, db: Session = Depends(get_db)):
    get_show(db, show_id)
    a = db.execute(select(TrainingAsset).where(TrainingAsset.id == asset_id, TrainingAsset.show_id == show_id)).scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Training asset not found.")
    db.delete(a)
    db.commit()
    return {"status": "deleted"}


# ─────────────────────────────────────────────
# Volunteer roles
# ─────────────────────────────────────────────
@router.post("/shows/{show_id}/volunteer-roles", response_model=VolunteerRoleOut, dependencies=[Depends(require_admin)])
def create_volunteer_role(show_id: str, payload: VolunteerRoleCreate, db: Session = Depends(get_db)):
    get_show(db, show_id)
    # DB constraint exists in fresh installs; keep a friendly error in v1.
    existing = db.execute(
        select(VolunteerRole).where(VolunteerRole.show_id == show_id, VolunteerRole.role_key == payload.role_key)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="role_key already exists for this show.")
    r = VolunteerRole(show_id=show_id, **payload.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@router.get("/shows/{show_id}/volunteer-roles", response_model=List[VolunteerRoleOut])
def list_volunteer_roles(show_id: str, db: Session = Depends(get_db)):
    get_show(db, show_id)
    return db.execute(select(VolunteerRole).where(VolunteerRole.show_id == show_id)).scalars().all()


@router.patch("/shows/{show_id}/volunteer-roles/{role_id}", response_model=VolunteerRoleOut, dependencies=[Depends(require_admin)])
def update_volunteer_role(show_id: str, role_id: str, payload: VolunteerRoleUpdate, db: Session = Depends(get_db)):
    get_show(db, show_id)
    r = db.execute(select(VolunteerRole).where(VolunteerRole.id == role_id, VolunteerRole.show_id == show_id)).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Role not found.")
    for k, val in payload.model_dump(exclude_unset=True).items():
        setattr(r, k, val)
    db.commit()
    db.refresh(r)
    return r


@router.delete("/shows/{show_id}/volunteer-roles/{role_id}", dependencies=[Depends(require_admin)])
def delete_volunteer_role(show_id: str, role_id: str, db: Session = Depends(get_db)):
    get_show(db, show_id)
    r = db.execute(select(VolunteerRole).where(VolunteerRole.id == role_id, VolunteerRole.show_id == show_id)).scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Role not found.")
    db.delete(r)
    db.commit()
    return {"status": "deleted"}


# ─────────────────────────────────────────────
# Shifts
# ─────────────────────────────────────────────
@router.post("/shows/{show_id}/volunteer-shifts", response_model=ShiftOut, dependencies=[Depends(require_admin)])
def create_shift(show_id: str, payload: ShiftCreate, db: Session = Depends(get_db)):
    get_show(db, show_id)
    role = db.execute(select(VolunteerRole).where(VolunteerRole.id == payload.role_id)).scalar_one_or_none()
    if not role or role.show_id != show_id:
        raise HTTPException(status_code=400, detail="Invalid role_id for this show.")
    s = VolunteerShift(show_id=show_id, **payload.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.get("/shows/{show_id}/volunteer-shifts", response_model=List[ShiftOut])
def list_shifts(show_id: str, db: Session = Depends(get_db)):
    get_show(db, show_id)
    return db.execute(select(VolunteerShift).where(VolunteerShift.show_id == show_id)).scalars().all()


@router.patch("/shows/{show_id}/volunteer-shifts/{shift_id}", response_model=ShiftOut, dependencies=[Depends(require_admin)])
def update_shift(show_id: str, shift_id: str, payload: ShiftUpdate, db: Session = Depends(get_db)):
    get_show(db, show_id)
    s = db.execute(select(VolunteerShift).where(VolunteerShift.id == shift_id, VolunteerShift.show_id == show_id)).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Shift not found.")

    data = payload.model_dump(exclude_unset=True)
    if "role_id" in data:
        role = db.execute(select(VolunteerRole).where(VolunteerRole.id == data["role_id"])).scalar_one_or_none()
        if not role or role.show_id != show_id:
            raise HTTPException(status_code=400, detail="Invalid role_id for this show.")
    for k, val in data.items():
        setattr(s, k, val)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/shows/{show_id}/volunteer-shifts/{shift_id}", dependencies=[Depends(require_admin)])
def delete_shift(show_id: str, shift_id: str, db: Session = Depends(get_db)):
    get_show(db, show_id)
    s = db.execute(select(VolunteerShift).where(VolunteerShift.id == shift_id, VolunteerShift.show_id == show_id)).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Shift not found.")
    db.delete(s)
    db.commit()
    return {"status": "deleted"}


# ─────────────────────────────────────────────
# Public signup (no account)
# ─────────────────────────────────────────────
@router.post("/public/shifts/{shift_id}/signup", response_model=SignupOut)
def public_signup(shift_id: str, payload: PublicSignupIn, db: Session = Depends(get_db)):
    shift = db.execute(select(VolunteerShift).where(VolunteerShift.id == shift_id)).scalar_one_or_none()
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found.")

    current = db.execute(
        select(VolunteerSignup).where(
            VolunteerSignup.shift_id == shift_id,
            VolunteerSignup.status.in_(["SIGNED_UP", "CHECKED_IN", "CHECKED_OUT"])
        )
    ).scalars().all()

    if len(current) >= shift.capacity:
        raise HTTPException(status_code=409, detail="Shift is full.")

    signup = VolunteerSignup(
        shift_id=shift_id,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        status="SIGNED_UP",
    )
    db.add(signup)
    db.commit()
    db.refresh(signup)
    return signup


# ─────────────────────────────────────────────
# Admin roster + check-in/out
# ─────────────────────────────────────────────
@router.get("/shows/{show_id}/roster", response_model=List[SignupOut], dependencies=[Depends(require_admin)])
def show_roster(show_id: str, db: Session = Depends(get_db)):
    get_show(db, show_id)
    shifts = db.execute(select(VolunteerShift).where(VolunteerShift.show_id == show_id)).scalars().all()
    shift_ids = [s.id for s in shifts]
    if not shift_ids:
        return []
    return db.execute(select(VolunteerSignup).where(VolunteerSignup.shift_id.in_(shift_ids))).scalars().all()


@router.patch("/signups/{signup_id}/status", response_model=SignupOut, dependencies=[Depends(require_admin)])
def set_signup_status(signup_id: str, payload: CheckinOutIn, db: Session = Depends(get_db)):
    s = db.execute(select(VolunteerSignup).where(VolunteerSignup.id == signup_id)).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Signup not found.")

    now = datetime.utcnow()
    if payload.status == "CHECKED_IN":
        s.status = "CHECKED_IN"
        s.checked_in_at = now
        s.checkin_method = payload.method
    elif payload.status == "CHECKED_OUT":
        s.status = "CHECKED_OUT"
        s.checked_out_at = now
        if not s.checkin_method:
            s.checkin_method = payload.method
    else:
        s.status = payload.status

    db.commit()
    db.refresh(s)
    return s
