import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router

log = logging.getLogger("calyx")

app = FastAPI(title="Calyx - Orchid Show Management System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.on_event("startup")
def startup():
    auto = os.getenv("AUTO_CREATE_TABLES", "0") == "1"
    if not auto:
        log.info("AUTO_CREATE_TABLES is off; skipping migrations.")
        return

    try:
        from app.database import get_engine
        from app.migrations.run_migrations import run_migrations
        run_migrations(get_engine())
        log.info("Migrations ran successfully.")
    except Exception as e:
        log.exception("Startup migrations failed (continuing anyway): %s", e)
