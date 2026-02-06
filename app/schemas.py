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


class JudgingEventCreate(BaseModel):
    name: Optional[str] = None
    judging_type: Optional[str] = "standard"
    is_blind: Optional[bool] = False


class JudgingEventOut(BaseModel):
    id: str
    show_id: str
    name: Optional[str] = None
    judging_type: str
    is_blind: bool
    status: str
    published_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class JudgingEventUpdate(BaseModel):
    name: Optional[str] = None
    judging_type: Optional[str] = None
    is_blind: Optional[bool] = None
    status: Optional[str] = None


class PlantCategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    sort_order: Optional[int] = 0


class PlantCategoryOut(BaseModel):
    id: str
    judging_event_id: str
    name: str
    description: Optional[str] = None
    sort_order: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class JudgingCriterionCreate(BaseModel):
    label: str
    weight: Optional[float] = None
    max_points: Optional[int] = None
    scoring_type: Optional[str] = "numeric"
    min_value: Optional[int] = None
    max_value: Optional[int] = None
    choices_json: Optional[str] = None


class JudgingCriterionOut(BaseModel):
    id: str
    category_id: str
    label: str
    weight: Optional[float] = None
    max_points: Optional[int] = None
    scoring_type: str = "numeric"
    min_value: Optional[int] = None
    max_value: Optional[int] = None
    choices_json: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ExhibitorCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None


class ExhibitorOut(BaseModel):
    id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PlantCreate(BaseModel):
    exhibitor_id: str
    category_id: str
    name: Optional[str] = None
    notes: Optional[str] = None


class PlantOut(BaseModel):
    id: str
    exhibitor_id: str
    judging_event_id: str
    category_id: str
    name: Optional[str] = None
    qr_code: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ScoreCreate(BaseModel):
    criterion_id: str
    value: Optional[float] = None
    choice: Optional[str] = None


class ScoreOut(BaseModel):
    id: str
    plant_id: str
    judge_id: str
    criterion_id: str
    value: Optional[float] = None
    choice: Optional[str] = None
    value_rank: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ScoreBatchCreate(BaseModel):
    scores: List[ScoreCreate]


class JudgeCreate(BaseModel):
    show_id: str
    name: str
    email: Optional[str] = None
    role: Optional[str] = None


class JudgeOut(BaseModel):
    id: str
    show_id: str
    name: str
    email: Optional[str] = None
    role: Optional[str] = None
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
    default_shift_length: Optional[int] = None


class VolunteerRoleOut(BaseModel):
    id: str
    show_id: str
    name: str
    description: Optional[str] = None
    default_shift_length: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class VolunteerShiftCreate(BaseModel):
    role_id: str
    start_time: datetime
    end_time: datetime
    capacity: Optional[int] = 1


class VolunteerShiftOut(BaseModel):
    id: str
    show_id: str
    role_id: str
    start_time: datetime
    end_time: datetime
    capacity: int
    created_at: datetime

    class Config:
        from_attributes = True


class VolunteerCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    opt_in_sms: Optional[bool] = False
    notes: Optional[str] = None
    approved: Optional[bool] = False


class VolunteerOut(BaseModel):
    id: str
    show_id: str
    name: str
    email: str
    phone: Optional[str] = None
    opt_in_sms: bool
    notes: Optional[str] = None
    approved: bool
    created_at: datetime

    class Config:
        from_attributes = True


class VolunteerAssignmentCreate(BaseModel):
    volunteer_id: str
    shift_id: str
    status: Optional[str] = "assigned"


class VolunteerAssignmentOut(BaseModel):
    id: str
    show_id: str
    volunteer_id: str
    shift_id: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class VolunteerAssignmentMove(BaseModel):
    shift_id: str


class FeedbackCreate(BaseModel):
    module: str
    step: Optional[str] = None
    worked: Optional[bool] = None
    confusion: Optional[str] = None
    suggestions: Optional[str] = None
    organization_id: Optional[str] = None


class FeedbackOut(BaseModel):
    id: str
    organization_id: Optional[str] = None
    module: str
    step: Optional[str] = None
    worked: Optional[bool] = None
    confusion: Optional[str] = None
    suggestions: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class JudgeAssignmentCreate(BaseModel):
    judge_id: str
    category_id: Optional[str] = None
    active: Optional[bool] = True


class JudgeAssignmentOut(BaseModel):
    id: str
    judging_event_id: str
    judge_id: str
    category_id: Optional[str] = None
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ScorecardOut(BaseModel):
    id: str
    judging_event_id: str
    plant_id: str
    judge_id: str
    status: str
    total: Optional[float] = None
    submitted_at: Optional[datetime] = None
    version: int = 1
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ScorecardScoreItem(BaseModel):
    criterion_id: str
    value: Optional[float] = None
    choice: Optional[str] = None
    value_rank: Optional[int] = None


class ScorecardSaveRequest(BaseModel):
    scores: List[ScorecardScoreItem]
    notes: Optional[str] = None


class ScorecardSubmitRequest(BaseModel):
    final_comment: Optional[str] = None


class ScorecardAuditOut(BaseModel):
    id: str
    scorecard_id: str
    actor_judge_id: Optional[str] = None
    action: str
    diff_json: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
