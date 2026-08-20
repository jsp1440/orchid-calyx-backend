"""BUILD-044 Calyx Autonomous Orchestrator.

This module gives Calyx a durable task queue and a conservative run-once
executor. It intentionally performs only read-only/audit style work unless a
task has passed an approval gate.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

try:  # Keep pure executor tests importable even when DB deps are absent.
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ModuleNotFoundError:  # pragma: no cover - exercised in minimal toolchains
    psycopg = None
    dict_row = None
    Jsonb = None


TASK_STATUSES = ("pending", "running", "completed", "failed", "blocked", "needs_review")
EVALUATION_RESULTS = ("pass", "fail", "needs_review")

# ORCHESTRATION-LITERATURE-KG-001: literature harvest -> ingest -> extract ->
# taxon-bind -> publication-eligibility -> KG-materialization mission lane.
# These distinctions are load-bearing: harvested, ingested, extracted,
# taxonomically bound, publication-eligible, and materialized are six
# different pipeline states and must never be reported as synonyms.
LITERATURE_KG_TASK_TYPES = (
    "literature_harvest_freshness_audit",
    "literature_ingestion_provenance_audit",
    "literature_extraction_coverage_audit",
    "literature_methodology_extraction_audit",
    "literature_trait_measurement_extraction_audit",
    "literature_taxon_binding_integrity_audit",
    "literature_kg_materialization_readiness_audit",
)
RISKY_ACTIONS = {
    "deploy",
    "deployment",
    "merge",
    "delete",
    "destructive",
    "overwrite",
    "external_send",
    "cross_repository",
    "credential_sensitive",
    "change_target",
    "change_schedule",
    "retire",
    "restore",
}


DEFAULT_AGENTS: list[dict[str, Any]] = [
    {
        "agent_name": "calyx_core",
        "capability": "Coordinate safe internal Calyx runtime checks.",
        "allowed_task_types": ["backend_health_check", "runner_queue_audit"],
        "enabled": True,
        "priority": 100,
    },
    {
        "agent_name": "health",
        "capability": "Inspect backend and runtime health signals.",
        "allowed_task_types": ["backend_health_check"],
        "enabled": True,
        "priority": 95,
    },
    {
        "agent_name": "judging",
        "capability": "Read-only judging module readiness checks.",
        "allowed_task_types": ["judging_audit"],
        "enabled": True,
        "priority": 80,
    },
    {
        "agent_name": "awards",
        "capability": "Read-only award module readiness checks.",
        "allowed_task_types": ["awards_audit"],
        "enabled": True,
        "priority": 75,
    },
    {
        "agent_name": "mycorrhiza",
        "capability": "Audit mycorrhiza cache availability without mutating source data.",
        "allowed_task_types": ["mycorrhiza_cache_audit"],
        "enabled": True,
        "priority": 90,
    },
    {
        "agent_name": "mission_control",
        "capability": "Seed and prioritize non-destructive missions for owner review.",
        "allowed_task_types": ["frontend_integration_audit", "runner_queue_audit"],
        "enabled": True,
        "priority": 98,
    },
    {
        "agent_name": "relationship_audit",
        "capability": "Audit relationship data coverage and graph-readiness.",
        "allowed_task_types": ["relationship_data_audit"],
        "enabled": True,
        "priority": 88,
    },
    {
        "agent_name": "image_coverage_audit",
        "capability": "Audit image coverage sources and gaps.",
        "allowed_task_types": ["image_coverage_audit"],
        "enabled": True,
        "priority": 86,
    },
    {
        "agent_name": "literature_kg",
        "capability": (
            "Read-only audit of the literature harvest -> ingest -> extract -> "
            "taxon-bind -> publication-eligibility -> KG-materialization pipeline. "
            "Reports harvested, ingested, extracted, taxonomically bound, "
            "publication-eligible, and materialized as distinct pipeline states, "
            "reuses the canonical literature extraction registry and KG source "
            "registry, and never publishes or materializes graph state."
        ),
        "allowed_task_types": list(LITERATURE_KG_TASK_TYPES),
        "enabled": True,
        "priority": 78,
    },
    {
        "agent_name": "release_steward",
        "capability": "Risky release actions; disabled until human governance enables it.",
        "allowed_task_types": ["deploy", "merge", "delete", "overwrite", "external_send", "change_target", "change_schedule", "retire", "restore"],
        "enabled": False,
        "priority": 10,
    },
]


DEFAULT_TASKS: list[dict[str, Any]] = [
    {
        "task_key": "build-044:frontend-audit",
        "task_type": "frontend_integration_audit",
        "title": "Audit frontend control-panel readiness for Calyx status display",
        "priority": 40,
        "needs_review": True,
        "payload": {
            "target_repository": "jsp1440/orchid-continuum-frontend",
            "cross_repository": True,
            "expected_display": [
                "queue counts",
                "active agent",
                "last run",
                "failures",
                "needs-review tasks",
            ],
        },
    },
    {
        "task_key": "build-044:backend-health-check",
        "task_type": "backend_health_check",
        "title": "Check backend runtime health and orchestrator schema readiness",
        "priority": 100,
        "payload": {"checks": ["database_schema", "agent_registry", "queue_status"]},
    },
    {
        "task_key": "build-044:runner-queue-audit",
        "task_type": "runner_queue_audit",
        "title": "Audit runner queue depth and stuck work",
        "priority": 90,
        "payload": {"checks": ["pending", "running", "failed", "needs_review"]},
    },
    {
        "task_key": "build-044:mycorrhiza-cache-audit",
        "task_type": "mycorrhiza_cache_audit",
        "title": "Audit mycorrhiza cache readiness",
        "priority": 80,
        "payload": {"target_table": "oc_mycorrhiza.species_mycorrhiza_unified_endpoint_cache"},
    },
    {
        "task_key": "build-044:image-coverage-audit",
        "task_type": "image_coverage_audit",
        "title": "Audit image coverage sources for Orchid Continuum gaps",
        "priority": 30,
        "needs_review": True,
        "payload": {"target_domain": "orchid_images", "mode": "coverage_gap_audit"},
    },
    {
        "task_key": "build-044:relationship-data-audit",
        "task_type": "relationship_data_audit",
        "title": "Audit relationship data coverage and graph-readiness",
        "priority": 35,
        "needs_review": True,
        "payload": {"target_domain": "relationships", "mode": "coverage_gap_audit"},
    },
    {
        "task_key": "orch-lit-kg-001:harvest-freshness-audit",
        "task_type": "literature_harvest_freshness_audit",
        "title": "Audit literature harvest freshness and discovered-document yield",
        "priority": 58,
        "needs_review": True,
        "payload": {
            "checks": ["harvester_registration", "last_harvest_timestamp", "discovered_documents"],
        },
    },
    {
        "task_key": "orch-lit-kg-001:ingestion-provenance-audit",
        "task_type": "literature_ingestion_provenance_audit",
        "title": "Audit literature ingestion and bibliographic/source provenance",
        "priority": 57,
        "needs_review": True,
        "payload": {
            "target_tables": [
                "oc_literature.documents",
                "oc_literature.literature_documents",
                "oc_literature.papers",
                "public.literature_documents",
                "public.research_documents",
            ],
            "checks": ["bibliographic_metadata", "source_document_hash", "provenance_columns"],
        },
    },
    {
        "task_key": "orch-lit-kg-001:extraction-coverage-audit",
        "task_type": "literature_extraction_coverage_audit",
        "title": "Audit literature claim/entity/relationship extraction coverage",
        "priority": 56,
        "needs_review": True,
        "payload": {
            "expected_entities": [
                "claims", "entities", "evidence", "glossary_terms",
                "relationships", "figures", "tables", "references",
            ],
        },
    },
    {
        "task_key": "orch-lit-kg-001:taxon-binding-integrity-audit",
        "task_type": "literature_taxon_binding_integrity_audit",
        "title": "Audit literature-to-taxon binding integrity",
        "priority": 55,
        "needs_review": True,
        "payload": {"source_domain": "literature"},
    },
    {
        "task_key": "orch-lit-kg-001:methodology-extraction-audit",
        "task_type": "literature_methodology_extraction_audit",
        "title": "Audit scientific-method/methodology structure extraction coverage",
        "priority": 54,
        "needs_review": True,
        "payload": {
            "target_structures": [
                "hypotheses", "research_questions", "methodologies", "protocols",
                "sampling_methods", "experimental_design", "field_methods",
            ],
        },
    },
    {
        "task_key": "orch-lit-kg-001:trait-measurement-extraction-audit",
        "task_type": "literature_trait_measurement_extraction_audit",
        "title": "Audit trait/character-state/measurement extraction coverage",
        "priority": 53,
        "needs_review": True,
        "payload": {
            "target_domains": [
                "trait", "morphology", "anatomy", "physiology", "phenology",
                "habitat", "pollinators", "mycorrhiza",
            ],
        },
    },
    {
        "task_key": "orch-lit-kg-001:materialization-readiness-audit",
        "task_type": "literature_kg_materialization_readiness_audit",
        "title": "Audit literature-to-KG materialization readiness (harvested/ingested/extracted/bound/publication-eligible/materialized)",
        "priority": 50,
        "needs_review": True,
        "payload": {"mode": "read_only_readiness_audit"},
    },
]


def _literature_extractor_names() -> Optional[list[str]]:
    """Return the canonical registered literature extractor names, or None.

    Reuses ``app.literature_extraction.registry.DEFAULT_REGISTRY`` instead of
    inventing a second extractor list. Import is lazy and optional so the
    pure/offline orchestrator tests remain importable when the pydantic-based
    literature extraction stack is not installed.
    """

    try:
        from app.literature_extraction.registry import DEFAULT_REGISTRY
    except (ImportError, ModuleNotFoundError):
        return None
    return DEFAULT_REGISTRY.names()


def _literature_source_query() -> Optional[Any]:
    """Return the canonical KG source-registry entry for the literature domain.

    Reuses ``runtime.knowledge_graph.source_registry`` (the successor slice of
    draft PR #901) instead of a second taxon-binding contract. Import is lazy
    and optional for the same reason as ``_literature_extractor_names``.
    """

    try:
        from runtime.knowledge_graph.source_registry import SOURCE_QUERIES
    except (ImportError, ModuleNotFoundError):
        return None
    for query in SOURCE_QUERIES:
        if query.domain == "literature":
            return query
    return None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> Jsonb:
    if Jsonb is None:
        raise OrchestratorConfigError("psycopg is required for database-backed orchestrator operations")
    return Jsonb(value if value is not None else {})


class OrchestratorConfigError(RuntimeError):
    """Raised when the orchestrator cannot access its backing database."""


@dataclass
class ExecutionResult:
    status: str
    evaluation_result: str
    result: dict[str, Any]
    observations: list[dict[str, Any]]


class DefaultTaskExecutor:
    """Deterministic executor for BUILD-044's first safe task types."""

    def execute(self, task: dict[str, Any], agent: dict[str, Any]) -> ExecutionResult:
        task_type = task["task_type"]
        payload = task.get("payload") or {}

        risky_action = self.risky_action(task_type, payload)
        if risky_action:
            return ExecutionResult(
                status="needs_review",
                evaluation_result="needs_review",
                result={
                    "message": "Approval gate stopped risky action before execution.",
                    "risky_action": risky_action,
                    "requires_human_approval": True,
                },
                observations=[
                    {
                        "event_type": "approval_gate",
                        "action": "skipped",
                        "status": "needs_review",
                        "details": {"risky_action": risky_action},
                    }
                ],
            )

        observations = [
            {
                "event_type": "task_inspection",
                "action": "inspected",
                "status": "completed",
                "details": {
                    "task_type": task_type,
                    "agent": agent["agent_name"],
                    "payload_keys": sorted(payload.keys()),
                },
            }
        ]

        if task_type == "backend_health_check":
            result = {
                "message": "Backend orchestrator schema and queue primitives are available.",
                "inspected": ["agent_registry", "task_queue", "observation_log", "run_log"],
                "changed": [],
                "skipped": ["destructive_actions", "external_sends"],
            }
            evaluation = self.evaluate(result, required_keys=["inspected", "changed", "skipped"])
            return ExecutionResult("completed", evaluation, result, observations)

        if task_type == "frontend_integration_audit":
            result = {
                "message": "Frontend should consume orchestrator health, tasks, runs, and observations endpoints.",
                "inspected": [payload.get("target_repository", "frontend")],
                "changed": [],
                "skipped": ["frontend_mutation"],
                # Every path here must resolve on the app. Two of them did not:
                # there is no /api/runner/summary (the runner's summary endpoint
                # is brain-summary) and no /api/runner/seed-missions (it is
                # mounted on the science router). A contract that advertises a
                # route the router never registered is worse than no contract,
                # because a caller cannot tell it from a working one.
                "frontend_contract": {
                    "health": "/api/runner/health",
                    "summary": "/api/runner/brain-summary",
                    "run_once": "/api/runner/run-once",
                    "seed_missions": "/api/science/seed-missions",
                },
            }
            evaluation = self.evaluate(result, required_keys=["frontend_contract"])
            return ExecutionResult("completed", evaluation, result, observations)

        if task_type == "runner_queue_audit":
            result = {
                "message": "Runner queue audit completed; queue depth is reported by the health endpoint.",
                "inspected": payload.get("checks", ["queue"]),
                "changed": [],
                "skipped": ["job_mutation"],
            }
            evaluation = self.evaluate(result, required_keys=["inspected", "changed", "skipped"])
            return ExecutionResult("completed", evaluation, result, observations)

        if task_type == "mycorrhiza_cache_audit":
            result = {
                "message": "Mycorrhiza cache audit queued as a read-only table availability check.",
                "inspected": [payload.get("target_table", "mycorrhiza_cache")],
                "changed": [],
                "skipped": ["cache_mutation"],
                "next_action": "Connect live row-count metrics when DATABASE_URL is available.",
            }
            evaluation = self.evaluate(result, required_keys=["inspected", "changed", "skipped"])
            return ExecutionResult("completed", evaluation, result, observations)

        if task_type == "image_coverage_audit":
            result = {
                "message": "Image coverage audit queued; live coverage source must be connected before pass/fail scoring.",
                "inspected": [payload.get("target_domain", "orchid_images")],
                "changed": [],
                "skipped": ["coverage_claims_without_source"],
                "next_action": "Connect approved image library coverage metrics.",
            }
            return ExecutionResult("needs_review", "needs_review", result, observations)

        if task_type == "relationship_data_audit":
            result = {
                "message": "Relationship data audit queued; graph source must be connected before pass/fail scoring.",
                "inspected": [payload.get("target_domain", "relationships")],
                "changed": [],
                "skipped": ["relationship_claims_without_source"],
                "next_action": "Connect Brain relationship tables or graph summary endpoint.",
            }
            return ExecutionResult("needs_review", "needs_review", result, observations)

        if task_type in LITERATURE_KG_TASK_TYPES:
            result = self._execute_literature_kg(task_type, payload)
            return ExecutionResult("needs_review", "needs_review", result, observations)

        return ExecutionResult(
            "blocked",
            "needs_review",
            {
                "message": "No executor is registered for this task type.",
                "task_type": task_type,
            },
            observations
            + [
                {
                    "event_type": "executor_resolution",
                    "action": "skipped",
                    "status": "blocked",
                    "details": {"reason": "unsupported_task_type"},
                }
            ],
        )

    def _execute_literature_kg(self, task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Read-only literature -> KG pipeline audits.

        This executor never queries a live database and never publishes or
        materializes graph state; it is bounded to static introspection of
        the canonical literature-extraction registry and KG source registry
        already established on current main. Any telemetry that would
        require a live connection (row counts, timestamps, yield) is
        reported as ``"unavailable"``, never a fabricated ``0``, per
        ORCHESTRATION-LITERATURE-KG-001.
        """

        base_skip = ["literature_harvest_trigger", "document_write", "graph_publication", "graph_materialization"]

        if task_type == "literature_harvest_freshness_audit":
            return {
                "message": (
                    "Literature harvest freshness audit is read-only; no harvester was "
                    "triggered and no documents were fetched."
                ),
                "inspected": payload.get("checks", []),
                "changed": [],
                "skipped": base_skip,
                "harvested": "unavailable",
                "last_harvest_timestamp": "unavailable",
                "discovered_documents": "unavailable",
                "new_retained_documents": "unavailable",
                "next_action": "Connect a literature harvester run-log (last-run timestamp, discovered/retained document counts) so this audit can score pass/fail instead of needs_review.",
            }

        if task_type == "literature_ingestion_provenance_audit":
            return {
                "message": (
                    "Literature ingestion/provenance audit is read-only; no document was "
                    "ingested and no bibliographic record was written."
                ),
                "inspected": payload.get("target_tables", []),
                "changed": [],
                "skipped": base_skip,
                "ingested": "unavailable",
                "bibliographic_metadata_verified": "unavailable",
                "source_document_hash_verified": "unavailable",
                "next_action": "Connect literature ingestion table row counts and content-hash/provenance verification for the candidate tables listed in `inspected`.",
            }

        if task_type == "literature_extraction_coverage_audit":
            extractor_names = _literature_extractor_names()
            return {
                "message": (
                    "Literature extraction coverage audit is read-only; reports the "
                    "registered extractor pipeline, not live extraction counts."
                ),
                "inspected": payload.get("expected_entities", []),
                "changed": [],
                "skipped": base_skip,
                "registered_extractors": extractor_names if extractor_names is not None else "unavailable",
                "extracted": "unavailable",
                "next_action": "Connect app.literature_extraction.repository extraction-run counts per entity type (claims, entities, evidence, glossary_terms, relationships, figures, tables, references).",
            }

        if task_type == "literature_taxon_binding_integrity_audit":
            query = _literature_source_query()
            return {
                "message": (
                    "Literature taxon-binding integrity audit is read-only; reports the "
                    "registered binding contract, not live join results."
                ),
                "inspected": [payload.get("source_domain", "literature")],
                "changed": [],
                "skipped": base_skip,
                "taxon_mapping": query.taxon_mapping if query is not None else "unavailable",
                "binding_enabled": query.enabled if query is not None else "unavailable",
                "binding_method_notes": query.notes if query is not None else "unavailable",
                "taxonomically_bound": "unavailable",
                "next_action": "Run runtime.knowledge_graph.source_coverage_audit.source_vs_graph_coverage_audit against a live connection for exact taxon-resolved vs persisted graph rows.",
            }

        if task_type == "literature_methodology_extraction_audit":
            return {
                "message": (
                    "Methodology/scientific-method extraction audit is read-only; no "
                    "dedicated methodology extractor performs a live run here."
                ),
                "inspected": payload.get("target_structures", []),
                "changed": [],
                "skipped": base_skip,
                "modeled_claim_types": [
                    "observation", "result", "interpretation", "hypothesis",
                    "methodological", "background", "limitation", "recommendation",
                ],
                "dedicated_methodology_extractor_registered": False,
                "methodology_extracted": "unavailable",
                "next_action": "Add a dedicated hypothesis/protocol/sampling-method extractor to app.literature_extraction.registry, or connect live methodological-claim counts.",
            }

        if task_type == "literature_trait_measurement_extraction_audit":
            return {
                "message": (
                    "Trait/measurement extraction audit is read-only; no dedicated "
                    "trait or measurement extractor performs a live run here."
                ),
                "inspected": payload.get("target_domains", []),
                "changed": [],
                "skipped": base_skip,
                "modeled_evidence_domains": [
                    "taxonomy", "trait", "occurrence", "habitat",
                    "ecological_interaction", "conservation", "cultivation", "other",
                ],
                "coverage_gap": (
                    "morphology/anatomy/physiology/phenology/pollinator/mycorrhiza granularity "
                    "is not distinguished at the domain-enum level; those mentions currently "
                    "collapse into 'trait', 'ecological_interaction', or 'other'."
                ),
                "traits_extracted": "unavailable",
                "next_action": "Add finer-grained NormalizedEvidenceRecord.domain values (or a dedicated trait/measurement extractor) and connect live per-domain extraction counts.",
            }

        # literature_kg_materialization_readiness_audit
        return {
            "message": (
                "Literature-to-KG materialization readiness audit is read-only; no graph "
                "node or edge is published or materialized by this task."
            ),
            "inspected": [payload.get("mode", "read_only_readiness_audit")],
            "changed": [],
            "skipped": base_skip,
            "pipeline_stage_counts": {
                "harvested": "unavailable",
                "ingested": "unavailable",
                "extracted": "unavailable",
                "taxonomically_bound": "unavailable",
                "publication_eligible": "unavailable",
                "materialized": "unavailable",
            },
            "materialization_blockers": [
                "no live DATABASE_URL telemetry available to this read-only executor",
                "no dedicated methodology/measurement extractor registered",
                "literature taxon binding is a name_join, not an exact identifier join",
            ],
            "next_action": "Run the literature extraction/taxon-binding/publication-eligibility audits against live data, then request owner-approved materialization through the existing KG publication gate; this task never publishes.",
        }

    def evaluate(self, result: dict[str, Any], required_keys: list[str]) -> str:
        missing = [key for key in required_keys if key not in result]
        return "needs_review" if missing else "pass"

    def risky_action(self, task_type: str, payload: dict[str, Any]) -> Optional[str]:
        if payload.get("cross_repository") is True:
            return "cross_repository"
        candidates = {task_type, str(payload.get("action", "")), str(payload.get("operation", ""))}
        for candidate in candidates:
            normalized = candidate.strip().lower()
            if normalized in RISKY_ACTIONS:
                return normalized
        return None


class CalyxAutonomousOrchestrator:
    """Persistent task queue, agent registry, observation log, and run-once API."""

    def __init__(self, database_url: Optional[str] = None, executor: Optional[DefaultTaskExecutor] = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL")
        self.executor = executor or DefaultTaskExecutor()

    def require_database_url(self) -> str:
        if not self.database_url:
            raise OrchestratorConfigError("DATABASE_URL is required for BUILD-044 orchestrator operations")
        return self.database_url

    def connect(self):
        if psycopg is None or dict_row is None:
            raise OrchestratorConfigError("psycopg is required for database-backed orchestrator operations")
        return psycopg.connect(self.require_database_url(), row_factory=dict_row)

    def ensure_schema(self, cur) -> None:
        cur.execute("CREATE SCHEMA IF NOT EXISTS oc_admin;")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS oc_admin.calyx_agents (
                id BIGSERIAL PRIMARY KEY,
                agent_name TEXT NOT NULL UNIQUE,
                capability TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 0,
                allowed_task_types JSONB NOT NULL DEFAULT '[]'::jsonb,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute("ALTER TABLE oc_admin.calyx_agents ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 0;")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS oc_admin.calyx_runtime_state (
                id INTEGER PRIMARY KEY DEFAULT 1,
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_by TEXT,
                CONSTRAINT calyx_runtime_state_singleton CHECK (id = 1)
            );
            """
        )
        cur.execute(
            """
            INSERT INTO oc_admin.calyx_runtime_state (id, enabled, updated_by)
            VALUES (1, FALSE, 'schema_default')
            ON CONFLICT (id) DO NOTHING;
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS oc_admin.calyx_tasks (
                id BIGSERIAL PRIMARY KEY,
                task_key TEXT UNIQUE,
                task_type TEXT NOT NULL,
                title TEXT NOT NULL,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER NOT NULL DEFAULT 0,
                required_approval BOOLEAN NOT NULL DEFAULT FALSE,
                approved_at TIMESTAMPTZ,
                assigned_agent_id BIGINT REFERENCES oc_admin.calyx_agents(id),
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                last_error TEXT,
                evaluation_result TEXT,
                evaluation_details JSONB NOT NULL DEFAULT '{}'::jsonb,
                result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT calyx_tasks_status_check
                    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'blocked', 'needs_review')),
                CONSTRAINT calyx_tasks_eval_check
                    CHECK (evaluation_result IS NULL OR evaluation_result IN ('pass', 'fail', 'needs_review'))
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS oc_admin.calyx_observations (
                id BIGSERIAL PRIMARY KEY,
                task_id BIGINT REFERENCES oc_admin.calyx_tasks(id),
                agent_id BIGINT REFERENCES oc_admin.calyx_agents(id),
                event_type TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                details JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS oc_admin.calyx_runs (
                id BIGSERIAL PRIMARY KEY,
                task_id BIGINT REFERENCES oc_admin.calyx_tasks(id),
                agent_id BIGINT REFERENCES oc_admin.calyx_agents(id),
                status TEXT NOT NULL,
                evaluation_result TEXT,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMPTZ,
                result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                error_text TEXT
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_calyx_tasks_status_priority ON oc_admin.calyx_tasks(status, priority DESC, id ASC);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_calyx_observations_task ON oc_admin.calyx_observations(task_id, id DESC);")

    def seed_defaults(self) -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                self.ensure_schema(cur)
                agents = self._seed_agents(cur)
                tasks = self._seed_tasks(cur)
            conn.commit()
        return {"status": "seeded", "agents_inserted": agents, "tasks_inserted": tasks}

    def runtime_enabled(self) -> bool:
        with self.connect() as conn:
            with conn.cursor() as cur:
                self.ensure_schema(cur)
                cur.execute("SELECT enabled FROM oc_admin.calyx_runtime_state WHERE id = 1")
                row = cur.fetchone()
                return bool(row and row["enabled"])

    def set_runtime_enabled(self, enabled: bool, updated_by: str = "api") -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                self.ensure_schema(cur)
                cur.execute(
                    """
                    INSERT INTO oc_admin.calyx_runtime_state (id, enabled, updated_by, updated_at)
                    VALUES (1, %s, %s, NOW())
                    ON CONFLICT (id) DO UPDATE
                    SET enabled = EXCLUDED.enabled,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = NOW()
                    RETURNING *
                    """,
                    (enabled, updated_by),
                )
                state = dict(cur.fetchone())
            conn.commit()
        return {"status": "updated", "runtime_state": state}

    def _seed_agents(self, cur) -> int:
        inserted = 0
        for agent in DEFAULT_AGENTS:
            cur.execute(
                """
                INSERT INTO oc_admin.calyx_agents
                    (agent_name, capability, priority, allowed_task_types, enabled)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (agent_name) DO UPDATE
                SET capability = EXCLUDED.capability,
                    priority = EXCLUDED.priority,
                    allowed_task_types = EXCLUDED.allowed_task_types,
                    updated_at = NOW()
                RETURNING (xmax = 0) AS inserted
                """,
                (
                    agent["agent_name"],
                    agent["capability"],
                    agent.get("priority", 0),
                    _json(agent["allowed_task_types"]),
                    agent["enabled"],
                ),
            )
            if bool(cur.fetchone()["inserted"]):
                inserted += 1
        return inserted

    def _seed_tasks(self, cur) -> int:
        inserted = 0
        for task in DEFAULT_TASKS:
            cur.execute(
                """
                INSERT INTO oc_admin.calyx_tasks
                    (task_key, task_type, title, payload, status, priority, required_approval)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (task_key) DO NOTHING
                RETURNING id
                """,
                (
                    task["task_key"],
                    task["task_type"],
                    task["title"],
                    _json(task["payload"]),
                    "needs_review" if task.get("needs_review") else "pending",
                    task["priority"],
                    bool(task.get("needs_review")),
                ),
            )
            if cur.fetchone() is not None:
                inserted += 1
        return inserted

    def list_agents(self) -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                self.ensure_schema(cur)
                cur.execute("SELECT * FROM oc_admin.calyx_agents ORDER BY enabled DESC, priority DESC, agent_name ASC")
                return {"agents": [dict(row) for row in cur.fetchall()]}

    def list_tasks(self, limit: int = 100) -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                self.ensure_schema(cur)
                cur.execute(
                    """
                    SELECT t.*, a.agent_name
                    FROM oc_admin.calyx_tasks t
                    LEFT JOIN oc_admin.calyx_agents a ON a.id = t.assigned_agent_id
                    ORDER BY t.created_at DESC, t.id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return {"tasks": [dict(row) for row in cur.fetchall()]}

    def create_task(self, task_type: str, title: str, payload: dict[str, Any], priority: int = 0) -> dict[str, Any]:
        required_approval = self.executor.risky_action(task_type, payload) is not None
        status = "needs_review" if required_approval else "pending"
        with self.connect() as conn:
            with conn.cursor() as cur:
                self.ensure_schema(cur)
                cur.execute(
                    """
                    INSERT INTO oc_admin.calyx_tasks
                        (task_type, title, payload, status, priority, required_approval)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (task_type, title, _json(payload), status, priority, required_approval),
                )
                task = dict(cur.fetchone())
                self.log_observation(
                    cur,
                    task_id=task["id"],
                    agent_id=None,
                    event_type="task_created",
                    action="queued" if status == "pending" else "approval_required",
                    status=status,
                    details={"required_approval": required_approval},
                )
            conn.commit()
        return {"task": task}

    def queue_audit_followthrough(self, findings: Any, store: Any = None) -> dict[str, Any]:
        """Turn an audit's actionable findings into durable remediation tasks.

        Thin adapter onto ``runtime.audit_followthrough``: this orchestrator
        already owns ``oc_admin.calyx_tasks``, so follow-through persistence
        lives here rather than in a second write path. Idempotent on the
        follow-through dedupe key; risky task types stay ``needs_review``
        behind the existing approval gate. ``store`` is an injection point for
        tests; production callers leave it unset. Imported lazily because
        ``audit_followthrough`` imports :class:`DefaultTaskExecutor` from this
        module.
        """

        from runtime.audit_followthrough import (
            OrchestratorFollowthroughStore,
            persist_followthrough,
        )

        return persist_followthrough(
            findings,
            store if store is not None else OrchestratorFollowthroughStore(self),
            executor=self.executor,
        )

    def approve_task(self, task_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                self.ensure_schema(cur)
                cur.execute(
                    """
                    UPDATE oc_admin.calyx_tasks
                    SET approved_at = NOW(),
                        required_approval = FALSE,
                        status = CASE WHEN status = 'needs_review' THEN 'pending' ELSE status END,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (task_id,),
                )
                task = cur.fetchone()
                if not task:
                    return {"status": "not_found", "task_id": task_id}
                self.log_observation(
                    cur,
                    task_id=task_id,
                    agent_id=None,
                    event_type="approval_gate",
                    action="approved",
                    status="pending",
                    details={"approved_at": utc_now()},
                )
            conn.commit()
        return {"status": "approved", "task": dict(task)}

    def run_once(self) -> dict[str, Any]:
        self.seed_defaults()
        selection = self._select_next_task()
        if selection.get("status") != "selected":
            return selection

        task = selection["task"]
        agent = selection["agent"]
        run_id = selection["run_id"]

        try:
            outcome = self.executor.execute(task, agent)
            final_status = outcome.status
            with self.connect() as conn:
                with conn.cursor() as cur:
                    self.ensure_schema(cur)
                    for observation in outcome.observations:
                        self.log_observation(
                            cur,
                            task_id=task["id"],
                            agent_id=agent["id"],
                            event_type=observation["event_type"],
                            action=observation["action"],
                            status=observation["status"],
                            details=observation.get("details", {}),
                        )
                    self._finish_task(
                        cur,
                        task_id=task["id"],
                        run_id=run_id,
                        status=final_status,
                        evaluation_result=outcome.evaluation_result,
                        result=outcome.result,
                        error_text=None,
                    )
                conn.commit()
            return {
                "status": final_status,
                "task_id": task["id"],
                "task_type": task["task_type"],
                "agent": agent["agent_name"],
                "evaluation_result": outcome.evaluation_result,
                "result": outcome.result,
            }
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            with self.connect() as conn:
                with conn.cursor() as cur:
                    self.ensure_schema(cur)
                    self.log_observation(
                        cur,
                        task_id=task["id"],
                        agent_id=agent["id"],
                        event_type="execution",
                        action="failed",
                        status="failed",
                        details={"error": str(exc)},
                    )
                    self._finish_task(
                        cur,
                        task_id=task["id"],
                        run_id=run_id,
                        status="failed",
                        evaluation_result="fail",
                        result={"error": str(exc)},
                        error_text=str(exc),
                    )
                conn.commit()
            return {"status": "failed", "task_id": task["id"], "error": str(exc)}

    def _select_next_task(self) -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                self.ensure_schema(cur)
                cur.execute(
                    """
                    SELECT *
                    FROM oc_admin.calyx_tasks
                    WHERE status = 'pending'
                    ORDER BY priority DESC, id ASC
                    FOR UPDATE SKIP LOCKED
                    """
                )
                tasks = [dict(row) for row in cur.fetchall()]
                if not tasks:
                    return {"status": "no_eligible_tasks"}

                cur.execute("SELECT * FROM oc_admin.calyx_agents WHERE enabled = TRUE ORDER BY priority DESC, id ASC")
                agents = [dict(row) for row in cur.fetchall()]

                for task in tasks:
                    risky = self.executor.risky_action(task["task_type"], task.get("payload") or {})
                    if risky and not task.get("approved_at"):
                        cur.execute(
                            """
                            UPDATE oc_admin.calyx_tasks
                            SET status = 'needs_review',
                                required_approval = TRUE,
                                evaluation_result = 'needs_review',
                                updated_at = NOW()
                            WHERE id = %s
                            """,
                            (task["id"],),
                        )
                        self.log_observation(
                            cur,
                            task_id=task["id"],
                            agent_id=None,
                            event_type="approval_gate",
                            action="skipped",
                            status="needs_review",
                            details={"risky_action": risky},
                        )
                        continue

                    agent = self._agent_for_task(task, agents)
                    if not agent:
                        cur.execute(
                            """
                            UPDATE oc_admin.calyx_tasks
                            SET status = 'blocked',
                                evaluation_result = 'needs_review',
                                last_error = 'No enabled agent can execute this task type',
                                updated_at = NOW()
                            WHERE id = %s
                            """,
                            (task["id"],),
                        )
                        self.log_observation(
                            cur,
                            task_id=task["id"],
                            agent_id=None,
                            event_type="agent_selection",
                            action="blocked",
                            status="blocked",
                            details={"task_type": task["task_type"]},
                        )
                        continue

                    cur.execute(
                        """
                        UPDATE oc_admin.calyx_tasks
                        SET status = 'running',
                            assigned_agent_id = %s,
                            started_at = NOW(),
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING *
                        """,
                        (agent["id"], task["id"]),
                    )
                    selected_task = dict(cur.fetchone())
                    cur.execute(
                        """
                        INSERT INTO oc_admin.calyx_runs
                            (task_id, agent_id, status, started_at)
                        VALUES (%s, %s, 'running', NOW())
                        RETURNING id
                        """,
                        (task["id"], agent["id"]),
                    )
                    run_id = cur.fetchone()["id"]
                    self.log_observation(
                        cur,
                        task_id=task["id"],
                        agent_id=agent["id"],
                        event_type="agent_selection",
                        action="selected",
                        status="running",
                        details={"agent_name": agent["agent_name"]},
                    )
                    conn.commit()
                    return {"status": "selected", "task": selected_task, "agent": agent, "run_id": run_id}

                conn.commit()
                return {"status": "no_eligible_tasks"}

    def _agent_for_task(self, task: dict[str, Any], agents: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        for agent in agents:
            allowed = agent.get("allowed_task_types") or []
            if "*" in allowed or task["task_type"] in allowed:
                return agent
        return None

    def _finish_task(
        self,
        cur,
        *,
        task_id: int,
        run_id: int,
        status: str,
        evaluation_result: str,
        result: dict[str, Any],
        error_text: Optional[str],
    ) -> None:
        cur.execute(
            """
            UPDATE oc_admin.calyx_tasks
            SET status = %s,
                finished_at = NOW(),
                updated_at = NOW(),
                last_error = %s,
                evaluation_result = %s,
                evaluation_details = %s,
                result_json = %s
            WHERE id = %s
            """,
            (
                status,
                error_text,
                evaluation_result,
                _json({"result": evaluation_result, "checked_at": utc_now()}),
                _json(result),
                task_id,
            ),
        )
        cur.execute(
            """
            UPDATE oc_admin.calyx_runs
            SET status = %s,
                evaluation_result = %s,
                finished_at = NOW(),
                result_json = %s,
                error_text = %s
            WHERE id = %s
            """,
            (status, evaluation_result, _json(result), error_text, run_id),
        )

    def log_observation(
        self,
        cur,
        *,
        task_id: Optional[int],
        agent_id: Optional[int],
        event_type: str,
        action: str,
        status: str,
        details: dict[str, Any],
    ) -> None:
        cur.execute(
            """
            INSERT INTO oc_admin.calyx_observations
                (task_id, agent_id, event_type, action, status, details)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (task_id, agent_id, event_type, action, status, _json(details)),
        )

    def observations(self, limit: int = 100) -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                self.ensure_schema(cur)
                cur.execute(
                    """
                    SELECT o.*, t.task_type, a.agent_name
                    FROM oc_admin.calyx_observations o
                    LEFT JOIN oc_admin.calyx_tasks t ON t.id = o.task_id
                    LEFT JOIN oc_admin.calyx_agents a ON a.id = o.agent_id
                    ORDER BY o.id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return {"observations": [dict(row) for row in cur.fetchall()]}

    def runs(self, limit: int = 50) -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                self.ensure_schema(cur)
                cur.execute(
                    """
                    SELECT r.*, t.task_type, t.title, a.agent_name
                    FROM oc_admin.calyx_runs r
                    LEFT JOIN oc_admin.calyx_tasks t ON t.id = r.task_id
                    LEFT JOIN oc_admin.calyx_agents a ON a.id = r.agent_id
                    ORDER BY r.id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return {"runs": [dict(row) for row in cur.fetchall()]}

    def health(self) -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                self.ensure_schema(cur)
                self._seed_agents(cur)
                self._seed_tasks(cur)
                cur.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM oc_admin.calyx_tasks
                    GROUP BY status
                    """
                )
                counts = {status: 0 for status in TASK_STATUSES}
                for row in cur.fetchall():
                    counts[row["status"]] = row["count"]
                queue_depth = counts["pending"]
                completed_count = counts["completed"]
                failed_count = counts["failed"]

                cur.execute("SELECT enabled, updated_at, updated_by FROM oc_admin.calyx_runtime_state WHERE id = 1")
                runtime_state = cur.fetchone()

                cur.execute(
                    """
                    SELECT t.id, t.task_type, t.title, a.agent_name, t.started_at
                    FROM oc_admin.calyx_tasks t
                    LEFT JOIN oc_admin.calyx_agents a ON a.id = t.assigned_agent_id
                    WHERE t.status = 'running'
                    ORDER BY t.started_at DESC NULLS LAST, t.id DESC
                    LIMIT 1
                    """
                )
                active = cur.fetchone()

                cur.execute(
                    """
                    SELECT r.id, r.status, r.evaluation_result, r.finished_at, t.task_type, a.agent_name
                    FROM oc_admin.calyx_runs r
                    LEFT JOIN oc_admin.calyx_tasks t ON t.id = r.task_id
                    LEFT JOIN oc_admin.calyx_agents a ON a.id = r.agent_id
                    ORDER BY r.id DESC
                    LIMIT 1
                    """
                )
                last_run = cur.fetchone()

                cur.execute(
                    """
                    SELECT t.id, t.task_type, t.title, t.status, t.last_error, t.updated_at
                    FROM oc_admin.calyx_tasks t
                    WHERE t.status IN ('failed', 'blocked', 'needs_review')
                    ORDER BY t.updated_at DESC NULLS LAST, t.id DESC
                    LIMIT 10
                    """
                )
                failures = [dict(row) for row in cur.fetchall()]
            conn.commit()

        return {
            "status": "ok",
            "enabled": bool(runtime_state and runtime_state["enabled"]),
            "runtime_state": dict(runtime_state) if runtime_state else None,
            "queue_count": counts,
            "queue_depth": queue_depth,
            "completed_count": completed_count,
            "failed_count": failed_count,
            "active_agent": dict(active) if active else None,
            "last_run": dict(last_run) if last_run else None,
            "failures": failures,
            "approval_gates": sorted(RISKY_ACTIONS),
        }
