from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import text

from app.database import get_engine
from app.readiness.live_graph_audit import run_live_graph_audit

router = APIRouter(prefix="/api", tags=["Orchid Widgets"])

_ALLOWED_MEDIA_ORIGINS = {
    "https://orchidcontinuum.org",
    "https://www.orchidcontinuum.org",
    "https://beta.orchidcontinuum.org",
    "https://orchid-continuum-frontend-vof6.onrender.com",
}

# Server-side rejection of records that do not belong in the public photograph
# gallery. The frontend receives only media Calyx has already filtered.
BLOCKED_MEDIA_RE = re.compile(
    r"(herbari|specimen|voucher|holotype|isotype|lectotype|sheet|barcode|"
    r"accession|preserved|pressed|exsiccat|illustration|plate|drawing|lineart|"
    r"\.pdf(?:[?#]|$)|\.(?:tif|tiff|djvu|docx?|csv|txt)(?:[?#]|$)|"
    r"biodiversitylibrary|archive\.org|botanicus|jstor|recolnat|idigbio)",
    re.IGNORECASE,
)


def _allow_frontend_origin(request: Request, response: Response) -> None:
    """Allow the public Orchid Continuum frontend to read this JSON response."""
    origin = request.headers.get("origin")
    if origin in _ALLOWED_MEDIA_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"


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


def _record_url(source: str | None, occurrence_key: str | None) -> str | None:
    if source and occurrence_key and "gbif" in source.lower():
        return f"https://www.gbif.org/occurrence/{occurrence_key}"
    return None


@router.options("/media/genus/{genus}")
def genus_media_options(genus: str, request: Request, response: Response):
    _allow_frontend_origin(request, response)
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Accept, Content-Type"
    return Response(status_code=204, headers=dict(response.headers))


@router.get("/widgets/genus-of-day")
def genus_of_day(limit: int = 25):
    """Legacy-compatible endpoint retained for pages outside Featured Genus."""
    limit = max(1, min(limit, 50))
    sql = text("""
        SELECT genus, taxonomy_id, accepted_scientific_name, species, hero_image,
               image_count, climate_tag, collection_tag, min_elevation, max_elevation
        FROM oc_widget.v_genus_of_day_cards
        LIMIT :limit;
    """)
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(sql, {"limit": limit}).mappings().all()
        return {"widget": "genus_of_day", "count": len(rows), "items": [dict(row) for row in rows]}
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to load genus-of-day widget data.") from exc


@router.get("/platform/readiness/homepage")
def homepage_readiness(request: Request, response: Response) -> dict[str, Any]:
    """Measure live relational linkage and persisted graph materialization.

    This endpoint is read-only. It deliberately does not equate a relational
    taxonomy foreign key with a persisted Knowledge Graph edge.
    """
    _allow_frontend_origin(request, response)
    raw = None
    try:
        raw = get_engine().raw_connection()
        cursor = raw.cursor()
        try:
            return run_live_graph_audit(cursor)
        finally:
            cursor.close()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Live homepage readiness audit is unavailable.",
        ) from exc
    finally:
        if raw is not None:
            raw.close()


@router.get("/media/genus/{genus}")
def genus_media(
    genus: str,
    request: Request,
    response: Response,
    limit: int = Query(default=12, ge=1, le=24),
):
    """Resolve Featured Genus photographs from canonical OC taxonomy/media rows.

    The endpoint is read-only. It does not call any external provider API. It
    intentionally excludes iNaturalist-source records for this homepage feature,
    because the legacy iNaturalist hero behavior is what this build replaces.
    """
    _allow_frontend_origin(request, response)
    accepted_genus = _normalize_genus(genus)
    exclusion_counts = {
        "herbarium_or_specimen": 0,
        "illustration_or_plate": 0,
        "document_or_scan": 0,
        "missing_taxon_link": 0,
        "unapproved_or_low_confidence": 0,
        "missing_usable_url": 0,
    }

    taxonomy_sql = text("""
        SELECT 1
        FROM public.orchid_taxonomy
        WHERE lower(genus) = lower(:genus)
        LIMIT 1
    """)
    media_sql = text("""
        SELECT
            i.id AS image_id,
            i.taxonomy_id,
            t.scientific_name,
            t.genus,
            i.image_url,
            i.image_source,
            i.image_license,
            i.image_rights_holder,
            i.observer_name,
            i.gbif_occurrence_key,
            i.image_type,
            i.image_description,
            i.alt_text,
            i.is_duplicate
        FROM public.orchid_images AS i
        JOIN public.orchid_taxonomy AS t ON t.id = i.taxonomy_id
        WHERE lower(t.genus) = lower(:genus)
          AND i.image_url IS NOT NULL
          AND NULLIF(trim(COALESCE(i.image_source, '')), '') IS NOT NULL
          AND COALESCE(i.is_duplicate, false) = false
          AND COALESCE(lower(i.image_source), '') NOT LIKE '%inaturalist%'
        ORDER BY
          CASE
            WHEN lower(COALESCE(i.image_source, '')) LIKE '%eol%' THEN 0
            WHEN lower(COALESCE(i.image_source, '')) LIKE '%gbif%' THEN 1
            ELSE 2
          END,
          i.id ASC
        LIMIT :scan_limit
    """)

    try:
        with get_engine().connect() as conn:
            exists = conn.execute(taxonomy_sql, {"genus": accepted_genus}).first()
            if not exists:
                return {
                    "status": "invalid_genus",
                    "requested_genus": genus,
                    "accepted_genus": None,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "items": [],
                    "summary": {"eligible_count": 0, "returned_count": 0, "exclusion_counts": exclusion_counts},
                }
            rows = conn.execute(
                media_sql,
                {"genus": accepted_genus, "scan_limit": max(limit * 12, 120)},
            ).mappings().all()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Unable to query canonical Orchid Continuum media.") from exc

    items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for row in rows:
        text_fields = " ".join(
            str(row.get(key) or "")
            for key in ("image_type", "image_description", "alt_text", "image_url")
        )
        if BLOCKED_MEDIA_RE.search(text_fields):
            if re.search(r"illustration|plate|drawing|lineart", text_fields, re.IGNORECASE):
                exclusion_counts["illustration_or_plate"] += 1
            elif re.search(r"pdf|tif|tiff|djvu|docx?|csv|txt", text_fields, re.IGNORECASE):
                exclusion_counts["document_or_scan"] += 1
            else:
                exclusion_counts["herbarium_or_specimen"] += 1
            continue

        url = _safe_url(row.get("image_url"))
        if not url:
            exclusion_counts["missing_usable_url"] += 1
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        source_name = str(row.get("image_source") or "").strip()
        items.append(
            {
                "media_id": f"oc-image:{row['image_id']}",
                "taxon_id": str(row["taxonomy_id"]),
                "scientific_name": str(row["scientific_name"]),
                "genus": str(row["genus"]),
                "image_url": url,
                "thumbnail_url": url,
                "source_name": source_name,
                "source_record_url": _record_url(source_name, row.get("gbif_occurrence_key")),
                "license": row.get("image_license") or None,
                "attribution": row.get("image_rights_holder") or row.get("observer_name") or None,
                "media_kind": "photograph",
                "quality_score": None,
            }
        )
        if len(items) >= limit:
            break

    return {
        "status": "ok" if items else "no_approved_media",
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
