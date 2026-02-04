import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.cors import CORSMiddleware
from app.routers import health, tiles, shows, entries, volunteers, awards, calyx_core, reference_docs

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("calyx")

app = FastAPI(
    title="Calyx - Orchid Show Management System",
    description=
    "Backend API for orchid show operations, entries, volunteers, and judging. Powered by Orchid Continuum.",
    version="1.0.0",
)

cors_origins_env = os.getenv("CORS_ALLOW_ORIGINS", "*")
if cors_origins_env == "*":
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
app.include_router(reference_docs.router, prefix="/api", tags=["Reference Documents"])


@app.get("/")
def root():
    return {"status": "ok", "app": "Calyx", "docs": "/docs"}


@app.on_event("startup")
def startup():
    auto = os.getenv("AUTO_CREATE_TABLES", "1") == "1"
    if not auto:
        log.info("AUTO_CREATE_TABLES is off; skipping table creation.")
        return

    try:
        from app.database import get_engine
        from app.models import Base
        Base.metadata.create_all(bind=get_engine())
        log.info("Database tables created/verified successfully.")
    except Exception as e:
        log.exception("Database initialization failed (continuing anyway): %s",
                      e)
