from __future__ import annotations

from sqlalchemy.engine import Engine
from app.models.base import Base

# Import models so they register on Base.metadata
from app.models.orchid_judge_show import Organization, Show, ShowEntry  # noqa: F401
from app.models.show_ops import (  # noqa: F401
    ShowZone,
    Vendor,
    TrainingAsset,
    VolunteerRole,
    VolunteerShift,
    VolunteerSignup,
)

def run_migrations(engine: Engine) -> None:
    """v1: idempotent create_all. Safe on every boot."""
    Base.metadata.create_all(bind=engine)
