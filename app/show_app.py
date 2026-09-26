"""Show Day profile: a small Calyx app that serves only orchid show operations.

Run it instead of ``app.main:app`` when a society only needs show management::

    uvicorn app.show_app:app --host 0.0.0.0 --port ${PORT:-3000}

It mounts the show, entry, award, judging, volunteer, feedback and tile routers
and nothing from the scientific or agent-automation layers, so it starts
without their dependencies and background loops. Authentication is unchanged:
every ``/api`` route still requires ``X-API-Key`` (``CALYX_API_KEY``).

``CALYX_SHOW_CREATE_TABLES=1`` creates the show tables on startup for a local
SQLite rehearsal. It is off by default; production schema changes stay with the
SQL migrations.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models
from app.database import Base, get_engine
from app.routers import (
    awards,
    entries,
    feedback,
    judging,
    show_day,
    shows,
    tiles,
    volunteer_ops,
)

SHOW_ROUTERS = (
    shows.router,
    entries.router,
    awards.router,
    judging.router,
    show_day.router,
    volunteer_ops.router,
    feedback.router,
    tiles.router,
)

SHOW_TABLES = tuple(
    model.__table__
    for model in (
        models.Organization,
        models.Show,
        models.Entry,
        models.Award,
        models.VolunteerRole,
        models.VolunteerShift,
        models.Volunteer,
        models.VolunteerAssignment,
        models.Feedback,
        models.JudgingEvent,
        models.PlantCategory,
        models.JudgingAward,
        models.JudgingCriterion,
        models.Exhibitor,
        models.Plant,
        models.Judge,
        models.Score,
        models.JudgeAssignment,
        models.Scorecard,
        models.ScorecardAuditLog,
        models.ScoreSubmission,
    )
)


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "*")
    return [origin.strip() for origin in raw.split(",") if origin.strip()] or ["*"]


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    if os.getenv("CALYX_SHOW_CREATE_TABLES", "").strip().lower() in {"1", "true", "yes", "on"}:
        Base.metadata.create_all(bind=get_engine(), tables=list(SHOW_TABLES))
    yield


def create_show_app() -> FastAPI:
    show_app = FastAPI(title="Calyx Show Day", lifespan=_lifespan)
    origins = _cors_origins()
    show_app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @show_app.get("/health")
    def health():
        return {"status": "ok", "profile": "show"}

    for router in SHOW_ROUTERS:
        show_app.include_router(router)
    return show_app


app = create_show_app()
