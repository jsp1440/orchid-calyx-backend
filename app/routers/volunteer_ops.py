import csv
import io
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, File
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import (
    Show,
    Volunteer,
    VolunteerRole,
    VolunteerShift,
    VolunteerAssignment,
    VolunteerCheckin,
)
from app.schemas import (
    VolunteerRoleCreate,
    VolunteerRoleUpdate,
    VolunteerRoleOut,
    VolunteerShiftCreate,
    VolunteerShiftUpdate,
    VolunteerShiftOut,
    VolunteerCreate,
    VolunteerUpdate,
    VolunteerOut,
    VolunteerAssignmentCreate,
    VolunteerAssignmentOut,
    VolunteerCheckinRequest,
    VolunteerCheckinOut,
    PublicVolunteerSignup,
)
from app.security import verify_api_key

router = APIRouter(prefix="/api", tags=["Volunteer Operations"], dependencies=[Depends(verify_api_key)])
public_router = APIRouter(prefix="/api/public", tags=["Public Volunteer"])


def _require_show(db: Session, show_id: str) -> Show:
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    return show


@router.post("/shows/{show_id}/volunteer-roles", response_model=VolunteerRoleOut)
def create_role(show_id: str, data: VolunteerRoleCreate, db: Session = Depends(get_db)):
    _require_show(db, show_id)
    role = VolunteerRole(show_id=show_id, **data.model_dump())
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


@router.get("/shows/{show_id}/volunteer-roles", response_model=List[VolunteerRoleOut])
def list_roles(show_id: str, db: Session = Depends(get_db)):
    return db.execute(select(VolunteerRole).where(VolunteerRole.show_id == show_id)).scalars().all()


@router.patch("/volunteer-roles/{role_id}", response_model=VolunteerRoleOut)
def update_role(role_id: str, data: VolunteerRoleUpdate, db: Session = Depends(get_db)):
    role = db.get(VolunteerRole, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(role, k, v)
    db.commit()
    db.refresh(role)
    return role


@router.delete("/volunteer-roles/{role_id}")
def delete_role(role_id: str, db: Session = Depends(get_db)):
    role = db.get(VolunteerRole, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    db.delete(role)
    db.commit()
    return {"status": "deleted"}


@router.post("/shows/{show_id}/volunteer-shifts", response_model=VolunteerShiftOut)
def create_shift(show_id: str, data: VolunteerShiftCreate, db: Session = Depends(get_db)):
    _require_show(db, show_id)
    role = db.get(VolunteerRole, data.role_id)
    if not role or role.show_id != show_id:
        raise HTTPException(status_code=404, detail="Role not found for this show")
    shift = VolunteerShift(show_id=show_id, **data.model_dump())
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return shift


@router.get("/shows/{show_id}/volunteer-shifts", response_model=List[VolunteerShiftOut])
def list_shifts(
    show_id: str,
    role_id: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = select(VolunteerShift).where(VolunteerShift.show_id == show_id)
    if role_id:
        q = q.where(VolunteerShift.role_id == role_id)
    if date:
        q = q.where(func.date(VolunteerShift.starts_at) == date)
    return db.execute(q).scalars().all()


@router.patch("/volunteer-shifts/{shift_id}", response_model=VolunteerShiftOut)
def update_shift(shift_id: str, data: VolunteerShiftUpdate, db: Session = Depends(get_db)):
    shift = db.get(VolunteerShift, shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(shift, k, v)
    db.commit()
    db.refresh(shift)
    return shift


@router.delete("/volunteer-shifts/{shift_id}")
def delete_shift(shift_id: str, db: Session = Depends(get_db)):
    shift = db.get(VolunteerShift, shift_id)
    if not shift:
        raise HTTPException(status_code=404, detail="Shift not found")
    db.delete(shift)
    db.commit()
    return {"status": "deleted"}


@router.post("/shows/{show_id}/volunteers", response_model=VolunteerOut)
def create_volunteer(show_id: str, data: VolunteerCreate, db: Session = Depends(get_db)):
    _require_show(db, show_id)
    vol = Volunteer(show_id=show_id, **data.model_dump())
    db.add(vol)
    db.commit()
    db.refresh(vol)
    return vol


@router.get("/shows/{show_id}/volunteers", response_model=List[VolunteerOut])
def list_volunteers(
    show_id: str,
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = select(Volunteer).where(Volunteer.show_id == show_id)
    if status:
        q = q.where(Volunteer.status == status)
    return db.execute(q).scalars().all()


@router.patch("/volunteers/{volunteer_id}", response_model=VolunteerOut)
def update_volunteer(volunteer_id: str, data: VolunteerUpdate, db: Session = Depends(get_db)):
    vol = db.get(Volunteer, volunteer_id)
    if not vol:
        raise HTTPException(status_code=404, detail="Volunteer not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(vol, k, v)
    db.commit()
    db.refresh(vol)
    return vol


def _count_assigned(db: Session, shift_id: str) -> int:
    return db.execute(
        select(func.count(VolunteerAssignment.id)).where(
            VolunteerAssignment.shift_id == shift_id,
            VolunteerAssignment.status == "assigned",
        )
    ).scalar_one()


@router.post("/volunteer-assignments", response_model=VolunteerAssignmentOut)
def create_assignment(data: VolunteerAssignmentCreate, db: Session = Depends(get_db)):
    _require_show(db, data.show_id)

    vol = db.get(Volunteer, data.volunteer_id)
    if not vol or vol.show_id != data.show_id:
        raise HTTPException(status_code=404, detail="Volunteer not found for this show")

    if vol.status != "approved":
        raise HTTPException(status_code=409, detail="Volunteer must be approved before assignment")

    shift = db.get(VolunteerShift, data.shift_id)
    if not shift or shift.show_id != data.show_id:
        raise HTTPException(status_code=404, detail="Shift not found for this show")

    current = _count_assigned(db, data.shift_id)
    if current >= shift.capacity:
        raise HTTPException(status_code=409, detail="Shift capacity exceeded")

    existing = db.execute(
        select(VolunteerAssignment).where(
            VolunteerAssignment.show_id == data.show_id,
            VolunteerAssignment.volunteer_id == data.volunteer_id,
            VolunteerAssignment.shift_id == data.shift_id,
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Volunteer already assigned to this shift")

    assignment = VolunteerAssignment(**data.model_dump())
    db.add(assignment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate assignment")
    db.refresh(assignment)
    return assignment


@router.get("/shows/{show_id}/volunteer-assignments", response_model=List[VolunteerAssignmentOut])
def list_assignments(
    show_id: str,
    shift_id: Optional[str] = Query(None),
    volunteer_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = select(VolunteerAssignment).where(VolunteerAssignment.show_id == show_id)
    if shift_id:
        q = q.where(VolunteerAssignment.shift_id == shift_id)
    if volunteer_id:
        q = q.where(VolunteerAssignment.volunteer_id == volunteer_id)
    return db.execute(q).scalars().all()


@router.delete("/volunteer-assignments/{assignment_id}")
def delete_assignment(assignment_id: str, db: Session = Depends(get_db)):
    a = db.get(VolunteerAssignment, assignment_id)
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(a)
    db.commit()
    return {"status": "deleted"}


@router.post("/volunteer-checkin", response_model=VolunteerCheckinOut)
def volunteer_checkin(data: VolunteerCheckinRequest, db: Session = Depends(get_db)):
    existing = db.execute(
        select(VolunteerCheckin).where(
            VolunteerCheckin.show_id == data.show_id,
            VolunteerCheckin.volunteer_id == data.volunteer_id,
            VolunteerCheckin.shift_id == data.shift_id,
        )
    ).scalar_one_or_none()

    if existing:
        if existing.check_in_at is not None:
            raise HTTPException(status_code=409, detail="Already checked in")
        existing.check_in_at = datetime.utcnow()
        existing.method = data.method or "web"
        db.commit()
        db.refresh(existing)
        return existing

    checkin = VolunteerCheckin(
        show_id=data.show_id,
        volunteer_id=data.volunteer_id,
        shift_id=data.shift_id,
        check_in_at=datetime.utcnow(),
        method=data.method or "web",
    )
    db.add(checkin)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate check-in record")
    db.refresh(checkin)
    return checkin


@router.post("/volunteer-checkout", response_model=VolunteerCheckinOut)
def volunteer_checkout(data: VolunteerCheckinRequest, db: Session = Depends(get_db)):
    existing = db.execute(
        select(VolunteerCheckin).where(
            VolunteerCheckin.show_id == data.show_id,
            VolunteerCheckin.volunteer_id == data.volunteer_id,
            VolunteerCheckin.shift_id == data.shift_id,
        )
    ).scalar_one_or_none()

    if not existing or existing.check_in_at is None:
        raise HTTPException(status_code=409, detail="Not checked in yet")

    if existing.check_out_at is not None:
        raise HTTPException(status_code=409, detail="Already checked out")

    existing.check_out_at = datetime.utcnow()
    db.commit()
    db.refresh(existing)
    return existing


@router.get("/shows/{show_id}/volunteers/export.csv")
def export_volunteers_csv(show_id: str, db: Session = Depends(get_db)):
    _require_show(db, show_id)

    roles = db.execute(select(VolunteerRole).where(VolunteerRole.show_id == show_id)).scalars().all()
    shifts = db.execute(select(VolunteerShift).where(VolunteerShift.show_id == show_id)).scalars().all()
    vols = db.execute(select(Volunteer).where(Volunteer.show_id == show_id)).scalars().all()
    assignments = db.execute(select(VolunteerAssignment).where(VolunteerAssignment.show_id == show_id)).scalars().all()
    checkins = db.execute(select(VolunteerCheckin).where(VolunteerCheckin.show_id == show_id)).scalars().all()

    role_map = {r.id: r for r in roles}
    shift_map = {s.id: s for s in shifts}
    vol_map = {v.id: v for v in vols}
    checkin_map = {(c.volunteer_id, c.shift_id): c for c in checkins}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "volunteer_name", "email", "phone", "sms_opt_in", "status",
        "role_name", "shift_starts_at", "shift_ends_at", "shift_location",
        "assignment_status", "assignment_source",
        "check_in_at", "check_out_at",
    ])

    if assignments:
        for a in assignments:
            vol = vol_map.get(a.volunteer_id)
            shift = shift_map.get(a.shift_id)
            role = role_map.get(shift.role_id) if shift else None
            ck = checkin_map.get((a.volunteer_id, a.shift_id))
            writer.writerow([
                vol.full_name if vol else "",
                vol.email if vol else "",
                vol.phone if vol else "",
                vol.sms_opt_in if vol else "",
                vol.status if vol else "",
                role.name if role else "",
                shift.starts_at.isoformat() if shift else "",
                shift.ends_at.isoformat() if shift else "",
                shift.location if shift else "",
                a.status,
                a.source,
                ck.check_in_at.isoformat() if ck and ck.check_in_at else "",
                ck.check_out_at.isoformat() if ck and ck.check_out_at else "",
            ])
    else:
        for vol in vols:
            writer.writerow([
                vol.full_name, vol.email, vol.phone, vol.sms_opt_in, vol.status,
                "", "", "", "", "", "", "", "",
            ])

    content = output.getvalue()
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=volunteers_{show_id}.csv"},
    )


@router.post("/shows/{show_id}/volunteers/import.csv")
async def import_volunteers_csv(show_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    _require_show(db, show_id)

    raw = await file.read()
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    stats = {"volunteers_created": 0, "volunteers_updated": 0, "roles_created": 0, "shifts_created": 0, "assignments_created": 0, "rows_processed": 0}

    role_cache = {}
    existing_roles = db.execute(select(VolunteerRole).where(VolunteerRole.show_id == show_id)).scalars().all()
    for r in existing_roles:
        role_cache[r.name.strip().lower()] = r

    shift_cache = {}
    existing_shifts = db.execute(select(VolunteerShift).where(VolunteerShift.show_id == show_id)).scalars().all()
    for s in existing_shifts:
        role = role_cache.get("") or None
        for rn, ro in role_cache.items():
            if ro.id == s.role_id:
                role = ro
                break
        key = (s.role_id, s.starts_at.isoformat() if s.starts_at else "", s.ends_at.isoformat() if s.ends_at else "")
        shift_cache[key] = s

    for row in reader:
        stats["rows_processed"] += 1

        vol_name = (row.get("volunteer_name") or "").strip()
        vol_email = (row.get("email") or "").strip()
        vol_phone = (row.get("phone") or "").strip()
        vol_sms = (row.get("sms_opt_in") or "").strip().lower() in ("true", "1", "yes")
        vol_status = (row.get("status") or "pending").strip()
        role_name = (row.get("role_name") or "").strip()
        shift_start = (row.get("shift_starts_at") or "").strip()
        shift_end = (row.get("shift_ends_at") or "").strip()
        shift_location = (row.get("shift_location") or "").strip()

        if not vol_name:
            continue

        vol = None
        if vol_email:
            vol = db.execute(
                select(Volunteer).where(Volunteer.show_id == show_id, Volunteer.email == vol_email)
            ).scalar_one_or_none()
        if not vol:
            vol = db.execute(
                select(Volunteer).where(
                    Volunteer.show_id == show_id,
                    Volunteer.full_name == vol_name,
                    Volunteer.phone == vol_phone if vol_phone else Volunteer.phone.is_(None),
                )
            ).scalar_one_or_none()

        if vol:
            vol.full_name = vol_name
            if vol_email:
                vol.email = vol_email
            if vol_phone:
                vol.phone = vol_phone
            vol.sms_opt_in = vol_sms
            if vol_status:
                vol.status = vol_status
            stats["volunteers_updated"] += 1
        else:
            vol = Volunteer(
                show_id=show_id,
                full_name=vol_name,
                email=vol_email or None,
                phone=vol_phone or None,
                sms_opt_in=vol_sms,
                status=vol_status,
            )
            db.add(vol)
            db.flush()
            stats["volunteers_created"] += 1

        if not role_name or not shift_start or not shift_end:
            continue

        role_key = role_name.lower()
        if role_key not in role_cache:
            role = VolunteerRole(show_id=show_id, name=role_name)
            db.add(role)
            db.flush()
            role_cache[role_key] = role
            stats["roles_created"] += 1
        role = role_cache[role_key]

        shift_key = (role.id, shift_start, shift_end)
        if shift_key not in shift_cache:
            try:
                starts = datetime.fromisoformat(shift_start)
                ends = datetime.fromisoformat(shift_end)
            except ValueError:
                continue
            shift = VolunteerShift(
                show_id=show_id,
                role_id=role.id,
                starts_at=starts,
                ends_at=ends,
                location=shift_location or None,
            )
            db.add(shift)
            db.flush()
            shift_cache[shift_key] = shift
            stats["shifts_created"] += 1
        shift = shift_cache[shift_key]

        existing_a = db.execute(
            select(VolunteerAssignment).where(
                VolunteerAssignment.show_id == show_id,
                VolunteerAssignment.volunteer_id == vol.id,
                VolunteerAssignment.shift_id == shift.id,
            )
        ).scalar_one_or_none()
        if not existing_a:
            a = VolunteerAssignment(
                show_id=show_id,
                volunteer_id=vol.id,
                shift_id=shift.id,
                source="import",
            )
            db.add(a)
            stats["assignments_created"] += 1

    db.commit()
    return stats


@router.get("/shows/{show_id}/volunteers/printable")
def printable_schedule(show_id: str, db: Session = Depends(get_db)):
    show = _require_show(db, show_id)
    roles = db.execute(select(VolunteerRole).where(VolunteerRole.show_id == show_id)).scalars().all()
    shifts = db.execute(
        select(VolunteerShift).where(VolunteerShift.show_id == show_id).order_by(VolunteerShift.starts_at)
    ).scalars().all()
    assignments = db.execute(select(VolunteerAssignment).where(VolunteerAssignment.show_id == show_id)).scalars().all()
    vols = db.execute(select(Volunteer).where(Volunteer.show_id == show_id)).scalars().all()

    role_map = {r.id: r.name for r in roles}
    vol_map = {v.id: v for v in vols}
    shift_assignments = {}
    for a in assignments:
        shift_assignments.setdefault(a.shift_id, []).append(a)

    html_parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        "<style>",
        "body{font-family:Arial,sans-serif;margin:20px}",
        "h1{font-size:18px}h2{font-size:14px;margin-top:16px}",
        "table{border-collapse:collapse;width:100%;margin-bottom:12px}",
        "th,td{border:1px solid #333;padding:4px 8px;font-size:12px;text-align:left}",
        "th{background:#eee}",
        "@media print{body{margin:0}h1{font-size:16px}}",
        "</style></head><body>",
        f"<h1>Volunteer Schedule &mdash; {show.name}</h1>",
    ]

    for shift in shifts:
        rname = role_map.get(shift.role_id, "Unknown")
        start_str = shift.starts_at.strftime("%b %d %I:%M%p") if shift.starts_at else ""
        end_str = shift.ends_at.strftime("%I:%M%p") if shift.ends_at else ""
        loc = f" &mdash; {shift.location}" if shift.location else ""
        html_parts.append(f"<h2>{rname}: {start_str} – {end_str}{loc}</h2>")
        html_parts.append("<table><tr><th>#</th><th>Name</th><th>Phone</th><th>Status</th></tr>")

        assigned = shift_assignments.get(shift.id, [])
        if assigned:
            for i, a in enumerate(assigned, 1):
                v = vol_map.get(a.volunteer_id)
                name = v.full_name if v else "?"
                phone = v.phone or "" if v else ""
                html_parts.append(f"<tr><td>{i}</td><td>{name}</td><td>{phone}</td><td>{a.status}</td></tr>")
        else:
            html_parts.append(f"<tr><td colspan='4' style='text-align:center'>No volunteers assigned (capacity: {shift.capacity})</td></tr>")

        html_parts.append("</table>")

    html_parts.append("</body></html>")
    return Response(content="".join(html_parts), media_type="text/html")


@public_router.post("/volunteer-signup")
def public_volunteer_signup(
    token: str = Query(..., description="Public signup token"),
    data: PublicVolunteerSignup = ...,
    db: Session = Depends(get_db),
):
    show = db.execute(
        select(Show).where(Show.public_volunteer_token == token)
    ).scalar_one_or_none()
    if not show:
        raise HTTPException(status_code=404, detail="Invalid signup token")

    if data.email:
        existing = db.execute(
            select(Volunteer).where(Volunteer.show_id == show.id, Volunteer.email == data.email)
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="Volunteer with this email already signed up")

    vol = Volunteer(
        show_id=show.id,
        full_name=data.full_name,
        email=data.email,
        phone=data.phone,
        sms_opt_in=data.sms_opt_in or False,
        status="pending",
    )
    db.add(vol)
    db.commit()
    db.refresh(vol)
    return {
        "id": vol.id,
        "full_name": vol.full_name,
        "status": vol.status,
        "message": "Signup received. A coordinator will approve your registration.",
    }
