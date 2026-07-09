"""BUILD-041 read-only Kernel activation services."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Literal

from pydantic import BaseModel, Field

from .kernel_registry import (
    BuildRegistryEntry,
    CapabilityRegistryEntry,
    IntegrationRegistryEntry,
    KernelRegistryService,
    RegistryObject,
    ServiceRegistryEntry,
    _dump_model,
)


class DependencyEdge(BaseModel):
    source_id: str
    target_id: str
    relationship: Literal["depends_on", "requires", "unblocks"]
    source_type: str
    target_type: str


class DependencyGraph(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[DependencyEdge]


class SecretReference(BaseModel):
    integration_id: str
    provider: str
    credential_reference: str
    state: Literal["reference_only", "missing_reference"]
    exposed: bool = False
    supported_future_providers: list[str] = Field(
        default_factory=lambda: ["Azure Key Vault", "Google Secret Manager", "AWS Secrets Manager"]
    )


class KernelSecretsVault:
    """Reference-only vault facade. It never reads or exposes secret values."""

    def references(self, integrations: list[IntegrationRegistryEntry]) -> list[SecretReference]:
        return [
            SecretReference(
                integration_id=integration.id,
                provider=integration.provider,
                credential_reference=integration.credential_reference or "",
                state="reference_only" if integration.credential_reference else "missing_reference",
            )
            for integration in integrations
        ]


class KernelQueryService:
    """Reusable read-only queries over Kernel registry objects."""

    def __init__(self, registry: KernelRegistryService | None = None) -> None:
        self.registry = registry or KernelRegistryService()

    def find_applications(self, query: str | None = None) -> list[dict[str, Any]]:
        return self._filter(self.registry.applications(), query)

    def find_services(self, query: str | None = None) -> list[dict[str, Any]]:
        return self._filter(self.registry.services(), query)

    def find_integrations(self, query: str | None = None) -> list[dict[str, Any]]:
        return self._filter(self.registry.integrations(), query)

    def find_capabilities(self, query: str | None = None, application_id: str | None = None) -> list[dict[str, Any]]:
        return [_dump_model(item) for item in self.registry.query_capabilities(query=query, application_id=application_id)]

    def find_blockers(self) -> list[dict[str, Any]]:
        blockers = []
        for build in self.registry.builds():
            for blocker in build.blockers:
                blockers.append({"build_id": build.id, "build_number": build.build_number, "blocker": blocker})
        return blockers

    def find_unhealthy_systems(self) -> list[dict[str, Any]]:
        items = self._all_registry_objects()
        return [_dump_model(item) for item in items if item.health in {"attention", "degraded", "critical", "unknown"}]

    def find_disconnected_integrations(self) -> list[dict[str, Any]]:
        return [
            _dump_model(item)
            for item in self.registry.integrations()
            if item.health != "healthy" or item.authentication_status in {"unknown", "not_configured"}
        ]

    def find_builds_waiting_on_dependencies(self) -> list[dict[str, Any]]:
        service_ids = {service.id for service in self.registry.services() if service.health == "healthy"}
        integration_ids = {integration.id for integration in self.registry.integrations() if integration.health == "healthy"}
        healthy_ids = service_ids | integration_ids | {build.id for build in self.registry.builds() if build.health == "healthy"}
        waiting = []
        for build in self.registry.builds():
            missing = [dep for dep in build.dependencies if dep not in healthy_ids and dep != "runtime"]
            if missing or build.blockers:
                waiting.append({**_dump_model(build), "waiting_on": missing})
        return waiting

    def dependencies_for(self, object_id: str) -> dict[str, Any]:
        graph = KernelDependencyGraphService(self.registry).graph()
        edges = [edge for edge in graph.edges if edge.source_id == object_id]
        reverse = [edge for edge in graph.edges if edge.target_id == object_id]
        return {
            "object_id": object_id,
            "depends_on": [_dump_model(edge) for edge in edges],
            "depended_on_by": [_dump_model(edge) for edge in reverse],
        }

    def query(self, kind: str | None = None, query: str | None = None) -> dict[str, Any]:
        kind = (kind or "all").lower()
        return {
            "kind": kind,
            "query": query,
            "applications": self.find_applications(query) if kind in {"all", "applications"} else [],
            "services": self.find_services(query) if kind in {"all", "services"} else [],
            "integrations": self.find_integrations(query) if kind in {"all", "integrations"} else [],
            "capabilities": self.find_capabilities(query=query) if kind in {"all", "capabilities"} else [],
            "blockers": self.find_blockers() if kind in {"all", "blockers"} else [],
            "unhealthy_systems": self.find_unhealthy_systems() if kind in {"all", "unhealthy"} else [],
            "disconnected_integrations": self.find_disconnected_integrations() if kind in {"all", "disconnected"} else [],
            "builds_waiting_on_dependencies": self.find_builds_waiting_on_dependencies() if kind in {"all", "builds"} else [],
        }

    def _filter(self, items: list[RegistryObject], query: str | None = None) -> list[dict[str, Any]]:
        if not query:
            return [_dump_model(item) for item in items]
        normalized = query.lower()
        return [
            _dump_model(item)
            for item in items
            if normalized in item.id.lower()
            or normalized in item.name.lower()
            or normalized in item.description.lower()
            or any(normalized in value.lower() for value in item.capabilities)
            or any(normalized in value.lower() for value in item.dependencies)
        ]

    def _all_registry_objects(self) -> list[RegistryObject]:
        return [
            *self.registry.applications(),
            *self.registry.services(),
            *self.registry.capabilities(),
            *self.registry.integrations(),
            *self.registry.builds(),
        ]


class KernelDependencyGraphService:
    """Builds traversable dependency relationships between registry objects."""

    def __init__(self, registry: KernelRegistryService | None = None) -> None:
        self.registry = registry or KernelRegistryService()

    def graph(self) -> DependencyGraph:
        nodes: list[dict[str, Any]] = []
        edges: list[DependencyEdge] = []

        for application in self.registry.applications():
            nodes.append({"id": application.id, "type": "application", "name": application.name})
            edges.extend(self._edges(application.id, "application", application.dependencies))

        for service in self.registry.services():
            nodes.append({"id": service.id, "type": "service", "name": service.name})
            edges.extend(self._edges(service.id, "service", service.dependencies))

        for capability in self.registry.capabilities():
            nodes.append({"id": capability.id, "type": "capability", "name": capability.name})
            dependencies = [capability.application_id, *capability.dependencies]
            edges.extend(self._edges(capability.id, "capability", sorted(set(dependencies))))

        for integration in self.registry.integrations():
            nodes.append({"id": integration.id, "type": "integration", "name": integration.name})

        for build in self.registry.builds():
            nodes.append({"id": build.id, "type": "build", "name": build.name})
            edges.extend(self._edges(build.id, "build", build.dependencies))
            if build.next_build:
                edges.append(
                    DependencyEdge(
                        source_id=build.id,
                        target_id=build.next_build.lower().replace(" ", "-"),
                        relationship="unblocks",
                        source_type="build",
                        target_type="build",
                    )
                )

        return DependencyGraph(nodes=nodes, edges=edges)

    def traverse(self, object_id: str, max_depth: int = 4) -> dict[str, Any]:
        graph = self.graph()
        adjacency: dict[str, list[DependencyEdge]] = defaultdict(list)
        for edge in graph.edges:
            adjacency[edge.source_id].append(edge)

        visited = {object_id}
        queue: deque[tuple[str, int]] = deque([(object_id, 0)])
        path_edges: list[DependencyEdge] = []

        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for edge in adjacency.get(current, []):
                path_edges.append(edge)
                if edge.target_id not in visited:
                    visited.add(edge.target_id)
                    queue.append((edge.target_id, depth + 1))

        return {
            "root": object_id,
            "max_depth": max_depth,
            "visited": sorted(visited),
            "edges": [_dump_model(edge) for edge in path_edges],
        }

    def _edges(self, source_id: str, source_type: str, dependencies: list[str]) -> list[DependencyEdge]:
        return [
            DependencyEdge(
                source_id=source_id,
                target_id=dependency,
                relationship="depends_on",
                source_type=source_type,
                target_type=self._target_type(dependency),
            )
            for dependency in dependencies
        ]

    def _target_type(self, dependency: str) -> str:
        if dependency.startswith("build-"):
            return "build"
        if dependency in {integration.id for integration in self.registry.integrations()}:
            return "integration"
        if dependency in {service.id for service in self.registry.services()}:
            return "service"
        if dependency in {application.id for application in self.registry.applications()}:
            return "application"
        return "external"


class CalyxKernelOrchestrator:
    """Read-only reasoning engine over the Kernel. It recommends; it never executes."""

    def __init__(self, registry: KernelRegistryService | None = None) -> None:
        self.registry = registry or KernelRegistryService()
        self.query = KernelQueryService(self.registry)
        self.graph = KernelDependencyGraphService(self.registry)
        self.vault = KernelSecretsVault()

    def recommendations(self) -> dict[str, Any]:
        unhealthy = self.query.find_unhealthy_systems()
        disconnected = self.query.find_disconnected_integrations()
        blocked = self.query.find_builds_waiting_on_dependencies()
        return {
            "mode": "recommendations_only_no_execution",
            "unhealthy_systems": unhealthy,
            "missing_integrations": disconnected,
            "blocked_builds": blocked,
            "recommended_next_build": self.recommended_next_build(),
            "deployment_order": self.deployment_order(),
            "dependency_resolution": self.dependency_resolution(unhealthy, disconnected),
            "registry_completion": self.registry_completion(),
            "telemetry_improvements": self.telemetry_improvements(),
            "governance": self.registry.governance()["constitution"],
        }

    def planner(self) -> dict[str, Any]:
        return {
            "mode": "planning_only_no_execution",
            "recommended_next_build": self.recommended_next_build(),
            "dependency_ordering": self.deployment_order(),
            "missing_infrastructure": [
                item["id"] for item in self.query.find_unhealthy_systems() if item.get("telemetry_unavailable_reason")
            ],
            "missing_integrations": [item["id"] for item in self.query.find_disconnected_integrations()],
            "registry_completion_score": self.registry_completion()["score"],
            "service_maturity_score": self.service_maturity()["score"],
            "future_autonomy_interfaces": self.runtime_interfaces(),
        }

    def tasks(self) -> dict[str, Any]:
        builds = sorted(self.registry.builds(), key=lambda build: build.priority, reverse=True)
        return {
            "tasks": [_dump_model(build) for build in builds],
            "completed_builds": [_dump_model(build) for build in builds if build.status == "active" and not build.blockers],
            "active_builds": [_dump_model(build) for build in builds if build.status == "active"],
            "blocked_builds": [_dump_model(build) for build in builds if build.blockers],
            "recommended_next_build": self.recommended_next_build(),
        }

    def runtime(self) -> dict[str, Any]:
        return {
            "interfaces": self.runtime_interfaces(),
            "secrets_vault": [_dump_model(ref) for ref in self.vault.references(self.registry.integrations())],
            "reasoning_context": {
                "registries": ["applications", "services", "capabilities", "integrations", "tasks", "governance"],
                "execution_allowed": False,
                "writes_allowed": False,
                "autonomous_deployment_allowed": False,
            },
        }

    def recommended_next_build(self) -> dict[str, Any]:
        candidates = [build for build in self.registry.builds() if build.id == "build-041" or build.next_build]
        best = max(candidates, key=lambda build: build.priority)
        return {
            "build_id": best.id,
            "build_number": best.build_number,
            "priority": best.priority,
            "estimated_complexity": best.estimated_complexity,
            "reason": "Highest-priority active Kernel task; recommendations remain read-only.",
        }

    def deployment_order(self) -> list[str]:
        return ["fastapi", "postgres", "telemetry", "scheduler", "taxonomy-service", "image-service", "relationship-engine", "mission-control", "atlas"]

    def dependency_resolution(self, unhealthy: list[dict[str, Any]], disconnected: list[dict[str, Any]]) -> list[dict[str, Any]]:
        actions = []
        for item in unhealthy[:10]:
            actions.append({
                "target": item["id"],
                "recommendation": item.get("recommendation") or "Connect live telemetry and validate dependencies.",
                "reason": item.get("telemetry_unavailable_reason") or item.get("warning") or "Health is not fully healthy.",
            })
        for item in disconnected[:10]:
            actions.append({
                "target": item["id"],
                "recommendation": "Validate credential reference and provider rate-limit telemetry.",
                "reason": item.get("telemetry_unavailable_reason") or "Integration is not confirmed healthy.",
            })
        return actions

    def registry_completion(self) -> dict[str, Any]:
        all_items = [
            *self.registry.applications(),
            *self.registry.services(),
            *self.registry.capabilities(),
            *self.registry.integrations(),
            *self.registry.builds(),
        ]
        complete = [
            item
            for item in all_items
            if item.telemetry_source and item.evidence and item.capabilities and item.confidence >= 0.5
        ]
        score = round(len(complete) / len(all_items), 3) if all_items else 0.0
        return {"score": score, "complete": len(complete), "total": len(all_items)}

    def service_maturity(self) -> dict[str, Any]:
        services = self.registry.services()
        mature = [service for service in services if service.health == "healthy" and service.last_heartbeat]
        score = round(len(mature) / len(services), 3) if services else 0.0
        return {"score": score, "mature": len(mature), "total": len(services)}

    def telemetry_improvements(self) -> list[dict[str, str]]:
        return [
            {
                "id": item.id,
                "reason": item.telemetry_unavailable_reason or item.warning or "Telemetry confidence below operational threshold.",
                "recommendation": item.recommendation or "Connect live telemetry source.",
            }
            for item in [
                *self.registry.applications(),
                *self.registry.services(),
                *self.registry.integrations(),
            ]
            if item.confidence < 0.8 or item.telemetry_unavailable_reason
        ]

    def runtime_interfaces(self) -> list[dict[str, str]]:
        return [
            {"id": "planner", "status": "architecture_only", "write_authority": "none"},
            {"id": "scheduler", "status": "architecture_only", "write_authority": "none"},
            {"id": "task-queue", "status": "architecture_only", "write_authority": "none"},
            {"id": "agent-registry", "status": "architecture_only", "write_authority": "none"},
            {"id": "execution-pipeline", "status": "architecture_only", "write_authority": "none"},
            {"id": "reasoning-context", "status": "active_read_only", "write_authority": "none"},
        ]
