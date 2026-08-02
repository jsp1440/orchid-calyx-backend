"""Live Mission Control registration for chat and governed runtime controls."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.mission_control_registration import register_mission_control_chat
from app.routers.calyx_runtime_controls import create_runtime_controls_router
from runtime.governed_worker_loop import GovernedWorkerLoop
from runtime.json_activation_store import JsonActivationStateStore
from runtime.persistent_activation_state import PersistentActivationController
from runtime.runtime_operator_controls import RuntimeOperatorControls


def _state_path() -> Path:
    return Path(
        os.environ.get(
            "CALYX_ACTIVATION_STATE_PATH",
            "/tmp/calyx/activation-state.json",
        )
    )


def _safe_cycle() -> str:
    """Return a bounded placeholder until the real cycle adapter is injected."""
    return "no-approved-live-cycle-adapter"


def build_runtime_controls() -> RuntimeOperatorControls:
    controller = PersistentActivationController(JsonActivationStateStore(_state_path()))
    worker = GovernedWorkerLoop(controller, _safe_cycle)
    return RuntimeOperatorControls(controller, worker)


def register_live_mission_control(
    app: FastAPI,
    *,
    require_owner: Callable[[], Any],
    get_controls: Callable[[], RuntimeOperatorControls] | None = None,
) -> None:
    """Register chat and owner-gated runtime routes exactly once."""
    if getattr(app.state, "calyx_live_mission_control_registered", False):
        return

    controls = get_controls or build_runtime_controls
    register_mission_control_chat(app)
    app.include_router(create_runtime_controls_router(controls, require_owner))
    app.state.calyx_live_mission_control_registered = True
