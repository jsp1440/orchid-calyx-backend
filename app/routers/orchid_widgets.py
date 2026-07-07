from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.database import get_engine

# Keep this router as the single public Calyx authority for homepage genus media.
# The frontend must not call or fall back to external image-provider APIs.
router = APIRouter(prefix="/api", tags=["Orchid Widgets"])

# Reject obvious non-photographic or specimen/document URLs before a record can
# leave Calyx. This is deliberately conservative; source-specific quality flags
# can be added once their canonical columns are exposed in the widget view.
BLOCKED_MEDIA_RE = re.compile(
    r"(herbari|specimen|voucher|holotype|isotype|lectotype|sheet|barcode|"
    r"accession|preserved|pressed|exsiccat|illustration|plate|drawing|lineart|"
    r"\\.pdf(?:[?#]|$)|\\.(?:tif|tiff|djvu|docx?|csv|txt)(?:[?#]|$)|"
    r"biodiversitylibrary|archive\\.org|botanicus|jstor|recolnat|idigbio)",
    re.IGNORECASE,
)


def _normalize_genus(value: str) -> str:
    candidate = " ".join((value or "").strip().split())
    if not re.fullmatch(r"[A-Za-z-]+", candidate):
        raise HTTPException(status_code=400, detail="Genus must contain letters only.")
    return candidate[:1].upper() + candidate[1:].lower()


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url or not re.match(r"^https?://", url, re.IGNORECASE):
        return None
    if BLOCKED_MEDIA_RE.search(url):
        return None
    return url


@router.get("/widgets/genus-of-day")
def genus_of_day(limit: int = 25):
    """Legacy-compatible widget endpoint, now retained under /api/widgets."""
    limit = max(1, min(limit, 50))
    sql = text("""
        SELECT
            genus,
            taxonomy_id,
            accepted_scientific_name,
            species,
            hero_image,
            image_count,
            climate_tag,
            collection_tag,
            min_elevation,
            max_elevation
        FROM oc_widget.v_genus_of_day_cards
        LIMIT :limit;
    """)
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(sql, {"limit": limit}).mappings().all()
        return {"widget": "genus_of_day", "count": len(rows), "items": [dict(row) for row in rows]}
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to load genus-of-day widget data.") from exc


@router.get("/media/genus/{genus}")
def genus_media(genus: str, limit: int = Query(default=12, ge=1, le=24)):
    """Return approved homepage media for one genus from the OC widget data path.

    This endpoint is intentionally read-only. It does not call iNaturalist, GBIF,
    Plantae, Wikimedia, or any other external provider. It returns only media
    already linked to accepted taxon rows in the Orchid Continuum widget view.
    """
    accepted_genus = _normalize_genus(genus)
    sql = text("""
        SELECT
            genus,
            taxonomy_id,
            accepted_scientific_name,
            species,
            hero_image,
            image_count,
            collection_tag
        FROM oc_widget.v_genus_of_day_cards
        WHERE lower(genus) = lower(:genus)
        ORDER BY accepted_scientific_name ASC NULLS LAST, taxonomy_id ASC NULLS LAST
        LIMIT :scan_limit;
    """)

    exclusion_counts = {
        "herbarium_or_specimen": 0,
        "illustration_or_plate": 0,
        "document_or_scan": 0,
        "missing_taxon_link": 0,
        "unapproved_or_low_confidence": 0,
        "missing_usable_url": 0,
    }

    try:
        with get_engine().connect() as conn:
            rows = conn.execute(sql, {"genus": accepted_genus, "scan_limit": max(limit * 8, 48)}).mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to query Calyx genus media.") from exc

    if not rows:
        return {
            "status": "invalid_genus",
            "requested_genus": genus,
            "accepted_genus": None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": [],
            "summary": {"eligible_count": 0, "returned_count": 0, "exclusion_counts": exclusion_counts},
        }

    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        taxon_id = row.get("taxonomy_id")
        scientific_name = row.get("accepted_scientific_name") or row.get("species")
        if not taxon_id or not scientific_name:
            exclusion_counts["missing_taxon_link"] += 1
            continue

        raw_url = row.get("hero_image")
        url = _safe_url(raw_url)
        if not url:
            raw_text = str(raw_url or "")
            if BLOCKED_MEDIA_RE.search(raw_text):
                if re.search(r"illustration|plate|drawing|lineart", raw_text, re.IGNORECASE):
                    exclusion_counts["illustration_or_plate"] += 1
                elif re.search(r"pdf|tif|tiff|djvu|docx?|csv|txt", raw_text, re.IGNORECASE):
                    exclusion_counts["document_or_scan"] += 1
                else:
                    exclusion_counts["herbarium_or_specimen"] += 1
            else:
                exclusion_counts["missing_usable_url"] += 1
            continue

        key = (str(taxon_id), url)
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "media_id": f"oc-widget:{taxon_id}:{len(items) + 1}",
                "taxon_id": str(taxon_id),
                "scientific_name": str(scientific_name),
                "genus": accepted_genus,
                "image_url": url,
                "thumbnail_url": url,
                "source_name": "Orchid Continuum linked widget media",
                "source_record_url": None,
                "license": None,
                "attribution": row.get("collection_tag") or None,
                "media_kind": "photograph",
                "quality_score": None,
            }
        )
        if len(items) >= limit:
            break

    status = "ok" if items else "no_approved_media"
    return {
        "status": status,
        "requested_genus": genus,
        "accepted_genus": accepted_genus,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "summary": {
            "eligible_count": len(items),
            "returned_count": len(items),
            "exclusion_counts": exclusion_counts,
        },
    }
