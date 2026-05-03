# orchid_api.py
# Full replacement script for Orchid Continuum API

import os
import sys

if os.getenv("OC_ALLOW_LEGACY_OC_SCRIPT_RUN") != "YES_I_UNDERSTAND_THIS_CAN_WRITE_TO_PRODUCTION":
    print("BLOCKED: This legacy Orchid Continuum/Calyx root-level script is write-capable or schema-stale and is disabled by default.")
    print("This safety guard prevents accidental production database writes.")
    print("To run intentionally, set OC_ALLOW_LEGACY_OC_SCRIPT_RUN=YES_I_UNDERSTAND_THIS_CAN_WRITE_TO_PRODUCTION after manual review.")
    sys.exit(2)

import psycopg2
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

DB = os.getenv("DATABASE_URL")

if not DB:
    raise RuntimeError("DATABASE_URL environment variable is not set")

app = FastAPI(title="Orchid Continuum API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_conn():
    return psycopg2.connect(DB)


@app.get("/")
def root():
    return {"status": "ok", "service": "Orchid Continuum API"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/db/ping")
def db_ping():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM oc_occurrences;")
        n = cur.fetchone()[0]
        cur.close()
        conn.close()
        return {"database": "connected", "occurrences": n}
    except Exception as e:
        return {"database": "error", "detail": str(e)}


@app.get("/api/occurrences")
def occurrences(limit: int = 20000):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT decimal_latitude, decimal_longitude
            FROM oc_occurrences
            WHERE decimal_latitude IS NOT NULL
              AND decimal_longitude IS NOT NULL
            LIMIT %s;
            """, (limit, ))
        rows = cur.fetchall()
        cur.close()
        conn.close()

        points = [{
            "lat": row[0],
            "lon": row[1]
        } for row in rows if row[0] is not None and row[1] is not None]

        return {"status": "ok", "count": len(points), "points": points}
    except Exception as e:
        return {"status": "error", "detail": str(e), "points": []}


@app.get("/api/taxa")
def taxa():
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT COUNT(DISTINCT species_id)
            FROM oc_occurrences
            WHERE species_id IS NOT NULL;
        """)
        species_count = cur.fetchone()[0] or 0

        cur.execute("""
            SELECT COUNT(DISTINCT genus_id)
            FROM oc_occurrences
            WHERE genus_id IS NOT NULL;
        """)
        genus_count = cur.fetchone()[0] or 0

        cur.close()
        conn.close()

        return {
            "status": "ok",
            "species_count": species_count,
            "genus_count": genus_count
        }
    except Exception as e:
        return {
            "status": "error",
            "detail": str(e),
            "species_count": 0,
            "genus_count": 0
        }


@app.get("/api/elevation")
def elevation():
    try:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                MIN(elevation_m),
                MAX(elevation_m),
                AVG(elevation_m)
            FROM oc_occurrences
            WHERE elevation_m IS NOT NULL;
        """)
        row = cur.fetchone()

        cur.close()
        conn.close()

        return {"status": "ok", "min": row[0], "max": row[1], "avg": row[2]}
    except Exception as e:
        return {
            "status": "error",
            "detail": str(e),
            "min": None,
            "max": None,
            "avg": None
        }


@app.get("/api/climate")
def climate():
    return {"status": "ok", "message": "climate endpoint placeholder"}


@app.get("/api/images")
def images():
    return {"status": "ok", "message": "images endpoint placeholder"}


@app.get("/api/vision/analyze")
def vision_analyze():
    return {"status": "ok", "message": "vision endpoint placeholder"}
