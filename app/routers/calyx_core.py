# ruff: noqa: B008
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.calyx_conversation.file_routes import router as calyx_file_analysis_router
from app.calyx_conversation.reasoning_routes import router as calyx_reasoning_router
from app.calyx_conversation.routes import router as calyx_conversation_router
from app.calyx_conversation.speak_routes import router as calyx_speak_router
from app.deps import get_db
from app.lexicon.routes import router as lexicon_router
from app.member_auth import owner_or_member_read
from app.models import (
    Contact,
    Event,
    File,
    IntegrationConnection,
    MessageTemplate,
    Organization,
    Show,
)
from app.routers.calyx_operator_workflow import router as calyx_operator_router
from app.schemas import (
    ContactCreate,
    ContactOut,
    EventCreate,
    EventOut,
    FileCreate,
    FileOut,
    IntegrationCreate,
    IntegrationOut,
    MessageTemplateCreate,
    MessageTemplateOut,
    OrganizationCreate,
    OrganizationOut,
    ShowCreate,
    ShowOut,
    TemplateRenderRequest,
    TemplateRenderResponse,
)
from app.show_output_safety import (
    check_template_size,
    ics_strip_line_breaks,
    ics_text_line,
    normalize_render_context,
    redact_config_json,
    render_template_text,
)
from app.university.routes import router as university_router
from runtime.calyx_core_certification import create_certification_router

router = APIRouter(prefix="/api", tags=["calyx-core"])

# Show management (organizations, org shows, templates, events + ICS, files,
# integrations) is owner-only. ``owner_or_member_read`` is default-deny and none of
# these endpoints is marked ``@member_readable``: the owner session or the backend API
# key is admitted exactly as by ``verify_owner_or_api_key``, a verified member gets 403
# OWNER_ACCESS_REQUIRED and anonymous/invalid credentials get 401. It is attached per
# route (not on this router) because the sub-routers included at the bottom of this
# module keep their own auth. It runs before body validation and before any lookup, so
# an anonymous caller learns nothing about which organizations or shows exist.
# No frontend, Brain or show-day consumer reads these routes anonymously; there is no
# public schema here, and none may reuse the owner schemas (they carry the volunteer
# token, storage keys, uploader identity and integration configuration).
OWNER_ONLY = [Depends(owner_or_member_read)]


@router.get("/organizations", response_model=list[OrganizationOut], dependencies=OWNER_ONLY)
def list_organizations(db: Session = Depends(get_db)):
    return db.execute(select(Organization)).scalars().all()


@router.post("/organizations", response_model=OrganizationOut, dependencies=OWNER_ONLY)
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db)):
    org = Organization(**payload.model_dump())
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@router.get("/organizations/{org_id}/shows", response_model=list[ShowOut], dependencies=OWNER_ONLY)
def list_org_shows(org_id: str, db: Session = Depends(get_db)):
    return db.execute(select(Show).where(Show.organization_id == org_id)).scalars().all()


@router.post("/organizations/{org_id}/shows", response_model=ShowOut, dependencies=OWNER_ONLY)
def create_org_show(org_id: str, payload: ShowCreate, db: Session = Depends(get_db)):
    org = db.execute(select(Organization).where(Organization.id == org_id)).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    # The path names the organization; a conflicting body value is rejected rather
    # than passed twice to the model (which raised TypeError -> 500 on every call).
    if payload.organization_id is not None and payload.organization_id != org_id:
        raise HTTPException(status_code=422, detail="organization_id in the body does not match the path")
    show = Show(organization_id=org_id, **payload.model_dump(exclude={"organization_id"}))
    db.add(show)
    db.commit()
    db.refresh(show)
    return show


@router.get("/shows/{show_id}/contacts", response_model=list[ContactOut])
def list_show_contacts(show_id: str, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    query = select(Contact).where(
        or_(
            Contact.show_id == show_id,
            (Contact.organization_id == show.organization_id) & (Contact.show_id == None)
        )
    )
    return db.execute(query).scalars().all()


@router.post("/shows/{show_id}/contacts", response_model=ContactOut)
def create_show_contact(show_id: str, payload: ContactCreate, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    contact = Contact(show_id=show_id, **payload.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.get("/shows/{show_id}/templates", response_model=list[MessageTemplateOut], dependencies=OWNER_ONLY)
def list_show_templates(show_id: str, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    org_templates = db.execute(
        select(MessageTemplate).where(
            (MessageTemplate.organization_id == show.organization_id) & (MessageTemplate.show_id == None)
        )
    ).scalars().all()
    show_templates = db.execute(
        select(MessageTemplate).where(MessageTemplate.show_id == show_id)
    ).scalars().all()
    show_names = {t.name for t in show_templates}
    merged = list(show_templates) + [t for t in org_templates if t.name not in show_names]
    return merged


@router.post("/shows/{show_id}/templates", response_model=MessageTemplateOut, dependencies=OWNER_ONLY)
def create_show_template(show_id: str, payload: MessageTemplateCreate, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    check_template_size(payload.subject_template, payload.body_template)
    template = MessageTemplate(show_id=show_id, **payload.model_dump())
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.post(
    "/shows/{show_id}/templates/{template_id}/render",
    response_model=TemplateRenderResponse,
    dependencies=OWNER_ONLY,
)
def render_template(show_id: str, template_id: str, payload: TemplateRenderRequest, db: Session = Depends(get_db)):
    """Render a template visible to this show with ``{name}`` values from ``context``.

    The template must belong to the show, or be an organization-wide template of the
    show's organization (the same set ``GET .../templates`` lists); otherwise 404.
    Substitution is plain ``{name}`` replacement (no ``str.format``), a missing
    variable is 422, and the rendered subject/body are size-bounded.
    """
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    template = db.execute(select(MessageTemplate).where(MessageTemplate.id == template_id)).scalar_one_or_none()
    visible = template is not None and (
        template.show_id == show_id
        or (template.show_id is None and template.organization_id is not None
            and template.organization_id == show.organization_id)
    )
    if not visible:
        raise HTTPException(status_code=404, detail="Template not found")
    context = normalize_render_context(payload.context)
    subject = render_template_text(template.subject_template, context, field="subject")
    body = render_template_text(template.body_template, context, field="body")
    return TemplateRenderResponse(subject=subject, body=body)


@router.get("/shows/{show_id}/events", response_model=list[EventOut], dependencies=OWNER_ONLY)
def list_show_events(show_id: str, db: Session = Depends(get_db)):
    return db.execute(select(Event).where(Event.show_id == show_id)).scalars().all()


@router.post("/shows/{show_id}/events", response_model=EventOut, dependencies=OWNER_ONLY)
def create_show_event(show_id: str, payload: EventCreate, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    event = Event(show_id=show_id, **payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("/shows/{show_id}/events/ics", response_class=PlainTextResponse, dependencies=OWNER_ONLY)
def export_events_ics(show_id: str, db: Session = Depends(get_db)):
    """iCalendar export. TEXT values are RFC 5545 escaped (CR/LF become ``\\n``) and
    every content line is folded at 75 octets, so event text cannot add calendar lines."""
    events = db.execute(select(Event).where(Event.show_id == show_id)).scalars().all()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Calyx//Orchid Show//EN"]
    for ev in events:
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{ics_strip_line_breaks(ev.id)}@calyx")
        lines.append(f"DTSTART:{ev.starts_at.strftime('%Y%m%dT%H%M%S')}")
        if ev.ends_at:
            lines.append(f"DTEND:{ev.ends_at.strftime('%Y%m%dT%H%M%S')}")
        lines.extend(ics_text_line("SUMMARY", ev.title))
        if ev.location:
            lines.extend(ics_text_line("LOCATION", ev.location))
        if ev.notes:
            lines.extend(ics_text_line("DESCRIPTION", ev.notes))
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    # RFC 5545 terminates every content line, including the last, with CRLF.
    return "\r\n".join(lines) + "\r\n"


@router.get("/shows/{show_id}/files", response_model=list[FileOut], dependencies=OWNER_ONLY)
def list_show_files(show_id: str, db: Session = Depends(get_db)):
    return db.execute(select(File).where(File.show_id == show_id)).scalars().all()


@router.post("/shows/{show_id}/files", response_model=FileOut, dependencies=OWNER_ONLY)
def create_show_file(show_id: str, payload: FileCreate, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    file = File(show_id=show_id, **payload.model_dump())
    db.add(file)
    db.commit()
    db.refresh(file)
    return file


def _integration_out(integration: IntegrationConnection) -> IntegrationOut:
    """Owner response for an integration: ``config_json`` secrets masked as ``***``.

    The stored configuration is unchanged (providers still need it); responses never
    echo passwords, tokens, API keys or authorization values, even to the owner.
    """
    out = IntegrationOut.model_validate(integration)
    return out.model_copy(update={"config_json": redact_config_json(out.config_json)})


@router.get("/shows/{show_id}/integrations", response_model=list[IntegrationOut], dependencies=OWNER_ONLY)
def list_show_integrations(show_id: str, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    query = select(IntegrationConnection).where(
        or_(
            IntegrationConnection.show_id == show_id,
            (IntegrationConnection.organization_id == show.organization_id) & (IntegrationConnection.show_id == None)
        )
    )
    return [_integration_out(item) for item in db.execute(query).scalars().all()]


@router.post("/shows/{show_id}/integrations", response_model=IntegrationOut, dependencies=OWNER_ONLY)
def create_show_integration(show_id: str, payload: IntegrationCreate, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    integration = IntegrationConnection(show_id=show_id, **payload.model_dump())
    db.add(integration)
    db.commit()
    db.refresh(integration)
    return _integration_out(integration)


router.include_router(university_router)
router.include_router(create_certification_router())
router.include_router(calyx_operator_router)
router.include_router(calyx_conversation_router)
router.include_router(calyx_file_analysis_router)
router.include_router(calyx_reasoning_router)
router.include_router(calyx_speak_router)
router.include_router(lexicon_router)
