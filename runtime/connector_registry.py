"""Connector Registry: discovery, lifecycle, and governed execution.

The registry is responsible for:
- automatic discovery of connectors in the connectors/ directory;
- loading and initializing connectors;
- managing connector lifecycle;
- routing execution requests;
- aggregating health checks;
- registering explicit connector capability manifests with the common Orchid
  Continuum security boundary before any governed execution is permitted.

Connectors are discovered using a plugin pattern: any .py file in the
connectors/ directory containing a class that implements ConnectorInterface
will be automatically discovered and registered.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from .connector_interface import ConnectorInterface

logger = logging.getLogger(__name__)


class CommonSecurityBoundary(Protocol):
    def register_server(self, manifest: Any) -> None: ...

    def register_capability(self, manifest: Any) -> None: ...

    def enforce_tool(self, **kwargs: object) -> Any: ...

    def manifest(self) -> dict[str, object]: ...


class ConnectorRegistry:
    """Manages connector discovery, initialization, and governed execution."""

    def __init__(
        self,
        connectors_dir: Path | None = None,
        *,
        security: CommonSecurityBoundary | None = None,
        security_agent_id: str = "calyx.connector_api",
    ) -> None:
        if connectors_dir is None:
            connectors_dir = Path(__file__).resolve().parent / "connectors"
        self.connectors_dir = connectors_dir
        self.connectors: dict[str, ConnectorInterface] = {}
        self.discovery_errors: list[dict[str, Any]] = []
        self.startup_time = datetime.now(timezone.utc).isoformat()
        self.security = security
        self.security_agent_id = security_agent_id

    def discover(self) -> None:
        """Auto-discover connectors from the connectors directory."""
        logger.info("Starting connector discovery in %s", self.connectors_dir)

        if not self.connectors_dir.exists():
            logger.warning("Connectors directory does not exist: %s", self.connectors_dir)
            self.connectors_dir.mkdir(parents=True, exist_ok=True)
            return

        py_files = [
            file_path
            for file_path in self.connectors_dir.glob("*.py")
            if file_path.name != "__init__.py"
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
        """Register one connector without silently replacing an identity.

        If a common security boundary is attached, server identity is registered
        before the connector becomes reachable. Connectors without an explicit
        capability declaration are still discoverable/inspectable, but all task
        execution fails closed.
        """
        name = connector.name.strip()
        if not name:
            raise ValueError("INVALID_CONNECTOR_IDENTITY")
        if name in self.connectors:
            raise ValueError("CONNECTOR_ALREADY_REGISTERED")
        if self.security is not None:
            self._register_security_manifest(connector)
        self.connectors[name] = connector

    def _register_security_manifest(self, connector: ConnectorInterface) -> None:
        from app.calyx_orchestrator.agent_security_gateway import ActionRisk
        from app.calyx_orchestrator.orchid_security_boundary import (
            CapabilityManifest,
            DataClass,
            ServerManifest,
            TransportClass,
        )

        server_id = f"connector.{connector.name}"
        declarations = list(connector.security_capabilities())
        if not declarations:
            declarations = self._builtin_security_capabilities(connector)

        self.security.register_server(
            ServerManifest(
                server_id=server_id,
                transport=TransportClass.CONNECTOR,
                enabled=True,
                description=f"Orchid Continuum connector: {connector.name}",
            )
        )
        for declaration in declarations:
            risk = ActionRisk(str(declaration.get("risk", "read")))
            allowed_data_classes = frozenset(
                DataClass(str(value))
                for value in declaration.get(
                    "allowed_data_classes", ("public", "internal")
                )
            )
            approval_required_for = frozenset(
                ActionRisk(str(value))
                for value in declaration.get("approval_required_for", ())
            )
            self.security.register_capability(
                CapabilityManifest(
                    server_id=server_id,
                    tool_name=str(declaration["task"]),
                    transport=TransportClass.CONNECTOR,
                    required_scopes=frozenset(
                        str(value)
                        for value in declaration.get(
                            "required_scopes", ("connector.read",)
                        )
                    ),
                    allowed_risks=frozenset({risk}),
                    allowed_data_classes=allowed_data_classes,
                    resource_allowlist=frozenset(
                        str(value)
                        for value in declaration.get("resource_allowlist", ())
                    ),
                    max_cost_units=int(declaration.get("max_cost_units", 0)),
                    approval_required_for=approval_required_for,
                )
            )

    @staticmethod
    def _builtin_security_capabilities(
        connector: ConnectorInterface,
    ) -> list[dict[str, object]]:
        """Explicit manifests for legacy built-ins pending in-class declarations.

        Unknown/external connector identities deliberately receive no fallback.
        """
        if connector.name == "github":
            approved_repositories = {
                str(getattr(connector, "default_repo", "jsp1440/orchid-calyx-backend")),
                str(
                    getattr(
                        connector,
                        "default_frontend_repo",
                        "jsp1440/orchid-continuum-frontend",
                    )
                ),
            }
            for env_name in ("GITHUB_REPOSITORY", "CALYX_FRONTEND_REPOSITORY"):
                configured = os.getenv(env_name, "").strip()
                if configured:
                    approved_repositories.add(configured)
            tasks = (
                "repo_status",
                "status",
                "list_open_prs",
                "list_recent_commits",
                "branch_status",
                "repo_tree",
                "list_files",
                "get_file",
                "repo_audit",
                "repo_engineer",
                "engineering_queue",
                "frontend_audit",
            )
            return [
                {
                    "task": task,
                    "required_scopes": ("connector.read",),
                    "risk": "read",
                    "allowed_data_classes": (
                        "public",
                        "internal",
                        "sensitive",
                        "restricted",
                    ),
                    "resource_allowlist": tuple(sorted(approved_repositories)),
                    "max_cost_units": 0,
                    "approval_required_for": (),
                }
                for task in tasks
            ]
        if isinstance(connector, ConnectorManifest):
            return [
                {
                    "task": "describe",
                    "required_scopes": ("connector.read",),
                    "risk": "read",
                    "allowed_data_classes": ("public", "internal"),
                    "resource_allowlist": (connector.name,),
                    "max_cost_units": 0,
                    "approval_required_for": (),
                }
            ]
        return []

    def get_connector(self, name: str) -> ConnectorInterface | None:
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

    def security_manifest(self) -> dict[str, object] | None:
        return self.security.manifest() if self.security is not None else None

    def list_connectors(self) -> list[str]:
        return list(self.connectors.keys())

    def execute(
        self,
        connector_name: str,
        task: str,
        *,
        security_context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute one connector task through the common security boundary."""
        connector = self.get_connector(connector_name)
        if connector is None:
            raise ValueError(f"Connector not found: {connector_name}")

        start_time = time.time()
        try:
            audit_id = None
            if self.security is not None:
                context = security_context or {}
                request_id = str(
                    context.get("request_id")
                    or f"connector:{connector_name}:{task}:{uuid4().hex}"
                )
                resource = str(
                    context.get("resource")
                    or kwargs.get("repo")
                    or kwargs.get("frontend_repo")
                    or connector_name
                )
                audit = self.security.enforce_tool(
                    request_id=request_id,
                    agent_id=str(
                        context.get("agent_id") or self.security_agent_id
                    ),
                    server_id=f"connector.{connector_name}",
                    tool_name=task,
                    data_class=str(context.get("data_class") or "internal"),
                    resource=resource,
                    provider=(
                        str(context["provider"])
                        if context.get("provider") is not None
                        else None
                    ),
                    untrusted_context=bool(
                        context.get("untrusted_context", False)
                    ),
                    approved=bool(context.get("approved", False)),
                    cost_units=int(context.get("cost_units", 0)),
                    argument_count=len(kwargs),
                )
                audit_id = audit.decision_id

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

            payload = {
                "connector": connector_name,
                "task": task,
                "status": "success",
                "result": result,
                "execution_time_ms": execution_time_ms,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if audit_id:
                payload["security_decision_id"] = audit_id
            return payload
        except Exception as exc:  # noqa: BLE001 - connector/security boundary
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
            "security_boundary": self.security is not None,
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

    def execute(self, task: str, **kwargs: Any) -> dict[str, Any]:
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
    from app.calyx_orchestrator.orchid_security_boundary import (
        build_orchid_continuum_security_boundary,
    )

    registry = ConnectorRegistry(
        security=build_orchid_continuum_security_boundary(),
        security_agent_id="calyx.agent",
    )
    registry.discover()
    for connector in LITERATURE_CONNECTOR_MANIFESTS:
        if registry.get_connector(connector.name) is None:
            registry.register(connector)
    return registry
