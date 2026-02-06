from datetime import date, datetime
from typing import Optional, Any, Dict, List
from pydantic import BaseModel


class ShowCreate(BaseModel):
    name: str
    start_date: date
    location: Optional[str] = None
    organization_id: Optional[str] = None


class ShowUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[date] = None
    location: Optional[str] = None
    judging_locked: Optional[bool] = None
    public_volunteer_token: Optional[str] = None


class ShowOut(BaseModel):
    id: str
    organization_id: Optional[str] = None
    name: str
    start_date: date
    location: Optional[str]
    judging_locked: bool
    public_volunteer_token: Optional[str] = None
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


class OrganizationCreate(BaseModel):
    name: str


class OrganizationOut(BaseModel):
    id: str
    name: str
    created_at: datetime

    class Config:
        from_attributes = True


class ContactCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    contact_type: Optional[str] = None


class ContactOut(BaseModel):
    id: str
    organization_id: Optional[str]
    show_id: Optional[str]
    name: str
    email: Optional[str]
    phone: Optional[str]
    city: Optional[str]
    contact_type: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class MessageTemplateCreate(BaseModel):
    name: str
    audience: Optional[str] = None
    subject_template: Optional[str] = None
    body_template: Optional[str] = None


class MessageTemplateOut(BaseModel):
    id: str
    organization_id: Optional[str]
    show_id: Optional[str]
    name: str
    audience: Optional[str]
    subject_template: Optional[str]
    body_template: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class TemplateRenderRequest(BaseModel):
    context: dict


class TemplateRenderResponse(BaseModel):
    subject: Optional[str]
    body: Optional[str]


class EventCreate(BaseModel):
    title: str
    starts_at: datetime
    ends_at: Optional[datetime] = None
    category: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class EventOut(BaseModel):
    id: str
    show_id: str
    title: str
    starts_at: datetime
    ends_at: Optional[datetime]
    category: Optional[str]
    location: Optional[str]
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class FileCreate(BaseModel):
    filename: str
    content_type: Optional[str] = None
    size_bytes: Optional[str] = None
    storage_key: Optional[str] = None
    uploaded_by: Optional[str] = None


class FileOut(BaseModel):
    id: str
    show_id: str
    filename: str
    content_type: Optional[str]
    size_bytes: Optional[str]
    storage_key: Optional[str]
    uploaded_by: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class IntegrationCreate(BaseModel):
    provider: str
    status: Optional[str] = "disabled"
    display_name: Optional[str] = None
    config_json: Optional[str] = None


class IntegrationOut(BaseModel):
    id: str
    organization_id: Optional[str]
    show_id: Optional[str]
    provider: str
    status: str
    display_name: Optional[str]
    config_json: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ReferenceDocumentCreate(BaseModel):
    document_type: str
    title: str
    version_label: str
    source_org: Optional[str] = "AOS"
    source_url: Optional[str] = None
    notes: Optional[str] = None


class ReferenceDocumentOut(BaseModel):
    id: str
    document_type: str
    title: str
    version_label: str
    source_org: str
    source_url: Optional[str]
    file_path: str
    mime_type: str
    file_size_bytes: int
    sha256: str
    is_active: bool
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ReferenceDocumentListOut(BaseModel):
    id: str
    document_type: str
    title: str
    version_label: str
    source_org: str
    source_url: Optional[str]
    file_size_bytes: int
    is_active: bool
    updated_at: datetime

    class Config:
        from_attributes = True


class ReferenceDocumentUpdate(BaseModel):
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class JudgeCreate(BaseModel):
    show_id: str
    name: str
    email: Optional[str] = None


class JudgeOut(BaseModel):
    id: str
    show_id: str
    name: str
    email: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ScoreSubmissionCreate(BaseModel):
    show_id: str
    entry_id: str
    judge_id: str
    total_points: int
    points_breakdown: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None


class ScoreSubmissionOut(BaseModel):
    id: str
    show_id: str
    entry_id: str
    judge_id: str
    total_points: int
    points_breakdown: Optional[Dict[str, Any]] = None
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class VolunteerRoleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    training_url: Optional[str] = None


class VolunteerRoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    training_url: Optional[str] = None


class VolunteerRoleOut(BaseModel):
    id: str
    show_id: str
    name: str
    description: Optional[str]
    training_url: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class VolunteerShiftCreate(BaseModel):
    role_id: str
    starts_at: datetime
    ends_at: datetime
    capacity: Optional[int] = 1
    location: Optional[str] = None
    notes: Optional[str] = None


class VolunteerShiftUpdate(BaseModel):
    role_id: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    capacity: Optional[int] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class VolunteerShiftOut(BaseModel):
    id: str
    show_id: str
    role_id: str
    starts_at: datetime
    ends_at: datetime
    capacity: int
    location: Optional[str]
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class VolunteerCreate(BaseModel):
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    sms_opt_in: Optional[bool] = False
    org_id: Optional[str] = None
    status: Optional[str] = "pending"


class VolunteerUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    sms_opt_in: Optional[bool] = None
    status: Optional[str] = None


class VolunteerOut(BaseModel):
    id: str
    org_id: Optional[str]
    show_id: str
    full_name: str
    email: Optional[str]
    phone: Optional[str]
    sms_opt_in: bool
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class VolunteerAssignmentCreate(BaseModel):
    show_id: str
    volunteer_id: str
    shift_id: str
    source: Optional[str] = "self_signup"


class VolunteerAssignmentOut(BaseModel):
    id: str
    show_id: str
    volunteer_id: str
    shift_id: str
    status: str
    source: str
    created_at: datetime

    class Config:
        from_attributes = True


class VolunteerCheckinRequest(BaseModel):
    show_id: str
    volunteer_id: str
    shift_id: str
    method: Optional[str] = "web"


class VolunteerCheckinOut(BaseModel):
    id: str
    show_id: str
    volunteer_id: str
    shift_id: str
    check_in_at: Optional[datetime]
    check_out_at: Optional[datetime]
    method: str
    created_at: datetime

    class Config:
        from_attributes = True


class PublicVolunteerSignup(BaseModel):
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    sms_opt_in: Optional[bool] = False
