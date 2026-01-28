import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine
from app.migrations.run_migrations import run_migrations
from app.api.router import router

app = FastAPI(title="Orchid Judge App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.getenv("AUTO_CREATE_TABLES", "1") == "1":
    run_migrations(engine)

app.include_router(router)

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/health")
def health():
    return {"status": "ok"}
