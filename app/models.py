import uuid
from datetime import datetime

from sqlalchemy import (
    DDL,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Session

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
# JUDGING (expanded system)
# -------------------------------------------------------------------


class JudgingEvent(Base):
    __tablename__ = "judging_events"

    id = Column(String, primary_key=True, default=generate_uuid)
    show_id = Column(String, ForeignKey("shows.id"), nullable=False, index=True)
    name = Column(Text, nullable=True)
    judging_type = Column(String, default="standard")
    is_blind = Column(Boolean, default=False)
    # Re-drawn each time the event enters blind mode; keys judge-facing handles.
    blind_handle_salt = Column(String(32), nullable=True)
    # The owner-approved event name judges see while the event is blind.
    blind_display_name = Column(Text, nullable=True)
    status = Column(String, default="draft")
    published_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PlantCategory(Base):
    __tablename__ = "plant_categories"

    id = Column(String, primary_key=True, default=generate_uuid)
    judging_event_id = Column(String, ForeignKey("judging_events.id"), nullable=False, index=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    # The owner-approved class name judges see while its event is blind.
    blind_display_name = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class JudgingAward(Base):
    __tablename__ = "judging_awards"

    award_id = Column(String, primary_key=True, default=generate_uuid)
    system_id = Column(String, nullable=False)
    award_name = Column(Text, nullable=False)
    award_type = Column(Text, nullable=True)
    target = Column(Text, nullable=True)
    eligibility_notes = Column(Text, nullable=True)
    score_min = Column(Float, nullable=True)
    score_max = Column(Float, nullable=True)
    score_thresholds_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class JudgingCriterion(Base):
    __tablename__ = "judging_criteria"

    criteria_id = Column(String, primary_key=True, default=generate_uuid)
    award_id = Column(String, ForeignKey("judging_awards.award_id"), nullable=False, index=True)
    criteria_name = Column(Text, nullable=False)
    criteria_description = Column(Text, nullable=True)
    points_min = Column(Float, nullable=True)
    points_max = Column(Float, nullable=True)
    weighting = Column(Float, nullable=True)
    rubric_json = Column(Text, nullable=True)
    scoring_type = Column(String, default="numeric")
    min_value = Column(Integer, nullable=True)
    max_value = Column(Integer, nullable=True)
    choices_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Exhibitor(Base):
    __tablename__ = "exhibitors"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(Text, nullable=False)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Plant(Base):
    __tablename__ = "plants"

    id = Column(String, primary_key=True, default=generate_uuid)
    exhibitor_id = Column(String, ForeignKey("exhibitors.id"), nullable=False, index=True)
    judging_event_id = Column(String, ForeignKey("judging_events.id"), nullable=False, index=True)
    category_id = Column(String, ForeignKey("plant_categories.id"), nullable=False, index=True)
    name = Column(Text, nullable=True)
    qr_code = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    # The only plant name a judge sees in a blind event; set by the owner.
    blind_display_name = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Judge(Base):
    __tablename__ = "judges"

    id = Column(String, primary_key=True, default=generate_uuid)
    show_id = Column(String, ForeignKey("shows.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    role = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Score(Base):
    __tablename__ = "scores"
    __table_args__ = (
        UniqueConstraint("plant_id", "judge_id", "criterion_id", name="uix_score_plant_judge_criterion"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    plant_id = Column(String, ForeignKey("plants.id"), nullable=False, index=True)
    judge_id = Column(String, ForeignKey("judges.id"), nullable=False, index=True)
    criterion_id = Column(String, ForeignKey("judging_criteria.criteria_id"), nullable=False, index=True)
    value = Column(Float, nullable=True)
    choice = Column(String, nullable=True)
    value_rank = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class JudgeAssignment(Base):
    __tablename__ = "judge_assignments"
    __table_args__ = (
        UniqueConstraint("judging_event_id", "judge_id", "category_id", name="uix_judge_assign_evt_judge_cat"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    judging_event_id = Column(String, ForeignKey("judging_events.id"), nullable=False, index=True)
    judge_id = Column(String, ForeignKey("judges.id"), nullable=False, index=True)
    category_id = Column(String, ForeignKey("plant_categories.id"), nullable=True, index=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Scorecard(Base):
    __tablename__ = "scorecards"
    __table_args__ = (
        UniqueConstraint("judging_event_id", "plant_id", "judge_id", name="uix_scorecard_evt_plant_judge"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    judging_event_id = Column(String, ForeignKey("judging_events.id"), nullable=False, index=True)
    plant_id = Column(String, ForeignKey("plants.id"), nullable=False, index=True)
    judge_id = Column(String, ForeignKey("judges.id"), nullable=False, index=True)
    status = Column(String, default="draft")
    total = Column(Float, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ScorecardAuditLog(Base):
    __tablename__ = "scorecard_audit_log"

    id = Column(String, primary_key=True, default=generate_uuid)
    scorecard_id = Column(String, ForeignKey("scorecards.id"), nullable=False, index=True)
    actor_judge_id = Column(String, nullable=True)
    action = Column(String, nullable=False)
    diff_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class JudgeCredential(Base):
    """A per-judge bearer credential, scoped to one show (and optionally to
    events and categories). Only an HMAC of the token is stored; the token
    itself is shown to the owner once, at issuance. See ``app/judge_auth.py``.
    """

    __tablename__ = "judge_credentials"

    id = Column(String(32), primary_key=True)
    judge_id = Column(String, ForeignKey("judges.id"), nullable=False, index=True)
    show_id = Column(String, ForeignKey("shows.id"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False)
    event_ids_json = Column(Text, nullable=True)
    category_ids_json = Column(Text, nullable=True)
    label = Column(String, nullable=True)
    issued_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)


class JudgeActionAudit(Base):
    """Append-only record of what a judge credential did, and with what outcome.

    It names the judge, the credential, the event, category, scorecard and
    plant, and never any exhibitor field. The owner reads it; no judge route
    does. Rows are never updated or deleted (ORM guard below, trigger in the
    SQL migration).
    """

    __tablename__ = "judge_action_audit"

    id = Column(String, primary_key=True, default=generate_uuid)
    judge_id = Column(String, nullable=False, index=True)
    credential_id = Column(String(32), nullable=True, index=True)
    action = Column(String, nullable=False)
    judging_event_id = Column(String, nullable=True, index=True)
    category_id = Column(String, nullable=True)
    scorecard_id = Column(String, nullable=True)
    plant_id = Column(String, nullable=True)
    plant_handle = Column(String, nullable=True)
    outcome = Column(String, nullable=False)
    http_status = Column(Integer, nullable=False)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class ShowOwnerAudit(Base):
    """Append-only record of owner actions on judging access and blind labels.

    Written by ``app/routers/judge_admin.py`` for credential issue, rotation
    and revocation, tag re-issue, and every blind display name the owner sets
    or confirms over a warning. A name that drew warnings is stored only as a
    SHA-256 digest (``text_sha256``, ``text_withheld``), never as text.
    """

    __tablename__ = "show_owner_audit"

    id = Column(String, primary_key=True, default=generate_uuid)
    actor = Column(String, nullable=False)
    auth_type = Column(String, nullable=False)
    action = Column(String, nullable=False)
    object_type = Column(String, nullable=False)
    object_id = Column(String, nullable=False, index=True)
    show_id = Column(String, nullable=True, index=True)
    judging_event_id = Column(String, nullable=True)
    warnings_json = Column(Text, nullable=True)
    confirmed_despite_warnings = Column(Boolean, nullable=False, default=False)
    text_value = Column(Text, nullable=True)
    text_sha256 = Column(String(64), nullable=True)
    text_withheld = Column(Boolean, nullable=False, default=False)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


APPEND_ONLY_MODELS = (JudgeActionAudit, ShowOwnerAudit)
APPEND_ONLY_TABLES = frozenset(m.__tablename__ for m in APPEND_ONLY_MODELS)


def _refuse_append_only_change(_mapper, _connection, target):
    raise ValueError(f"{target.__tablename__} is append-only")


for _model in APPEND_ONLY_MODELS:
    event.listen(_model, "before_update", _refuse_append_only_change)
    event.listen(_model, "before_delete", _refuse_append_only_change)


@event.listens_for(Session, "do_orm_execute")
def _append_only_tables_reject_bulk_writes(state):
    """Refuse ``update(...)`` / ``delete(...)`` statements aimed at an audit.

    The mapper events above only see unit-of-work flushes; bulk statements
    executed through a session bypass them.
    """
    if not (state.is_update or state.is_delete):
        return
    name = getattr(getattr(state.statement, "table", None), "name", None)
    if name in APPEND_ONLY_TABLES:
        raise ValueError(f"{name} is append-only")


def _install_append_only_triggers(table) -> None:
    """Database-level guards for tables made by ``create_all``.

    That is the show profile's rehearsal path and the tests;
    ``migrations/20260930_show_judge_credentials.sql`` installs the same
    PostgreSQL triggers on a migrated database.
    """
    name = table.name
    for op in ("UPDATE", "DELETE"):
        event.listen(
            table,
            "after_create",
            DDL(
                f"CREATE TRIGGER {name}_no_{op.lower()} BEFORE {op} ON {name} BEGIN "
                f"SELECT RAISE(ABORT, '{name} is append-only'); END"
            ).execute_if(dialect="sqlite"),
        )
    for ddl in (
        (
            f"CREATE OR REPLACE FUNCTION {name}_append_only() RETURNS trigger AS $$ "
            f"BEGIN RAISE EXCEPTION '{name} is append-only'; END; $$ LANGUAGE plpgsql"
        ),
        (
            f"CREATE TRIGGER {name}_no_update_delete BEFORE UPDATE OR DELETE ON {name} "
            f"FOR EACH ROW EXECUTE FUNCTION {name}_append_only()"
        ),
        (
            f"CREATE TRIGGER {name}_no_truncate BEFORE TRUNCATE ON {name} "
            f"FOR EACH STATEMENT EXECUTE FUNCTION {name}_append_only()"
        ),
    ):
        event.listen(table, "after_create", DDL(ddl).execute_if(dialect="postgresql"))


for _model in APPEND_ONLY_MODELS:
    _install_append_only_triggers(_model.__table__)


class ScoreSubmission(Base):
    __tablename__ = "score_submissions"
    __table_args__ = (UniqueConstraint("show_id",
                                       "entry_id",
                                       "judge_id",
                                       name="uix_score_show_entry_judge"), )

    id = Column(String, primary_key=True, default=generate_uuid)
    show_id = Column(String, ForeignKey("shows.id"), nullable=False, index=True)
    entry_id = Column(String, ForeignKey("entries.id"), nullable=False, index=True)
    judge_id = Column(String, ForeignKey("judges.id"), nullable=False, index=True)
    total_points = Column(Integer, nullable=False)
    points_breakdown = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
