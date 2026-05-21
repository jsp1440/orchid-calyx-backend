from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from app.database import engine

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
        with engine.connect() as conn:
            rows = conn.execute(sql, {"limit": limit}).mappings().all()

        return {
            "widget": "genus_of_day",
            "count": len(rows),
            "items": [dict(row) for row in rows],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
