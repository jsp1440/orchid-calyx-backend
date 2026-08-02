"""Registration helper for Mission Control operator chat routes."""

from fastapi import FastAPI

from app.routers.calyx_operator_chat import router as calyx_operator_chat_router


def register_mission_control_chat(app: FastAPI) -> None:
    """Mount the governed operator chat router exactly once."""
    status_path = "/brain/mission-control/chat/status"
    if getattr(app.state, "calyx_chat_registered", False):
        return
    app.include_router(calyx_operator_chat_router)
    app.state.calyx_chat_registered = True
    assert any(
        getattr(route, "path", None) == status_path for route in app.routes
    ), "Mission Control chat status route was not registered"
