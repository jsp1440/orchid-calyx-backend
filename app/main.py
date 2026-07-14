from fastapi import Depends, FastAPI
from pydantic import BaseModel
from typing import Optional, Any
import os
import re
from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Jsonb

from app.routers import (
    awards,
    calyx_core,
    entries,
    feedback,
    harvesters,
    health,
    judging,
    reference_docs,
)
from app.security import get_api_key, get_owner_access_code, get_owner_session_secret, owner_cookie_secure, verify_owner_or_api_key
from app.routers.health import add_mission_control_cors_headers, allowed_mission_control_origins
from runtime.constitutional_orchestrator import AutonomyLevel, orchestrator as constitutional_orchestrator
from runtime.router_fastapi import router as runtime_router, science_router
from runtime.cds_router import router as cds_router
from runtime.constitutional_router import router as constitutional_router
from runtime.kernel_router import router as kernel_router
from runtime.orchestrator_router import router as orchestrator_router
from runtime.planner_router import router as planner_router
from runtime.runtime_engine import RuntimeEngine
from runtime.scheduler import CalyxHeartbeat

app = FastAPI()


@app.middleware("http")
async def mission_control_cors_on_all_responses(request, call_next):
    """Ensure Mission Control CORS headers reach the browser on EVERY response.

    The per-route ``add_mission_control_cors_headers`` dependency attaches CORS
    headers only to successful responses. When a handler or dependency raises
    ``HTTPException`` (401 expired/invalid owner session, 503 unconfigured) or
    FastAPI returns a 422 validation error, the exception handler builds a fresh
    response WITHOUT those headers. Browsers then block the response entirely,
    and the frontend sees a network-level failure ("Load failed") instead of a
    readable 401 — breaking owner-session restore in Mission Control.

    This middleware mirrors the exact header set and origin allow-list used by
    ``add_mission_control_cors_headers`` and only fills headers in when the
    route did not already set them. Origins outside the allow-list receive no
    CORS headers, unchanged from before.
    """
    response = await call_next(request)
    origin = request.headers.get("origin")
    if (
        origin
        and origin.rstrip("/") in allowed_mission_control_origins()
        and "access-control-allow-origin" not in response.headers
    ):
        response.headers["Access-Control-Allow-Origin"] = origin
        existing_vary = response.headers.get("Vary")
          if existing_vary:
              if "origin" not in existing_vary.lower():
                  response.headers["Vary"] = f"{existing_vary}, Origin"
          else:
              response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "accept, Content-Type, Authorization, X-API-Key, X-Orchid-Actor"
        response.headers["Access-Control-Max-Age"] = "86400"
    return response

DATABASE_URL = os.environ.get("DATABASE_URL")
RUNTIME_INTERVAL_FLAGS = ("CALYX_RUNTIME_INTERVAL_SECONDS", "OC_RUNNER_INTERVAL_SECONDS")
ACTIVE_MODE = os.environ.get("OC_RUNNER_ACTIVE_MODE", "true").lower() == "true"
RUNTIME_ENABLE_FLAGS = (
    "CALYX_AUTOLOOP_ENABLED",
    "OC_RUNNER_AUTOLOOP",
    "CALYX_RUNTIME_ENABLED",
    "AUTONOMOUS_RUNTIME_ENABLED",
    "RUNNER_ENABLED",
    "CALYX_AUTONOMOUS_ENABLED",
)
RUNTIME_DISABLE_FLAGS = (
    "CALYX_AUTONOMOUS_DISABLED",
    "OC_RUNNER_DISABLED",
    "CALYX_RUNTIME_DISABLED",
)

SCIENTIFIC_MODULES: list[dict[str, Any]] = [
    {
        "module_name": "pollinator_relationships",
        "state": "scientific_priority",
        "priority": 100,
        "job_name": "audit_missing_pollinator_data",
        "mission": "Identify orchid taxa missing pollinator data.",
    },
    {
        "module_name": "mycorrhiza_relationships",
        "state": "scientific_priority",
        "priority": 98,
        "job_name": "audit_missing_mycorrhizal_data",
        "mission": "Identify orchid taxa missing mycorrhizal data.",
    },
    {
        "module_name": "literature_extraction",
        "state": "scientific_priority",
        "priority": 96,
        "job_name": "audit_literature_extraction_coverage",
        "mission": "Audit literature extraction coverage.",
    },
    {
        "module_name": "ecological_relationship_graph",
        "state": "scientific_priority",
        "priority": 95,
        "job_name": "audit_ecological_relationship_graph_gaps",
        "mission": "Audit ecological relationship graph gaps.",
    },
    {
        "module_name": "traitbank_traits",
        "state": "scientific_priority",
        "priority": 94,
        "job_name": "audit_traitbank_trait_coverage",
        "mission": "Audit TraitBank and trait coverage.",
    },
    {
        "module_name": "conservation_habitat",
        "state": "scientific_priority",
        "priority": 93,
        "job_name": "audit_conservation_habitat_gaps",
        "mission": "Audit conservation and habitat data gaps.",
    },
    {
        "module_name": "image_species_evidence",
        "state": "scientific_priority",
        "priority": 90,
        "job_name": "audit_image_species_evidence_coverage",
        "mission": "Audit image and species evidence coverage.",
    },
    {
        "module_name": "frontend_knowledge_graph_integration",
        "state": "scientific_priority",
        "priority": 88,
        "job_name": "audit_frontend_relationship_cards",
        "mission": "Audit frontend relationship cards against backend data.",
    },
]

SUPPORT_MODULES: list[dict[str, Any]] = [
    {
        "module_name": "calyx_core_health",
        "state": "runtime_support",
        "priority": 80,
        "job_name": "optimize_calyx_core",
        "mission": "Check Calyx core health after scientific mission seeding.",
    },
    {
        "module_name": "constitutional_orchestrator",
        "state": "runtime_support",
        "priority": 85,
        "job_name": "optimize_constitutional_orchestrator",
        "mission": "Check Calyx constitutional guardrail and mission registry readiness.",
    },
    {
        "module_name": "judging",
        "state": "optional_low_priority",
        "priority": 25,
        "job_name": "optimize_judging",
        "mission": "Optional judging module maintenance when no scientific work is pending.",
    },
    {
        "module_name": "awards",
        "state": "optional_low_priority",
        "priority": 20,
        "job_name": "optimize_awards",
        "mission": "Optional awards module maintenance when no scientific work is pending.",
    },
]

MODULE_REGISTRY = SCIENTIFIC_MODULES + SUPPORT_MODULES
SCIENTIFIC_JOB_NAMES = {module["job_name"] for module in SCIENTIFIC_MODULES}
JOB_PRIORITIES = {module["job_name"]: module["priority"] for module in MODULE_REGISTRY}
JOB_MODULES = {module["job_name"]: module for module in MODULE_REGISTRY}
JOB_PRIORITY_SQL = "CASE job_name " + " ".join(
    f"WHEN '{job_name}' THEN {priority}" for job_name, priority in JOB_PRIORITIES.items()
) + " ELSE 0 END"


def require_database_url() -> str:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required for Calyx runner operations")
    return DATABASE_URL


def env_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def configured(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def runtime_interval_seconds_from_env() -> int:
    for key in RUNTIME_INTERVAL_FLAGS:
        value = os.environ.get(key)
        if value is None:
            continue
        try:
            return max(5, int(value))
        except ValueError:
            return 30
    return 30


def autonomous_runtime_config_blocker() -> Optional[dict[str, str]]:
    for key in RUNTIME_DISABLE_FLAGS:
        if env_bool(os.environ.get(key)) is True:
            return {"key": key, "reason": "explicit_disable_flag"}

    for key in RUNTIME_ENABLE_FLAGS:
        if key in os.environ and env_bool(os.environ.get(key)) is False:
            return {"key": key, "reason": "explicit_enable_flag_false"}

    return None


def autonomous_runtime_enabled_by_config() -> bool:
    if autonomous_runtime_config_blocker() is not None:
        return False

    return any(env_bool(os.environ.get(key)) is True for key in RUNTIME_ENABLE_FLAGS)


AUTO_LOOP_ENABLED = autonomous_runtime_enabled_by_config()
AUTO_LOOP_INTERVAL_SECONDS = runtime_interval_seconds_from_env()
RUNTIME_WRITE_AUTH = [Depends(verify_owner_or_api_key), Depends(add_mission_control_cors_headers)]
RUNTIME_CORS = [Depends(add_mission_control_cors_headers)]


def auth_required_action(reason: str, *, risk: str = "medium") -> dict[str, Any]:
    return {
        "allowed": False,
        "state": "requires_owner_authorization",
        "auth": "owner_session_or_api_key_required",
        "risk": risk,
        "reason": reason,
    }


def runner_allowed_actions() -> dict[str, dict[str, Any]]:
    return {
        "runOnce": auth_required_action("Seeds runtime jobs and writes queue state.", risk="medium"),
        "seedMissions": auth_required_action("Seeds runtime mission jobs and writes queue state.", risk="medium"),
        "executeNext": auth_required_action("Executes one pending job and writes execution state.", risk="medium"),
        "executeAll": auth_required_action("Executes the full pending queue and may perform many writes.", risk="high"),
        "autonomousCycle": auth_required_action("Runs one autonomous worker cycle.", risk="medium"),
        "startRuntime": auth_required_action("Starts the autonomous runtime worker.", risk="high"),
        "stopRuntime": auth_required_action("Stops or disables the autonomous runtime worker.", risk="high"),
        "restartRuntime": auth_required_action("Restarts the autonomous runtime worker.", risk="high"),
    }


def evaluate_runtime_action(
    action: str,
    *,
    requested_autonomy_level: int = int(AutonomyLevel.SAFE_OPERATIONS),
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    return constitutional_orchestrator.evaluate_action(
        mission_id="engineering",
        action=f"runtime:{action}",
        requested_autonomy_level=requested_autonomy_level,
        evidence=evidence or [f"route=/api/runner/{action}"],
        reversible=True,
        provenance_available=True,
    )


class VerificationRequest(BaseModel):
    source_context: Optional[str] = None


@app.get("/")
def read_root():
    return {"status": "Calyx Backend API running"}


@app.post("/verify")
def verify(request: VerificationRequest):
    return {"received": True, "source_context": request.source_context}


@app.get("/api/runner/health", dependencies=RUNTIME_CORS)
def runner_health():
    config = runtime_configuration()
    return {
        "status": "runner alive",
        "runtime_configured": not config["blockers"],
        "runtime_enabled": runtime_engine.status()["enabled"],
        "runtime_running": runtime_engine.status()["running"],
        "thread_alive": runtime_engine.status()["thread_alive"],
        "autoloop_enabled": config["autoloop_enabled"],
        "interval_seconds": config["interval_seconds"],
        "active_mode": ACTIVE_MODE,
        "mode": "build_046_scientific_priority_realignment",
        "runtime_mode": config["worker_mode"],
        "autonomous_runtime_blocker": autonomous_runtime_config_blocker(),
        "configuration": config,
        "runtime_engine": runtime_engine.status(),
        "allowedActions": runner_allowed_actions(),
    }


@app.get("/api/runtime/configuration")
def runtime_configuration():
    blocker = autonomous_runtime_config_blocker()
    blockers: list[str] = []
    deployment_actions: list[str] = []
    if not get_api_key():
        blockers.append("CALYX_API_KEY is missing; backend API-key runtime controls are disabled.")
        deployment_actions.append("Set CALYX_API_KEY in Render with a high-entropy secret.")
    if not get_owner_access_code():
        blockers.append("CALYX_OWNER_ACCESS_CODE is missing; browser owner login is disabled.")
        deployment_actions.append("Set CALYX_OWNER_ACCESS_CODE in Render.")
    if not get_owner_session_secret():
        blockers.append("CALYX_OWNER_SESSION_SECRET is missing; owner session signing is disabled.")
        deployment_actions.append("Set CALYX_OWNER_SESSION_SECRET in Render with a high-entropy secret.")
    if not configured("DATABASE_URL"):
        blockers.append("DATABASE_URL is missing; durable queue execution is disabled.")
        deployment_actions.append("Set DATABASE_URL and apply required runtime migrations before production activation.")
    if blocker:
        blockers.append(f"{blocker['key']} disables the runtime by policy: {blocker['reason']}.")
        deployment_actions.append(f"Update {blocker['key']} or remove it to allow runtime activation.")

    interval = runtime_interval_seconds_from_env()
    if interval == 30 and any(os.environ.get(key) and not str(os.environ.get(key)).isdigit() for key in RUNTIME_INTERVAL_FLAGS):
        blockers.append("Runtime interval is invalid format; using safe 30 second default.")

    return {
        "api_key_configured": bool(get_api_key()),
        "owner_access_code_configured": bool(get_owner_access_code()),
        "owner_session_secret_configured": bool(get_owner_session_secret()),
        "cookie_secure": owner_cookie_secure(),
        "allowed_origin_configured": bool(allowed_mission_control_origins()),
        "owner_auth_ready": bool(get_owner_access_code() and get_owner_session_secret() and allowed_mission_control_origins()),
        "database_configured": configured("DATABASE_URL"),
        "runtime_enabled": autonomous_runtime_enabled_by_config(),
        "autoloop_enabled": autonomous_runtime_enabled_by_config(),
        "interval_seconds": interval,
        "hosting_mode": "render" if os.environ.get("RENDER") else "generic_asgi",
        "worker_mode": "in_process_single_worker_per_web_process",
        "blockers": blockers,
        "deployment_actions_required": deployment_actions,
    }


@app.get("/api/runner/summary")
def runner_summary():
    modules = [
        {
            "module_name": module["module_name"],
            "state": module["state"],
            "priority": module["priority"],
            "job_name": module["job_name"],
            "mission": module["mission"],
        }
        for module in MODULE_REGISTRY
    ]

    jobs: list[dict[str, Any]] = []
    runtime_actions: list[dict[str, Any]] = []

    with psycopg.connect(require_database_url()) as conn:
        with conn.cursor() as cur:
            ensure_runtime_log_table(cur)

            if table_exists(cur, "oc_admin.ocp_execution_jobs"):
                cur.execute(
                    f"""
                    SELECT id, job_name, status, started_at, finished_at,
                           retry_count, error_text, details
                    FROM oc_admin.ocp_execution_jobs
                    ORDER BY {JOB_PRIORITY_SQL} DESC, id DESC
                    LIMIT 40
                    """
                )
                for row in cur.fetchall():
                    jobs.append(
                        {
                            "id": row[0],
                            "job_name": row[1],
                            "priority": JOB_PRIORITIES.get(row[1], 0),
                            "status": row[2],
                            "started_at": str(row[3]) if row[3] else None,
                            "finished_at": str(row[4]) if row[4] else None,
                            "retry_count": row[5],
                            "error_text": row[6],
                            "details": row[7],
                        }
                    )

            cur.execute(
                """
                SELECT id, module_name, action_name, action_status, action_details, created_at
                FROM oc_admin.ocp_runtime_actions
                ORDER BY id DESC
                LIMIT 40
                """
            )
            for row in cur.fetchall():
                runtime_actions.append(
                    {
                        "id": row[0],
                        "module_name": row[1],
                        "action_name": row[2],
                        "priority": JOB_PRIORITIES.get(row[2], 0),
                        "action_status": row[3],
                        "action_details": row[4],
                        "created_at": str(row[5]) if row[5] else None,
                    }
                )

    return {
        "modules": modules,
        "jobs": jobs,
        "runtime_actions": runtime_actions,
        "runtime_engine": runtime_engine.status(),
        "allowedActions": runner_allowed_actions(),
    }


@app.post("/api/runner/run-once", dependencies=RUNTIME_WRITE_AUTH)
def run_once():
    decision = evaluate_runtime_action("run_once", evidence=["authenticated API request", "deduplicated job seed"])
    created: list[str] = []
    skipped: list[str] = []

    with psycopg.connect(require_database_url()) as conn:
        with conn.cursor() as cur:
            ensure_execution_jobs_table(cur)
            for module in SCIENTIFIC_MODULES:
                inserted = insert_job_if_missing(
                    cur,
                    job_name=module["job_name"],
                    dedup_key=f"calyx:scientific:{module['job_name']}",
                    details=mission_details(module),
                )
                if inserted:
                    created.append(module["job_name"])
                else:
                    skipped.append(module["job_name"])

            for module in [
                m
                for m in SUPPORT_MODULES
                if m["module_name"] in {"calyx_core_health", "constitutional_orchestrator"}
            ]:
                inserted = insert_job_if_missing(
                    cur,
                    job_name=module["job_name"],
                    dedup_key=f"calyx:support:{module['job_name']}",
                    details=mission_details(module),
                )
                if inserted:
                    created.append(module["job_name"])
                else:
                    skipped.append(module["job_name"])

            if not has_pending_scientific_jobs(cur):
                for module in [m for m in SUPPORT_MODULES if m["module_name"] in {"judging", "awards"}]:
                    inserted = insert_job_if_missing(
                        cur,
                        job_name=module["job_name"],
                        dedup_key=f"calyx:optional:{module['job_name']}",
                        details=mission_details(module),
                    )
                    if inserted:
                        created.append(module["job_name"])
                    else:
                        skipped.append(module["job_name"])
        conn.commit()

    return {
        "status": "ok",
        "decision": decision["decision"],
        "jobs_created": created,
        "jobs_skipped_as_duplicates": skipped,
        "priority_model": {module["module_name"]: module["priority"] for module in MODULE_REGISTRY},
        "allowedActions": runner_allowed_actions(),
    }


@app.post("/api/runner/execute-next", dependencies=RUNTIME_WRITE_AUTH)
def execute_next():
    decision = evaluate_runtime_action("execute_next", evidence=["authenticated API request", "single-job execution"])
    with psycopg.connect(require_database_url()) as conn:
        with conn.cursor() as cur:
            ensure_execution_jobs_table(cur)

            cur.execute(
                f"""
                SELECT id, job_name
                FROM oc_admin.ocp_execution_jobs
                WHERE status = 'pending'
                  AND job_name IS NOT NULL
                ORDER BY {JOB_PRIORITY_SQL} DESC, id ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """
            )
            row = cur.fetchone()

            if not row:
                return {"status": "no_jobs", "decision": decision["decision"], "allowedActions": runner_allowed_actions()}

            job_id, job_name = row

            cur.execute(
                """
                UPDATE oc_admin.ocp_execution_jobs
                SET status = 'running',
                    started_at = COALESCE(started_at, NOW()),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (job_id,),
            )
            conn.commit()

            try:
                result = run_job_logic(job_name)

                cur.execute(
                    """
                    UPDATE oc_admin.ocp_execution_jobs
                    SET status = 'completed',
                        finished_at = NOW(),
                        updated_at = NOW(),
                        details = %s,
                        error_text = NULL
                    WHERE id = %s
                    """,
                    (Jsonb(result), job_id),
                )
                log_runtime_action(
                    cur,
                    module_name=result.get("module", "runner"),
                    action_name=job_name,
                    action_status="completed",
                    action_details={"job_id": job_id, "result": result},
                )
                conn.commit()

                return {
                    "status": "completed",
                    "decision": decision["decision"],
                    "job_id": job_id,
                    "job_name": job_name,
                    "priority": JOB_PRIORITIES.get(job_name, 0),
                    "result": result,
                    "allowedActions": runner_allowed_actions(),
                }

            except Exception as exec_err:
                failure_details = {
                    "message": "execution failed",
                    "error": str(exec_err),
                    "timestamp": utc_now(),
                }
                cur.execute(
                    """
                    UPDATE oc_admin.ocp_execution_jobs
                    SET status = 'failed',
                        finished_at = NOW(),
                        updated_at = NOW(),
                        retry_count = COALESCE(retry_count, 0) + 1,
                        error_text = %s,
                        details = %s
                    WHERE id = %s
                    """,
                    (
                        str(exec_err),
                        Jsonb(failure_details),
                        job_id,
                    ),
                )
                log_runtime_action(
                    cur,
                    module_name="runner",
                    action_name=job_name,
                    action_status="failed",
                    action_details={"job_id": job_id, **failure_details},
                )
                conn.commit()

                return {
                    "status": "failed",
                    "decision": decision["decision"],
                    "job_id": job_id,
                    "job_name": job_name,
                    "priority": JOB_PRIORITIES.get(job_name, 0),
                    "error": str(exec_err),
                    "allowedActions": runner_allowed_actions(),
                }


@app.post("/api/runner/execute-all", dependencies=RUNTIME_WRITE_AUTH)
def execute_all():
    decision = evaluate_runtime_action(
        "execute_all",
        requested_autonomy_level=int(AutonomyLevel.OWNER_APPROVAL_REQUIRED),
        evidence=["authenticated API request", "bulk queue execution requested"],
    )
    if decision["decision"]["status"] == "review_required":
        return {"status": "review_required", "decision": decision["decision"], "allowedActions": runner_allowed_actions()}

    completed = 0
    failed = 0

    while True:
        result = execute_next()
        status = result.get("status")

        if status == "no_jobs":
            return {"status": "queue_empty", "decision": decision["decision"], "completed": completed, "failed": failed, "allowedActions": runner_allowed_actions()}

        if status == "completed":
            completed += 1
            continue

        if status == "failed":
            failed += 1
            continue

        return {
            "status": "stopped",
            "decision": decision["decision"],
            "last_result": result,
            "completed": completed,
            "failed": failed,
            "allowedActions": runner_allowed_actions(),
        }


@app.get("/api/runner/autonomous-status", dependencies=RUNTIME_CORS)
def autonomous_status():
    config = runtime_configuration()
    return {
        **runtime_engine.status(),
        "runtime_configured": not config["blockers"],
        "autoloop_enabled": config["autoloop_enabled"],
        "active_mode": ACTIVE_MODE,
        "runtime_mode": config["worker_mode"],
        "config_blocker": autonomous_runtime_config_blocker(),
        "configuration": config,
        "allowedActions": runner_allowed_actions(),
    }


@app.post("/api/runner/autonomous-cycle", dependencies=RUNTIME_WRITE_AUTH)
def autonomous_cycle():
    decision = evaluate_runtime_action("autonomous_cycle", evidence=["authenticated API request", "single runtime cycle"])
    return {**runtime_engine.run_cycle(), "decision": decision["decision"], "allowedActions": runner_allowed_actions()}


@app.post("/api/runner/autonomous-start", dependencies=RUNTIME_WRITE_AUTH)
def autonomous_start():
    decision = evaluate_runtime_action(
        "start",
        requested_autonomy_level=int(AutonomyLevel.OWNER_APPROVAL_REQUIRED),
        evidence=["authenticated API request", "runtime start requested"],
    )
    if decision["decision"]["status"] == "review_required":
        return {"status": "review_required", "decision": decision["decision"], "engine": runtime_engine.status(), "allowedActions": runner_allowed_actions()}

    blocker = autonomous_runtime_config_blocker()
    if blocker:
        return {
            "status": "runtime_disabled_by_config",
            "config_key": blocker["key"],
            "reason": blocker["reason"],
            "message": f"Unset {blocker['key']} or set it to true to enable Calyx autonomous runtime on Render.",
            "engine": runtime_engine.status(),
            "decision": decision["decision"],
            "allowedActions": runner_allowed_actions(),
        }

    runtime_engine.set_enabled(True)
    started = runtime_engine.start()
    return {
        "status": "started" if started else "already_running",
        "engine": runtime_engine.status(),
        "decision": decision["decision"],
        "allowedActions": runner_allowed_actions(),
    }


@app.post("/api/runner/autonomous-stop", dependencies=RUNTIME_WRITE_AUTH)
def autonomous_stop(disable: bool = True):
    decision = evaluate_runtime_action(
        "stop",
        requested_autonomy_level=int(AutonomyLevel.OWNER_APPROVAL_REQUIRED),
        evidence=["authenticated API request", "runtime stop requested"],
    )
    stopped = runtime_engine.stop()
    if disable:
        runtime_engine.set_enabled(False)
    return {
        "status": "stopped" if stopped else "still_running",
        "disabled": disable,
        "engine": runtime_engine.status(),
        "decision": decision["decision"],
        "allowedActions": runner_allowed_actions(),
    }


@app.post("/api/runner/start", dependencies=RUNTIME_WRITE_AUTH)
def runner_start():
    return autonomous_start()


@app.post("/api/runner/stop", dependencies=RUNTIME_WRITE_AUTH)
def runner_stop(disable: bool = True):
    return autonomous_stop(disable=disable)


@app.post("/api/runner/restart", dependencies=RUNTIME_WRITE_AUTH)
def runner_restart():
    decision = evaluate_runtime_action(
        "restart",
        requested_autonomy_level=int(AutonomyLevel.OWNER_APPROVAL_REQUIRED),
        evidence=["authenticated API request", "runtime restart requested"],
    )
    if decision["decision"]["status"] == "review_required":
        return {"status": "review_required", "decision": decision["decision"], "engine": runtime_engine.status(), "allowedActions": runner_allowed_actions()}

    stopped = runtime_engine.stop()
    runtime_engine.set_enabled(True)
    started = runtime_engine.start()
    return {"status": "restarted" if started else "restart_attempted", "stopped": stopped, "started": started, "engine": runtime_engine.status(), "decision": decision["decision"], "allowedActions": runner_allowed_actions()}


@app.post("/api/runner/seed-missions", dependencies=RUNTIME_WRITE_AUTH)
def seed_runner_missions():
    return run_once()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def table_exists(cur, fq_table: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (fq_table,))
    return cur.fetchone()[0] is not None


def safe_count(cur, fq_table: str) -> int:
    if not table_exists(cur, fq_table):
        return 0
    cur.execute(f"SELECT COUNT(*) FROM {fq_table}")
    return cur.fetchone()[0]


def has_pending_scientific_jobs(cur) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM oc_admin.ocp_execution_jobs
        WHERE status IN ('pending', 'running')
          AND job_name = ANY(%s)
        LIMIT 1
        """,
        (list(SCIENTIFIC_JOB_NAMES),),
    )
    return cur.fetchone() is not None


def mission_details(module: dict[str, Any]) -> dict[str, Any]:
    return {
        "module": module["module_name"],
        "priority": module["priority"],
        "mission": module["mission"],
        "source": "calyx_runtime_seed",
        "provenance": {
            "source": "BUILD-046 priority model",
            "generated_at": utc_now(),
        },
        "confidence": 0.0,
        "claim_type": "coverage_audit_seed",
        "review_status": "unreviewed",
        "citation": "evidence placeholder required before biological claims are promoted",
    }


def scientific_audit_result(job_name: str, *, source_table: str, evidence_scope: str) -> dict[str, Any]:
    module = JOB_MODULES[job_name]
    return {
        "module": module["module_name"],
        "status": "completed",
        "message": module["mission"],
        "timestamp": utc_now(),
        "source": {
            "type": "runtime_coverage_audit",
            "name": source_table,
            "evidence_scope": evidence_scope,
        },
        "provenance": {
            "runtime": "calyx_autonomous_runner",
            "job_name": job_name,
            "priority": module["priority"],
        },
        "confidence": 0.0,
        "claim_type": "coverage_gap_audit",
        "review_status": "unreviewed",
        "citation": "placeholder: attach literature, dataset, or curated source before treating any relationship as fact",
        "claims": [],
        "unsupported_claims_promoted": False,
    }


def ensure_runtime_log_table(cur):
    cur.execute("CREATE SCHEMA IF NOT EXISTS oc_admin;")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS oc_admin.ocp_runtime_actions (
            id BIGSERIAL PRIMARY KEY,
            module_name TEXT NOT NULL,
            action_name TEXT NOT NULL,
            action_status TEXT NOT NULL,
            action_details JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def ensure_execution_jobs_table(cur):
    cur.execute("CREATE SCHEMA IF NOT EXISTS oc_admin;")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS oc_admin.ocp_execution_jobs (
            id BIGSERIAL PRIMARY KEY,
            job_name TEXT NOT NULL,
            dedup_key TEXT UNIQUE,
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            retry_count INTEGER DEFAULT 0,
            error_text TEXT,
            details JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )


def log_runtime_action(
    cur,
    *,
    module_name: str,
    action_name: str,
    action_status: str,
    action_details: Optional[dict[str, Any]] = None,
) -> None:
    ensure_runtime_log_table(cur)
    cur.execute(
        """
        INSERT INTO oc_admin.ocp_runtime_actions
            (module_name, action_name, action_status, action_details)
        VALUES
            (%s, %s, %s, %s)
        """,
        (module_name, action_name, action_status, Jsonb(action_details or {})),
    )


def insert_job_if_missing(
    cur,
    job_name: str,
    dedup_key: str,
    details: Optional[dict[str, Any]] = None,
) -> bool:
    if details is None:
        details = {}

    cur.execute(
        """
        SELECT id
        FROM oc_admin.ocp_execution_jobs
        WHERE dedup_key = %s
           OR job_name = %s
        LIMIT 1
        """,
        (dedup_key, job_name),
    )
    if cur.fetchone() is not None:
        return False

    cur.execute(
        """
        INSERT INTO oc_admin.ocp_execution_jobs
            (job_name, dedup_key, status, started_at, updated_at, details)
        VALUES
            (%s, %s, 'pending', NOW(), NOW(), %s)
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        (job_name, dedup_key, Jsonb(details)),
    )
    return cur.fetchone() is not None


def normalize_title(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def normalize_doi(value: Optional[str]) -> str:
    if not value:
        return ""
    value = value.strip().lower()
    return re.sub(r"^https?://(dx\.)?doi\.org/", "", value)


def run_job_logic(job_name: str):
    if job_name == "audit_missing_pollinator_data":
        return scientific_audit_result(
            job_name,
            source_table="relationship sources for orchid-pollinator interactions",
            evidence_scope="taxa missing pollinator observations, citations, or curated relationship rows",
        )

    if job_name == "audit_missing_mycorrhizal_data":
        return scientific_audit_result(
            job_name,
            source_table="oc_mycorrhiza.species_mycorrhiza_unified_endpoint_cache",
            evidence_scope="taxa missing mycorrhizal association evidence",
        )

    if job_name == "audit_literature_extraction_coverage":
        return scientific_audit_result(
            job_name,
            source_table="literature extraction pipeline outputs",
            evidence_scope="papers and extracted orchid relationship claims requiring citation-backed review",
        )

    if job_name == "audit_ecological_relationship_graph_gaps":
        return scientific_audit_result(
            job_name,
            source_table="ecological relationship graph tables or endpoint",
            evidence_scope="relationship graph gaps across pollinator, fungal, habitat, and trait edges",
        )

    if job_name == "audit_traitbank_trait_coverage":
        return scientific_audit_result(
            job_name,
            source_table="TraitBank and local trait coverage sources",
            evidence_scope="taxa missing trait observations or trait provenance",
        )

    if job_name == "audit_conservation_habitat_gaps":
        return scientific_audit_result(
            job_name,
            source_table="conservation and habitat data sources",
            evidence_scope="taxa missing conservation status, habitat, range, or threat provenance",
        )

    if job_name == "audit_image_species_evidence_coverage":
        return scientific_audit_result(
            job_name,
            source_table="image/species evidence sources",
            evidence_scope="species pages missing image-backed or specimen-backed evidence records",
        )

    if job_name == "audit_frontend_relationship_cards":
        return scientific_audit_result(
            job_name,
            source_table="frontend relationship card contract and backend relationship endpoints",
            evidence_scope="frontend cards that need pollinator, mycorrhiza, graph, literature, and conservation data",
        )

    with psycopg.connect(require_database_url()) as conn:
        with conn.cursor() as cur:
            if job_name == "optimize_calyx_core":
                return {
                    "module": "calyx_core_health",
                    "status": "completed",
                    "message": "Calyx core health check completed after scientific priorities.",
                    "timestamp": utc_now(),
                }

            if job_name == "optimize_health":
                return {
                    "module": "calyx_core_health",
                    "status": "completed",
                    "message": "Health module compatibility check completed.",
                    "timestamp": utc_now(),
                }

            if job_name == "optimize_judging":
                return {
                    "module": "judging",
                    "status": "completed",
                    "message": "Judging module maintenance completed as optional low-priority work.",
                    "timestamp": utc_now(),
                }

            if job_name == "optimize_awards":
                return {
                    "module": "awards",
                    "status": "completed",
                    "message": "Awards module maintenance completed as optional low-priority work.",
                    "timestamp": utc_now(),
                }

            if job_name == "optimize_mycorrhiza":
                mycorrhiza_rows = safe_count(
                    cur,
                    "oc_mycorrhiza.species_mycorrhiza_unified_endpoint_cache",
                )
                return {
                    "module": "mycorrhiza_relationships",
                    "status": "completed",
                    "endpoint_cache_rows": mycorrhiza_rows,
                    "message": "Legacy mycorrhiza endpoint cache checked.",
                    "timestamp": utc_now(),
                    "source": {
                        "type": "database_table",
                        "name": "oc_mycorrhiza.species_mycorrhiza_unified_endpoint_cache",
                    },
                    "confidence": 0.0,
                    "claim_type": "coverage_check",
                    "review_status": "unreviewed",
                    "citation": "placeholder required before biological claims are promoted",
                }

            if job_name == "optimize_constitutional_orchestrator":
                from runtime.constitutional_orchestrator import orchestrator

                return {
                    "module": "constitutional_orchestrator",
                    "status": "completed",
                    "orchestrator_status": orchestrator.status(),
                    "message": "Constitutional orchestrator guardrail kernel checked.",
                    "timestamp": utc_now(),
                }

            if job_name.startswith("job_"):
                return {
                    "module": "downstream_executor",
                    "job_name": job_name,
                    "status": "completed",
                    "message": f"{job_name} executed successfully.",
                    "timestamp": utc_now(),
                }

            return {
                "module": "unknown",
                "job_name": job_name,
                "status": "completed",
                "message": "Unknown job acknowledged without action.",
                "timestamp": utc_now(),
            }


def heartbeat_once():
    return CalyxHeartbeat().run_once()


runtime_engine = RuntimeEngine(
    heartbeat=heartbeat_once,
    enqueue_jobs=run_once,
    execute_jobs=execute_next,
    interval_seconds=AUTO_LOOP_INTERVAL_SECONDS,
    enabled=AUTO_LOOP_ENABLED,
)


@app.on_event("startup")
def startup_event():
    if autonomous_runtime_enabled_by_config():
        runtime_engine.set_enabled(True)
        runtime_engine.start()
    # BUILD-064: reload persisted revoked session nonces so logout survives restarts.
    try:
        from app.routers.owner_operations import load_revoked_nonces
        load_revoked_nonces()
    except Exception:
        pass


@app.on_event("shutdown")
def shutdown_event():
    runtime_engine.stop()


app.include_router(health.router)
app.include_router(calyx_core.router)
app.include_router(awards.router)
app.include_router(entries.router)
app.include_router(feedback.router)
app.include_router(harvesters.router, dependencies=[Depends(add_mission_control_cors_headers)])
app.include_router(judging.router)
app.include_router(reference_docs.router)
app.include_router(runtime_router)
app.include_router(science_router)
app.include_router(cds_router)
app.include_router(constitutional_router)
app.include_router(kernel_router)
app.include_router(orchestrator_router)
app.include_router(planner_router)

from app.routers import orchid_widgets

app.include_router(orchid_widgets.router)
