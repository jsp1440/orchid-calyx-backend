import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import (
    health,
    tiles,
    shows,
    entries,
    volunteers,
    awards,
    calyx_core,
    reference_docs,
    judging,
)
from app.routers.volunteer_ops import router as volunteer_ops_router, public_router as volunteer_public_router

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("calyx")

app = FastAPI(
    title="Calyx - Orchid Show Management System",
    description="Backend API for orchid show operations, entries, volunteers, and judging. Powered by Orchid Continuum.",
    version="1.0.0",
)

# ---- CORS ----
# Prefer CORS_ALLOW_ORIGINS (comma-separated). Fall back to CORS_ALLOW_ORIGIN if that's what your secrets use.
cors_env = os.getenv("CORS_ALLOW_ORIGINS") or os.getenv("CORS_ALLOW_ORIGIN") or "*"
cors_env = cors_env.strip()

if cors_env == "*" or cors_env == "":
    allow_origins = ["*"]
else:
    allow_origins = [o.strip() for o in cors_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Routers ----
app.include_router(health.router)
app.include_router(tiles.router)
app.include_router(shows.router)
app.include_router(entries.router)
app.include_router(volunteers.router)
app.include_router(awards.router)
app.include_router(calyx_core.router)

# Keep reference docs under /api, tagged clearly
app.include_router(reference_docs.router, prefix="/api", tags=["Reference Documents"])

# Judging router already uses prefix="/api" internally (per your file), so include directly
app.include_router(judging.router)

# Volunteer operations (full module: roles, shifts, directory, assignments, check-in/out, export/import)
app.include_router(volunteer_ops_router)
app.include_router(volunteer_public_router)


@app.get("/")
def root():
    return {"status": "ok", "app": "Calyx", "docs": "/docs"}


def _safe_add_column(engine, table_name: str, col_name: str, col_type: str):
    from sqlalchemy import text, inspect as sa_inspect
    insp = sa_inspect(engine)
    if table_name not in insp.get_table_names():
        return
    existing = [c["name"] for c in insp.get_columns(table_name)]
    if col_name not in existing:
        try:
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))
                conn.commit()
            log.info("Added column %s.%s", table_name, col_name)
        except Exception as e:
            log.warning("Could not add column %s.%s: %s", table_name, col_name, e)


def _reconcile_schema(engine):
    from sqlalchemy import inspect as sa_inspect
    insp = sa_inspect(engine)
    existing_tables = insp.get_table_names()

    stale_schemas = {}
    expected = {
        "volunteer_roles": ["id", "show_id", "name", "description", "training_url", "created_at"],
        "volunteer_shifts": ["id", "show_id", "role_id", "starts_at", "ends_at", "capacity", "location", "notes", "created_at"],
    }
    for tbl, expected_cols in expected.items():
        if tbl in existing_tables:
            actual = [c["name"] for c in insp.get_columns(tbl)]
            missing = set(expected_cols) - set(actual)
            if missing:
                stale_schemas[tbl] = missing

    if stale_schemas:
        from sqlalchemy import text
        log.warning("Detected stale table schemas, recreating: %s", list(stale_schemas.keys()))
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS volunteer_checkins CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS volunteer_assignments CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS volunteer_shifts CASCADE"))
            conn.execute(text("DROP TABLE IF EXISTS volunteer_roles CASCADE"))
            conn.commit()
        log.info("Dropped stale volunteer tables; create_all will recreate them.")

    _safe_add_column(engine, "shows", "public_volunteer_token", "VARCHAR")


@app.on_event("startup")
def startup():
    auto = os.getenv("AUTO_CREATE_TABLES", "1") == "1"
    if not auto:
        log.info("AUTO_CREATE_TABLES is off; skipping table creation.")
        return

    try:
        from app.database import get_engine
        from app.models import Base

        engine = get_engine()
        _reconcile_schema(engine)
        Base.metadata.create_all(bind=engine)
        log.info("Database tables created/verified successfully.")
    except Exception as e:
        log.exception("Database initialization failed (continuing anyway): %s", e)