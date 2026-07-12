"""Read-only Mission Control telemetry endpoints.

BUILD-039 turns the Calyx backend into the first live telemetry provider for
Orchid Continuum Mission Control.  These routes are deliberately read-only:
they expose health, subsystem, harvester, repository/deployment, metrics,
completeness, recommendation, and governance payloads, but they do not run,
pause, resume, deploy, mutate credentials, or write production data.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable

import psycopg
from fastapi import APIRouter

router = APIRouter(prefix="/api/mission-control", tags=["mission-control"])

BUILD_ID = "BUILD-065"
DATABASE_URL = os.environ.get("DATABASE_URL")

REPOSITORIES = [
    {
        "name": "jsp1440/orchid-continuum-frontend",
        "default_branch": "main",
        "deployment_target": "Frontend hosting",
        "frontend_deploy_needed": False,
        "backend_deploy_needed": False,
        "known_blockers": ["Live GitHub/Render telemetry requires backend-owned connector credentials."],
    },
    {
        "name": "jsp1440/orchid-calyx-backend",
        "default_branch": "main",
        "deployment_target": "https://orchid-calyx-backend.onrender.com",
        "frontend_deploy_needed": False,
        "backend_deploy_needed": True,
        "known_blockers": ["Redeploy backend after BUILD-039 merge to expose live Mission Control endpoints."],
    },
    {
        "name": "jsp1440/Orchid-Continuum-Brain",
        "default_branch": "main",
        "deployment_target": "Brain services",
        "frontend_deploy_needed": False,
        "backend_deploy_needed": False,
        "known_blockers": ["Brain runtime status must be routed through a future telemetry adapter."],
    },
]

HARVESTERS = [
    ("inaturalist", "iNaturalist", "iNaturalist observations/media", "audit_image_species_evidence_coverage"),
    ("gbif", "GBIF", "GBIF occurrence backbone", "audit_ecological_relationship_graph_gaps"),
    ("world_plants_hassler", "World Plants / Hassler", "Taxonomic backbone", "audit_frontend_relationship_cards"),
    ("eol_traitbank", "EOL / TraitBank", "Trait records", "audit_traitbank_trait_coverage"),
    ("globi", "GloBI", "Interaction records", "audit_missing_pollinator_data"),
    ("pollinator_datasets", "Pollinator datasets", "Pollination sources", "audit_missing_pollinator_data"),
    ("mycorrhizal_data", "Mycorrhizal literature/data", "Mycorrhizal sources", "audit_missing_mycorrhizal_data"),
    ("image_media", "Image/media harvesters", "Image/media services", "audit_image_species_evidence_coverage"),
    ("literature", "Literature harvesters", "Literature and citation sources", "audit_literature_extraction_coverage"),
    ("climate_elevation", "Climate/elevation enrichment", "Climate and elevation sources", "audit_conservation_habitat_gaps"),
    ("conservation_status", "Conservation status enrichment", "Conservation sources", "audit_conservation_habitat_gaps"),
]

METRIC_CANDIDATES = {
    "taxonomy": [
        "oc_taxonomy.taxa",
        "oc_taxonomy.orchid_taxa",
        "public.orchid_taxa",
        "public.orchid_species",
        "public.taxonomy",
    ],
    "occurrences": [
        "oc_atlas.occurrences",
        "oc_atlas.map_data",
        "public.occurrences",
        "public.orchid_occurrences",
        "public.map_data",
    ],
    "images": [
        "public.orchid_images_linked_v2",
        "public.orchid_images",
        "public.record_media_link",
        "oc_media.orchid_images",
    ],
    "literature": [
        "oc_literature.documents",
        "oc_literature.literature_documents",
        "oc_literature.papers",
        "public.literature_documents",
    ],
    "relationships": [
        "oc_relationships.relationships",
        "oc_interactions.relationships",
        "oc_literature.extracted_relationships",
        "public.relationships",
    ],
    "mycorrhiza": [
        "oc_mycorrhiza.species_mycorrhiza_unified_endpoint_cache",
        "oc_mycorrhiza.relationships",
    ],
    "runtime_jobs": ["oc_admin.ocp_execution_jobs"],
    "runtime_actions": ["oc_admin.ocp_runtime_actions"],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_unavailable_payload() -> dict[str, Any]:
    return {
        "database_connected": False,
        "blockers": ["DATABASE_URL is not configured for this backend runtime."],
        "generated_at": utc_now(),
    }


def with_connection(callback):
    if not DATABASE_URL:
        return db_unavailable_payload()
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                return callback(cur)
    except Exception as exc:  # pragma: no cover - exercised in deployed runtime
        return {
            "database_connected": False,
            "blockers": [f"Database telemetry unavailable: {exc}"],
            "generated_at": utc_now(),
        }


def table_exists(cur, fq_table: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (fq_table,))
    return cur.fetchone()[0] is not None


def safe_count(cur, fq_table: str) -> int | None:
    if not table_exists(cur, fq_table):
        return None
    cur.execute(f"SELECT COUNT(*) FROM {fq_table}")
    return int(cur.fetchone()[0])


def first_available_count(cur, candidates: Iterable[str]) -> dict[str, Any]:
    checked: list[str] = []
    for table in candidates:
        checked.append(table)
        count = safe_count(cur, table)
        if count is not None:
            return {"table": table, "count": count, "available": True, "checked": checked}
    return {"table": None, "count": 0, "available": False, "checked": checked}


def metric_snapshot() -> dict[str, Any]:
    def _read(cur):
        metrics = {
            name: first_available_count(cur, candidates)
            for name, candidates in METRIC_CANDIDATES.items()
        }
        return {"database_connected": True, "metrics": metrics, "generated_at": utc_now()}

    return with_connection(_read)


def score_from_metric(metric: dict[str, Any], target: int) -> tuple[int, list[str], list[str]]:
    count = int(metric.get("count") or 0)
    table = metric.get("table")
    evidence: list[str] = []
    blockers: list[str] = []
    if table:
        evidence.append(f"{table} reachable with {count:,} row(s).")
    else:
        blockers.append("No configured source table was reachable for this metric.")
    if count <= 0:
        return 15, evidence, blockers
    return max(25, min(95, int((count / target) * 100))), evidence, blockers


def completeness_rows() -> list[dict[str, Any]]:
    snapshot = metric_snapshot()
    metrics = snapshot.get("metrics") or {}
    specs = [
        ("atlas", "Atlas", "Science", "occurrences", 100000, "Occurrence/atlas telemetry."),
        ("species_explorer", "Species Explorer", "Science", "taxonomy", 50000, "Taxonomy backbone telemetry."),
        ("images_media", "Images / Media", "Media", "images", 500000, "Image/media table telemetry."),
        ("literature", "Literature System", "Science", "literature", 10000, "Literature extraction telemetry."),
        ("knowledge_graph", "Knowledge Graph", "Science", "relationships", 100000, "Relationship graph telemetry."),
        ("mycorrhiza", "Mycorrhizal System", "Science", "mycorrhiza", 1000, "Mycorrhizal endpoint/cache telemetry."),
        ("runtime_jobs", "Runtime Jobs", "Runtime", "runtime_jobs", 10, "Calyx execution queue telemetry."),
    ]
    rows: list[dict[str, Any]] = []
    for subsystem_id, name, category, metric_name, target, summary in specs:
        score, evidence, blockers = score_from_metric(metrics.get(metric_name, {}), target)
        status = "healthy" if score >= 75 else "warning" if score >= 40 else "stub"
        blocker_text = "; ".join(blockers) if blockers else None
        recommendation = "Wire deeper source-specific freshness and provenance checks."
        rows.append(
            {
                "id": subsystem_id,
                "display_name": name,
                "name": name,
                "health": status,
                "category": category,
                "status": status,
                "completion": score,
                "completeness": score,
                "summary": summary,
                "telemetry_source": metrics.get(metric_name, {}).get("table") or "not connected",
                "evidence": evidence,
                "warning_text": blocker_text if status in {"warning", "stub"} else None,
                "blocker_text": blocker_text,
                "blockers": blockers,
                "last_update": utc_now(),
                "lastChecked": utc_now(),
                "recommendation": recommendation,
                "recommended_next_action": recommendation,
                "dataSource": metrics.get(metric_name, {}).get("table") or "not connected",
            }
        )
    return rows


def runtime_telemetry() -> dict[str, Any]:
    snapshot = metric_snapshot()
    metrics = snapshot.get("metrics") or {}
    runtime_jobs = metrics.get("runtime_jobs", {})
    runtime_actions = metrics.get("runtime_actions", {})
    db_connected = bool(snapshot.get("database_connected"))
    blockers = list(snapshot.get("blockers", []))
    evidence: list[str] = []

    for label, metric in (("runtime jobs", runtime_jobs), ("runtime actions", runtime_actions)):
        table = metric.get("table")
        if table:
            evidence.append(f"{table} reachable for {label} with {int(metric.get('count') or 0):,} row(s).")
        else:
            blockers.append(f"No configured {label} table was reachable.")

    health = "healthy" if db_connected and not blockers else "warning"
    blocker_text = "; ".join(blockers) if blockers else None
    return {
        "id": "calyx_runtime",
        "display_name": "Calyx Runtime",
        "health": health,
        "status": "read_only_observable" if db_connected else "database_unavailable",
        "completion": 70 if db_connected else 25,
        "last_update": snapshot.get("generated_at") or utc_now(),
        "telemetry_source": "oc_admin.ocp_execution_jobs / oc_admin.ocp_runtime_actions",
        "evidence": evidence,
        "warning_text": blocker_text if health != "healthy" else None,
        "blocker_text": blocker_text,
        "recommendation": "Add source-specific freshness checks and owner-authorized operations in a later build.",
        "database_connected": db_connected,
        "metrics": {
            "runtime_jobs": runtime_jobs,
            "runtime_actions": runtime_actions,
        },
        "safety": {
            "read_only": True,
            "write_controls_enabled": False,
            "deploy_controls_enabled": False,
            "pause_resume_enabled": False,
            "owner_authorization_required_for_operations": True,
        },
    }


def latest_job(cur, job_name: str) -> dict[str, Any] | None:
    if not table_exists(cur, "oc_admin.ocp_execution_jobs"):
        return None
    cur.execute(
        """
        SELECT job_name, status, started_at, finished_at, updated_at,
               retry_count, error_text, details
        FROM oc_admin.ocp_execution_jobs
        WHERE job_name = %s
        ORDER BY COALESCE(updated_at, finished_at, started_at) DESC NULLS LAST, id DESC
        LIMIT 1
        """,
        (job_name,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "job_name": row[0],
        "status": row[1],
        "started_at": row[2].isoformat() if row[2] else None,
        "finished_at": row[3].isoformat() if row[3] else None,
        "updated_at": row[4].isoformat() if row[4] else None,
        "retry_count": row[5] or 0,
        "error_text": row[6],
        "details": row[7] or {},
    }


def harvester_rows() -> list[dict[str, Any]]:
    def _read(cur):
        rows: list[dict[str, Any]] = []
        for harvester_id, name, source, job_name in HARVESTERS:
            job = latest_job(cur, job_name)
            state = "planned"
            errors: list[str] = []
            last_run = "not connected"
            heartbeat_at = None
            warning_count = 1
            if job:
                raw_status = str(job.get("status") or "unknown").lower()
                state = "running" if raw_status == "running" else "idle" if raw_status in {"completed", "success", "succeeded"} else "error" if raw_status in {"failed", "error"} else "unknown"
                last_run = job.get("finished_at") or job.get("started_at") or "not recorded"
                heartbeat_at = job.get("updated_at")
                errors = [job["error_text"]] if job.get("error_text") else []
                warning_count = len(errors)
            rows.append(
                {
                    "id": harvester_id,
                    "name": name,
                    "source": source,
                    "enabled": bool(job),
                    "state": state,
                    "last_run": last_run,
                    "heartbeat_at": heartbeat_at,
                    "checkpoint": job_name,
                    "rows_processed": 0,
                    "rows_inserted": 0,
                    "errors": errors,
                    "warning_count": warning_count,
                    "runNow": "requires_owner_authorization",
                    "pauseResume": "requires_owner_authorization",
                    "logSummary": "Read-only heartbeat derived from oc_admin.ocp_execution_jobs when available.",
                }
            )
        return rows

    result = with_connection(_read)
    if isinstance(result, dict) and result.get("database_connected") is False:
        return [
            {
                "id": harvester_id,
                "name": name,
                "source": source,
                "enabled": False,
                "state": "unknown",
                "last_run": "database unavailable",
                "heartbeat_at": None,
                "checkpoint": job_name,
                "rows_processed": 0,
                "rows_inserted": 0,
                "errors": result.get("blockers", []),
                "warning_count": 1,
                "runNow": "requires_owner_authorization",
                "pauseResume": "requires_owner_authorization",
                "logSummary": "Database telemetry is unavailable; no write controls enabled.",
            }
            for harvester_id, name, source, job_name in HARVESTERS
        ]
    return result


@router.get("/status")
def mission_control_status() -> dict[str, Any]:
    snapshot = metric_snapshot()
    db_connected = bool(snapshot.get("database_connected"))
    return {
        "build": BUILD_ID,
        "status": "healthy" if db_connected else "warning",
        "service": "orchid-calyx-backend",
        "mode": "read_only_live_telemetry",
        "generated_at": utc_now(),
        "database_connected": db_connected,
        "blockers": snapshot.get("blockers", []),
        "safety": {
            "read_only": True,
            "write_controls_enabled": False,
            "owner_authorization_required": True,
        },
    }


@router.get("/health")
def mission_control_health() -> dict[str, Any]:
    status = mission_control_status()
    health = status["status"]
    blockers = status.get("blockers", [])
    blocker_text = "; ".join(blockers) if blockers else None
    return {
        **status,
        "id": "mission_control_backend",
        "display_name": "Mission Control Backend Telemetry",
        "health": health,
        "completion": 80 if status["database_connected"] else 35,
        "last_update": status["generated_at"],
        "telemetry_source": "orchid-calyx-backend read-only telemetry router",
        "evidence": ["Mission Control telemetry router is mounted."] if status["database_connected"] else [],
        "warning_text": blocker_text if health != "healthy" else None,
        "blocker_text": blocker_text,
        "recommendation": "Redeploy the backend after merge, then verify the frontend reads live telemetry.",
    }


@router.get("/subsystems")
def mission_control_subsystems() -> dict[str, Any]:
    return {"build": BUILD_ID, "subsystems": completeness_rows(), "generated_at": utc_now()}


@router.get("/audit")
def mission_control_audit() -> dict[str, Any]:
    subsystems = completeness_rows()
    failing = [row for row in subsystems if row["status"] in {"warning", "error", "stub", "unknown"}]
    return {
        "build": BUILD_ID,
        "status": "healthy" if not failing else "warning",
        "subsystems": subsystems,
        "diagnostics": [
            {
                "id": row["id"],
                "status": row["status"],
                "summary": row["summary"],
                "blockers": row.get("blockers", []),
                "evidence": row.get("evidence", []),
            }
            for row in subsystems
        ],
        "generated_at": utc_now(),
    }


@router.get("/harvesters")
def mission_control_harvesters() -> dict[str, Any]:
    return {"build": BUILD_ID, "harvesters": harvester_rows(), "generated_at": utc_now()}


@router.get("/runtime")
def mission_control_runtime() -> dict[str, Any]:
    return {"build": BUILD_ID, "runtime": runtime_telemetry(), "generated_at": utc_now()}


@router.get("/repositories")
def mission_control_repositories() -> dict[str, Any]:
    repositories = [
        {
            **repo,
            "deploy_status": "warning" if repo["backend_deploy_needed"] else "unknown",
            "latest_commit": None,
            "open_pull_requests": None,
            "last_deploy": None,
        }
        for repo in REPOSITORIES
    ]
    return {"build": BUILD_ID, "repositories": repositories, "generated_at": utc_now()}


@router.get("/builds")
def mission_control_builds() -> dict[str, Any]:
    return {
        "build": BUILD_ID,
        "builds": [
            {
                "id": BUILD_ID.lower(),
                "title": "Mission Control Backend Live Telemetry API",
                "status": "implemented_backend_pr",
                "repository": "jsp1440/orchid-calyx-backend",
                "safety": "read_only_no_write_controls",
                "frontend_deploy_needed": False,
                "backend_deploy_needed": True,
            }
        ],
        "generated_at": utc_now(),
    }


@router.get("/deployments")
def mission_control_deployments() -> dict[str, Any]:
    return {
        "build": BUILD_ID,
        "deployments": [
            {
                "id": "calyx-backend-render",
                "name": "Calyx backend",
                "target": "https://orchid-calyx-backend.onrender.com",
                "status": "warning",
                "last_deploy": None,
                "backend_deploy_needed": True,
                "known_blockers": ["Redeploy backend after BUILD-039 merge."],
            },
            {
                "id": "continuum-frontend",
                "name": "Orchid Continuum frontend",
                "target": "Frontend hosting",
                "status": "unknown",
                "last_deploy": None,
                "frontend_deploy_needed": False,
                "known_blockers": ["Live Render telemetry requires connector credentials."],
            },
        ],
        "generated_at": utc_now(),
    }


@router.get("/metrics")
def mission_control_metrics() -> dict[str, Any]:
    snapshot = metric_snapshot()
    return {"build": BUILD_ID, **snapshot}


@router.get("/completeness")
def mission_control_completeness() -> dict[str, Any]:
    rows = completeness_rows()
    return {"build": BUILD_ID, "completeness": rows, "items": rows, "generated_at": utc_now()}


@router.get("/recommendations")
def mission_control_recommendations() -> dict[str, Any]:
    return {
        "build": BUILD_ID,
        "recommendations": [
            {
                "id": "backend-deploy-build-039",
                "title": "Deploy backend telemetry endpoints",
                "priority": "critical",
                "rationale": "Mission Control can only leave fallback mode after backend live telemetry endpoints are deployed.",
                "ownerDecisionNeeded": "Merge BUILD-039, then redeploy orchid-calyx-backend.",
                "nextBuild": "DEPLOY-BACKEND-BUILD-039",
            },
            {
                "id": "github-render-connectors",
                "title": "Add backend-owned GitHub and Render telemetry connectors",
                "priority": "high",
                "rationale": "Repository and deployment status remain unknown without server-side connector credentials.",
                "ownerDecisionNeeded": "Approve read-only connector tokens and storage strategy.",
                "nextBuild": "BUILD-040",
            },
            {
                "id": "source-specific-freshness",
                "title": "Add source-specific freshness checks",
                "priority": "medium",
                "rationale": "Row counts are useful but do not prove data freshness or pipeline health.",
                "ownerDecisionNeeded": "Prioritize Atlas, Images, Literature, or Harvesters for freshness telemetry.",
                "nextBuild": "BUILD-041",
            },
        ],
        "generated_at": utc_now(),
    }


@router.get("/governance")
def mission_control_governance() -> dict[str, Any]:
    return {
        "build": BUILD_ID,
        "status": "warning",
        "north_star": "The Orchid Continuum exists to cultivate understanding by revealing relationships.",
        "missions": [
            {
                "mission_key": "build-039",
                "title": "Mission Control Backend Live Telemetry API",
                "status": "implemented_backend_pr",
                "next_action": "Merge and redeploy backend, then confirm frontend exits 0/endpoint fallback mode.",
                "safe_autonomy_level": 1,
            }
        ],
        "policies": [
            {
                "policy_key": "read_only_telemetry_first",
                "title": "Read-only telemetry before operations",
                "principle": "Mission Control may observe systems before it is allowed to operate them.",
                "protected": True,
            },
            {
                "policy_key": "owner_authorization_required",
                "title": "Owner authorization required",
                "principle": "Run, pause, resume, deploy, credential, and production-write actions require server-side owner authorization.",
                "protected": True,
            },
        ],
        "decisions": [
            {
                "decision_id": "build-039-decision",
                "action": "Expose safe read-only Mission Control telemetry endpoints in the backend.",
                "status": "recorded",
                "risk_level": "low",
                "rationale": "Read-only observability reduces fallback ambiguity without enabling destructive actions.",
                "created_at": utc_now(),
            }
        ],
        "questions": [
            {
                "question_id": "build-040-scope",
                "question": "Should the next backend build prioritize GitHub/Render deployment telemetry, source-specific harvester freshness, or owner authorization?",
                "status": "open",
                "created_at": utc_now(),
            }
        ],
        "generated_at": utc_now(),
    }


# ─── BUILD-065: Executive Operating System Integration ────────────────────────

_EXECUTIVE_FLOW_STEPS = [
    {
        "step": 1,
        "section": "daily_brief",
        "title": "Daily Brief",
        "api_endpoint": "/api/mission-control/owner/executive-session",
        "description": "Authenticated session state, owner permissions, and platform readiness at a glance.",
        "orientation": {
            "what_is_this": "A live status snapshot of the Orchid Continuum platform assembled for the owner.",
            "why_it_matters": "Establishes context before any decisions are made and confirms system health.",
            "what_can_i_do_here": "Review authenticated status, active alerts, and current session permissions.",
            "what_is_calyx_doing": "Aggregating platform telemetry and preparing the executive briefing.",
            "what_decision_do_i_need_to_make": "Decide whether to proceed with normal operations or investigate a flagged alert.",
            "expected_outputs": "Authenticated session, system health summary, and recommended next step.",
            "dependencies": ["backend", "authentication", "mission_control"],
        },
    },
    {
        "step": 2,
        "section": "platform_status",
        "title": "Platform Status",
        "api_endpoint": "/api/mission-control/status",
        "description": "Database connectivity, backend health, and service availability.",
        "orientation": {
            "what_is_this": "Real-time platform health across backend, database, and deployed services.",
            "why_it_matters": "All executive decisions and Calyx operations depend on a stable platform foundation.",
            "what_can_i_do_here": "Identify service degradations and confirm readiness for authorized operations.",
            "what_is_calyx_doing": "Polling database connectivity and service heartbeats.",
            "what_decision_do_i_need_to_make": "Approve a deployment, investigate a service warning, or defer operations.",
            "expected_outputs": "Platform health status, blocker list, and database connectivity confirmation.",
            "dependencies": ["database", "backend"],
        },
    },
    {
        "step": 3,
        "section": "critical_alerts",
        "title": "Critical Alerts",
        "api_endpoint": "/api/mission-control/health",
        "description": "Subsystems in warning or blocked state that require owner attention.",
        "orientation": {
            "what_is_this": "Filtered view of the highest-severity issues across all subsystems.",
            "why_it_matters": "Unaddressed alerts block scientific progress and can cascade across dependent subsystems.",
            "what_can_i_do_here": "Triage alerts by severity and assign corrective actions.",
            "what_is_calyx_doing": "Monitoring subsystem health and escalating persistent blockers.",
            "what_decision_do_i_need_to_make": "Which alerts need immediate owner action versus monitoring.",
            "expected_outputs": "Ordered alert list with impact and recommended actions.",
            "dependencies": ["health", "completeness", "mission_control"],
        },
    },
    {
        "step": 4,
        "section": "calyx_activity",
        "title": "Current Calyx Activity",
        "api_endpoint": "/api/mission-control/runtime",
        "description": "Active Calyx jobs, harvester states, and autonomous pipeline progress.",
        "orientation": {
            "what_is_this": "Live view of what Calyx is executing, planning, or waiting on right now.",
            "why_it_matters": "Understanding Calyx's current posture prevents conflicting owner actions.",
            "what_can_i_do_here": "Monitor job progress, review waiting harvester queues, and authorize pending operations.",
            "what_is_calyx_doing": "Running or pausing harvesters, executing scheduled jobs, and queuing owner-pending tasks.",
            "what_decision_do_i_need_to_make": "Authorize, pause, or reschedule pending Calyx operations.",
            "expected_outputs": "Runtime job summary, harvester states, and pending authorization queue.",
            "dependencies": ["runtime_jobs", "harvesters", "governance"],
        },
    },
    {
        "step": 5,
        "section": "owner_decisions",
        "title": "Owner Decisions Waiting",
        "api_endpoint": "/api/mission-control/owner/decisions",
        "description": "Categorized decision items requiring owner action, approval, or review.",
        "orientation": {
            "what_is_this": "Every item that cannot proceed without a direct owner decision.",
            "why_it_matters": "Unresolved decisions block the entire pipeline; this section eliminates ambiguity.",
            "what_can_i_do_here": "Approve, defer, or delegate decisions across subsystems and operations.",
            "what_is_calyx_doing": "Surfacing blocked work items and preparing decision context for the owner.",
            "what_decision_do_i_need_to_make": "Which items to approve, defer, or escalate to external partners.",
            "expected_outputs": "Categorized decision queue with impact, effort, and dependency context.",
            "dependencies": ["governance", "harvesters", "recommendations", "completeness"],
        },
    },
    {
        "step": 6,
        "section": "recommended_next_build",
        "title": "Recommended Next Build",
        "api_endpoint": "/api/mission-control/owner/priorities",
        "description": "Unified global priority queue ranking all subsystem recommendations.",
        "orientation": {
            "what_is_this": "A single ranked list of what to build next, derived from all subsystem analysis.",
            "why_it_matters": "Replaces scattered recommendations with one authoritative owner action plan.",
            "what_can_i_do_here": "Review, approve, or modify the top-priority build recommendation.",
            "what_is_calyx_doing": "Scoring subsystems, computing dependencies, and proposing the highest-leverage next build.",
            "what_decision_do_i_need_to_make": "Approve the top recommended build or adjust the priority order.",
            "expected_outputs": "Ranked priority queue with suggested BUILD numbers, impact, and effort estimates.",
            "dependencies": ["executive_state", "dependency_graph", "recommendations"],
        },
    },
    {
        "step": 7,
        "section": "subsystem_deep_dive",
        "title": "Subsystem Deep Dive",
        "api_endpoint": "/api/mission-control/subsystems",
        "description": "Per-subsystem health, completion, relationships, and readiness dimensions.",
        "orientation": {
            "what_is_this": "Detailed telemetry and multi-dimensional readiness for every Orchid Continuum subsystem.",
            "why_it_matters": "Deep subsystem context surfaces hidden leverage points and unblocks systematic progress.",
            "what_can_i_do_here": "Inspect individual subsystem health, review dependencies, and identify the highest-leverage improvements.",
            "what_is_calyx_doing": "Collecting telemetry, computing completeness scores, and mapping subsystem relationships.",
            "what_decision_do_i_need_to_make": "Which subsystem to prioritize for the next build cycle.",
            "expected_outputs": "Per-subsystem health cards, readiness dimensions, and relationship graph.",
            "dependencies": ["completeness", "health", "relationships"],
        },
    },
    {
        "step": 8,
        "section": "research_workspace",
        "title": "Research Workspace",
        "api_endpoint": "/api/mission-control/owner/research-requests",
        "description": "Active research requests, scientific intelligence, and literature pipeline.",
        "orientation": {
            "what_is_this": "The owner-facing workspace for managing scientific research requests and intelligence.",
            "why_it_matters": "Research drives grant applications, publications, and evidence-based system improvements.",
            "what_can_i_do_here": "Submit research requests, review parsed intelligence, and promote verified items to Brain knowledge.",
            "what_is_calyx_doing": "Parsing source briefings, extracting intelligence items, and queuing research tasks.",
            "what_decision_do_i_need_to_make": "Which intelligence items to promote, which research requests to prioritize.",
            "expected_outputs": "Research queue, intelligence review panel, and Brain knowledge pipeline status.",
            "dependencies": ["knowledge_graph", "literature", "grant_office"],
        },
    },
    {
        "step": 9,
        "section": "governance_audit",
        "title": "Governance / Audit",
        "api_endpoint": "/api/mission-control/owner/governance",
        "description": "Constitutional policies, decisions, audit trail, and mission compliance.",
        "orientation": {
            "what_is_this": "The governance layer ensuring every Calyx action aligns with Orchid Continuum Constitutional policies.",
            "why_it_matters": "Owner-authorized governance prevents unauthorized writes and maintains mission integrity.",
            "what_can_i_do_here": "Review policy compliance, inspect the decision ledger, and generate operational audits.",
            "what_is_calyx_doing": "Enforcing constitutional autonomy limits and logging every privileged action.",
            "what_decision_do_i_need_to_make": "Whether governance policies require updates based on the current operational phase.",
            "expected_outputs": "Policy compliance summary, decision history, and full operational audit.",
            "dependencies": ["governance", "constitutional_policies", "build_history"],
        },
    },
]


def _subsystem_display_names() -> dict[str, str]:
    """Map subsystem IDs to display names for relationship rendering."""
    return {
        "mission_control": "Mission Control",
        "atlas": "Atlas",
        "species_explorer": "Species Explorer",
        "knowledge_graph": "Knowledge Graph",
        "literature": "Literature",
        "pollinators": "Pollinators",
        "mycorrhiza": "Mycorrhiza",
        "vision_lab": "Vision Lab",
        "grant_office": "Grant Office",
        "partnership_generator": "Partnership Generator",
        "harvesters": "Harvesters",
        "runtime_jobs": "Runtime Jobs",
        "governance": "Governance",
        "build_history": "Build History",
        "recommendations": "Recommendations",
        "health": "Health",
        "completeness": "Completeness",
        "integrations": "Integrations",
    }


def _leverage_note(subsystem_id: str, depends_on: list[str], depended_on_by: list[str]) -> str:
    names = _subsystem_display_names()
    name = names.get(subsystem_id, subsystem_id.replace("_", " ").title())
    if depended_on_by:
        dependents = [names.get(d, d.replace("_", " ").title()) for d in depended_on_by[:4]]
        return f"Improving {name} directly improves {', '.join(dependents)}."
    if depends_on:
        upstream = [names.get(d, d.replace("_", " ").title()) for d in depends_on[:3]]
        return f"{name} requires {', '.join(upstream)} to be operational."
    return f"{name} is a standalone component."


@router.get("/executive-flow")
def mission_control_executive_flow() -> dict[str, Any]:
    """Return the Executive Operating System workflow map.

    BUILD-065: Provides a structured workflow that connects all Mission Control
    sections into a continuous executive operating experience.  Each step
    includes orientation blocks answering: What is this? Why it matters?
    What can I do here? What is Calyx doing? What decision do I need to make?
    """
    return {
        "build": BUILD_ID,
        "eos_version": BUILD_ID,
        "eos_title": "Orchid Continuum Executive Operating System",
        "eos_description": (
            "Mission Control integrated workflow connecting all subsystems into one coherent Executive "
            "Operating System.  Every section answers: What is happening? What needs my attention? "
            "What decisions are waiting? What should happen next?"
        ),
        "workflow_steps": _EXECUTIVE_FLOW_STEPS,
        "total_steps": len(_EXECUTIVE_FLOW_STEPS),
        "generated_at": utc_now(),
    }


@router.get("/relationships")
def mission_control_relationships() -> dict[str, Any]:
    """Return generalized subsystem relationship display.

    BUILD-065: Surfaces dependency and reverse-dependency relationships for
    all subsystems so the owner can understand leverage effects across the
    platform.  Replaces the prior Atlas-only dependency display.
    """
    from runtime.executive.dependencies import dependency_graph, reverse_dependencies

    graph = dependency_graph()
    reverse = reverse_dependencies(graph)
    names = _subsystem_display_names()

    relationships = []
    for subsystem_id, depends_on in graph.items():
        depended_on_by = reverse.get(subsystem_id, [])
        display = names.get(subsystem_id, subsystem_id.replace("_", " ").title())
        dep_names = [names.get(d, d.replace("_", " ").title()) for d in depends_on]
        rev_names = [names.get(d, d.replace("_", " ").title()) for d in depended_on_by]
        relationships.append(
            {
                "subsystem_id": subsystem_id,
                "display_name": display,
                "depends_on_ids": depends_on,
                "depends_on_names": dep_names,
                "depended_on_by_ids": depended_on_by,
                "depended_on_by_names": rev_names,
                "leverage_note": _leverage_note(subsystem_id, depends_on, depended_on_by),
                "dependency_count": len(depends_on),
                "dependent_count": len(depended_on_by),
            }
        )

    # Sort by most downstream leverage (most things depend on it)
    relationships.sort(key=lambda r: r["dependent_count"], reverse=True)

    return {
        "build": BUILD_ID,
        "description": "Subsystem dependency relationships showing leverage effects across the platform.",
        "relationships": relationships,
        "total_subsystems": len(relationships),
        "generated_at": utc_now(),
    }


def _compute_readiness_dimensions(row: dict[str, Any]) -> dict[str, int]:
    """Derive multi-dimensional readiness scores from a completeness row."""
    completion = int(row.get("completion") or row.get("completeness") or 0)
    status = str(row.get("status") or row.get("health") or "stub")
    blockers = row.get("blockers") or []
    category = str(row.get("category") or "")
    has_blockers = bool(blockers)
    db_penalty = 20 if "not connected" in str(row.get("telemetry_source") or "") else 0

    # Scientific readiness: data coverage and evidence quality
    sci = max(10, completion - db_penalty) if category in {"Science", "Ecology", "Media", "Relationships"} else max(10, completion // 2 - db_penalty)

    # Integration readiness: backend connectivity and API health
    integration = max(10, completion - db_penalty - (10 if has_blockers else 0))

    # Automation readiness: pipeline automation capability
    automation = max(10, completion - (15 if has_blockers else 0) - db_penalty)

    # Evidence readiness: verified citations, data lineage, provenance
    evidence = max(10, (completion - 10 - db_penalty) if status not in {"stub", "planned"} else max(10, completion // 3))

    # Publication readiness: sufficient evidence for external output
    publication = max(5, sci - 20 - (10 if has_blockers else 0))

    # Grant readiness: completeness for competitive grant applications
    grant = max(5, (completion - 25 - db_penalty) if status not in {"stub", "planned"} else 5)

    # Operational readiness: runtime stability and deployment readiness
    operational = max(10, completion - (15 if has_blockers else 0) - db_penalty)

    # Overall executive readiness: weighted composite
    overall = max(5, int(
        sci * 0.20
        + integration * 0.20
        + automation * 0.15
        + evidence * 0.20
        + publication * 0.10
        + grant * 0.05
        + operational * 0.10
    ))

    return {
        "scientific_readiness": min(100, sci),
        "integration_readiness": min(100, integration),
        "automation_readiness": min(100, automation),
        "evidence_readiness": min(100, evidence),
        "publication_readiness": min(100, publication),
        "grant_readiness": min(100, grant),
        "operational_readiness": min(100, operational),
        "overall_executive_readiness": min(100, overall),
    }


@router.get("/readiness")
def mission_control_readiness() -> dict[str, Any]:
    """Return multi-dimensional readiness model for all subsystems.

    BUILD-065: Replaces isolated completion percentages with connected readiness
    dimensions: scientific, integration, automation, evidence, publication,
    grant, operational, and overall executive readiness.
    """
    rows = completeness_rows()
    readiness_items = []
    for row in rows:
        dims = _compute_readiness_dimensions(row)
        readiness_items.append(
            {
                "id": row["id"],
                "display_name": row["display_name"],
                "category": row.get("category"),
                "status": row.get("status"),
                **dims,
            }
        )

    readiness_dimensions = [
        "scientific_readiness",
        "integration_readiness",
        "automation_readiness",
        "evidence_readiness",
        "publication_readiness",
        "grant_readiness",
        "operational_readiness",
        "overall_executive_readiness",
    ]

    return {
        "build": BUILD_ID,
        "readiness_dimensions": readiness_dimensions,
        "description": "Multi-dimensional readiness replacing isolated completion percentages.",
        "subsystems": readiness_items,
        "generated_at": utc_now(),
    }
