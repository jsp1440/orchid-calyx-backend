"""Health connector for demonstration and testing.

Provides basic health check and status reporting.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..connector_interface import ConnectorInterface


class HealthConnector(ConnectorInterface):
    """Provides health check and diagnostic endpoints."""

    @property
    def name(self) -> str:
        """Return connector name."""
        return "health"

    def security_capabilities(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "task": task,
                "required_scopes": ("connector.read",),
                "risk": "read",
                "allowed_data_classes": ("public", "internal"),
                "resource_allowlist": ("health",),
                "max_cost_units": 0,
                "approval_required_for": (),
            }
            for task in ("status", "ping")
        )

    def health(self) -> dict[str, Any]:
        """Return health status."""
        return {
            "status": "healthy",
            "name": "health",
            "mode": "read_only",
            "supported_tasks": ["status", "ping"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def execute(self, task: str, **kwargs) -> dict[str, Any]:
        """Execute health-related tasks.

        Supported tasks:
        - status: Return service status
        - ping: Return ping response
        """
        if task == "status":
            return {
                "service": "health",
                "status": "healthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        if task == "ping":
            return {"message": "pong", "timestamp": datetime.now(timezone.utc).isoformat()}
        raise ValueError(f"Unknown task: {task}")
