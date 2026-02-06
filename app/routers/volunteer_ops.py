import csv
import io
from datetime import datetime, time, date
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
    VolunteerSignup,
    VolunteerAttendance,
)
from app.schemas import (
    VolunteerRoleCreate,
    VolunteerRoleOut,
    VolunteerShiftCreate,
    VolunteerShiftOut,
    VolunteerCreate,
    VolunteerOut,
    VolunteerSignupCreate,
    VolunteerSignupOut,
    VolunteerSignupMove,
    AttendanceRequest,
    AttendanceOut,
)
from app.security import verify_api_key

router = APIRouter(
    prefix="/api/shows/{show_id}/volunteer",
    tags=["Volunteer Operations"],
    dependencies=[Depends(verify_api_key)],
)


def _require_show(db: Session, show_id: str) -> Show:
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(status_code=404, detail="Show not found")
    return show


def _time_str(t) -> str:
    if isinstance(t, time):
        return t.strftime("%H:%M")
    return str(t) if t else ""


def _shift_to_out(s) -> dict:
    return {
        "id": s.id,
        "show_id": s.show_id,
        "role_id": s.role_id,
        "shift_date": s.shift_date,
        "start_time": _time_str(s.start_time),
        "end_time": _time_str(s.end_time),
        "slots_needed": s.slots_needed,
        "notes": s.notes,
        "created_at": s.created_at,
    }


@router.post("/roles", response_model=VolunteerRoleOut)
def create_role(show_id: str, data: VolunteerRoleCreate, db: Session = Depends(get_db)):
    _require_show(db, show_id)
    role = VolunteerRole(show_id=show_id, **data.model_dump())
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


@router.get("/roles", response_model=List[VolunteerRoleOut])
def list_roles(show_id: str, db: Session = Depends(get_db)):
    return db.execute(select(VolunteerRole).where(VolunteerRole.show_id == show_id)).scalars().all()


@router.post("/shifts")
def create_shift(show_id: str, data: VolunteerShiftCreate, db: Session = Depends(get_db)):
    _require_show(db, show_id)
    role = db.get(VolunteerRole, data.role_id)
    if not role or role.show_id != show_id:
        raise HTTPException(status_code=404, detail="Role not found for this show")

    try:
        st = time.fromisoformat(data.start_time)
        et = time.fromisoformat(data.end_time)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid time format. Use HH:MM or HH:MM:SS")

    shift = VolunteerShift(
        show_id=show_id,
        role_id=data.role_id,
        shift_date=data.shift_date,
        start_time=st,
        end_time=et,
        slots_needed=data.slots_needed or 1,
        notes=data.notes,
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return _shift_to_out(shift)


@router.get("/shifts")
def list_shifts(show_id: str, db: Session = Depends(get_db)):
    shifts = db.execute(
        select(VolunteerShift).where(VolunteerShift.show_id == show_id)
    ).scalars().all()
    return [_shift_to_out(s) for s in shifts]


@router.patch("/shifts/{shift_id}")
def update_shift(show_id: str, shift_id: str, db: Session = Depends(get_db),
                 role_id: Optional[str] = None, shift_date: Optional[str] = None,
                 start_time: Optional[str] = None, end_time: Optional[str] = None,
                 slots_needed: Optional[int] = None, notes: Optional[str] = None):
    shift = db.get(VolunteerShift, shift_id)
    if not shift or shift.show_id != show_id:
        raise HTTPException(status_code=404, detail="Shift not found")
    if role_id is not None:
        shift.role_id = role_id
    if shift_date is not None:
        shift.shift_date = date.fromisoformat(shift_date)
    if start_time is not None:
        shift.start_time = time.fromisoformat(start_time)
    if end_time is not None:
        shift.end_time = time.fromisoformat(end_time)
    if slots_needed is not None:
        shift.slots_needed = slots_needed
    if notes is not None:
        shift.notes = notes
    db.commit()
    db.refresh(shift)
    return _shift_to_out(shift)


@router.delete("/shifts/{shift_id}")
def delete_shift(show_id: str, shift_id: str, db: Session = Depends(get_db)):
    shift = db.get(VolunteerShift, shift_id)
    if not shift or shift.show_id != show_id:
        raise HTTPException(status_code=404, detail="Shift not found")
    db.delete(shift)
    db.commit()
    return {"status": "deleted"}


@router.post("/volunteers", response_model=VolunteerOut)
def create_volunteer(show_id: str, data: VolunteerCreate, db: Session = Depends(get_db)):
    _require_show(db, show_id)
    vol = Volunteer(show_id=show_id, **data.model_dump())
    db.add(vol)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Volunteer with this email already exists for this show")
    db.refresh(vol)
    return vol


@router.get("/volunteers", response_model=List[VolunteerOut])
def list_volunteers(show_id: str, db: Session = Depends(get_db)):
    return db.execute(select(Volunteer).where(Volunteer.show_id == show_id)).scalars().all()


@router.post("/signups", response_model=VolunteerSignupOut)
def create_signup(show_id: str, data: VolunteerSignupCreate, db: Session = Depends(get_db)):
    _require_show(db, show_id)

    vol = db.get(Volunteer, data.volunteer_id)
    if not vol or vol.show_id != show_id:
        raise HTTPException(status_code=404, detail="Volunteer not found for this show")

    shift = db.get(VolunteerShift, data.shift_id)
    if not shift or shift.show_id != show_id:
        raise HTTPException(status_code=404, detail="Shift not found for this show")

    current = db.execute(
        select(func.count(VolunteerSignup.id)).where(
            VolunteerSignup.shift_id == data.shift_id,
        )
    ).scalar_one()
    if current >= shift.slots_needed:
        raise HTTPException(status_code=409, detail="Shift slots full")

    signup = VolunteerSignup(
        show_id=show_id,
        shift_id=data.shift_id,
        volunteer_id=data.volunteer_id,
        signup_source=data.signup_source or "self",
    )
    db.add(signup)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Volunteer already signed up for this shift")
    db.refresh(signup)
    return signup


@router.get("/signups", response_model=List[VolunteerSignupOut])
def list_signups(show_id: str, db: Session = Depends(get_db)):
    return db.execute(
        select(VolunteerSignup).where(VolunteerSignup.show_id == show_id)
    ).scalars().all()


@router.patch("/signups/{signup_id}/approve", response_model=VolunteerSignupOut)
def approve_signup(show_id: str, signup_id: str,
                   approved_by: Optional[str] = Query(None),
                   db: Session = Depends(get_db)):
    signup = db.get(VolunteerSignup, signup_id)
    if not signup or signup.show_id != show_id:
        raise HTTPException(status_code=404, detail="Signup not found")
    signup.approved = True
    signup.approved_by = approved_by
    signup.approved_at = datetime.utcnow()
    db.commit()
    db.refresh(signup)
    return signup


@router.patch("/signups/{signup_id}/move", response_model=VolunteerSignupOut)
def move_signup(show_id: str, signup_id: str, data: VolunteerSignupMove, db: Session = Depends(get_db)):
    signup = db.get(VolunteerSignup, signup_id)
    if not signup or signup.show_id != show_id:
        raise HTTPException(status_code=404, detail="Signup not found")

    new_shift = db.get(VolunteerShift, data.shift_id)
    if not new_shift or new_shift.show_id != show_id:
        raise HTTPException(status_code=404, detail="Target shift not found")

    existing = db.execute(
        select(VolunteerSignup).where(
            VolunteerSignup.shift_id == data.shift_id,
            VolunteerSignup.volunteer_id == signup.volunteer_id,
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Volunteer already signed up for target shift")

    current = db.execute(
        select(func.count(VolunteerSignup.id)).where(
            VolunteerSignup.shift_id == data.shift_id,
        )
    ).scalar_one()
    if current >= new_shift.slots_needed:
        raise HTTPException(status_code=409, detail="Target shift slots full")

    signup.shift_id = data.shift_id
    db.commit()
    db.refresh(signup)
    return signup


@router.delete("/signups/{signup_id}")
def delete_signup(show_id: str, signup_id: str, db: Session = Depends(get_db)):
    signup = db.get(VolunteerSignup, signup_id)
    if not signup or signup.show_id != show_id:
        raise HTTPException(status_code=404, detail="Signup not found")
    db.delete(signup)
    db.commit()
    return {"status": "deleted"}


@router.post("/attendance/check-in", response_model=AttendanceOut)
def attendance_checkin(show_id: str, data: AttendanceRequest, db: Session = Depends(get_db)):
    _require_show(db, show_id)

    existing = db.execute(
        select(VolunteerAttendance).where(
            VolunteerAttendance.show_id == show_id,
            VolunteerAttendance.volunteer_id == data.volunteer_id,
            VolunteerAttendance.shift_id == data.shift_id,
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

    att = VolunteerAttendance(
        show_id=show_id,
        shift_id=data.shift_id,
        volunteer_id=data.volunteer_id,
        check_in_at=datetime.utcnow(),
        method=data.method or "web",
    )
    db.add(att)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate attendance record")
    db.refresh(att)
    return att


@router.post("/attendance/check-out", response_model=AttendanceOut)
def attendance_checkout(show_id: str, data: AttendanceRequest, db: Session = Depends(get_db)):
    existing = db.execute(
        select(VolunteerAttendance).where(
            VolunteerAttendance.show_id == show_id,
            VolunteerAttendance.volunteer_id == data.volunteer_id,
            VolunteerAttendance.shift_id == data.shift_id,
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


@router.get("/export.csv")
def export_csv(show_id: str, db: Session = Depends(get_db)):
    _require_show(db, show_id)

    roles = {r.id: r for r in db.execute(select(VolunteerRole).where(VolunteerRole.show_id == show_id)).scalars().all()}
    shifts = {s.id: s for s in db.execute(select(VolunteerShift).where(VolunteerShift.show_id == show_id)).scalars().all()}
    vols = {v.id: v for v in db.execute(select(Volunteer).where(Volunteer.show_id == show_id)).scalars().all()}
    signups = db.execute(select(VolunteerSignup).where(VolunteerSignup.show_id == show_id)).scalars().all()
    attendances = db.execute(select(VolunteerAttendance).where(VolunteerAttendance.show_id == show_id)).scalars().all()
    att_map = {(a.volunteer_id, a.shift_id): a for a in attendances}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "volunteer_name", "email", "phone", "status",
        "role_name", "shift_date", "start_time", "end_time",
        "signup_source", "approved", "approved_by",
        "check_in_at", "check_out_at",
    ])

    if signups:
        for su in signups:
            vol = vols.get(su.volunteer_id)
            shift = shifts.get(su.shift_id)
            role = roles.get(shift.role_id) if shift else None
            att = att_map.get((su.volunteer_id, su.shift_id))
            writer.writerow([
                vol.name if vol else "",
                vol.email if vol else "",
                vol.phone if vol else "",
                vol.status if vol else "",
                role.name if role else "",
                str(shift.shift_date) if shift else "",
                _time_str(shift.start_time) if shift else "",
                _time_str(shift.end_time) if shift else "",
                su.signup_source,
                su.approved,
                su.approved_by or "",
                att.check_in_at.isoformat() if att and att.check_in_at else "",
                att.check_out_at.isoformat() if att and att.check_out_at else "",
            ])
    else:
        for vol in vols.values():
            writer.writerow([
                vol.name, vol.email, vol.phone, vol.status,
                "", "", "", "", "", "", "", "", "",
            ])

    content = output.getvalue()
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=volunteers_{show_id}.csv"},
    )


@router.post("/import")
async def import_volunteers(show_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    _require_show(db, show_id)

    raw = await file.read()
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    stats = {
        "volunteers_created": 0, "volunteers_updated": 0,
        "roles_created": 0, "shifts_created": 0,
        "signups_created": 0, "rows_processed": 0,
    }

    role_cache = {}
    for r in db.execute(select(VolunteerRole).where(VolunteerRole.show_id == show_id)).scalars().all():
        role_cache[r.name.strip().lower()] = r

    shift_cache = {}
    for s in db.execute(select(VolunteerShift).where(VolunteerShift.show_id == show_id)).scalars().all():
        key = (s.role_id, str(s.shift_date), _time_str(s.start_time), _time_str(s.end_time))
        shift_cache[key] = s

    for row in reader:
        stats["rows_processed"] += 1

        vol_name = (row.get("volunteer_name") or "").strip()
        vol_email = (row.get("email") or "").strip()
        vol_phone = (row.get("phone") or "").strip()
        vol_status = (row.get("status") or "pending").strip()
        role_name = (row.get("role_name") or "").strip()
        s_date = (row.get("shift_date") or "").strip()
        s_start = (row.get("start_time") or "").strip()
        s_end = (row.get("end_time") or "").strip()

        if not vol_name or not vol_email:
            continue

        vol = db.execute(
            select(Volunteer).where(Volunteer.show_id == show_id, Volunteer.email == vol_email)
        ).scalar_one_or_none()

        if vol:
            vol.name = vol_name
            if vol_phone:
                vol.phone = vol_phone
            if vol_status:
                vol.status = vol_status
            stats["volunteers_updated"] += 1
        else:
            vol = Volunteer(
                show_id=show_id,
                name=vol_name,
                email=vol_email,
                phone=vol_phone or None,
                status=vol_status,
            )
            db.add(vol)
            db.flush()
            stats["volunteers_created"] += 1

        if not role_name or not s_date or not s_start or not s_end:
            continue

        rkey = role_name.lower()
        if rkey not in role_cache:
            role = VolunteerRole(show_id=show_id, name=role_name)
            db.add(role)
            db.flush()
            role_cache[rkey] = role
            stats["roles_created"] += 1
        role = role_cache[rkey]

        try:
            sd = date.fromisoformat(s_date)
            st = time.fromisoformat(s_start)
            et = time.fromisoformat(s_end)
        except ValueError:
            continue

        skey = (role.id, str(sd), _time_str(st), _time_str(et))
        if skey not in shift_cache:
            shift = VolunteerShift(
                show_id=show_id, role_id=role.id,
                shift_date=sd, start_time=st, end_time=et,
            )
            db.add(shift)
            db.flush()
            shift_cache[skey] = shift
            stats["shifts_created"] += 1
        shift = shift_cache[skey]

        existing_su = db.execute(
            select(VolunteerSignup).where(
                VolunteerSignup.shift_id == shift.id,
                VolunteerSignup.volunteer_id == vol.id,
            )
        ).scalar_one_or_none()
        if not existing_su:
            su = VolunteerSignup(
                show_id=show_id,
                shift_id=shift.id,
                volunteer_id=vol.id,
                signup_source="coordinator",
            )
            db.add(su)
            stats["signups_created"] += 1

    db.commit()
    return stats


@router.get("/printable")
def printable_schedule(show_id: str, db: Session = Depends(get_db)):
    show = _require_show(db, show_id)
    roles = {r.id: r.name for r in db.execute(select(VolunteerRole).where(VolunteerRole.show_id == show_id)).scalars().all()}
    shifts = db.execute(
        select(VolunteerShift).where(VolunteerShift.show_id == show_id)
        .order_by(VolunteerShift.shift_date, VolunteerShift.start_time)
    ).scalars().all()
    signups = db.execute(select(VolunteerSignup).where(VolunteerSignup.show_id == show_id)).scalars().all()
    vols = {v.id: v for v in db.execute(select(Volunteer).where(Volunteer.show_id == show_id)).scalars().all()}

    shift_signups = {}
    for su in signups:
        shift_signups.setdefault(su.shift_id, []).append(su)

    html = [
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
        rname = roles.get(shift.role_id, "Unknown")
        html.append(
            f"<h2>{rname}: {shift.shift_date} {_time_str(shift.start_time)}&ndash;{_time_str(shift.end_time)}</h2>"
        )
        html.append("<table><tr><th>#</th><th>Name</th><th>Phone</th><th>Approved</th></tr>")
        assigned = shift_signups.get(shift.id, [])
        if assigned:
            for i, su in enumerate(assigned, 1):
                v = vols.get(su.volunteer_id)
                html.append(
                    f"<tr><td>{i}</td><td>{v.name if v else '?'}</td>"
                    f"<td>{v.phone or '' if v else ''}</td>"
                    f"<td>{'Yes' if su.approved else 'No'}</td></tr>"
                )
        else:
            html.append(f"<tr><td colspan='4' style='text-align:center'>No signups (slots: {shift.slots_needed})</td></tr>")
        html.append("</table>")

    html.append("</body></html>")
    return Response(content="".join(html), media_type="text/html")
