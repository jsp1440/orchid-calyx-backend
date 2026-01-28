from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


class ShowCreate(BaseModel):
    name: str
    start_date: date
    location: Optional[str] = None


class ShowUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[date] = None
    location: Optional[str] = None


class ShowOut(BaseModel):
    id: str
    name: str
    start_date: date
    location: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class EntryCreate(BaseModel):
    show_id: str
    exhibitor_name: str
    plant_name: str
    class_code: Optional[str] = None
    status: Optional[str] = "pending"


class EntryUpdate(BaseModel):
    exhibitor_name: Optional[str] = None
    plant_name: Optional[str] = None
    class_code: Optional[str] = None
    status: Optional[str] = None


class EntryOut(BaseModel):
    id: str
    show_id: str
    exhibitor_name: str
    plant_name: str
    class_code: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class VolunteerTaskCreate(BaseModel):
    show_id: str
    title: str
    assigned_to: Optional[str] = None
    status: Optional[str] = "open"


class VolunteerTaskUpdate(BaseModel):
    title: Optional[str] = None
    assigned_to: Optional[str] = None
    status: Optional[str] = None


class VolunteerTaskOut(BaseModel):
    id: str
    show_id: str
    title: str
    assigned_to: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class AwardCreate(BaseModel):
    entry_id: str
    award_name: str
    level: Optional[str] = None


class AwardUpdate(BaseModel):
    award_name: Optional[str] = None
    level: Optional[str] = None


class AwardOut(BaseModel):
    id: str
    entry_id: str
    award_name: str
    level: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
