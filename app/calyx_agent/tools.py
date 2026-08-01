from __future__ import annotations

import importlib.util
import os
from collections.abc import Callable
from typing import Any

from .models import ActionClass, ToolDescriptor, ToolResult

ToolHandler = Callable[[dict[str, Any]], ToolResult]


class AgentToolRegistry:
    def __init__(self) -> None:
        self._descriptors: dict[str, ToolDescriptor] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, descriptor: ToolDescriptor, handler: ToolHandler) -> None:
        if descriptor.tool_id in self._handlers:
            raise ValueError("TOOL_ALREADY_REGISTERED")
        self._descriptors[descriptor.tool_id] = descriptor
        self._handlers[descriptor.tool_id] = handler

    def describe(self) -> list[dict[str, Any]]:
        return [self._descriptors[key].to_dict() for key in sorted(self._descriptors)]

    def execute(self, tool_id: str, payload: dict[str, Any] | None = None) -> ToolResult:
        descriptor = self._descriptors.get(tool_id)
        if descriptor is None:
            raise LookupError("TOOL_NOT_REGISTERED")
        if descriptor.action_class is not ActionClass.READ_ONLY:
            raise PermissionError("TOOL_REQUIRES_APPROVAL")
        return self._handlers[tool_id](payload or {})


def _module_available(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _brain_readiness(_: dict[str, Any]) -> ToolResult:
    configured = bool(os.getenv("DATABASE_URL"))
    return ToolResult(
        tool_id="brain.readiness",
        status="ready" if configured else "degraded",
        data={
            "database_configured": configured,
            "knowledge_graph_routes": True,
            "deterministic_inference_families": 13,
            "reasoning_ledger": True,
            "controlled_publication_adapter": True,
            "operational_certification": "required",
        },
        sources=("app/brain", "app/reasoning_ledger", "app/reasoning_publication"),
        warnings=(() if configured else ("DATABASE_URL is not configured in this process.",)),
    )


def _mission_control_readiness(_: dict[str, Any]) -> ToolResult:
    return ToolResult(
        tool_id="mission_control.readiness",
        status="available",
        data={
            "owner_authentication": True,
            "executive_telemetry": True,
            "harvester_telemetry": True,
            "release_readiness": True,
            "mutations_automatic": False,
        },
        sources=("app/executive_telemetry", "app/mission_control_release"),
    )


def _build_inventory(_: dict[str, Any]) -> ToolResult:
    return ToolResult(
        tool_id="continuum.build_inventory",
        status="available",
        data={
            "canonical_brain_components": [
                "knowledge_graph",
                "deterministic_inference",
                "reasoning_ledger",
                "controlled_publication",
            ],
            "priority_gaps": [
                "end_to_end_brain_certification",
                "agent_provider_configuration",
                "durable_agent_session_store",
                "post_publication_lifecycle",
                "mission_control_agent_telemetry",
            ],
            "parallelizable": [
                "frontend_calyx_workspace",
                "brain_certification",
                "agent_durable_persistence",
            ],
        },
        sources=("docs/architecture", "registered runtime modules"),
        warnings=("This initial inventory is code-declared; repository adapter expansion is pending.",),
    )


def _journalism_readiness(_: dict[str, Any]) -> ToolResult:
    configured = bool(os.getenv("DATABASE_URL") or os.getenv("PGHOST"))
    return ToolResult(
        tool_id="journalism.readiness",
        status="ready" if configured else "degraded",
        data={
            "evidence_preview": True,
            "article_generation_contract": True,
            "markdown_export": True,
            "durable_repository": True,
            "owner_scoped_retrieval": True,
            "automatic_publication": False,
            "external_model_generation": False,
        },
        sources=("app/calyx_journalism", "app/calyx_journalism/persistence.py"),
        warnings=(
            ()
            if configured
            else ("No PostgreSQL configuration is visible in this process; SQLite fallback may be used.",)
        ),
    )


def _archive_readiness(_: dict[str, Any]) -> ToolResult:
    modules = {
        "institutional_archive": _module_available("app.institutional_archive"),
        "archive": _module_available("app.archive"),
        "document_ingestion": _module_available("app.document_ingestion"),
    }
    available = any(modules.values())
    return ToolResult(
        tool_id="archive.readiness",
        status="available" if available else "degraded",
        data={
            "database_configured": bool(os.getenv("DATABASE_URL") or os.getenv("PGHOST")),
            "runtime_modules": modules,
            "provenance_required": True,
            "automatic_publication": False,
        },
        sources=("app/institutional_archive", "app/archive", "app/document_ingestion"),
        warnings=(
            ()
            if available
            else ("No canonical archive runtime module was discoverable in this process.",)
        ),
    )


def _harvester_readiness(_: dict[str, Any]) -> ToolResult:
    modules = {
        "harvester": _module_available("app.harvester"),
        "harvesters": _module_available("app.harvesters"),
        "connectors": _module_available("app.runtime.connectors"),
    }
    available = any(modules.values())
    return ToolResult(
        tool_id="harvester.readiness",
        status="available" if available else "degraded",
        data={
            "database_configured": bool(os.getenv("DATABASE_URL") or os.getenv("PGHOST")),
            "runtime_modules": modules,
            "mission_control_telemetry": _module_available("app.executive_telemetry"),
            "automatic_source_mutation": False,
        },
        sources=("app/harvester", "app/harvesters", "app/runtime/connectors"),
        warnings=(
            ()
            if available
            else ("No canonical harvester or connector runtime module was discoverable in this process.",)
        ),
    )


def default_tool_registry() -> AgentToolRegistry:
    registry = AgentToolRegistry()
    registry.register(
        ToolDescriptor(
            "brain.readiness",
            "Brain readiness",
            ActionClass.READ_ONLY,
            "Inspect Knowledge Graph, inference, ledger, and publication readiness.",
        ),
        _brain_readiness,
    )
    registry.register(
        ToolDescriptor(
            "mission_control.readiness",
            "Mission Control readiness",
            ActionClass.READ_ONLY,
            "Inspect operational telemetry and governance availability.",
        ),
        _mission_control_readiness,
    )
    registry.register(
        ToolDescriptor(
            "continuum.build_inventory",
            "Continuum build inventory",
            ActionClass.READ_ONLY,
            "Return the current canonical build map and priority gaps.",
        ),
        _build_inventory,
    )
    registry.register(
        ToolDescriptor(
            "journalism.readiness",
            "Calyx journalism readiness",
            ActionClass.READ_ONLY,
            "Inspect durable evidence, article generation, export, and publication boundaries.",
        ),
        _journalism_readiness,
    )
    registry.register(
        ToolDescriptor(
            "archive.readiness",
            "Institutional archive readiness",
            ActionClass.READ_ONLY,
            "Inspect archive runtime availability, persistence configuration, and provenance boundaries.",
        ),
        _archive_readiness,
    )
    registry.register(
        ToolDescriptor(
            "harvester.readiness",
            "Harvester readiness",
            ActionClass.READ_ONLY,
            "Inspect harvester and connector runtime availability and telemetry boundaries.",
        ),
        _harvester_readiness,
    )
    return registry
