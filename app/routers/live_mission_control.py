"""Deployed Mission Control chat and governed runtime-control routes."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter

from app.routers.calyx_operator_chat import router as chat_router
from app.routers.calyx_runtime_controls import create_runtime_controls_router
from app.routers.post_publication_monitoring import (
    router as post_publication_monitoring_router,
)
from app.security import verify_owner_or_api_key
from runtime.governed_worker_loop import GovernedWorkerLoop
from runtime.json_activation_store import JsonActivationStateStore
from runtime.persistent_activation_state import PersistentActivationController
from runtime.runtime_operator_controls import RuntimeOperatorControls
from runtime.supervised_pilot import run_supervised_pilot


def _state_path() -> Path:
    return Path(
        os.environ.get(
            "CALYX_ACTIVATION_STATE_PATH",
            "/tmp/calyx/activation-state.json",
        )
    )


_controller = PersistentActivationController(JsonActivationStateStore(_state_path()))
_worker = GovernedWorkerLoop(_controller, run_supervised_pilot)
_controls = RuntimeOperatorControls(_controller, _worker)


def get_runtime_controls() -> RuntimeOperatorControls:
    return _controls


router = APIRouter()
router.include_router(chat_router)
router.include_router(
    create_runtime_controls_router(get_runtime_controls, verify_owner_or_api_key)
)
router.include_router(post_publication_monitoring_router)
