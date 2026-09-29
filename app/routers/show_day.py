"""Show Day endpoints: plant QR tags, scan resolution and per-class results.

Phase 1 of the Calyx phased PRD ("Show Day"). These close the judging QR gaps
recorded by the show-management audit (``judging_qr_scan_resolution`` and
``judging_qr_image_render``) and add class placements computed only from
submitted scorecards, so a draft a judge is still editing never ranks a plant.
"""

import html
import os
from io import BytesIO
from typing import Annotated

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Exhibitor, JudgingEvent, Plant, PlantCategory, Scorecard
from app.security import verify_api_key

DbSession = Annotated[Session, Depends(get_db)]

router = APIRouter(prefix="/api", tags=["Show Day"], dependencies=[Depends(verify_api_key)])


def tag_payload(qr_token: str) -> str:
    """What a tag's QR code encodes.

    With ``CALYX_TAG_BASE_URL`` set (for example the frontend's scan page) the
    code is a link ending in the token; otherwise it is the bare token, which
    ``GET /api/judging/scan/{qr_token}`` resolves.
    """
    base = os.getenv("CALYX_TAG_BASE_URL", "").strip().rstrip("/")
    return f"{base}/{qr_token}" if base else qr_token


def _qr_svg(payload: str) -> str:
    image = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage, border=2)
    buffer = BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode("utf-8")


def _get_plant(db: Session, plant_id: str) -> Plant:
    plant = db.get(Plant, plant_id)
    if not plant:
        raise HTTPException(status_code=404, detail="Plant not found")
    return plant


def _get_event(db: Session, event_id: str) -> JudgingEvent:
    event = db.get(JudgingEvent, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Judging event not found")
    return event


def _exhibitor_name(db: Session, event: JudgingEvent, exhibitor_id: str) -> str | None:
    """Blind judging hides who grew the plant, on tags and on scans alike."""
    if event.is_blind:
        return None
    exhibitor = db.get(Exhibitor, exhibitor_id)
    return exhibitor.name if exhibitor else None


@router.get("/judging/plants/{plant_id}/qr.svg")
def plant_qr_svg(plant_id: str, db: DbSession):
    plant = _get_plant(db, plant_id)
    if not plant.qr_code:
        raise HTTPException(status_code=409, detail="Plant has no QR token")
    return Response(content=_qr_svg(tag_payload(plant.qr_code)), media_type="image/svg+xml")


@router.get("/judging/scan/{qr_token}")
def scan_plant(qr_token: str, db: DbSession):
    plant = db.execute(select(Plant).where(Plant.qr_code == qr_token)).scalar_one_or_none()
    if not plant:
        raise HTTPException(status_code=404, detail="No plant carries this QR token")
    event = _get_event(db, plant.judging_event_id)
    category = db.get(PlantCategory, plant.category_id)
    scorecards = db.execute(select(Scorecard).where(Scorecard.plant_id == plant.id)).scalars().all()
    return {
        "plant_id": plant.id,
        "plant_name": plant.name,
        "qr_code": plant.qr_code,
        "category_id": plant.category_id,
        "category_name": category.name if category else None,
        "judging_event_id": event.id,
        "judging_event_status": event.status,
        "exhibitor_name": _exhibitor_name(db, event, plant.exhibitor_id),
        "scorecards": {
            "total": len(scorecards),
            "submitted": sum(1 for s in scorecards if s.status == "submitted"),
        },
    }


@router.get("/judging/events/{event_id}/tags", response_class=HTMLResponse)
def printable_tags(
    event_id: str,
    db: DbSession,
    category_id: Annotated[str | None, Query()] = None,
):
    """A print-ready sheet of entry tags, grouped by class in schedule order."""
    event = _get_event(db, event_id)
    categories = db.execute(
        select(PlantCategory)
        .where(PlantCategory.judging_event_id == event_id)
        .order_by(PlantCategory.sort_order, PlantCategory.name)
    ).scalars().all()
    if category_id:
        categories = [c for c in categories if c.id == category_id]
        if not categories:
            raise HTTPException(status_code=404, detail="Category not found in this judging event")

    tags: list[str] = []
    for category in categories:
        plants = db.execute(
            select(Plant)
            .where(Plant.judging_event_id == event_id, Plant.category_id == category.id)
            .order_by(Plant.created_at, Plant.id)
        ).scalars().all()
        for number, plant in enumerate(plants, start=1):
            exhibitor = _exhibitor_name(db, event, plant.exhibitor_id)
            exhibitor_line = f'<div class="exhibitor">{html.escape(exhibitor)}</div>' if exhibitor else ""
            qr = _qr_svg(tag_payload(plant.qr_code)) if plant.qr_code else ""
            tags.append(
                '<div class="tag">'
                f'<div class="qr">{qr}</div>'
                f'<div class="class">{html.escape(category.name)} &middot; #{number}</div>'
                f'<div class="plant">{html.escape(plant.name or "Unnamed plant")}</div>'
                f"{exhibitor_line}"
                f'<div class="token">{html.escape(plant.qr_code or "")}</div>'
                "</div>"
            )

    title = html.escape(event.name or "Entry tags")
    body = "".join(tags) or "<p>No plants registered.</p>"
    page = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{title}</title><style>"
        "body{font-family:sans-serif;margin:12mm}"
        ".sheet{display:grid;grid-template-columns:repeat(3,1fr);gap:4mm}"
        ".tag{border:1px solid #000;padding:3mm;break-inside:avoid}"
        ".qr svg{width:28mm;height:28mm}"
        ".class{font-size:9pt}.plant{font-weight:bold;font-style:italic}"
        ".exhibitor{font-size:9pt}.token{font-family:monospace;font-size:8pt}"
        f"</style></head><body><h1>{title}</h1><div class=\"sheet\">{body}</div></body></html>"
    )
    return HTMLResponse(page)


def _competition_ranks(totals: list[float]) -> list[int]:
    """1, 2, 2, 4 ranking: tied totals share a place, the next place is skipped."""
    ranks: list[int] = []
    for index, total in enumerate(totals):
        ranks.append(ranks[-1] if index and total == totals[index - 1] else index + 1)
    return ranks


@router.get("/judging/events/{event_id}/class-results")
def class_results(event_id: str, db: DbSession):
    """Placements per class from submitted scorecards only.

    A plant with no submitted scorecard is listed as unplaced rather than
    ranked on drafts; ``pending_scorecards`` says how many cards are still out.
    """
    event = _get_event(db, event_id)
    categories = db.execute(
        select(PlantCategory)
        .where(PlantCategory.judging_event_id == event_id)
        .order_by(PlantCategory.sort_order, PlantCategory.name)
    ).scalars().all()
    scorecards = db.execute(select(Scorecard).where(Scorecard.judging_event_id == event_id)).scalars().all()
    cards_by_plant: dict[str, list[Scorecard]] = {}
    for card in scorecards:
        cards_by_plant.setdefault(card.plant_id, []).append(card)

    classes = []
    for category in categories:
        plants = db.execute(
            select(Plant).where(Plant.judging_event_id == event_id, Plant.category_id == category.id)
        ).scalars().all()
        scored, unplaced = [], []
        for plant in plants:
            cards = cards_by_plant.get(plant.id, [])
            submitted = [c.total for c in cards if c.status == "submitted" and c.total is not None]
            row = {
                "plant_id": plant.id,
                "plant_name": plant.name,
                "qr_code": plant.qr_code,
                "exhibitor_name": _exhibitor_name(db, event, plant.exhibitor_id),
                "submitted_scorecards": len(submitted),
                "pending_scorecards": sum(1 for c in cards if c.status != "submitted"),
                "average_total": round(sum(submitted) / len(submitted), 2) if submitted else None,
            }
            (scored if submitted else unplaced).append(row)
        scored.sort(key=lambda r: (-r["average_total"], r["plant_name"] or "", r["plant_id"]))
        for row, place in zip(scored, _competition_ranks([r["average_total"] for r in scored])):
            row["place"] = place
        for row in unplaced:
            row["place"] = None
        classes.append({
            "category_id": category.id,
            "category_name": category.name,
            "entries": scored + unplaced,
        })

    return {
        "judging_event_id": event.id,
        "judging_event_name": event.name,
        "status": event.status,
        "classes": classes,
    }
