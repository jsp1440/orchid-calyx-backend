import hmac
import os

import psycopg2
from fastapi import Depends, FastAPI, Header, HTTPException

app = FastAPI()

DB = os.getenv("DATABASE_URL")
_EXACT_LOCATION_ENABLE_VALUE = "YES_I_UNDERSTAND_THIS_EXPOSES_EXACT_ORCHID_LOCATIONS"


def require_exact_occurrence_access(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """Fail closed for the legacy exact-coordinate occurrence endpoint.

    This standalone API predates partner-data governance and returns raw latitude
    and longitude from the legacy occurrence table.  It must never become public
    merely because somebody starts the FastAPI module.
    """

    if os.getenv("OC_ALLOW_EXACT_OCCURRENCE_API") != _EXACT_LOCATION_ENABLE_VALUE:
        raise HTTPException(
            status_code=503,
            detail="Exact occurrence API is disabled by security policy",
        )

    expected = os.getenv("CALYX_API_KEY")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Exact occurrence API authentication is not configured",
        )
    if not x_api_key or not hmac.compare_digest(
        x_api_key.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.get("/orchid_points", dependencies=[Depends(require_exact_occurrence_access)])
def orchid_points():
    if not DB:
        raise HTTPException(status_code=503, detail="Database is not configured")

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
        "warning": "Exact orchid locations; restricted legacy endpoint",
    }
