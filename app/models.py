import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Date,
    Time,
    DateTime,
    ForeignKey,
    Text,
    Boolean,
    Integer,
    UniqueConstraint,
)

from app.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(String, primary_key=True, default=generate_uuid)
    slug = Column(String, nullable=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Show(Base):
    __tablename__ = "shows"

    id = Column(String, primary_key=True, default=generate_uuid)
    organization_id = Column(String,
                             ForeignKey("organizations.id"),
                             nullable=True)

    name = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    location = Column(String, nullable=True)

    judging_locked = Column(Boolean, default=False, nullable=False)
    public_volunteer_token = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class Entry(Base):
    __tablename__ = "entries"

    id = Column(String, primary_key=True, default=generate_uuid)
    show_id = Column(String, ForeignKey("shows.id"), nullable=False)

    # Keep current "demo reality" fields (acts like plant registration)
    exhibitor_name = Column(String, nullable=False)
    plant_name = Column(String, nullable=False)
    class_code = Column(String, nullable=True)

    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)


class VolunteerTask(Base):
    __tablename__ = "volunteer_tasks"

    id = Column(String, primary_key=True, default=generate_uuid)
    show_id = Column(String, ForeignKey("shows.id"), nullable=False)

    title = Column(String, nullable=False)
    assigned_to = Column(String, nullable=True)
    status = Column(String, default="open")
    created_at = Column(DateTime, default=datetime.utcnow)


class Award(Base):
    __tablename__ = "awards"

    id = Column(String, primary_key=True, default=generate_uuid)
    entry_id = Column(String, ForeignKey("entries.id"), nullable=False)

    award_name = Column(String, nullable=False)
    level = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(String, primary_key=True, default=generate_uuid)
    organization_id = Column(String,
                             ForeignKey("organizations.id"),
                             nullable=True)
    show_id = Column(String, ForeignKey("shows.id"), nullable=True)

    name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    city = Column(String, nullable=True)
    contact_type = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MessageTemplate(Base):
    __tablename__ = "message_templates"

    id = Column(String, primary_key=True, default=generate_uuid)
    organization_id = Column(String,
                             ForeignKey("organizations.id"),
                             nullable=True)
    show_id = Column(String, ForeignKey("shows.id"), nullable=True)

    name = Column(String, nullable=False)
    audience = Column(String, nullable=True)
    subject_template = Column(Text, nullable=True)
    body_template = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MessageLog(Base):
    __tablename__ = "message_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    show_id = Column(String, ForeignKey("shows.id"), nullable=False)

    channel = Column(String, nullable=True)
    to_contact_id = Column(String, ForeignKey("contacts.id"), nullable=True)
    to_raw = Column(String, nullable=True)
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    status = Column(String, default="drafted")
    created_at = Column(DateTime, default=datetime.utcnow)


class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=generate_uuid)
    show_id = Column(String, ForeignKey("shows.id"), nullable=False)

    title = Column(String, nullable=False)
    starts_at = Column(DateTime, nullable=False)
    ends_at = Column(DateTime, nullable=True)
    category = Column(String, nullable=True)
    location = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class File(Base):
    __tablename__ = "files"

    id = Column(String, primary_key=True, default=generate_uuid)
    show_id = Column(String, ForeignKey("shows.id"), nullable=False)

    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    size_bytes = Column(String, nullable=True)
    storage_key = Column(String, nullable=True)
    uploaded_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class IntegrationConnection(Base):
    __tablename__ = "integration_connections"

    id = Column(String, primary_key=True, default=generate_uuid)
    organization_id = Column(String,
                             ForeignKey("organizations.id"),
                             nullable=True)
    show_id = Column(String, ForeignKey("shows.id"), nullable=True)

    provider = Column(String, nullable=False)
    status = Column(String, default="disabled")
    display_name = Column(String, nullable=True)
    config_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SystemReferenceDocument(Base):
    __tablename__ = "system_reference_documents"

    id = Column(String, primary_key=True, default=generate_uuid)
    document_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    version_label = Column(String, nullable=False)
    source_org = Column(String, default="AOS")
    source_url = Column(String, nullable=True)

    # points at a local stored file OR an internal key
    file_path = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String, nullable=False)

    is_active = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime,
                        default=datetime.utcnow,
                        onupdate=datetime.utcnow)


# -------------------------------------------------------------------
# VOLUNTEERS (spec-aligned: design doc v2)
# -------------------------------------------------------------------


class VolunteerRole(Base):
    __tablename__ = "volunteer_roles"

    id = Column(String, primary_key=True, default=generate_uuid)
    show_id = Column(String, ForeignKey("shows.id"), nullable=False, index=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    default_shift_length = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class VolunteerShift(Base):
    __tablename__ = "volunteer_shifts"

    id = Column(String, primary_key=True, default=generate_uuid)
    show_id = Column(String, ForeignKey("shows.id"), nullable=False, index=True)
    role_id = Column(String, ForeignKey("volunteer_roles.id"), nullable=False, index=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    capacity = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)


class Volunteer(Base):
    __tablename__ = "volunteers"
    __table_args__ = (
        UniqueConstraint("show_id", "email", name="uix_vol_show_email"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    show_id = Column(String, ForeignKey("shows.id"), nullable=False, index=True)
    name = Column(Text, nullable=False)
    email = Column(Text, nullable=False)
    phone = Column(Text, nullable=True)
    opt_in_sms = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    approved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class VolunteerAssignment(Base):
    __tablename__ = "volunteer_assignments"
    __table_args__ = (
        UniqueConstraint("shift_id", "volunteer_id", name="uix_assign_shift_vol"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    show_id = Column(String, ForeignKey("shows.id"), nullable=False, index=True)
    volunteer_id = Column(String, ForeignKey("volunteers.id"), nullable=False, index=True)
    shift_id = Column(String, ForeignKey("volunteer_shifts.id"), nullable=False, index=True)
    status = Column(Text, default="assigned")
    created_at = Column(DateTime, default=datetime.utcnow)


# -------------------------------------------------------------------
# FEEDBACK (beta capture)
# -------------------------------------------------------------------


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(String, primary_key=True, default=generate_uuid)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=True)
    module = Column(Text, nullable=False)
    step = Column(Text, nullable=True)
    worked = Column(Boolean, nullable=True)
    confusion = Column(Text, nullable=True)
    suggestions = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# -------------------------------------------------------------------
# JUDGING (minimal demo tables)
# -------------------------------------------------------------------


class Judge(Base):
    __tablename__ = "judges"

    id = Column(String, primary_key=True, default=generate_uuid)
    show_id = Column(String,
                     ForeignKey("shows.id"),
                     nullable=False,
                     index=True)

    name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ScoreSubmission(Base):
    __tablename__ = "score_submissions"
    __table_args__ = (UniqueConstraint("show_id",
                                       "entry_id",
                                       "judge_id",
                                       name="uix_score_show_entry_judge"), )

    id = Column(String, primary_key=True, default=generate_uuid)

    show_id = Column(String,
                     ForeignKey("shows.id"),
                     nullable=False,
                     index=True)
    entry_id = Column(String,
                      ForeignKey("entries.id"),
                      nullable=False,
                      index=True)
    judge_id = Column(String,
                      ForeignKey("judges.id"),
                      nullable=False,
                      index=True)

    total_points = Column(Integer, nullable=False)

    # Optional structured criteria dump (store JSON as text for now, demo-safe)
    points_breakdown = Column(Text, nullable=True)

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
