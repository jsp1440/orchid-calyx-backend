"""BUILD-040/041 Orchid Continuum Kernel registries.

The Kernel is intentionally read-only. It exposes a typed, registry-driven
view of existing Orchid Continuum applications, services, capabilities,
integrations, builds, and governance state without reaching for secrets or
mutating runtime systems.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from .constitutional_orchestrator import orchestrator


KernelStatus = Literal["active", "planned", "degraded", "blocked", "retired"]
KernelHealth = Literal["healthy", "attention", "degraded", "critical", "unknown"]

KERNEL_VERSION = "0.2.0"
KERNEL_UPDATED_AT = "2026-07-09T00:00:00+00:00"


class TelemetryEvidence(BaseModel):
    source: str
    summary: str
    observed_at: str = KERNEL_UPDATED_AT


class TelemetryState(BaseModel):
    status: KernelStatus
    health: KernelHealth
    availability: str = "unknown"
    last_heartbeat: str | None = None
    last_updated: str = KERNEL_UPDATED_AT
    telemetry_source: str
    evidence: list[TelemetryEvidence] = Field(default_factory=list)
    warning: str | None = None
    warnings: list[str] = Field(default_factory=list)
    recommendation: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    unavailable_reason: str | None = None


class RegistryObject(BaseModel):
    id: str
    name: str
    description: str
    version: str
    status: KernelStatus
    health: KernelHealth
    owner: str
    repository: str | None = None
    url: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    availability: str = "unknown"
    last_heartbeat: str | None = None
    telemetry_source: str
    last_updated: str = KERNEL_UPDATED_AT
    evidence: list[TelemetryEvidence] = Field(default_factory=list)
    warning: str | None = None
    warnings: list[str] = Field(default_factory=list)
    recommendation: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    telemetry_unavailable_reason: str | None = None

    def telemetry(self) -> TelemetryState:
        return TelemetryState(
            status=self.status,
            health=self.health,
            availability=self.availability,
            last_heartbeat=self.last_heartbeat,
            last_updated=self.last_updated,
            telemetry_source=self.telemetry_source,
            evidence=self.evidence,
            warning=self.warning,
            warnings=self.warnings or ([self.warning] if self.warning else []),
            recommendation=self.recommendation,
            confidence=self.confidence,
            unavailable_reason=self.telemetry_unavailable_reason,
        )


class ApplicationRegistryEntry(RegistryObject):
    route: str
    deployment: str
    permissions: list[str] = Field(default_factory=list)


class ServiceRegistryEntry(RegistryObject):
    pass


class CapabilityRegistryEntry(RegistryObject):
    application_id: str
    capability_key: str
    query_terms: list[str] = Field(default_factory=list)


class RateLimit(BaseModel):
    window: str
    limit: str
    source: str


class IntegrationRegistryEntry(RegistryObject):
    authentication_status: Literal["configured", "not_configured", "external", "unknown"]
    rate_limits: list[RateLimit] = Field(default_factory=list)
    provider: str
    last_validation: str | None = None
    credential_reference: str | None = None


class BuildRegistryEntry(RegistryObject):
    build_number: str
    branch: str
    pr: str | None = None
    deployment: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    next_build: str | None = None
    priority: int = Field(default=50, ge=0, le=100)
    estimated_complexity: Literal["low", "medium", "high"] = "medium"


class ConstitutionRegistryEntry(BaseModel):
    governance_version: str
    policy_count: int
    decision_count: int
    mission_count: int = 0
    question_count: int = 0
    constitutional_status: str
    telemetry: TelemetryState


class KernelHealthSummary(BaseModel):
    kernel_version: str
    generated_at: str
    status: str
    health: KernelHealth
    registry_counts: dict[str, int]
    degraded: list[str]
    warnings: list[str]
    governance: ConstitutionRegistryEntry


def _evidence(source: str, summary: str) -> list[TelemetryEvidence]:
    return [TelemetryEvidence(source=source, summary=summary)]


class KernelRegistryService:
    """Read-only registry service for the Orchid Continuum Kernel."""

    owner = "Orchid Continuum"
    backend_repo = "jsp1440/orchid-calyx-backend"
    frontend_repo = "jsp1440/orchid-continuum-frontend"

    def applications(self) -> list[ApplicationRegistryEntry]:
        return [
            ApplicationRegistryEntry(
                id="mission-control",
                name="Mission Control",
                description="Operational command surface for telemetry, health, recommendations, build tracking, safety, and governance.",
                version="build-039+",
                status="active",
                health="healthy",
                owner=self.owner,
                repository=self.frontend_repo,
                url="/mission-control",
                route="/mission-control",
                deployment="frontend",
                dependencies=["fastapi", "telemetry", "scheduler"],
                capabilities=["telemetry", "health", "recommendations", "build-tracking", "safety", "governance"],
                permissions=["read:kernel", "read:telemetry", "read:builds"],
                telemetry_source="mission_control_backend_telemetry",
                evidence=_evidence("BUILD-039", "Mission Control backend telemetry exists and remains the consumer target."),
                availability="available",
                last_heartbeat=KERNEL_UPDATED_AT,
                confidence=0.82,
            ),
            ApplicationRegistryEntry(
                id="atlas",
                name="Atlas",
                description="Geospatial orchid exploration application for regions, habitats, occurrences, imagery, and climate layers.",
                version="continuum",
                status="active",
                health="attention",
                owner=self.owner,
                repository=self.frontend_repo,
                url="/atlas",
                route="/atlas",
                deployment="frontend",
                dependencies=["taxonomy-service", "image-service", "gbif", "inaturalist"],
                capabilities=["explore-regions", "habitat-viewer", "occurrence-search", "image-browser", "climate-layers"],
                permissions=["read:atlas", "read:occurrences"],
                telemetry_source="kernel_static_registry",
                evidence=_evidence("BUILD-040", "Atlas is registered for discoverability; runtime health should be wired later."),
                warning="Runtime Atlas health is not yet probed by the Kernel.",
                warnings=["Runtime Atlas health is not yet probed by the Kernel."],
                recommendation="Connect Atlas route and data-layer probes in a future build.",
                confidence=0.62,
                telemetry_unavailable_reason="No deployment-aware Atlas route probe is available to the backend Kernel yet.",
            ),
            self._app("species-explorer", "Species Explorer", "/species", "Species search and profile exploration.", ["taxonomy-search", "species-profiles", "media-review"]),
            self._app("knowledge-graph", "Knowledge Graph", "/knowledge-graph", "Relationship graph for orchid taxa, traits, evidence, and citations.", ["graph-search", "relationship-browser", "evidence-review"]),
            self._app("vision-lab", "Vision Lab", "/vision-lab", "Computer vision workspace for image evidence, identification support, and review queues.", ["image-analysis", "identification-assist", "evidence-queue"]),
            self._app("grant-office", "Grant Office", "/grant-office", "Funding and grant coordination workspace.", ["grant-tracking", "proposal-support", "deadline-review"]),
            self._app("research-workspace", "Research Workspace", "/research", "Research coordination surface for literature, datasets, and synthesis.", ["literature-workspace", "dataset-review", "research-notes"]),
            self._app("university", "University", "/university", "Learning and curriculum surface for Orchid University.", ["lessons", "quizzes", "glossary"]),
            self._app("conservatory", "Conservatory", "/conservatory", "Collection and stewardship experience for the Orchid Continuum.", ["collection-view", "stewardship", "care-records"]),
            self._app("settings", "Settings", "/settings", "Configuration and account settings surface.", ["preferences", "permissions-view", "configuration-review"]),
        ]

    def services(self) -> list[ServiceRegistryEntry]:
        return [
            self._service("fastapi", "FastAPI", "Primary backend API service.", "healthy", "active", ["postgres", "runtime-router"]),
            self._service("postgres", "Postgres", "Relational persistence layer.", "unknown", "active", [], warning="Database health requires deployment environment telemetry."),
            self._service("supabase", "Supabase", "Supabase project services and authentication-adjacent data integrations.", "unknown", "active", ["postgres"]),
            self._service("render", "Render", "Backend deployment host.", "unknown", "active", ["fastapi"]),
            self._service("harvester-runner", "Harvester Runner", "Background data harvesting runner.", "attention", "planned", ["scheduler", "gbif", "inaturalist"]),
            self._service("scheduler", "Scheduler", "Calyx heartbeat and autonomous loop scheduler.", "healthy", "active", ["fastapi"]),
            self._service("telemetry", "Telemetry", "Operational telemetry collection for Mission Control.", "healthy", "active", ["fastapi"]),
            self._service("image-service", "Image Service", "Image metadata and evidence support service.", "attention", "planned", ["openai", "inaturalist"]),
            self._service("taxonomy-service", "Taxonomy Service", "Taxonomic backbone and species lookup service.", "attention", "active", ["gbif", "world-plants"]),
            self._service("relationship-engine", "Relationship Engine", "Relationship extraction and graph reasoning service.", "attention", "planned", ["postgres", "traitbank", "eol", "zotero"]),
        ]

    def capabilities(self) -> list[CapabilityRegistryEntry]:
        capability_map = {
            "atlas": ["explore-regions", "habitat-viewer", "occurrence-search", "image-browser", "climate-layers"],
            "mission-control": ["telemetry", "health", "recommendations", "build-tracking", "safety", "governance"],
            "species-explorer": ["taxonomy-search", "species-profiles", "media-review"],
            "knowledge-graph": ["graph-search", "relationship-browser", "evidence-review"],
            "vision-lab": ["image-analysis", "identification-assist", "evidence-queue"],
            "grant-office": ["grant-tracking", "proposal-support", "deadline-review"],
            "research-workspace": ["literature-workspace", "dataset-review", "research-notes"],
            "university": ["lessons", "quizzes", "glossary"],
            "conservatory": ["collection-view", "stewardship", "care-records"],
            "settings": ["preferences", "permissions-view", "configuration-review"],
        }
        entries: list[CapabilityRegistryEntry] = []
        for app_id, capabilities in capability_map.items():
            for capability in capabilities:
                entries.append(
                    CapabilityRegistryEntry(
                        id=f"{app_id}.{capability}",
                        name=capability.replace("-", " ").title(),
                        description=f"{capability.replace('-', ' ').title()} capability exposed by {app_id}.",
                        version=KERNEL_VERSION,
                        status="active",
                        health="healthy",
                        owner=self.owner,
                        repository=self.frontend_repo if app_id != "mission-control" else self.backend_repo,
                        dependencies=[app_id],
                        capabilities=[capability],
                        telemetry_source="kernel_capability_registry",
                        evidence=_evidence("BUILD-040", "Capability declared in the Kernel registry."),
                        application_id=app_id,
                        capability_key=capability,
                        query_terms=[app_id, capability, capability.replace("-", " ")],
                    )
                )
        return entries

    def integrations(self) -> list[IntegrationRegistryEntry]:
        return [
            self._integration("github", "GitHub", ["repository", "pull-requests", "issues"], "external", "healthy"),
            self._integration("render", "Render", ["deployments", "service-health"], "external", "unknown"),
            self._integration("azure", "Azure", ["cloud-services"], "unknown", "unknown"),
            self._integration("openai", "OpenAI", ["language-models", "vision", "embeddings"], "unknown", "attention"),
            self._integration("claude", "Claude", ["language-models"], "unknown", "unknown"),
            self._integration("kimi", "Kimi", ["language-models"], "unknown", "unknown"),
            self._integration("google-drive", "Google Drive", ["docs", "sheets", "file-storage"], "external", "unknown"),
            self._integration("gmail", "Gmail", ["mail-search", "mail-triage"], "external", "unknown"),
            self._integration("supabase", "Supabase", ["database", "auth-adjacent-services"], "unknown", "unknown"),
            self._integration("neon", "Neon", ["postgres"], "unknown", "unknown"),
            self._integration("gbif", "GBIF", ["occurrences", "taxonomy"], "external", "healthy"),
            self._integration("inaturalist", "iNaturalist", ["observations", "images"], "external", "healthy"),
            self._integration("eol", "EOL", ["species-pages", "traits"], "external", "unknown"),
            self._integration("traitbank", "TraitBank", ["traits"], "external", "unknown"),
            self._integration("world-plants", "World Plants", ["taxonomy"], "external", "unknown"),
            self._integration("zenodo", "Zenodo", ["datasets", "archives"], "external", "unknown"),
            self._integration("genbank", "GenBank", ["sequences"], "external", "unknown"),
            self._integration("bold", "BOLD", ["barcodes"], "external", "unknown"),
            self._integration("zotero", "Zotero", ["citations", "libraries"], "unknown", "unknown"),
        ]

    def builds(self) -> list[BuildRegistryEntry]:
        return [
            BuildRegistryEntry(
                id="build-040",
                name="BUILD-040 Orchid Continuum Kernel",
                description="Foundational registry-driven Kernel for Orchid Continuum discoverability.",
                version=KERNEL_VERSION,
                status="active",
                health="healthy",
                owner=self.owner,
                repository=self.backend_repo,
                dependencies=["fastapi", "runtime"],
                capabilities=["application-registry", "service-registry", "capability-registry", "integration-registry", "task-registry"],
                telemetry_source="kernel_build_registry",
                evidence=_evidence("BUILD-040", "Build represented as structured Kernel task/build registry object."),
                build_number="BUILD-040",
                branch="feature/build-040-orchid-continuum-kernel",
                pr=None,
                deployment="backend",
                success_criteria=[
                    "Typed registries exist",
                    "Read-only /api/kernel endpoints are mounted",
                    "Mission Control can consume registry data in a later build",
                ],
                blockers=[],
                next_build="BUILD-041",
                priority=95,
                estimated_complexity="medium",
            ),
            BuildRegistryEntry(
                id="build-039",
                name="BUILD-039 Mission Control Backend Telemetry",
                description="Mission Control backend telemetry foundation consumed by Kernel registry evidence.",
                version="build-039",
                status="active",
                health="healthy",
                owner=self.owner,
                repository=self.backend_repo,
                dependencies=["fastapi"],
                capabilities=["telemetry", "mission-control"],
                telemetry_source="docs/builds/BUILD-039_MISSION_CONTROL_BACKEND_TELEMETRY.md",
                evidence=_evidence("BUILD-039", "Prior build establishes Mission Control telemetry context."),
                build_number="BUILD-039",
                branch="build-039-mission-control-backend-telemetry",
                deployment="backend",
                success_criteria=["Mission Control telemetry endpoint exists"],
                next_build="BUILD-040",
                priority=80,
                estimated_complexity="medium",
            ),
            BuildRegistryEntry(
                id="build-041",
                name="BUILD-041 Kernel Activation",
                description="Activation layer that lets Calyx query, reason over, and recommend next actions from Kernel registries.",
                version=KERNEL_VERSION,
                status="active",
                health="healthy",
                owner=self.owner,
                repository=self.backend_repo,
                dependencies=["build-040", "fastapi", "runtime"],
                capabilities=["kernel-query-engine", "dependency-graph", "planning", "recommendations", "governance-registry"],
                telemetry_source="kernel_build_registry",
                evidence=_evidence("BUILD-041", "Build represented as structured active Kernel task object."),
                build_number="BUILD-041",
                branch="feature/build-041-kernel-activation",
                deployment="backend",
                success_criteria=[
                    "Kernel dependency graph is queryable",
                    "Read-only planner and recommendation endpoints exist",
                    "Governance is exposed through the Kernel",
                ],
                blockers=["Existing RuntimeExecutor test mismatch remains outside BUILD-041 scope."],
                next_build="Mission Control registry consumption",
                priority=100,
                estimated_complexity="high",
            ),
        ]

    def constitution(self) -> ConstitutionRegistryEntry:
        status = orchestrator.status()
        missions = orchestrator.mission_registry().get("missions", [])
        questions = orchestrator.governance_questions().get("questions", [])
        health: KernelHealth = "healthy" if status.get("status") else "unknown"
        return ConstitutionRegistryEntry(
            governance_version=str(status.get("build", "unknown")),
            policy_count=int(status.get("policy_count", 0)),
            decision_count=int(status.get("decision_count", 0)),
            mission_count=len(missions),
            question_count=len(questions),
            constitutional_status=str(status.get("status", "unknown")),
            telemetry=TelemetryState(
                status="active",
                health=health,
                availability="available",
                last_heartbeat=str(status.get("timestamp", KERNEL_UPDATED_AT)),
                telemetry_source="runtime.constitutional_orchestrator",
                evidence=_evidence("BUILD-034", "Constitutional orchestrator supplies governance status."),
                recommendation="Expose this Kernel governance block to Mission Control after frontend registry consumption work.",
                confidence=0.9,
            ),
        )

    def health(self) -> KernelHealthSummary:
        registries: dict[str, list[RegistryObject]] = {
            "applications": self.applications(),
            "services": self.services(),
            "capabilities": self.capabilities(),
            "integrations": self.integrations(),
            "builds": self.builds(),
        }
        all_items = [item for items in registries.values() for item in items]
        degraded = [item.id for item in all_items if item.health in {"degraded", "critical"}]
        warnings = [f"{item.id}: {item.warning}" for item in all_items if item.warning]
        attention_count = sum(1 for item in all_items if item.health in {"attention", "unknown"})

        if any(item.health == "critical" for item in all_items):
            health: KernelHealth = "critical"
        elif degraded:
            health = "degraded"
        elif attention_count:
            health = "attention"
        else:
            health = "healthy"

        return KernelHealthSummary(
            kernel_version=KERNEL_VERSION,
            generated_at=datetime.now(timezone.utc).isoformat(),
            status="kernel_registry_ready",
            health=health,
            registry_counts={name: len(items) for name, items in registries.items()},
            degraded=degraded,
            warnings=warnings,
            governance=self.constitution(),
        )

    def governance(self) -> dict[str, Any]:
        return {
            "status": orchestrator.status(),
            "missions": orchestrator.mission_registry().get("missions", []),
            "policies": orchestrator.policy_registry().get("policies", []),
            "decisions": orchestrator.decision_ledger().get("decisions", []),
            "questions": orchestrator.governance_questions().get("questions", []),
            "constitution": _dump_model(self.constitution()),
        }

    def query_capabilities(self, query: str | None = None, application_id: str | None = None) -> list[CapabilityRegistryEntry]:
        capabilities = self.capabilities()
        if application_id:
            capabilities = [cap for cap in capabilities if cap.application_id == application_id]
        if query:
            normalized = query.lower()
            capabilities = [
                cap
                for cap in capabilities
                if normalized in cap.name.lower()
                or normalized in cap.description.lower()
                or any(normalized in term.lower() for term in cap.query_terms)
            ]
        return capabilities

    def _app(
        self,
        app_id: str,
        name: str,
        route: str,
        description: str,
        capabilities: list[str],
    ) -> ApplicationRegistryEntry:
        return ApplicationRegistryEntry(
            id=app_id,
            name=name,
            description=description,
            version="continuum",
            status="active",
            health="attention",
            owner=self.owner,
            repository=self.frontend_repo,
            url=route,
            route=route,
            deployment="frontend",
            dependencies=["fastapi"],
            capabilities=capabilities,
            permissions=[f"read:{app_id}"],
            telemetry_source="kernel_static_registry",
            evidence=_evidence("BUILD-040", f"{name} registered for platform discovery."),
            warning="Kernel registration is present; live application probe is not wired yet.",
            warnings=["Kernel registration is present; live application probe is not wired yet."],
            recommendation="Add deployment-aware health probes when Mission Control consumes the registry.",
            confidence=0.58,
            telemetry_unavailable_reason="No frontend route probe is available from the backend Kernel in this build.",
        )

    def _service(
        self,
        service_id: str,
        name: str,
        description: str,
        health: KernelHealth,
        status: KernelStatus,
        dependencies: list[str],
        warning: str | None = None,
    ) -> ServiceRegistryEntry:
        return ServiceRegistryEntry(
            id=service_id,
            name=name,
            description=description,
            version="continuum",
            status=status,
            health=health,
            owner=self.owner,
            repository=self.backend_repo,
            dependencies=dependencies,
            capabilities=[service_id],
            telemetry_source="kernel_service_registry",
            evidence=_evidence("BUILD-040", f"{name} registered as backend service infrastructure."),
            warning=warning,
            warnings=[warning] if warning else [],
            recommendation="Replace static service telemetry with live deployment heartbeat when available.",
            availability="available" if health == "healthy" else "unknown",
            last_heartbeat=KERNEL_UPDATED_AT if health == "healthy" else None,
            confidence=0.85 if health == "healthy" else 0.45,
            telemetry_unavailable_reason=None if health == "healthy" else "Live service telemetry source is not configured for this registry object.",
        )

    def _integration(
        self,
        integration_id: str,
        name: str,
        capabilities: list[str],
        authentication_status: Literal["configured", "not_configured", "external", "unknown"],
        health: KernelHealth,
    ) -> IntegrationRegistryEntry:
        return IntegrationRegistryEntry(
            id=integration_id,
            name=name,
            description=f"{name} integration for Orchid Continuum capabilities: {', '.join(capabilities)}.",
            version="continuum",
            status="active",
            health=health,
            owner=self.owner,
            repository=self.backend_repo,
            dependencies=[],
            capabilities=capabilities,
            telemetry_source="kernel_integration_registry",
            evidence=_evidence("BUILD-040", f"{name} integration registered without exposing secrets."),
            warning=None if health == "healthy" else "Authentication and live rate limit telemetry are not probed by the Kernel.",
            warnings=[] if health == "healthy" else ["Authentication and live rate limit telemetry are not probed by the Kernel."],
            recommendation="Connect provider-specific health checks through approved connector services.",
            availability="available" if health == "healthy" else "unknown",
            last_heartbeat=KERNEL_UPDATED_AT if health == "healthy" else None,
            confidence=0.75 if health == "healthy" else 0.42,
            telemetry_unavailable_reason=None if health == "healthy" else "Provider validation has not been connected to the Kernel.",
            authentication_status=authentication_status,
            provider=name,
            last_validation=KERNEL_UPDATED_AT if health == "healthy" else None,
            credential_reference=f"vault://orchid-continuum/{integration_id}",
            rate_limits=[
                RateLimit(window="provider-defined", limit="unknown", source="not_configured_in_kernel")
            ],
        )


def as_payload(items: list[BaseModel]) -> list[dict[str, Any]]:
    return [_dump_model(item) for item in items]


def _dump_model(item: BaseModel) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return item.dict()
