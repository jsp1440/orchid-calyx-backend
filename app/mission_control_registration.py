"""Registration helper for Mission Control operator chat routes."""

from fastapi import FastAPI

from app.routers.calyx_operator_chat import router as calyx_operator_chat_router


def register_mission_control_chat(app: FastAPI) -> None:
    """Mount the governed operator chat router exactly once."""
    route_paths = {route.path for route in app.routes}
    status_path = "/brain/mission-control/chat/status"
    if status_path not in route_paths:
        app.include_router(calyx_operator_chat_router)
