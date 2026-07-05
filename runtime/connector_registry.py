"""Connector Registry: Discovery, loading, lifecycle, and execution management.

The registry is responsible for:
- Automatic discovery of connectors in the connectors/ directory
- Loading and initializing connectors
- Managing connector lifecycle
- Routing execution requests
- Aggregating health checks

Connectors are discovered using a plugin pattern: any .py file in the
connectors/ directory containing a class that implements ConnectorInterface
will be automatically discovered and registered.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .connector_interface import ConnectorInterface

logger = logging.getLogger(__name__)


class ConnectorRegistry:
    """Manages connector discovery, initialization, and execution."""

    def __init__(self, connectors_dir: Path | None = None) -> None:
        """Initialize the registry.

        Args:
            connectors_dir: Path to connectors directory. Defaults to runtime/connectors/
        """
        if connectors_dir is None:
            connectors_dir = Path(__file__).resolve().parent / "connectors"
        self.connectors_dir = connectors_dir
        self.connectors: dict[str, ConnectorInterface] = {}
        self.discovery_errors: list[dict[str, Any]] = []
        self.startup_time = datetime.now(timezone.utc).isoformat()

    def discover(self) -> None:
        """Auto-discover connectors from the connectors directory.

        Discovers all .py files in connectors/ directory and attempts to load
        any classes that implement ConnectorInterface.
        """
        logger.info("Starting connector discovery in %s", self.connectors_dir)

        if not self.connectors_dir.exists():
            logger.warning("Connectors directory does not exist: %s", self.connectors_dir)
            self.connectors_dir.mkdir(parents=True, exist_ok=True)
            return

        # Discover Python files
        py_files = [f for f in self.connectors_dir.glob("*.py") if f.name != "__init__.py"]
        logger.info("Found %d potential connector files", len(py_files))

        for py_file in py_files:
            self._load_connector_from_file(py_file)

        logger.info(
            "Discovery complete: %d connectors loaded, %d errors",
            len(self.connectors),
            len(self.discovery_errors),
        )

    def _load_connector_from_file(self, py_file: Path) -> None:
        """Load connector class from a Python file.

        Args:
            py_file: Path to the Python file
        """
        module_name = py_file.stem

        try:
            # Dynamically import the module
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load spec for {py_file}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find classes implementing ConnectorInterface
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    obj is not ConnectorInterface
                    and issubclass(obj, ConnectorInterface)
                    and hasattr(obj, "__abstractmethods__") is False
                ):
                    try:
                        instance = obj()
                        connector_name = instance.name
                        self.connectors[connector_name] = instance
                        logger.info(
                            "Loaded connector: %s (from %s.%s)",
                            connector_name,
                            module_name,
                            name,
                        )
                    except Exception as exc:
                        error_msg = f"Failed to instantiate {name} from {module_name}: {str(exc)}"
                        logger.error(error_msg)
                        self.discovery_errors.append(
                            {
                                "file": str(py_file),
                                "class": name,
                                "error": str(exc),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                        )
        except Exception as exc:
            error_msg = f"Failed to load connectors from {py_file}: {str(exc)}"
            logger.error(error_msg)
            self.discovery_errors.append(
                {
                    "file": str(py_file),
                    "error": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

    def get_connector(self, name: str) -> ConnectorInterface | None:
        """Retrieve a connector by name.

        Args:
            name: Connector name (e.g., 'github')

        Returns:
            The connector instance, or None if not found
        """
        return self.connectors.get(name)

    def list_connectors(self) -> list[str]:
        """Return list of available connector names."""
        return list(self.connectors.keys())

    def execute(self, connector_name: str, task: str, **kwargs) -> dict[str, Any]:
        """Execute a task through a connector.

        Args:
            connector_name: Name of the connector
            task: Task to execute
            **kwargs: Task-specific parameters

        Returns:
            Execution result with status, result/error, and execution time

        Raises:
            ValueError: If connector not found or task execution fails
        """
        connector = self.get_connector(connector_name)
        if connector is None:
            raise ValueError(f"Connector not found: {connector_name}")

        start_time = time.time()
        try:
            logger.info(
                "Executing task '%s' on connector '%s'",
                task,
                connector_name,
            )
            result = connector.execute(task, **kwargs)
            execution_time_ms = (time.time() - start_time) * 1000

            logger.info(
                "Task '%s' on '%s' completed in %.2fms",
                task,
                connector_name,
                execution_time_ms,
            )

            return {
                "connector": connector_name,
                "task": task,
                "status": "success",
                "result": result,
                "execution_time_ms": execution_time_ms,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            execution_time_ms = (time.time() - start_time) * 1000
            logger.error(
                "Task '%s' on '%s' failed: %s",
                task,
                connector_name,
                str(exc),
                exc_info=True,
            )
            return {
                "connector": connector_name,
                "task": task,
                "status": "failure",
                "error": str(exc),
                "execution_time_ms": execution_time_ms,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def health(self) -> dict[str, Any]:
        """Aggregate health status for all connectors.

        Returns:
            dict with:
            - 'status': 'healthy' if all connectors healthy, else 'degraded'
            - 'startup_time': Registry startup timestamp
            - 'connectors_total': Total number of connectors
            - 'connectors_healthy': Number of healthy connectors
            - 'connectors': Per-connector health status
            - 'discovery_errors': Errors from discovery phase
        """
        connector_health = {}
        healthy_count = 0
        unhealthy_count = 0

        for name, connector in self.connectors.items():
            try:
                health_result = connector.health()
                connector_health[name] = health_result
                if health_result.get("status") == "healthy":
                    healthy_count += 1
                else:
                    unhealthy_count += 1
            except Exception as exc:
                logger.error("Failed to get health for connector %s: %s", name, str(exc))
                connector_health[name] = {
                    "status": "unhealthy",
                    "error": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                unhealthy_count += 1

        overall_status = "healthy" if unhealthy_count == 0 else "degraded"
        if len(self.connectors) == 0:
            overall_status = "no_connectors"

        return {
            "status": overall_status,
            "startup_time": self.startup_time,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total": len(self.connectors),
                "healthy": healthy_count,
                "unhealthy": unhealthy_count,
            },
            "connectors": connector_health,
            "discovery_errors": self.discovery_errors if self.discovery_errors else [],
        }
