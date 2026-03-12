import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

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
    volunteer_ops,
    feedback,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("calyx")

app = FastAPI(
    title="Calyx - Orchid Show Management System",
    description=
    "Backend API for orchid show operations, entries, volunteers, and judging. Powered by Orchid Continuum.",
    version="1.0.0",
)

cors_origins_env = os.getenv("CORS_ALLOW_ORIGINS", "*")
if cors_origins_env.strip() == "*":
    allow_origins = ["*"]
else:
    allow_origins = [
        o.strip() for o in cors_origins_env.split(",") if o.strip()
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(tiles.router)
app.include_router(shows.router)
app.include_router(entries.router)
app.include_router(volunteers.router)
app.include_router(awards.router)
app.include_router(calyx_core.router)
app.include_router(reference_docs.router,
                   prefix="/api",
                   tags=["Reference Documents"])
app.include_router(judging.router)
app.include_router(volunteer_ops.router)
app.include_router(feedback.router)


@app.get("/")
def root():
    return {"status": "ok", "app": "Calyx", "docs": "/docs"}


def _safe_add_column(engine, table: str, column: str, col_type: str):
    try:
        with engine.connect() as conn:
            conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
            conn.commit()
            log.info("Added column %s.%s", table, column)
    except Exception:
        pass


def _reconcile_schema(engine):
    _safe_add_column(engine, "shows", "public_volunteer_token", "VARCHAR")
    _safe_add_column(engine, "judges", "role", "VARCHAR")

    _safe_add_column(engine, "judging_events", "published_at", "TIMESTAMP")
    _safe_add_column(engine, "judging_events", "closed_at", "TIMESTAMP")
    _safe_add_column(engine, "judging_events", "updated_at", "TIMESTAMP")
    _safe_add_column(engine, "plant_categories", "sort_order",
                     "INTEGER DEFAULT 0")
    _safe_add_column(engine, "scores", "value_rank", "INTEGER")
    _safe_add_column(engine, "scores", "updated_at", "TIMESTAMP")


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
        Base.metadata.create_all(bind=engine)
        _reconcile_schema(engine)
        log.info("Database tables created/verified successfully.")
    except Exception as e:
        log.exception("Database initialization failed (continuing anyway): %s",
                      e)


@app.get("/system/status")
async def system_status():
    return {
        "status": "ok",
        "service": "orchid-continuum",
        "backend": "calyx",
        "message": "System operational"
    }
