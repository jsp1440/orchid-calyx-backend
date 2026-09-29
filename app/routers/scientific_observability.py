"""Read-only scientific observability endpoints for Mission Control.

Serves ``GET /api/scientific-observability/workflow-intelligence``, which the
Mission Control page renders through ``WorkflowIntelligencePanel``. The panel
existed with no producer, so it was permanently empty and the dashboard could
never reach ``live`` mode.

Advisory only. Nothing here dispatches work, mutates state, publishes, or
spends; the payload declares each of those, and the frontend parser discards
the whole response if any declaration is missing.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter

from runtime.workflow_intelligence import (
    build_workflow_intelligence,
    observe_workflows,
)

_DEFAULT_LIMIT = 50


def _reservoir_tasks() -> list[dict[str, Any]]:
    """Read recent autonomy tasks from the durable reservoir.

    Returns an empty list when no reservoir is configured. Raising here would
    be wrong: "no database wired" is a truthful empty observation, not a fault,
    and the observation layer distinguishes the two anyway.
    """
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return []

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.calyx_orchestrator.durable_reservoir_models import DurableReservoirTask

    engine = create_engine(database_url)
    try:
        session = sessionmaker(bind=engine)()
        try:
            rows = (
                session.execute(
                    select(DurableReservoirTask)
                    .order_by(DurableReservoirTask.updated_at.desc())
                    .limit(_DEFAULT_LIMIT)
                )
                .scalars()
                .all()
            )
            return [
                {
                    "task_key": row.task_key,
                    "run_id": row.run_id,
                    "state": row.state,
                    "module": row.module,
                    "authority_class": row.authority_class,
                    "consequence_risk": row.consequence_risk,
                    "blocked_reason": row.blocked_reason,
                    "evidence": dict(row.evidence or {}),
                    "retry_count": 0,
                    "rework_count": 0,
                }
                for row in rows
            ]
        finally:
            session.close()
    finally:
        engine.dispose()


def create_scientific_observability_router(
    read_tasks: Callable[[], Any] = _reservoir_tasks,
) -> APIRouter:
    router = APIRouter(tags=["scientific-observability"])

    @router.get("/api/scientific-observability/workflow-intelligence")
    def workflow_intelligence() -> dict[str, Any]:
        """Advisory ranking of current autonomous workflows.

        Always 200. An unreadable reservoir yields an empty workflow list with
        ``source_available`` false, because the panel's job is to report the
        state of the system including "we could not read it", and an error
        status would just render as a dead tile.
        """
        observation = observe_workflows(read_tasks)
        return build_workflow_intelligence(observation)

    return router


router = create_scientific_observability_router()
