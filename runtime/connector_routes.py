"""FastAPI routes for the Connector Execution Framework.

Provides:
- GET /api/connectors - List all connectors and their status
- GET /api/connectors/health - Aggregate health check
- POST /api/connectors/execute - Execute a task through a connector
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .connector_registry import ConnectorRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/connectors", tags=["Connectors"])

# Global registry instance
_registry: ConnectorRegistry | None = None


def get_registry() -> ConnectorRegistry:
    """Get or create the global connector registry."""
    global _registry
    if _registry is None:
        _registry = ConnectorRegistry()
        _registry.discover()
    return _registry


@router.get("")
def list_connectors() -> dict[str, Any]:
    """List all discovered connectors and their health status.

    Returns:
        dict with:
        - 'connectors': List of connector info (name, healthy)
        - 'total': Total connector count
        - 'healthy': Healthy connector count
    """
    registry = get_registry()
    connector_list = []

    for name in registry.list_connectors():
        connector = registry.get_connector(name)
        if connector:
            try:
                health_info = connector.health()
                is_healthy = health_info.get("status") == "healthy"
            except Exception:
                is_healthy = False

            connector_list.append({"name": name, "healthy": is_healthy})

    logger.info("Listed %d connectors", len(connector_list))

    return {
        "connectors": connector_list,
        "total": len(connector_list),
        "healthy": sum(1 for c in connector_list if c["healthy"]),
    }


@router.get("/health")
def connector_health() -> dict[str, Any]:
    """Get aggregate health status for all connectors.

    Returns:
        Detailed health report with per-connector status
    """
    registry = get_registry()
    return registry.health()


@router.post("/execute")
def execute_task(
    connector: str = Query(..., description="Connector name"),
    task: str = Query(..., description="Task to execute"),
    **kwargs,
) -> dict[str, Any]:
    """Execute a task through a connector.

    Args:
        connector: Name of the connector
        task: Task to execute
        **kwargs: Task-specific parameters

    Returns:
        Execution result with status, result/error, and execution time

    Raises:
        404: If connector not found
        400: If task execution fails
    """
    if not connector:
        logger.warning("Execute request with missing connector name")
        raise HTTPException(status_code=400, detail="connector parameter is required")

    if not task:
        logger.warning("Execute request with missing task")
        raise HTTPException(status_code=400, detail="task parameter is required")

    registry = get_registry()

    # Check if connector exists
    if registry.get_connector(connector) is None:
        logger.warning("Execute request for unknown connector: %s", connector)
        raise HTTPException(
            status_code=404,
            detail=f"Connector not found: {connector}",
        )

    # Execute the task
    try:
        result = registry.execute(connector, task, **kwargs)
        if result["status"] == "failure":
            logger.warning(
                "Task '%s' failed on connector '%s': %s",
                task,
                connector,
                result.get("error"),
            )
            raise HTTPException(status_code=400, detail=result.get("error"))
        return result
    except ValueError as exc:
        logger.error("Invalid connector/task: %s", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Unexpected error executing task: %s", str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from exc
