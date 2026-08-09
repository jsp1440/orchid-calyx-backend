from __future__ import annotations

import os

from .persistence import PostgresBrainMissionPersistence


def build_brain_mission_persistence() -> PostgresBrainMissionPersistence:
    database_url = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for durable Brain missions")
    return PostgresBrainMissionPersistence(database_url)
