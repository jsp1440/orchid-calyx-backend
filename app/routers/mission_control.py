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

BUILD_ID = "BUILD-064"
DATABASE_URL = os.environ.get("DATABASE_URL")

REPOSITORIES = [
    {
        "name": "jsp1440/orchid-continuum-frontend",
        "default_branch": "main",
        "deployment_target": "Frontend hosting",
        "frontend_deploy_needed": True,
        "backend_deploy_needed": False,
        "known_blockers": [
            "Frontend deploy needed to connect BUILD-064 recommendations, governance, and Brain promotion controls.",
            "Live GitHub/Render telemetry requires backend-owned connector credentials.",
        ],
    },
    {
        "name": "jsp1440/orchid-calyx-backend",
        "default_branch": "main",
        "deployment_target": "https://orchid-calyx-backend.onrender.com",
        "frontend_deploy_needed": False,
        "backend_deploy_needed": True,
        "known_blockers": [
            "Redeploy backend after BUILD-064 merge to activate production operations endpoints.",
            "Live Render deployment telemetry requires connector credentials.",
        ],
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
                "id": "build-039",
                "title": "Mission Control Backend Live Telemetry API",
                "status": "deployed",
                "repository": "jsp1440/orchid-calyx-backend",
                "safety": "read_only_telemetry",
                "frontend_deploy_needed": False,
                "backend_deploy_needed": False,
            },
            {
                "id": "build-051",
                "title": "Owner Operations Console Backend",
                "status": "deployed",
                "repository": "jsp1440/orchid-calyx-backend",
                "safety": "owner_authorized_writes",
                "frontend_deploy_needed": False,
                "backend_deploy_needed": False,
            },
            {
                "id": "build-052",
                "title": "Calyx Executive Intelligence Engine",
                "status": "deployed",
                "repository": "jsp1440/orchid-calyx-backend",
                "safety": "read_only_executive_state",
                "frontend_deploy_needed": False,
                "backend_deploy_needed": False,
            },
            {
                "id": "build-062",
                "title": "Backend Execution Integration — Calyx Queue, Harvester Control, Worker Dispatch",
                "status": "deployed",
                "repository": "jsp1440/orchid-calyx-backend",
                "safety": "owner_authorized_operations",
                "frontend_deploy_needed": False,
                "backend_deploy_needed": False,
            },
            {
                "id": "build-063",
                "title": "Owner Authentication Completion + Live Backend Activation",
                "status": "deployed",
                "repository": "jsp1440/orchid-calyx-backend",
                "safety": "owner_session_httponly_cookie",
                "frontend_deploy_needed": False,
                "backend_deploy_needed": False,
            },
            {
                "id": BUILD_ID.lower(),
                "title": "Mission Control Production Operations Activation",
                "status": "deployed",
                "repository": "jsp1440/orchid-calyx-backend",
                "safety": "owner_authorized_production_operations",
                "frontend_deploy_needed": True,
                "backend_deploy_needed": False,
                "activated": [
                    "recommendations — owner authenticated review",
                    "governance — owner authenticated read access",
                    "promoteBrainKnowledge — owner authorized intelligence promotion",
                    "persistent session revocation — DB-backed nonce store",
                ],
            },
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
                "status": "unknown",
                "last_deploy": None,
                "backend_deploy_needed": True,
                "known_blockers": [
                    "Redeploy backend after BUILD-064 merge to activate production operations.",
                    "Live Render deployment telemetry requires connector credentials.",
                ],
            },
            {
                "id": "continuum-frontend",
                "name": "Orchid Continuum frontend",
                "target": "Frontend hosting",
                "status": "unknown",
                "last_deploy": None,
                "frontend_deploy_needed": True,
                "known_blockers": [
                    "Frontend deploy needed to connect recommendations, governance, and promoteBrainKnowledge controls to BUILD-064 endpoints.",
                    "Live Render telemetry requires connector credentials.",
                ],
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
                "id": "deploy-build-064-backend",
                "title": "Redeploy backend to activate BUILD-064 production operations",
                "priority": "critical",
                "rationale": (
                    "BUILD-064 activates recommendations, governance, and promoteBrainKnowledge endpoints. "
                    "The backend must be redeployed so Mission Control can call these new owner-authenticated routes."
                ),
                "ownerDecisionNeeded": "Merge BUILD-064 and redeploy orchid-calyx-backend on Render.",
                "nextBuild": "DEPLOY-BACKEND-BUILD-064",
            },
            {
                "id": "deploy-frontend-build-064",
                "title": "Deploy frontend to connect new BUILD-064 production controls",
                "priority": "high",
                "rationale": (
                    "Three capabilities activated in BUILD-064 require frontend updates: "
                    "owner-authenticated recommendations review, governance read panel, and Brain knowledge promotion. "
                    "These backend endpoints are live but not yet wired to frontend controls."
                ),
                "ownerDecisionNeeded": "Coordinate frontend BUILD-064 branch deployment after backend redeploy.",
                "nextBuild": "BUILD-064-FRONTEND",
            },
            {
                "id": "github-render-connectors",
                "title": "Add backend-owned GitHub and Render telemetry connectors",
                "priority": "high",
                "rationale": (
                    "Repository and deployment status remain static stubs. "
                    "Live GitHub branch/PR/workflow telemetry and Render deploy status require backend-owned connector credentials."
                ),
                "ownerDecisionNeeded": "Approve read-only connector tokens and storage strategy.",
                "nextBuild": "BUILD-065",
            },
            {
                "id": "intelligence-promotion-review",
                "title": "Review intelligence items for Brain knowledge promotion",
                "priority": "medium",
                "rationale": (
                    "BUILD-064 activates promoteBrainKnowledge. Intelligence items with verification_state "
                    "'reviewed' or 'owner_reviewed' are now eligible for promotion to authoritative Brain knowledge."
                ),
                "ownerDecisionNeeded": (
                    "Open the intelligence workspace, review eligible items, and use "
                    "POST /api/mission-control/owner/intelligence/{id}/promote to promote approved records."
                ),
                "nextBuild": "BUILD-065",
            },
            {
                "id": "source-specific-freshness",
                "title": "Add source-specific freshness checks",
                "priority": "medium",
                "rationale": (
                    "Row counts prove data presence but not freshness or pipeline health. "
                    "Atlas, Images, Literature, and Harvester pipelines need source-specific timestamp and provenance checks."
                ),
                "ownerDecisionNeeded": "Prioritize Atlas, Images, Literature, or Harvesters for freshness telemetry in the next build.",
                "nextBuild": "BUILD-065",
            },
        ],
        "generated_at": utc_now(),
    }


@router.get("/governance")
def mission_control_governance() -> dict[str, Any]:
    return {
        "build": BUILD_ID,
        "status": "operational",
        "north_star": "The Orchid Continuum exists to cultivate understanding by revealing relationships.",
        "missions": [
            {
                "mission_key": "build-039",
                "title": "Mission Control Backend Live Telemetry API",
                "status": "deployed",
                "next_action": None,
                "safe_autonomy_level": 1,
            },
            {
                "mission_key": "build-051",
                "title": "Owner Operations Console — Authenticated Control Plane",
                "status": "deployed",
                "next_action": None,
                "safe_autonomy_level": 2,
            },
            {
                "mission_key": "build-052",
                "title": "Calyx Executive Intelligence Engine",
                "status": "deployed",
                "next_action": None,
                "safe_autonomy_level": 2,
            },
            {
                "mission_key": "build-063",
                "title": "Owner Authentication Completion + Live Backend Activation",
                "status": "deployed",
                "next_action": None,
                "safe_autonomy_level": 3,
            },
            {
                "mission_key": "build-064",
                "title": "Mission Control Production Operations Activation",
                "status": "deployed",
                "next_action": (
                    "Redeploy backend and coordinate frontend deployment to connect "
                    "recommendations, governance, and Brain promotion controls."
                ),
                "safe_autonomy_level": 3,
            },
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
            {
                "policy_key": "no_unconfirmed_high_risk",
                "title": "High-risk actions require explicit confirmation",
                "principle": "Destructive, promotional, or irreversible actions require confirm: true in the request payload.",
                "protected": True,
            },
        ],
        "decisions": [
            {
                "decision_id": "build-039-decision",
                "action": "Expose safe read-only Mission Control telemetry endpoints in the backend.",
                "status": "implemented",
                "risk_level": "low",
                "rationale": "Read-only observability reduces fallback ambiguity without enabling destructive actions.",
            },
            {
                "decision_id": "build-051-decision",
                "action": "Implement owner-authenticated operations console with durable command, queue, and intelligence records.",
                "status": "implemented",
                "risk_level": "medium",
                "rationale": "Owner-authorized writes are necessary for operational Mission Control while remaining safe from anonymous writes.",
            },
            {
                "decision_id": "build-064-decision",
                "action": "Activate recommendations, governance, and Brain knowledge promotion as owner-authorized production operations.",
                "status": "implemented",
                "risk_level": "low",
                "rationale": "These capabilities were scaffolded with implemented=False; BUILD-064 activates their backend endpoints and marks them as operational.",
            },
        ],
        "questions": [
            {
                "question_id": "build-064-frontend-scope",
                "question": (
                    "Which frontend controls should be updated first: recommendations review panel, "
                    "governance read panel, or Brain knowledge promotion workflow?"
                ),
                "status": "open",
                "created_at": utc_now(),
            },
            {
                "question_id": "build-065-connector-scope",
                "question": (
                    "Should the next build prioritize GitHub/Render deployment telemetry connectors "
                    "or source-specific freshness checks for Atlas and harvester pipelines?"
                ),
                "status": "open",
                "created_at": utc_now(),
            },
        ],
        "generated_at": utc_now(),
    }
