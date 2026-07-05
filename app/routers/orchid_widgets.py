from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from app.database import get_engine
from app.routers.genus_experience import genus_experience as build_genus_experience

router = APIRouter(prefix="/api/widgets", tags=["Orchid Widgets"])


@router.get("/genus-of-day")
def genus_of_day(limit: int = 25):
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

        return {
            "widget": "genus_of_day",
            "count": len(rows),
            "items": [dict(row) for row in rows],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/genus-experience/{genus}")
def genus_experience_widget(genus: str, limit: int = Query(24, ge=1, le=100)):
    """OC-database-only Featured Genus payload.

    This intentionally lives under the already-mounted widgets router so BUILD-040
    can expose the rebuild without changing app/main.py. It delegates to the new
    app.routers.genus_experience implementation.
    """
    return build_genus_experience(genus=genus, limit=limit)
