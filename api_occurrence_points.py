import os

import psycopg2
from fastapi import Depends, FastAPI, HTTPException, Request, Response, Security

from app.security import api_key_header, verify_owner_or_api_key

app = FastAPI()

DB = os.getenv("DATABASE_URL")


async def require_exact_occurrence_access(
    request: Request,
    api_key: str | None = Security(api_key_header),
) -> dict[str, object]:
    """Authorize internal exact-coordinate use without making it public.

    Exact coordinates are a legitimate scientific input for Orchid Continuum.
    This legacy endpoint therefore remains available to an authenticated owner
    session or the configured backend API key. It is not protected by a blanket
    kill switch because internal scientific use and public disclosure are
    different operations.

    Future partner-restricted records must still be filtered by their own
    record/project policy before reaching this legacy table or endpoint.
    """

    return await verify_owner_or_api_key(request, api_key)


@app.get("/orchid_points")
def orchid_points(
    response: Response,
    _identity: dict[str, object] = Depends(require_exact_occurrence_access),
):
    if not DB:
        raise HTTPException(status_code=503, detail="Database is not configured")

    # Raw exact coordinates must not be cached by browsers, proxies, or CDNs.
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"

    conn = psycopg2.connect(DB)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT decimal_latitude, decimal_longitude
            FROM oc_occurrences
            WHERE decimal_latitude IS NOT NULL
              AND decimal_longitude IS NOT NULL
            LIMIT 20000
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    points = [{"lat": r[0], "lon": r[1]} for r in rows]
    return {
        "points": points,
        "visibility": "authenticated_internal",
        "warning": (
            "Exact orchid locations for authorized internal scientific use; "
            "do not expose this response through a public client or cache."
        ),
    }
