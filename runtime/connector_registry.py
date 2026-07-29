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
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import entry_points
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
            logger.warning(
                "Connectors directory does not exist: %s", self.connectors_dir
            )
            self.connectors_dir.mkdir(parents=True, exist_ok=True)
            return

        py_files = [
            f for f in self.connectors_dir.glob("*.py") if f.name != "__init__.py"
        ]
        logger.info("Found %d potential connector files", len(py_files))

        for py_file in py_files:
            self._load_connector_from_file(py_file)

        self._discover_entry_points()

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
        package_module_name = f"runtime.connectors.{module_name}"

        try:
            module = importlib.import_module(package_module_name)

            for name, obj in inspect.getmembers(module, inspect.isclass):
                if (
                    obj is not ConnectorInterface
                    and issubclass(obj, ConnectorInterface)
                    and not inspect.isabstract(obj)
                ):
                    try:
                        instance = obj()
                        connector_name = instance.name
                        self.register(instance)
                        logger.info(
                            "Loaded connector: %s (from %s.%s)",
                            connector_name,
                            module_name,
                            name,
                        )
                    except Exception as exc:  # noqa: BLE001 - plugin boundary
                        error_msg = (
                            f"Failed to instantiate {name} from {module_name}: {exc!s}"
                        )
                        logger.error(error_msg)
                        self.discovery_errors.append(
                            {
                                "file": str(py_file),
                                "class": name,
                                "error": str(exc),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                        )
        except Exception as exc:  # noqa: BLE001 - plugin import boundary
            error_msg = f"Failed to load connectors from {py_file}: {exc!s}"
            logger.error(error_msg)
            self.discovery_errors.append(
                {
                    "file": str(py_file),
                    "error": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

    def _discover_entry_points(self) -> None:
        """Discover external connectors through the canonical plugin group."""
        selected = entry_points()
        selected = (
            selected.select(group="orchid_continuum.brain_connectors")
            if hasattr(selected, "select")
            else selected.get("orchid_continuum.brain_connectors", [])
        )
        for entry_point in selected:
            try:
                loaded = entry_point.load()
                connector = loaded() if callable(loaded) else loaded
                self.register(connector)
            except Exception as exc:  # noqa: BLE001 - external entry point boundary
                self.discovery_errors.append(
                    {
                        "entry_point": entry_point.name,
                        "error": str(exc),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )

    def register(self, connector: ConnectorInterface) -> None:
        """Register one connector without silently replacing an identity."""
        name = connector.name.strip()
        if not name:
            raise ValueError("INVALID_CONNECTOR_IDENTITY")
        if name in self.connectors:
            raise ValueError("CONNECTOR_ALREADY_REGISTERED")
        self.connectors[name] = connector

    def get_connector(self, name: str) -> ConnectorInterface | None:
        """Retrieve a connector by name.

        Args:
            name: Connector name (e.g., 'github')

        Returns:
            The connector instance, or None if not found
        """
        return self.connectors.get(name)

    def get(self, name: str) -> ConnectorInterface:
        connector = self.get_connector(name)
        if connector is None:
            raise LookupError("CONNECTOR_NOT_FOUND")
        return connector

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "id": connector.name,
                "name": getattr(connector, "display_name", connector.name),
                "version": getattr(connector, "version", "unspecified"),
                "capabilities": list(getattr(connector, "capabilities", ())),
                "health": connector.health(),
            }
            for connector in sorted(
                self.connectors.values(), key=lambda item: item.name
            )
        ]

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
            logger.exception(
                "Task '%s' on '%s' failed",
                task,
                connector_name,
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
            except Exception as exc:  # noqa: BLE001 - connector health boundary
                logger.error(
                    "Failed to get health for connector %s: %s", name, str(exc)
                )
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


@dataclass(frozen=True)
class ConnectorManifest(ConnectorInterface):
    """Declared, non-operational connector metadata in the canonical registry."""

    connector_id: str
    display_name: str
    connector_version: str
    connector_capabilities: tuple[str, ...]
    metadata_only: bool = True

    @property
    def name(self) -> str:
        return self.connector_id

    @property
    def version(self) -> str:
        return self.connector_version

    @property
    def capabilities(self) -> tuple[str, ...]:
        return self.connector_capabilities

    def execute(self, task: str, **kwargs) -> dict[str, Any]:
        if task != "describe":
            raise RuntimeError("CONNECTOR_ADAPTER_NOT_CONFIGURED")
        return {
            "connector_id": self.connector_id,
            "metadata_only": self.metadata_only,
            "capabilities": list(self.connector_capabilities),
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "declared",
            "operational": False,
            "metadata_only": self.metadata_only,
        }


LITERATURE_CONNECTOR_MANIFESTS = (
    ConnectorManifest("crossref", "Crossref", "1.0", ("doi", "authors", "citations")),
    ConnectorManifest(
        "openalex", "OpenAlex", "1.0", ("works", "authors", "concepts", "citations")
    ),
    ConnectorManifest(
        "semantic-scholar",
        "Semantic Scholar",
        "1.0",
        ("papers", "authors", "citations"),
    ),
    ConnectorManifest("pubmed", "PubMed", "1.0", ("papers", "authors", "abstracts")),
    ConnectorManifest("gbif", "GBIF", "1.0", ("occurrences", "taxonomy", "geography")),
    ConnectorManifest(
        "bhl",
        "Biodiversity Heritage Library",
        "1.0",
        ("literature", "pages", "taxonomy"),
    ),
    ConnectorManifest("jstor", "JSTOR", "1.0", ("metadata",), metadata_only=True),
)


def default_brain_registry() -> ConnectorRegistry:
    registry = ConnectorRegistry()
    registry.discover()
    for connector in LITERATURE_CONNECTOR_MANIFESTS:
        if registry.get_connector(connector.name) is None:
            registry.register(connector)
    return registry
