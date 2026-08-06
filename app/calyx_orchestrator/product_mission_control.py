from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .mission_control import mission_control_snapshot
from .product_program import product_mission_control_snapshot


def phase_3_mission_control_snapshot(db: Session, *, owner: str) -> dict[str, Any]:
    return {
        "engineering": mission_control_snapshot(db, owner=owner),
        "product": product_mission_control_snapshot(),
        "phase": 3,
        "stack_dependencies": [
            "Phase 1 autonomous engineering core",
            "Phase 2 scientific and data agents",
        ],
        "deployment_gate": "owner_approval_required",
        "funding_submission_gate": "owner_approval_required",
    }
