"""Registration helper for Mission Control operator chat routes."""

from fastapi import FastAPI

from app.routers.calyx_conversation_sources import (
    router as calyx_conversation_sources_router,
)
from app.routers.calyx_operator_chat import router as calyx_operator_chat_router


def register_mission_control_chat(app: FastAPI) -> None:
    """Mount the governed operator chat routers exactly once."""
    if getattr(app.state, "calyx_chat_registered", False):
        return
    app.include_router(calyx_operator_chat_router)
    app.include_router(calyx_conversation_sources_router)
    app.state.calyx_chat_registered = True
