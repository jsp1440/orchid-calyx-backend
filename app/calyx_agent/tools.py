from __future__ import annotations

import importlib.util
import os
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from .models import ActionClass, ToolDescriptor, ToolResult

ToolHandler = Callable[[dict[str, Any]], ToolResult]


class AgentToolRegistry:
    """Calyx internal tool registry with optional common-boundary enforcement."""

    def __init__(
        self,
        *,
        security: Any | None = None,
        security_agent_id: str = "calyx.agent",
    ) -> None:
        self._descriptors: dict[str, ToolDescriptor] = {}
        self._handlers: dict[str, ToolHandler] = {}
        self.security = security
        self.security_agent_id = security_agent_id
        self.security_server_id = "internal.calyx_agent"
        if self.security is not None:
            from app.calyx_orchestrator.orchid_security_boundary import (
                ServerManifest,
                TransportClass,
            )

            self.security.register_server(
                ServerManifest(
                    server_id=self.security_server_id,
                    transport=TransportClass.INTERNAL,
                    enabled=True,
                    description="Governed internal Calyx inspection and preparation tools",
                )
            )

    def register(self, descriptor: ToolDescriptor, handler: ToolHandler) -> None:
        if descriptor.tool_id in self._handlers:
            raise ValueError("TOOL_ALREADY_REGISTERED")
        if self.security is not None:
            self._register_security_capability(descriptor)
        self._descriptors[descriptor.tool_id] = descriptor
        self._handlers[descriptor.tool_id] = handler

    def _register_security_capability(self, descriptor: ToolDescriptor) -> None:
        from app.calyx_orchestrator.agent_security_gateway import ActionRisk
        from app.calyx_orchestrator.orchid_security_boundary import (
            CapabilityManifest,
            DataClass,
            TransportClass,
        )

        if descriptor.action_class is ActionClass.READ_ONLY:
            risk = ActionRisk.READ
            required_scopes = frozenset({"continuum.read"})
            allowed_data_classes = frozenset(
                {
                    DataClass.PUBLIC,
                    DataClass.INTERNAL,
                    DataClass.SENSITIVE,
                    DataClass.RESTRICTED,
                }
            )
            approval_required_for = frozenset()
        elif descriptor.action_class is ActionClass.PREPARE_ONLY:
            risk = ActionRisk.WRITE
            required_scopes = frozenset({"continuum.prepare"})
            allowed_data_classes = frozenset(
                {DataClass.INTERNAL, DataClass.SENSITIVE, DataClass.RESTRICTED}
            )
            approval_required_for = frozenset()
        elif descriptor.action_class is ActionClass.SCIENTIFIC_APPROVAL:
            risk = ActionRisk.PUBLICATION
            required_scopes = frozenset({"continuum.prepare"})
            allowed_data_classes = frozenset(
                {DataClass.INTERNAL, DataClass.SENSITIVE, DataClass.RESTRICTED}
            )
            approval_required_for = frozenset({ActionRisk.PUBLICATION})
        else:
            risk = ActionRisk.PRODUCTION
            required_scopes = frozenset({"continuum.prepare"})
            allowed_data_classes = frozenset(
                {DataClass.INTERNAL, DataClass.SENSITIVE, DataClass.RESTRICTED}
            )
            approval_required_for = frozenset({ActionRisk.PRODUCTION})

        self.security.register_capability(
            CapabilityManifest(
                server_id=self.security_server_id,
                tool_name=descriptor.tool_id,
                transport=TransportClass.INTERNAL,
                required_scopes=required_scopes,
                allowed_risks=frozenset({risk}),
                allowed_data_classes=allowed_data_classes,
                max_cost_units=0,
                approval_required_for=approval_required_for,
            )
        )

    def describe(self) -> list[dict[str, Any]]:
        return [self._descriptors[key].to_dict() for key in sorted(self._descriptors)]

    def execute(
        self,
        tool_id: str,
        payload: dict[str, Any] | None = None,
        *,
        security_context: dict[str, Any] | None = None,
    ) -> ToolResult:
        descriptor = self._descriptors.get(tool_id)
        if descriptor is None:
            raise LookupError("TOOL_NOT_REGISTERED")
        if descriptor.action_class is not ActionClass.READ_ONLY:
            raise PermissionError("TOOL_REQUIRES_APPROVAL")

        safe_payload = payload or {}
        if self.security is not None:
            context = security_context or {}
            self.security.enforce_tool(
                request_id=str(
                    context.get("request_id")
                    or f"internal-tool:{tool_id}:{uuid4().hex}"
                ),
                agent_id=str(context.get("agent_id") or self.security_agent_id),
                server_id=self.security_server_id,
                tool_name=tool_id,
                data_class=str(context.get("data_class") or "internal"),
                resource=(
                    str(context["resource"])
                    if context.get("resource") is not None
                    else tool_id
                ),
                provider=(
                    str(context["provider"])
                    if context.get("provider") is not None
                    else None
                ),
                untrusted_context=bool(context.get("untrusted_context", False)),
                approved=bool(context.get("approved", False)),
                cost_units=0,
                argument_count=len(safe_payload),
            )
        return self._handlers[tool_id](safe_payload)


def _module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


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
            "external_synthesis": True,
            "durable_orchestrator": True,
            "operational_certification": "required",
        },
        sources=(
            "app/brain",
            "app/reasoning_ledger",
            "app/reasoning_publication",
            "app/calyx_orchestrator",
        ),
        warnings=(
            () if configured else ("DATABASE_URL is not configured in this process.",)
        ),
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
            "orchestrator_telemetry": True,
            "mutations_automatic": False,
        },
        sources=(
            "app/executive_telemetry",
            "app/mission_control_release",
            "app/calyx_orchestrator",
        ),
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
                "external_synthesis",
                "durable_orchestrator",
                "design_intelligence",
                "educational_design_intelligence",
            ],
            "priority_gaps": [
                "end_to_end_brain_certification",
                "preproduction_orchestrator_activation",
                "university_course_runtime_integration",
                "design_to_frontend_approval_workflow",
                "post_publication_lifecycle",
            ],
            "parallelizable": [
                "frontend_calyx_workspace",
                "brain_certification",
                "education_runtime_integration",
                "website_design_audits",
            ],
        },
        sources=("docs/architecture", "registered runtime modules"),
        warnings=("Repository-wide dynamic inventory expansion remains pending.",),
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
            else ("No PostgreSQL configuration is visible in this process.",)
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
            () if available else ("No canonical archive runtime module was discoverable.",)
        ),
    )


def _harvester_readiness(_: dict[str, Any]) -> ToolResult:
    modules = {
        "harvest": _module_available("app.harvest"),
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
        sources=(
            "app/harvest",
            "app/harvester",
            "app/harvesters",
            "app/runtime/connectors",
        ),
        warnings=(
            () if available else ("No canonical harvester runtime module was discoverable.",)
        ),
    )


def _design_readiness(_: dict[str, Any]) -> ToolResult:
    available = _module_available("app.design_intelligence")
    configured = bool(os.getenv("DATABASE_URL") or os.getenv("PGHOST"))
    return ToolResult(
        tool_id="design_intelligence.readiness",
        status=(
            "ready"
            if available and configured
            else "available"
            if available
            else "degraded"
        ),
        data={
            "runtime_available": available,
            "database_configured": configured,
            "corpus_search": True,
            "semantic_reasoning_search": True,
            "ux_ui": True,
            "accessibility": True,
            "information_architecture": True,
            "scientific_visualization": True,
            "automatic_frontend_mutation": False,
        },
        sources=(
            "app/design_intelligence",
            "docs/BUILD-089A-DESIGN-INTELLIGENCE-CORPUS.md",
        ),
        warnings=(
            () if available else ("Design Intelligence runtime is not importable.",)
        ),
    )


def _design_search(payload: dict[str, Any]) -> ToolResult:
    query = str(payload.get("query") or "").strip()
    if not query:
        raise ValueError("DESIGN_QUERY_REQUIRED")
    from app.design_intelligence.routes import REASONING_SERVICE

    result = REASONING_SERVICE.search(
        query,
        limit=min(int(payload.get("limit", 10)), 25),
    )
    return ToolResult(
        tool_id="design_intelligence.search",
        status="completed",
        data=result,
        sources=("app/design_intelligence/reasoning.py",),
        warnings=("Results are advisory; website changes require owner approval.",),
    )


def _education_readiness(_: dict[str, Any]) -> ToolResult:
    from app.design_intelligence.knowledge import EducationalClassification

    classifications = [item.value for item in EducationalClassification]
    return ToolResult(
        tool_id="education.readiness",
        status="partial",
        data={
            "educational_design_classifications": classifications,
            "learning_sciences_indexing": True,
            "curriculum_runtime": False,
            "course_persistence": False,
            "assessment_engine": False,
            "student_progress": False,
            "virtual_lab_runtime": False,
            "recommendation_preparation": True,
            "automatic_course_publication": False,
        },
        sources=(
            "app/design_intelligence/knowledge.py",
            "app/design_intelligence/reasoning.py",
        ),
        warnings=(
            "Educational design intelligence exists, but the complete University runtime is not integrated.",
        ),
    )


def default_tool_registry() -> AgentToolRegistry:
    from app.calyx_orchestrator.orchid_security_boundary import (
        build_orchid_continuum_security_boundary,
    )

    registry = AgentToolRegistry(
        security=build_orchid_continuum_security_boundary(),
        security_agent_id="calyx.agent",
    )
    registrations = (
        (
            "brain.readiness",
            "Brain readiness",
            "Inspect Knowledge Graph, inference, ledger, publication, and orchestration readiness.",
            _brain_readiness,
        ),
        (
            "mission_control.readiness",
            "Mission Control readiness",
            "Inspect operational telemetry and governance availability.",
            _mission_control_readiness,
        ),
        (
            "continuum.build_inventory",
            "Continuum build inventory",
            "Return the canonical build map and priority gaps.",
            _build_inventory,
        ),
        (
            "journalism.readiness",
            "Calyx journalism readiness",
            "Inspect durable evidence and article-generation boundaries.",
            _journalism_readiness,
        ),
        (
            "archive.readiness",
            "Institutional archive readiness",
            "Inspect archive runtime and provenance boundaries.",
            _archive_readiness,
        ),
        (
            "harvester.readiness",
            "Harvester readiness",
            "Inspect harvester and connector runtime availability.",
            _harvester_readiness,
        ),
        (
            "design_intelligence.readiness",
            "Design Intelligence readiness",
            "Inspect website design, UX, accessibility, and visualization intelligence.",
            _design_readiness,
        ),
        (
            "design_intelligence.search",
            "Design Intelligence search",
            "Search existing design and educational-design knowledge with provenance.",
            _design_search,
        ),
        (
            "education.readiness",
            "Education readiness",
            "Inspect educational-design knowledge and University runtime gaps.",
            _education_readiness,
        ),
    )
    for tool_id, title, description, handler in registrations:
        registry.register(
            ToolDescriptor(tool_id, title, ActionClass.READ_ONLY, description),
            handler,
        )
    return registry
