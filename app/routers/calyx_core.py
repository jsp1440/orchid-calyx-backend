from typing import List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from sqlalchemy import select, or_

from app.deps import get_db
from app.models import (
    Organization, Show, Contact, MessageTemplate, Event, File, IntegrationConnection
)
from app.schemas import (
    OrganizationCreate, OrganizationOut,
    ShowCreate, ShowOut,
    ContactCreate, ContactOut,
    MessageTemplateCreate, MessageTemplateOut, TemplateRenderRequest, TemplateRenderResponse,
    EventCreate, EventOut,
    FileCreate, FileOut,
    IntegrationCreate, IntegrationOut,
)
from app.routers.calyx_operator_workflow import router as calyx_operator_router
from app.routers.calyx_unified_owner_flow import router as calyx_unified_owner_flow_router
from app.university.routes import router as university_router
from app.calyx_conversation.routes import router as calyx_conversation_router
from app.calyx_conversation.file_routes import router as calyx_file_analysis_router
from app.calyx_conversation.reasoning_routes import router as calyx_reasoning_router
from runtime.calyx_core_certification import create_certification_router

router = APIRouter(prefix="/api", tags=["calyx-core"])


@router.get("/organizations", response_model=List[OrganizationOut])
def list_organizations(db: Session = Depends(get_db)):
    return db.execute(select(Organization)).scalars().all()


@router.post("/organizations", response_model=OrganizationOut)
def create_organization(payload: OrganizationCreate, db: Session = Depends(get_db)):
    org = Organization(**payload.model_dump())
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


@router.get("/organizations/{org_id}/shows", response_model=List[ShowOut])
def list_org_shows(org_id: str, db: Session = Depends(get_db)):
    return db.execute(select(Show).where(Show.organization_id == org_id)).scalars().all()


@router.post("/organizations/{org_id}/shows", response_model=ShowOut)
def create_org_show(org_id: str, payload: OrganizationCreate, db: Session = Depends(get_db)):
    org = db.execute(select(Organization).where(Organization.id == org_id)).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    show = Show(organization_id=org_id, **payload.model_dump())
    db.add(show)
    db.commit()
    db.refresh(show)
    return show


@router.get("/shows/{show_id}/contacts", response_model=List[ContactOut])
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


@router.get("/shows/{show_id}/templates", response_model=List[MessageTemplateOut])
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


@router.post("/shows/{show_id}/templates", response_model=MessageTemplateOut)
def create_show_template(show_id: str, payload: MessageTemplateCreate, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    template = MessageTemplate(show_id=show_id, **payload.model_dump())
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.post("/shows/{show_id}/templates/{template_id}/render", response_model=TemplateRenderResponse)
def render_template(show_id: str, template_id: str, payload: TemplateRenderRequest, db: Session = Depends(get_db)):
    template = db.execute(select(MessageTemplate).where(MessageTemplate.id == template_id)).scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    variables = payload.variables
    subject = (template.subject_template or "").format(**variables) if template.subject_template else ""
    body = (template.body_template or "").format(**variables) if template.body_template else ""
    return TemplateRenderResponse(subject=subject, body=body)


@router.get("/shows/{show_id}/events", response_model=List[EventOut])
def list_show_events(show_id: str, db: Session = Depends(get_db)):
    return db.execute(select(Event).where(Event.show_id == show_id)).scalars().all()


@router.post("/shows/{show_id}/events", response_model=EventOut)
def create_show_event(show_id: str, payload: EventCreate, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    event = Event(show_id=show_id, **payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("/shows/{show_id}/events/ics", response_class=PlainTextResponse)
def export_events_ics(show_id: str, db: Session = Depends(get_db)):
    events = db.execute(select(Event).where(Event.show_id == show_id)).scalars().all()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Calyx//Orchid Show//EN"]
    for ev in events:
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{ev.id}@calyx")
        lines.append(f"DTSTART:{ev.starts_at.strftime('%Y%m%dT%H%M%S')}")
        if ev.ends_at:
            lines.append(f"DTEND:{ev.ends_at.strftime('%Y%m%dT%H%M%S')}")
        lines.append(f"SUMMARY:{ev.title}")
        if ev.location:
            lines.append(f"LOCATION:{ev.location}")
        if ev.notes:
            lines.append(f"DESCRIPTION:{ev.notes}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


@router.get("/shows/{show_id}/files", response_model=List[FileOut])
def list_show_files(show_id: str, db: Session = Depends(get_db)):
    return db.execute(select(File).where(File.show_id == show_id)).scalars().all()


@router.post("/shows/{show_id}/files", response_model=FileOut)
def create_show_file(show_id: str, payload: FileCreate, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    file = File(show_id=show_id, **payload.model_dump())
    db.add(file)
    db.commit()
    db.refresh(file)
    return file


@router.get("/shows/{show_id}/integrations", response_model=List[IntegrationOut])
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
    return db.execute(query).scalars().all()


@router.post("/shows/{show_id}/integrations", response_model=IntegrationOut)
def create_show_integration(show_id: str, payload: IntegrationCreate, db: Session = Depends(get_db)):
    show = db.execute(select(Show).where(Show.id == show_id)).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    integration = IntegrationConnection(show_id=show_id, **payload.model_dump())
    db.add(integration)
    db.commit()
    db.refresh(integration)
    return integration


router.include_router(university_router)
router.include_router(create_certification_router())
router.include_router(calyx_operator_router)
router.include_router(calyx_unified_owner_flow_router)
router.include_router(calyx_conversation_router)
router.include_router(calyx_file_analysis_router)
router.include_router(calyx_reasoning_router)
