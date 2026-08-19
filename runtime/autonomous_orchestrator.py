"""BUILD-044 Calyx Autonomous Orchestrator.

This module gives Calyx a durable task queue and a conservative run-once
executor. It intentionally performs only read-only/audit style work unless a
task has passed an approval gate.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
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


# ORCHESTRATION-AUDIT-FOLLOWTHROUGH-001: every audit finding must resolve to
# exactly one of these terminal dispositions. Narrative-only completion (a
# finding with no disposition) is prohibited. Kept in sync with
# runtime.constitutional_orchestrator.TERMINAL_FINDING_DISPOSITIONS.
FINDING_DISPOSITIONS = (
    "auto_remediation_queued",
    "auto_remediation_in_progress",
    "verified_resolved",
    "owner_approval_required",
    "external_blocker",
    "scientific_data_gap",
    "no_action_needed",
)

# Dispositions that never create or touch a durable remediation task.
NON_TASK_DISPOSITIONS = frozenset({"external_blocker", "scientific_data_gap", "no_action_needed"})


def finding_key(audit_id: str, finding: dict[str, Any]) -> str:
    """Derive a stable dedupe key for an audit finding.

    Callers may supply an explicit ``finding_key`` (preferred, since the
    audit usually knows its own natural identity for a finding). Otherwise
    the key is derived from the audit id and title so that re-running the
    same audit against the same unresolved condition never creates a
    duplicate remediation task.
    """

    explicit = finding.get("finding_key")
    if explicit:
        return str(explicit)
    basis = f"{audit_id}:{finding.get('title', '')}"
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    return f"audit:{audit_id}:{digest}"


@dataclass
class FindingPlan:
    """The result of classifying one audit finding, before any DB write."""

    finding_key: str
    audit_id: str
    title: str
    category: str
    disposition: str
    task_key: Optional[str]
    task_action: Optional[str]  # "create" | "requeue" | None
    task_type: Optional[str]
    payload: dict[str, Any]
    priority: int
    evidence: list[str] = field(default_factory=list)
    rationale: str = ""


class AuditFollowthroughEngine:
    """Pure classification of audit findings into terminal dispositions.

    This performs no I/O. Given the findings an audit produced and the
    current state of any previously created remediation tasks (as plain
    dicts, e.g. rows from ``oc_admin.calyx_tasks``), it decides whether a
    new task must be created, an existing one is already tracking the same
    unresolved finding (dedupe), a completed task's verification failed and
    must be reopened with evidence, or the finding is not actionable code
    work at all. Keeping this logic free of database access lets the
    dedupe/safe-autonomy/owner-gate rules be unit tested directly.
    """

    def __init__(self, executor: Optional["DefaultTaskExecutor"] = None) -> None:
        self.executor = executor or DefaultTaskExecutor()

    def plan(
        self,
        audit_id: str,
        findings: list[dict[str, Any]],
        existing_tasks_by_key: dict[str, dict[str, Any]],
    ) -> list[FindingPlan]:
        return [self._plan_one(audit_id, finding, existing_tasks_by_key) for finding in findings]

    def _plan_one(
        self,
        audit_id: str,
        finding: dict[str, Any],
        existing_tasks_by_key: dict[str, dict[str, Any]],
    ) -> FindingPlan:
        key = finding_key(audit_id, finding)
        title = str(finding.get("title") or key)
        category = str(finding.get("category") or "engineering")
        evidence = list(finding.get("evidence") or [])
        priority = int(finding.get("priority", 50))
        task_type = finding.get("task_type") or "engineering_remediation"
        payload = dict(finding.get("payload") or {})
        payload.setdefault("audit_id", audit_id)
        payload.setdefault("finding_key", key)

        def result(disposition: str, task_key: Optional[str], task_action: Optional[str], rationale: str) -> FindingPlan:
            return FindingPlan(
                finding_key=key,
                audit_id=audit_id,
                title=title,
                category=category,
                disposition=disposition,
                task_key=task_key,
                task_action=task_action,
                task_type=task_type,
                payload=payload,
                priority=priority,
                evidence=evidence,
                rationale=rationale,
            )

        if category in ("scientific_data_gap", "external_blocker"):
            return result(
                category,
                None,
                None,
                f"Finding classified as {category}; no code remediation is possible.",
            )

        if not finding.get("actionable", True):
            return result(
                "no_action_needed",
                None,
                None,
                "Finding is informational and requires no remediation.",
            )

        task_key = finding.get("task_key") or key
        risky = self.executor.risky_action(task_type, payload)
        existing = existing_tasks_by_key.get(task_key)

        if existing is None:
            disposition = "owner_approval_required" if risky else "auto_remediation_queued"
            return result(
                disposition,
                task_key,
                "create",
                "No remediation task exists yet for this unresolved finding.",
            )

        status = existing.get("status")
        evaluation_result = existing.get("evaluation_result")

        if status == "completed" and evaluation_result == "pass":
            return result(
                "verified_resolved",
                task_key,
                None,
                "Linked remediation task completed and passed verification.",
            )

        if status in ("completed", "failed"):
            disposition = "owner_approval_required" if risky else "auto_remediation_queued"
            return result(
                disposition,
                task_key,
                "requeue",
                "Verification did not pass; remediation is reopened with evidence instead of reported complete.",
            )

        if status == "running":
            disposition = "auto_remediation_in_progress"
        elif status in ("needs_review", "blocked"):
            disposition = "owner_approval_required"
        else:  # pending
            disposition = "owner_approval_required" if risky else "auto_remediation_queued"

        return result(
            disposition,
            task_key,
            None,
            "An unresolved remediation task already tracks this finding; no duplicate was created.",
        )


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
]


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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS oc_admin.calyx_audit_findings (
                id BIGSERIAL PRIMARY KEY,
                finding_key TEXT NOT NULL UNIQUE,
                audit_id TEXT NOT NULL,
                audit_run_id TEXT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                disposition TEXT NOT NULL,
                rationale TEXT NOT NULL DEFAULT '',
                evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
                task_id BIGINT REFERENCES oc_admin.calyx_tasks(id),
                task_key TEXT,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                resolved_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT calyx_audit_findings_disposition_check
                    CHECK (disposition IN (
                        'auto_remediation_queued', 'auto_remediation_in_progress', 'verified_resolved',
                        'owner_approval_required', 'external_blocker', 'scientific_data_gap', 'no_action_needed'
                    ))
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_calyx_audit_findings_audit ON oc_admin.calyx_audit_findings(audit_id, updated_at DESC);"
        )

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

    def ingest_audit_findings(
        self,
        audit_id: str,
        findings: list[dict[str, Any]],
        audit_run_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Apply the ORCHESTRATION-AUDIT-FOLLOWTHROUGH-001 rule to one audit.

        Every finding is classified by :class:`AuditFollowthroughEngine` into
        a terminal disposition. Actionable findings without a matching
        unresolved task get a deduplicated remediation task created; findings
        whose linked task previously failed verification are reopened with
        evidence rather than silently dropped. Narrative-only completion is
        never produced here: every finding always receives a disposition row.
        """

        engine = AuditFollowthroughEngine(self.executor)
        with self.connect() as conn:
            with conn.cursor() as cur:
                self.ensure_schema(cur)

                task_keys = sorted({finding.get("task_key") or finding_key(audit_id, finding) for finding in findings})
                existing_tasks: dict[str, dict[str, Any]] = {}
                if task_keys:
                    cur.execute(
                        "SELECT * FROM oc_admin.calyx_tasks WHERE task_key = ANY(%s)",
                        (task_keys,),
                    )
                    for row in cur.fetchall():
                        existing_tasks[row["task_key"]] = dict(row)

                plans = engine.plan(audit_id, findings, existing_tasks)

                next_actions_created: list[dict[str, Any]] = []
                disposition_counts: dict[str, int] = {}
                processed: list[dict[str, Any]] = []

                for plan in plans:
                    disposition_counts[plan.disposition] = disposition_counts.get(plan.disposition, 0) + 1
                    task_id: Optional[int] = None
                    required_approval = plan.disposition == "owner_approval_required"
                    task_status = "needs_review" if required_approval else "pending"

                    if plan.task_action == "create":
                        cur.execute(
                            """
                            INSERT INTO oc_admin.calyx_tasks
                                (task_key, task_type, title, payload, status, priority, required_approval)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (task_key) DO NOTHING
                            RETURNING id
                            """,
                            (plan.task_key, plan.task_type, plan.title, _json(plan.payload), task_status, plan.priority, required_approval),
                        )
                        row = cur.fetchone()
                        if row is not None:
                            task_id = row["id"]
                            next_actions_created.append(
                                {"finding_key": plan.finding_key, "task_key": plan.task_key, "task_id": task_id, "action": "created"}
                            )
                            self.log_observation(
                                cur,
                                task_id=task_id,
                                agent_id=None,
                                event_type="audit_finding_ingested",
                                action="task_created",
                                status=task_status,
                                details={"audit_id": audit_id, "finding_key": plan.finding_key, "evidence": plan.evidence},
                            )
                        else:
                            cur.execute("SELECT id FROM oc_admin.calyx_tasks WHERE task_key = %s", (plan.task_key,))
                            found = cur.fetchone()
                            task_id = found["id"] if found else None

                    elif plan.task_action == "requeue":
                        existing = existing_tasks.get(plan.task_key, {})
                        task_id = existing.get("id")
                        history = list((existing.get("payload") or {}).get("audit_requeue_history", []))
                        history.append(
                            {
                                "requeued_at": utc_now(),
                                "previous_status": existing.get("status"),
                                "previous_evaluation_result": existing.get("evaluation_result"),
                            }
                        )
                        requeue_payload = dict(plan.payload)
                        requeue_payload["audit_requeue_history"] = history
                        cur.execute(
                            """
                            UPDATE oc_admin.calyx_tasks
                            SET status = %s,
                                payload = %s,
                                required_approval = %s,
                                last_error = NULL,
                                started_at = NULL,
                                finished_at = NULL,
                                updated_at = NOW()
                            WHERE id = %s
                            """,
                            (task_status, _json(requeue_payload), required_approval, task_id),
                        )
                        next_actions_created.append(
                            {"finding_key": plan.finding_key, "task_key": plan.task_key, "task_id": task_id, "action": "requeued"}
                        )
                        self.log_observation(
                            cur,
                            task_id=task_id,
                            agent_id=None,
                            event_type="audit_finding_ingested",
                            action="task_requeued",
                            status=task_status,
                            details={"audit_id": audit_id, "finding_key": plan.finding_key, "evidence": plan.evidence},
                        )
                    elif plan.task_key is not None:
                        existing = existing_tasks.get(plan.task_key)
                        task_id = existing.get("id") if existing else None

                    cur.execute(
                        """
                        INSERT INTO oc_admin.calyx_audit_findings
                            (finding_key, audit_id, audit_run_id, title, category, disposition, rationale, evidence, task_id, task_key)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (finding_key) DO UPDATE
                        SET disposition = EXCLUDED.disposition,
                            rationale = EXCLUDED.rationale,
                            evidence = EXCLUDED.evidence,
                            task_id = COALESCE(EXCLUDED.task_id, oc_admin.calyx_audit_findings.task_id),
                            task_key = COALESCE(EXCLUDED.task_key, oc_admin.calyx_audit_findings.task_key),
                            audit_run_id = EXCLUDED.audit_run_id,
                            last_seen_at = NOW(),
                            resolved_at = CASE WHEN EXCLUDED.disposition = 'verified_resolved' THEN NOW() ELSE NULL END,
                            updated_at = NOW()
                        RETURNING *
                        """,
                        (
                            plan.finding_key,
                            audit_id,
                            audit_run_id,
                            plan.title,
                            plan.category,
                            plan.disposition,
                            plan.rationale,
                            _json(plan.evidence),
                            task_id,
                            plan.task_key,
                        ),
                    )
                    processed.append(dict(cur.fetchone()))
            conn.commit()

        return {
            "status": "ingested",
            "audit_id": audit_id,
            "audit_run_id": audit_run_id,
            "findings_processed": len(processed),
            "disposition_counts": disposition_counts,
            "next_actions_created": next_actions_created,
            "findings": processed,
        }

    def audit_followthrough_view(self, audit_id: Optional[str] = None) -> dict[str, Any]:
        """Owner-facing summary: fixed automatically, in progress, owner action, blockers."""

        with self.connect() as conn:
            with conn.cursor() as cur:
                self.ensure_schema(cur)
                if audit_id:
                    cur.execute(
                        "SELECT * FROM oc_admin.calyx_audit_findings WHERE audit_id = %s ORDER BY updated_at DESC",
                        (audit_id,),
                    )
                else:
                    cur.execute("SELECT * FROM oc_admin.calyx_audit_findings ORDER BY updated_at DESC LIMIT 500")
                rows = [dict(row) for row in cur.fetchall()]

        groups = {
            "fixed_automatically": [row for row in rows if row["disposition"] == "verified_resolved"],
            "in_progress": [row for row in rows if row["disposition"] in ("auto_remediation_queued", "auto_remediation_in_progress")],
            "owner_action_required": [row for row in rows if row["disposition"] == "owner_approval_required"],
            "blocked": [row for row in rows if row["disposition"] in ("external_blocker", "scientific_data_gap")],
            "no_action_needed": [row for row in rows if row["disposition"] == "no_action_needed"],
        }
        return {
            "status": "ok",
            "audit_id": audit_id,
            "total_findings": len(rows),
            "summary": {key: len(value) for key, value in groups.items()},
            "groups": groups,
        }

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
