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

    def health(self) -> dict[str, Any]:
        """Return health status."""
        return {
            "status": "healthy",
            "name": "health",
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
        elif task == "ping":
            return {"message": "pong", "timestamp": datetime.now(timezone.utc).isoformat()}
        else:
            raise ValueError(f"Unknown task: {task}")
