"""FastAPI routes for the Connector Execution Framework.

Provides:
- GET /api/connectors - List all connectors and their status
- GET /api/connectors/health - Aggregate health check
- GET /api/connectors/tasks - List supported tasks for all connectors
- GET /api/connectors/tasks/{connector} - List supported tasks for one connector
- POST /api/connectors/execute - Execute a task through a connector
"""

from __future__ import annotations

import json
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


def parse_kwargs(raw_kwargs: str | None) -> dict[str, Any]:
    """Parse JSON kwargs from Swagger query string input.

    Swagger sends kwargs as a query parameter string, so `**kwargs` in the
    route signature never receives nested values. This helper accepts either
    an empty value, `{}`, or a JSON object string and returns a dictionary that
    can be passed to connector.execute(..., **kwargs).
    """
    if raw_kwargs is None or raw_kwargs.strip() == "":
        return {}

    try:
        parsed = json.loads(raw_kwargs)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="kwargs must be valid JSON") from exc

    if parsed in (None, []):
        return {}

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="kwargs must be a JSON object")

    return parsed


def connector_task_payload(name: str) -> dict[str, Any]:
    """Return a normalized task/capability payload for one connector."""
    registry = get_registry()
    connector = registry.get_connector(name)
    if connector is None:
        raise HTTPException(status_code=404, detail=f"Connector not found: {name}")

    try:
        health_info = connector.health()
    except Exception as exc:
        logger.error("Failed to read connector health for task discovery: %s", name, exc_info=True)
        health_info = {"status": "unhealthy", "error": str(exc)}

    supported_tasks = health_info.get("supported_tasks") or []
    if not isinstance(supported_tasks, list):
        supported_tasks = []

    return {
        "name": name,
        "healthy": health_info.get("status") == "healthy",
        "status": health_info.get("status"),
        "mode": health_info.get("mode"),
        "supported_tasks": supported_tasks,
        "task_count": len(supported_tasks),
    }


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


@router.get("/tasks")
def connector_tasks() -> dict[str, Any]:
    """List supported tasks for all discovered connectors."""
    registry = get_registry()
    connectors = [connector_task_payload(name) for name in registry.list_connectors()]
    return {
        "build": "BUILD-027",
        "status": "connector_tasks_ready",
        "total": len(connectors),
        "connectors": connectors,
    }


@router.get("/tasks/{connector}")
def connector_tasks_for(connector: str) -> dict[str, Any]:
    """List supported tasks for one connector."""
    payload = connector_task_payload(connector)
    return {
        "build": "BUILD-027",
        "status": "connector_tasks_ready",
        "connector": payload,
    }


@router.post("/execute")
def execute_task(
    connector: str = Query(..., description="Connector name"),
    task: str = Query(..., description="Task to execute"),
    kwargs: str | None = Query(default=None, description="JSON object of task-specific parameters"),
) -> dict[str, Any]:
    """Execute a task through a connector.

    Args:
        connector: Name of the connector
        task: Task to execute
        kwargs: JSON object string of task-specific parameters

    Returns:
        Execution result with status, result/error, and execution time

    Raises:
        404: If connector not found
        400: If task execution fails or kwargs is invalid
    """
    if not connector:
        logger.warning("Execute request with missing connector name")
        raise HTTPException(status_code=400, detail="connector parameter is required")

    if not task:
        logger.warning("Execute request with missing task")
        raise HTTPException(status_code=400, detail="task parameter is required")

    task_kwargs = parse_kwargs(kwargs)
    registry = get_registry()

    if registry.get_connector(connector) is None:
        logger.warning("Execute request for unknown connector: %s", connector)
        raise HTTPException(
            status_code=404,
            detail=f"Connector not found: {connector}",
        )

    try:
        result = registry.execute(connector, task, **task_kwargs)
        if result["status"] == "failure":
            logger.warning(
                "Task '%s' failed on connector '%s': %s",
                task,
                connector,
                result.get("error"),
            )
            raise HTTPException(status_code=400, detail=result.get("error"))
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        logger.error("Invalid connector/task: %s", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Unexpected error executing task: %s", str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from exc
