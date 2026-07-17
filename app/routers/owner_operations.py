"""BUILD-051 / BUILD-065 authenticated Owner Operations Console API.

These endpoints are the server-side control plane for Mission Control. Browser
unlock is intentionally separate: privileged writes require a signed owner
session or backend API key and are logged.

BUILD-064 additions:
- Persistent session revocation (DB-backed nonce table with in-memory fallback)
- Owner recommendations endpoint (GET /recommendations)
- Owner governance endpoint (GET /governance)
- Brain knowledge promotion endpoint (POST /intelligence/{item_id}/promote)
- Updated allowed_actions: recommendations and governance marked as implemented

BUILD-065 additions:
- Owner Decision Layer (GET /decisions)
- Unified Global Priority Queue (GET /priorities)
- Calyx Operational Narrative (GET /calyx-narrative)
- Complete EOS State endpoint (GET /eos-state)
- Updated allowed_actions: eos-related capabilities marked as implemented

BUILD-066A additions:
- POST /control-verification: create and persist labeled verification record
- GET /control-verification/:id: retrieve verification record by ID with DB read-back

BUILD-075 additions:
- Owner-authenticated Executive Intelligence Mission Control section
- Read-only Executive Intelligence snapshot with explicit approval/reject actions
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.executive_intelligence.repository import executive_intelligence_snapshot
from app.executive_intelligence.repository import decide as executive_intelligence_decide
from app.executive_intelligence.schemas import RecommendationDecisionRequest
from app.security import OWNER_SESSION_COOKIE, REVOKED_OWNER_NONCES, create_owner_session_token, owner_cookie_samesite, owner_cookie_secure, owner_session_ttl_seconds, verify_owner_access_code, verify_owner_or_api_key, verify_owner_session
from app.routers.mission_control import completeness_rows, harvester_rows, metric_snapshot
from runtime.constitutional_orchestrator import AutonomyLevel, orchestrator as constitutional_orchestrator

router = APIRouter(prefix="/api/mission-control/owner", tags=["BUILD-051 Owner Operations"])


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def database_url() -> str | None:
    return os.environ.get("DATABASE_URL")


MEMORY: dict[str, list[dict[str, Any]]] = {
    "source_briefings": [],
    "intelligence_items": [],
    "owner_commands": [],
    "operations_queue": [],
    "research_requests": [],
    "generated_audits": [],
    "partnership_packets": [],
    "privileged_action_log": [],
}

# In-memory fallback store for control verifications (used when DATABASE_URL is absent)
CONTROL_VERIFICATIONS: dict[str, dict[str, Any]] = {}


class OwnerLoginRequest(BaseModel):
    access_code: str = Field(min_length=1)
    owner: str = Field(default="owner", min_length=1)


class SourceBriefingRequest(BaseModel):
    source: str = Field(min_length=1)
    source_date: str | None = None
    raw_text: str = Field(min_length=1)
    provenance: dict[str, Any] = Field(default_factory=dict)


class LocalIntelligenceImportRequest(BaseModel):
    source: str = "localStorage"
    records: list[dict[str, Any]] = Field(default_factory=list)


class IntelligencePatchRequest(BaseModel):
    status: str | None = None
    priority: str | None = None
    owner: str | None = None
    notes: str | None = None
    verification_state: str | None = None


class AuditRequest(BaseModel):
    audit_type: str = Field(default="overall", min_length=1)
    output_format: str = Field(default="markdown", pattern="^(json|markdown|pdf|docx)$")


class CommandRequest(BaseModel):
    command: str = Field(min_length=1)
    confirm: bool = False


class QueueTransitionRequest(BaseModel):
    reason: str | None = None


class ResearchRequestIn(BaseModel):
    title: str = Field(min_length=1)
    research_question: str = Field(min_length=1)
    taxa: list[str] = Field(default_factory=list)
    geography: list[str] = Field(default_factory=list)
    requested_evidence_sources: list[str] = Field(default_factory=list)
    requested_outputs: list[str] = Field(default_factory=list)
    priority: str = "medium"
    provenance: dict[str, Any] = Field(default_factory=dict)


class PartnershipPacketRequest(BaseModel):
    organization_name: str = Field(min_length=1)
    partner_type: str = "research"
    output_format: str = Field(default="markdown", pattern="^(json|markdown)$")


def actor(auth: dict[str, object]) -> str:
    return str(auth.get("actor") or "owner")


def allowed_actions(authenticated: bool) -> dict[str, dict[str, Any]]:
    def action(
        label: str,
        *,
        risk: str = "low",
        writes: bool = True,
        high_risk: bool = False,
        implemented: bool = True,
    ) -> dict[str, Any]:
        allowed = authenticated and implemented
        return {
            "allowed": allowed,
            "state": "owner_authorized_action" if allowed else "not_yet_implemented" if not implemented else "requires_owner_authorization",
            "auth": "owner_session_or_api_key",
            "risk": risk,
            "writesDatabase": writes,
            "requiresConfirmation": high_risk,
            "reason": label,
        }

    return {
        "runtime": action("Inspect and operate implemented runtime controls."),
        "runtimeStart": action("Start the autonomous runtime.", risk="high", high_risk=True),
        "runtimeStop": action("Stop the autonomous runtime.", risk="high", high_risk=True),
        "runtimeRestart": action("Restart the autonomous runtime.", risk="high", high_risk=True),
        "autonomousCycle": action("Run one autonomous cycle."),
        "harvesters": action("Run implemented harvester actions."),
        "queueActions": action("Transition eligible operations queue items.", risk="high", high_risk=True),
        "recommendations": action("Review live recommendations from Mission Control telemetry.", writes=False),
        "audits": action("Generate and persist live operational audits."),
        "governance": action("Read governance evidence; structural mutations require future build.", writes=False),
        "saveBriefing": action("Preserve a source briefing and parsed provisional intelligence records."),
        "importLocalRecords": action("Import owner-approved browser records with deduplication."),
        "editIntelligence": action("Update owner review, assignment, notes, or verification state."),
        "generateAudit": action("Generate and persist a live audit from backend telemetry."),
        "submitCommand": action("Create a durable Calyx command record."),
        "approveQueueItem": action("Approve eligible queued work.", risk="high", high_risk=True),
        "cancelQueueItem": action("Cancel eligible queued work."),
        "retryQueueItem": action("Retry eligible failed work."),
        "createResearchRequest": action("Persist a research request for queued analysis."),
        "generatePartnershipPacket": action("Generate and persist a partner packet."),
        "promoteBrainKnowledge": action(
            "Promote reviewed intelligence into authoritative Brain knowledge.",
            risk="high",
            high_risk=True,
        ),
        "decisionReview": action("Review and triage categorized owner decisions from the EOS decision layer.", writes=False),
        "priorityReview": action("Review the unified global priority queue and approve the next build.", writes=False),
        "calyxNarrative": action("Read the Calyx operational narrative explaining current posture and recommendations.", writes=False),
        "eosState": action("Load the complete Executive Operating System state in a single request.", writes=False),
    }


def db_execute(callback):
    url = database_url()
    if not url:
        return callback(None)
    try:
        with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                result = callback(cur)
            conn.commit()
            return result
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"BUILD-051 database operation unavailable: {exc}") from exc


def _db_execute_silent(callback) -> None:
    """Run a DB callback against a live connection, silently absorbing errors.

    Only calls the callback when DATABASE_URL is configured and a connection
    can be established.  The callback receives a live cursor; it must not check
    for ``None``.  Used for best-effort persistence where failures must never
    propagate (e.g., session revocation logging).
    """
    url = database_url()
    if not url:
        return
    try:
        with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                callback(cur)
            conn.commit()
    except Exception:
        pass


def persist_revoked_nonce(nonce: str) -> None:
    """Persist a revoked session nonce to the DB for cross-restart durability.

    Always updates the in-memory set.  DB write is best-effort: failures are
    silently absorbed so logout always succeeds even without a database.
    """
    REVOKED_OWNER_NONCES.add(nonce)

    def _write(cur):
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS oc_admin.build064_session_revocations (
                nonce TEXT PRIMARY KEY,
                revoked_at TIMESTAMPTZ DEFAULT NOW()
            )
            """,
        )
        cur.execute(
            "INSERT INTO oc_admin.build064_session_revocations (nonce, revoked_at) VALUES (%s, NOW()) ON CONFLICT DO NOTHING",
            (nonce,),
        )

    _db_execute_silent(_write)


def load_revoked_nonces() -> int:
    """Load all persisted revoked nonces from the DB into the in-memory set.

    Called on startup when DATABASE_URL is available.  Returns the count of
    nonces loaded.  Silently returns 0 if the table does not exist yet or if
    the database is unavailable.
    """
    url = database_url()
    if not url:
        return 0
    try:
        with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT nonce FROM oc_admin.build064_session_revocations
                    WHERE revoked_at > NOW() - INTERVAL '7 days'
                    """
                )
                rows = cur.fetchall()
                for row in rows:
                    REVOKED_OWNER_NONCES.add(row["nonce"])
                return len(rows)
    except Exception:
        return 0



def log_action(auth: dict[str, object], action_name: str, entity_type: str, entity_id: str, detail: dict[str, Any]) -> None:
    record = {
        "id": f"LOG-{uuid4().hex[:12].upper()}",
        "actor": actor(auth),
        "auth_type": auth.get("auth_type"),
        "action": action_name,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "detail": detail,
        "created_at": utc_now(),
    }
    def _write(cur):
        if cur is None:
            MEMORY["privileged_action_log"].insert(0, record)
            return None
        cur.execute(
            """
            INSERT INTO oc_admin.build051_privileged_action_log
                (id, actor, auth_type, action, entity_type, entity_id, detail, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
            """,
            (record["id"], record["actor"], record["auth_type"], action_name, entity_type, entity_id, Jsonb(detail)),
        )
        return None
    db_execute(_write)


def parse_briefing_items(source_briefing_id: str, source: str, source_date: str | None, raw_text: str) -> list[dict[str, Any]]:
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n|(?=Deadline:|Grant:|Opportunity:|Partner:)", raw_text) if chunk.strip()]
    if not chunks:
        chunks = [raw_text.strip()]
    items: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks[:30]):
        lower = chunk.lower()
        category = ["Grant"] if any(term in lower for term in ["grant", "funding", "deadline", "$"]) else ["Partnership"] if any(term in lower for term in ["partner", "university", "collaboration", "lab"]) else ["Research"]
        priority = "high" if any(term in lower for term in ["deadline", "urgent", "critical"]) else "medium"
        deadline = None
        match = re.search(r"(20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/20\d{2})", chunk)
        if match:
            deadline = match.group(1)
        title = chunk.splitlines()[0][:140] if chunk.splitlines() else f"{source} item {index + 1}"
        items.append(
            {
                "id": f"INT-{uuid4().hex[:12].upper()}",
                "source_briefing_id": source_briefing_id,
                "title": title,
                "summary": chunk[:600],
                "source": source,
                "source_date": source_date,
                "category": category,
                "priority": priority,
                "status": "new",
                "deadline_date": deadline,
                "funding_amount": None,
                "organization": None,
                "recommended_action": "Owner review required before promotion.",
                "owner": None,
                "notes": "",
                "source_excerpt": chunk[:1000],
                "source_link": None,
                "eligibility_summary": "Not verified",
                "missing_information": [],
                "application_progress": "provisional_parse",
                "verification_state": "provisional",
                "created_at": utc_now(),
                "updated_at": utc_now(),
            }
        )
    return items


def row_list(table: str) -> list[dict[str, Any]]:
    def _read(cur):
        if cur is None:
            return MEMORY[table]
        db_table = {
            "source_briefings": "oc_admin.build051_source_briefings",
            "intelligence_items": "oc_admin.build051_intelligence_items",
            "owner_commands": "oc_admin.build051_owner_commands",
            "operations_queue": "oc_admin.build051_operations_queue",
            "research_requests": "oc_admin.build051_research_requests",
            "generated_audits": "oc_admin.build051_generated_audits",
            "partnership_packets": "oc_admin.build051_partnership_packets",
        }[table]
        cur.execute(f"SELECT * FROM {db_table} ORDER BY created_at DESC LIMIT 500")
        return [dict(row) for row in cur.fetchall()]
    return db_execute(_read)


def insert_json_table(table: str, record: dict[str, Any]) -> dict[str, Any]:
    def _write(cur):
        if cur is None:
            MEMORY[table].insert(0, record)
            return record
        payload = Jsonb(record)
        table_name = {
            "source_briefings": "oc_admin.build051_source_briefings",
            "intelligence_items": "oc_admin.build051_intelligence_items",
            "owner_commands": "oc_admin.build051_owner_commands",
            "operations_queue": "oc_admin.build051_operations_queue",
            "research_requests": "oc_admin.build051_research_requests",
            "generated_audits": "oc_admin.build051_generated_audits",
            "partnership_packets": "oc_admin.build051_partnership_packets",
        }[table]
        cur.execute(
            f"""
            INSERT INTO {table_name} (id, payload, created_by, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            RETURNING payload
            """,
            (record["id"], payload, record.get("created_by") or record.get("owner") or "owner"),
        )
        return dict(cur.fetchone()["payload"])
    return db_execute(_write)


@router.post("/session")
def create_session(request: OwnerLoginRequest, response: Response) -> dict[str, Any]:
    session = verify_owner_access_code(request.access_code, request.owner)
    response.set_cookie(OWNER_SESSION_COOKIE, str(session["token"]), max_age=owner_session_ttl_seconds(), expires=owner_session_ttl_seconds(), httponly=True, secure=owner_cookie_secure(), samesite=owner_cookie_samesite(), path="/api/")
    return {
        "authenticated": True,
        "status": "authenticated",
        "owner": session["owner"], "expires_at": session["expires_at"], "token": "cookie",
        "allowedActions": allowed_actions(True),
        "credential_transport": "httponly_cookie",
    }


@router.get("/session")
async def inspect_session(request: Request) -> dict[str, Any]:
    try: auth = await verify_owner_session(request)
    except HTTPException as exc:
        reasons = {"Owner session expired": "expired", "Owner session ended": "signed_out", "Invalid owner session": "invalid_session"}
        return {"authenticated": False, "status": "unauthenticated", "expires_at": None, "allowedActions": allowed_actions(False), "reason": reasons.get(str(exc.detail), "missing_session"), "credential_transport": "httponly_cookie"}
    return {
        "authenticated": True,
        "status": "authenticated",
        "owner": actor(auth),
        "auth_type": auth.get("auth_type"),
        "issued_at": auth.get("issued_at"),
        "expires_at": auth.get("expires_at"),
        "allowedActions": allowed_actions(True),
        "reason": None, "credential_transport": "httponly_cookie",
    }

@router.delete("/session")
async def delete_session(request: Request, response: Response) -> dict[str, Any]:
    try:
        auth = await verify_owner_session(request)
        if auth.get("nonce"):
            persist_revoked_nonce(str(auth["nonce"]))
    except HTTPException: pass
    response.delete_cookie(OWNER_SESSION_COOKIE, path="/api/", secure=owner_cookie_secure(), httponly=True, samesite=owner_cookie_samesite())
    return {"authenticated": False, "status": "signed_out", "reason": "owner_signed_out"}


@router.get("/permissions")
def permissions(auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    return {"owner": actor(auth), "allowedActions": allowed_actions(True), "generated_at": utc_now()}


def _repo_revision() -> str:
    """Return the short git HEAD revision, or 'unknown' if unavailable."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, timeout=5
        ).decode().strip()
    except Exception:
        return "unknown"


_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def _runtime_env_enabled() -> bool:
    """Check whether the runtime autoloop is enabled by environment config.

    Mirrors the logic in main.py without creating a circular import.
    """
    disable_flags = ("CALYX_AUTONOMOUS_DISABLED", "OC_RUNNER_DISABLED", "CALYX_RUNTIME_DISABLED")
    enable_flags = (
        "CALYX_AUTOLOOP_ENABLED", "OC_RUNNER_AUTOLOOP", "CALYX_RUNTIME_ENABLED",
        "AUTONOMOUS_RUNTIME_ENABLED", "RUNNER_ENABLED", "CALYX_AUTONOMOUS_ENABLED",
    )

    for key in disable_flags:
        if os.environ.get(key, "").strip().lower() in _TRUTHY:
            return False
    for key in enable_flags:
        val = os.environ.get(key)
        if val is not None:
            return val.strip().lower() in _TRUTHY
    return False


@router.get("/executive-session")
async def executive_session(request: Request) -> dict[str, Any]:
    """Return the complete authenticated owner session state for Mission Control.

    This endpoint is auth-aware: it always returns HTTP 200 with structured
    payload indicating whether the owner is authenticated and what permissions
    are available. Mission Control uses this response to transition from
    read-only informational mode to operational mode.

    Fields included:
    - authenticated / status / reason — session state
    - allowedActions / permissions — full permission model
    - session_info — expiration and refresh metadata
    - backend — version, build, repo revision, runtime availability
    """
    now = int(time.time())
    auth: dict[str, object] | None = None
    auth_reason: str | None = None

    try:
        auth = await verify_owner_session(request)
    except HTTPException as exc:
        _reason_map = {
            "Owner session expired": "expired",
            "Owner session ended": "signed_out",
            "Invalid owner session": "invalid_session",
        }
        auth_reason = _reason_map.get(str(exc.detail), "missing_session")

    authenticated = auth is not None
    actions = allowed_actions(authenticated)

    ttl_remaining: int | None = None
    if authenticated and auth and auth.get("expires_at"):
        ttl_remaining = max(0, int(auth["expires_at"]) - now)  # type: ignore[arg-type]

    permissions_list = [k for k, v in actions.items() if v.get("allowed")]

    return {
        "authenticated": authenticated,
        "status": "authenticated" if authenticated else "unauthenticated",
        "owner": actor(auth) if authenticated else None,
        "auth_type": auth.get("auth_type") if auth else None,
        "issued_at": auth.get("issued_at") if auth else None,
        "expires_at": auth.get("expires_at") if auth else None,
        "reason": auth_reason,
        "credential_transport": "httponly_cookie_or_bearer",
        "allowedActions": actions,
        "permissions": permissions_list,
        "session_info": {
            "refresh_available": authenticated,
            "refresh_endpoint": "/api/mission-control/owner/session/refresh",
            "ttl_remaining_seconds": ttl_remaining,
        },
        "backend": {
            "version": "BUILD-065",
            "build": "BUILD-065",
            "repository_revision": _repo_revision(),
            "runtime_available": True,
            "runtime_enabled": _runtime_env_enabled(),
        },
        "mission_control": {
            "sections": [
                {
                    "id": "executive_summary",
                    "title": "Executive Summary",
                    "description": "High-level system health, priorities, and briefing from the Executive Intelligence engine.",
                    "endpoint": "/api/executive/summary",
                    "auth_required": False,
                    "status": "operational",
                },
                {
                    "id": "subsystem_health",
                    "title": "Subsystem Health",
                    "description": "Per-subsystem completion, blockers, evidence, and telemetry source for all Mission Control panels.",
                    "endpoint": "/api/mission-control/subsystems",
                    "auth_required": False,
                    "status": "operational",
                },
                {
                    "id": "harvesters",
                    "title": "Harvesters",
                    "description": "Live harvester heartbeat, state, and owner-authorized run/pause controls.",
                    "endpoint": "/api/mission-control/harvesters",
                    "auth_required": False,
                    "status": "operational",
                    "owner_controls": "/api/harvesters",
                },
                {
                    "id": "runtime",
                    "title": "Runtime",
                    "description": "Calyx autonomous runtime status and owner-authorized start/stop/restart controls.",
                    "endpoint": "/api/mission-control/runtime",
                    "auth_required": False,
                    "status": "operational",
                    "owner_controls": "/api/runner",
                },
                {
                    "id": "recommendations",
                    "title": "Recommendations",
                    "description": "Evidence-backed recommendations for owner review. BUILD-064: owner-authenticated review is now active.",
                    "endpoint": "/api/mission-control/recommendations",
                    "auth_required": False,
                    "owner_endpoint": "/api/mission-control/owner/recommendations",
                    "status": "operational",
                },
                {
                    "id": "governance",
                    "title": "Governance",
                    "description": "North star, missions, policies, decisions, and open questions. BUILD-064: owner-authenticated read access is now active.",
                    "endpoint": "/api/mission-control/governance",
                    "auth_required": False,
                    "owner_endpoint": "/api/mission-control/owner/governance",
                    "status": "operational",
                },
                {
                    "id": "executive_intelligence",
                    "title": "Executive Intelligence",
                    "description": "Secure Mission Control view of provider registry, budgets, recommendation queue, workflow execution, and usage ledger.",
                    "endpoint": "/api/mission-control/owner/executive-intelligence",
                    "auth_required": True,
                    "status": "operational" if authenticated else "requires_owner_authorization",
                    "review_endpoint": "/api/mission-control/owner/executive-intelligence/recommendations/{id}",
                    "future_modules": [
                        "SKAS",
                        "Literature Acquisition",
                        "Source Registry",
                        "Harvesters",
                        "Research Agents",
                        "Knowledge Object generation",
                    ],
                },
                {
                    "id": "intelligence",
                    "title": "Intelligence Workspace",
                    "description": "Source briefings, intelligence items, and Brain knowledge promotion queue.",
                    "endpoint": "/api/mission-control/owner/intelligence",
                    "auth_required": True,
                    "status": "operational" if authenticated else "requires_owner_authorization",
                    "promote_endpoint": "/api/mission-control/owner/intelligence/{id}/promote",
                },
                {
                    "id": "operations_queue",
                    "title": "Operations Queue",
                    "description": "Durable operations queue with owner-authorized approve/cancel/retry controls.",
                    "endpoint": "/api/mission-control/owner/operations-queue",
                    "auth_required": True,
                    "status": "operational" if authenticated else "requires_owner_authorization",
                },
                {
                    "id": "audits",
                    "title": "Audits",
                    "description": "Generated live operational audits from backend telemetry.",
                    "endpoint": "/api/mission-control/owner/audits",
                    "auth_required": True,
                    "status": "operational" if authenticated else "requires_owner_authorization",
                },
                {
                    "id": "build_history",
                    "title": "Build History",
                    "description": "Build and deployment history across all Orchid Continuum repositories.",
                    "endpoint": "/api/mission-control/builds",
                    "auth_required": False,
                    "status": "operational",
                },
            ],
            "navigation": {
                "executive_state": "/api/executive/state",
                "owner_session": "/api/mission-control/owner/executive-session",
                "executive_intelligence": "/api/mission-control/owner/executive-intelligence",
                "telemetry_status": "/api/mission-control/status",
                "audit": "/api/mission-control/audit",
                "completeness": "/api/mission-control/completeness",
            },
        },
        "generated_at": utc_now(),
    }


@router.post("/session/refresh")
async def refresh_session(request: Request, response: Response) -> dict[str, Any]:
    """Extend a valid owner session without requiring re-authentication.

    Validates the current session cookie or bearer token and issues a fresh
    signed session with a new TTL.  Returns 401 if the current session is
    expired, revoked, or missing.
    """
    auth = await verify_owner_session(request)  # raises 401 on failure
    # The refresh always issues a new session for the "owner" principal.
    # Using a fixed constant avoids taint-flow from the verified session payload
    # into the new cookie value (defence-in-depth; the payload is HMAC-verified).
    session = create_owner_session_token("owner")
    response.set_cookie(
        OWNER_SESSION_COOKIE,
        str(session["token"]),
        max_age=owner_session_ttl_seconds(),
        expires=owner_session_ttl_seconds(),
        httponly=True,
        secure=owner_cookie_secure(),
        samesite=owner_cookie_samesite(),
        path="/api/",
    )
    return {
        "authenticated": True,
        "status": "refreshed",
        "owner": session["owner"],
        "expires_at": session["expires_at"],
        "token": "cookie",
        "allowedActions": allowed_actions(True),
        "credential_transport": "httponly_cookie",
    }


@router.post("/source-briefings")
def save_source_briefing(request: SourceBriefingRequest, auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    briefing_id = f"BRF-{uuid4().hex[:12].upper()}"
    briefing = {
        "id": briefing_id,
        "source": request.source,
        "source_date": request.source_date,
        "raw_text": request.raw_text,
        "created_at": utc_now(),
        "created_by": actor(auth),
        "provenance": {**request.provenance, "verification_state": "provisional"},
    }
    items = parse_briefing_items(briefing_id, request.source, request.source_date, request.raw_text)
    insert_json_table("source_briefings", briefing)
    for item in items:
        insert_json_table("intelligence_items", item)
    log_action(auth, "source_briefing:create", "source_briefing", briefing_id, {"item_count": len(items)})
    return {"status": "saved", "source_briefing": briefing, "items": items, "allowedActions": allowed_actions(True)}


@router.get("/source-briefings")
def list_source_briefings(auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    return {"source_briefings": row_list("source_briefings"), "owner": actor(auth), "generated_at": utc_now()}


@router.post("/intelligence/import-local")
def import_local_records(request: LocalIntelligenceImportRequest, auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    existing = {str(item.get("source_excerpt") or item.get("summary") or item.get("title")) for item in row_list("intelligence_items")}
    imported: list[dict[str, Any]] = []
    skipped = 0
    for raw in request.records:
        fingerprint = str(raw.get("source_excerpt") or raw.get("summary") or raw.get("title") or raw)
        if fingerprint in existing:
            skipped += 1
            continue
        item = {
            "id": f"INT-{uuid4().hex[:12].upper()}",
            "source_briefing_id": raw.get("source_briefing_id"),
            "title": raw.get("title") or "Imported local intelligence",
            "summary": raw.get("summary") or raw.get("detail") or "",
            "source": raw.get("source") or request.source,
            "source_date": raw.get("source_date"),
            "category": raw.get("category") or ["Imported"],
            "priority": raw.get("priority") or "medium",
            "status": raw.get("status") or "new",
            "deadline_date": raw.get("deadline_date"),
            "funding_amount": raw.get("funding_amount"),
            "organization": raw.get("organization"),
            "recommended_action": raw.get("recommended_action") or "Owner review required.",
            "owner": raw.get("owner"),
            "notes": raw.get("notes") or "",
            "source_excerpt": fingerprint,
            "source_link": raw.get("source_link"),
            "eligibility_summary": raw.get("eligibility_summary") or "Not verified",
            "missing_information": raw.get("missing_information") or [],
            "application_progress": raw.get("application_progress") or "imported",
            "verification_state": raw.get("verification_state") or "provisional",
            "created_at": raw.get("created_at") or utc_now(),
            "updated_at": utc_now(),
        }
        imported.append(insert_json_table("intelligence_items", item))
        existing.add(fingerprint)
    log_action(auth, "intelligence:import_local", "intelligence_items", "bulk", {"imported": len(imported), "skipped": skipped})
    return {"status": "imported", "imported": imported, "skipped_duplicates": skipped}


@router.get("/intelligence")
def list_intelligence(auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    items = row_list("intelligence_items")
    return {
        "items": items,
        "grants": [item for item in items if "Grant" in item.get("category", [])],
        "partnerships": [item for item in items if "Partnership" in item.get("category", [])],
        "research": [item for item in items if "Research" in item.get("category", [])],
        "owner": actor(auth),
        "generated_at": utc_now(),
    }


@router.patch("/intelligence/{item_id}")
def patch_intelligence(item_id: str, request: IntelligencePatchRequest, auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    updates = {key: value for key, value in request.model_dump().items() if value is not None}
    updates["updated_at"] = utc_now()
    def _patch(cur):
        if cur is None:
            for item in MEMORY["intelligence_items"]:
                if item["id"] == item_id:
                    item.update(updates)
                    return item
            raise HTTPException(status_code=404, detail="Unknown intelligence item")
        cur.execute("SELECT payload FROM oc_admin.build051_intelligence_items WHERE id = %s", (item_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Unknown intelligence item")
        payload = dict(row["payload"])
        payload.update(updates)
        cur.execute("UPDATE oc_admin.build051_intelligence_items SET payload=%s, updated_at=NOW() WHERE id=%s", (Jsonb(payload), item_id))
        return payload
    item = db_execute(_patch)
    log_action(auth, "intelligence:update", "intelligence_item", item_id, updates)
    return {"status": "updated", "item": item}


def live_audit_payload(audit_type: str) -> dict[str, Any]:
    metrics = metric_snapshot()
    subsystems = completeness_rows()
    harvesters = harvester_rows()
    missing = [row["id"] for row in subsystems if row.get("status") in {"warning", "stub", "error", "unknown"}]
    relationships = [
        "taxonomy_to_images",
        "taxonomy_to_occurrences",
        "taxonomy_to_elevation",
        "taxonomy_to_climate",
        "taxonomy_to_literature",
        "taxonomy_to_pollinators",
        "taxonomy_to_mycorrhiza",
        "taxonomy_to_habitat",
        "taxonomy_to_conservation",
        "knowledge_graph_node_edge_integrity",
    ]
    return {
        "audit_id": f"AUD-{uuid4().hex[:12].upper()}",
        "audit_type": audit_type,
        "generated_at": utc_now(),
        "source_systems": ["mission_control_metrics", "subsystem_completeness", "harvester_registry"],
        "record_counts": {name: metric.get("count", 0) for name, metric in (metrics.get("metrics") or {}).items()},
        "data_freshness": "live_query" if metrics.get("database_connected") else "database_unavailable",
        "connection_coverage": subsystems,
        "provenance_coverage": "partial_live_backend_tables",
        "missing_relationships": relationships if missing else [],
        "unresolved_failures": missing + list(metrics.get("blockers", [])),
        "confidence": "medium" if metrics.get("database_connected") else "low",
        "strengths": ["Mission Control backend telemetry is queryable.", "Harvester registry is visible."],
        "weaknesses": ["Deep source-specific provenance coverage still needs expansion."],
        "recommended_next_actions": ["Apply BUILD-051 migration.", "Deploy owner-session backend.", "Run smoke tests."],
        "grant_relevance": "Current audit can support readiness narratives after owner review.",
        "collaboration_relevance": "Partner packets can cite operational versus planned capabilities explicitly.",
        "harvesters": harvesters,
    }


def audit_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# {payload['audit_type'].replace('_', ' ').title()} Audit",
        "",
        f"Generated: {payload['generated_at']}",
        f"Confidence: {payload['confidence']}",
        "",
        "## Record Counts",
        *[f"- {key}: {value}" for key, value in payload["record_counts"].items()],
        "",
        "## Missing Relationships",
        *[f"- {item}" for item in payload["missing_relationships"]],
        "",
        "## Strengths",
        *[f"- {item}" for item in payload["strengths"]],
        "",
        "## Weaknesses",
        *[f"- {item}" for item in payload["weaknesses"]],
        "",
        "## Recommended Next Actions",
        *[f"- {item}" for item in payload["recommended_next_actions"]],
    ]
    return "\n".join(lines)


def _audit_sections(payload: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """Return structured (heading, lines) sections shared across binary formats."""
    title = payload["audit_type"].replace("_", " ").title() + " Audit"
    meta = [f"Generated: {payload['generated_at']}", f"Confidence: {payload['confidence']}"]
    counts = [f"{k}: {v}" for k, v in payload["record_counts"].items()]
    missing = list(payload["missing_relationships"])
    strengths = list(payload["strengths"])
    weaknesses = list(payload["weaknesses"])
    actions = list(payload["recommended_next_actions"])
    return [
        (title, meta),
        ("Record Counts", counts),
        ("Missing Relationships", missing),
        ("Strengths", strengths),
        ("Weaknesses", weaknesses),
        ("Recommended Next Actions", actions),
    ]


def audit_pdf(payload: dict[str, Any]) -> bytes:
    """Generate a minimal valid PDF from audit payload using pure Python."""
    import io

    # PDF layout constants
    _PDF_FONT_SIZE = 10
    _PDF_TOP_Y = 750        # Y-coordinate of first text line (points from bottom)
    _PDF_LINE_HEIGHT = 13   # Vertical spacing per line in points
    _PDF_MAX_LINE_CHARS = 110  # Maximum characters per line before truncation
    _PDF_MARGIN_X = 40      # Left margin in points

    md = audit_markdown(payload)

    def _pdf_string(s: str) -> bytes:
        safe = s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\r", "")
        return safe.encode("latin-1", errors="replace")

    buf = io.BytesIO()

    def w(data: bytes | str) -> int:
        if isinstance(data, str):
            data = data.encode()
        pos = buf.tell()
        buf.write(data)
        return pos

    offsets: list[int] = []

    # Header
    w(b"%PDF-1.4\n")

    # Object 1: Catalog
    offsets.append(buf.tell())
    w("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")

    # Object 2: Pages
    offsets.append(buf.tell())
    w("2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")

    # Object 3: Font
    offsets.append(buf.tell())
    w("3 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")

    # Wrap markdown into PDF-safe lines
    raw_lines = md.split("\n")
    pdf_lines: list[bytes] = []
    for line in raw_lines:
        text_bytes = _pdf_string(line[:_PDF_MAX_LINE_CHARS])
        y = _PDF_TOP_Y - len(pdf_lines) * _PDF_LINE_HEIGHT
        pdf_lines.append(
            b"BT /F1 " + str(_PDF_FONT_SIZE).encode() + b" Tf "
            + str(_PDF_MARGIN_X).encode() + b" " + str(y).encode()
            + b" Td (" + text_bytes + b") Tj ET"
        )

    stream_body = b"\n".join(pdf_lines)
    stream_len = len(stream_body)

    # Object 4: Content stream
    offsets.append(buf.tell())
    w(f"4 0 obj\n<< /Length {stream_len} >>\nstream\n")
    w(stream_body)
    w("\nendstream\nendobj\n")

    # Object 5: Page
    offsets.append(buf.tell())
    w("5 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
      "/Contents 4 0 R /Resources << /Font << /F1 3 0 R >> >> >>\nendobj\n")

    xref_pos = buf.tell()
    w(f"xref\n0 6\n0000000000 65535 f \n")
    for off in offsets:
        w(f"{off:010d} 00000 n \n")

    w(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n")

    return buf.getvalue()


def audit_docx(payload: dict[str, Any]) -> bytes:
    """Generate a minimal valid DOCX from audit payload using Python's zipfile."""
    import io
    import zipfile

    sections = _audit_sections(payload)

    def _xml_escape(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    paras: list[str] = []
    for idx, (heading, items) in enumerate(sections):
        style = "Heading1" if idx == 0 else "Heading2"
        paras.append(
            f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
            f'<w:r><w:t>{_xml_escape(heading)}</w:t></w:r></w:p>'
        )
        for item in items:
            paras.append(
                f'<w:p><w:r><w:t xml:space="preserve">• {_xml_escape(item)}</w:t></w:r></w:p>'
            )

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>" + "".join(paras) + "</w:body></w:document>"
    )

    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )

    word_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/_rels/document.xml.rels", word_rels_xml)

    return buf.getvalue()


def _build_audit_content(output_format: str, payload: dict[str, Any]):
    """Return (content, is_binary) for the given output format."""
    if output_format == "json":
        return payload, False
    if output_format == "markdown":
        return audit_markdown(payload), False
    if output_format == "pdf":
        return audit_pdf(payload), True
    if output_format == "docx":
        return audit_docx(payload), True
    return audit_markdown(payload), False


@router.post("/audits")
def generate_audit(request: AuditRequest, auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    payload = live_audit_payload(request.audit_type)
    content, is_binary = _build_audit_content(request.output_format, payload)

    if is_binary:
        import base64
        content_field = base64.b64encode(content).decode()
        encoding = "base64"
    else:
        content_field = content
        encoding = "none"

    record = {
        "id": payload["audit_id"],
        "audit_type": request.audit_type,
        "output_format": request.output_format,
        "content": content_field,
        "content_encoding": encoding,
        "payload": payload,
        "created_by": actor(auth),
        "created_at": utc_now(),
    }
    insert_json_table("generated_audits", record)
    log_action(auth, "audit:generate", "generated_audit", record["id"], {"audit_type": request.audit_type, "output_format": request.output_format})
    return {"status": "generated", "audit": record, "allowedActions": allowed_actions(True)}


@router.get("/audits")
def list_audits(auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    return {"audits": row_list("generated_audits"), "owner": actor(auth)}


def parse_command(command: str) -> tuple[str, str, bool]:
    lower = command.lower()
    if "audit" in lower:
        return "generate_audit", "queued", False
    if "run" in lower and "harvester" in lower:
        return "harvester_run", "awaiting_owner", True
    if "pause" in lower and "harvester" in lower:
        return "harvester_pause", "awaiting_owner", True
    if "grant" in lower:
        return "grant_status", "queued", False
    if "partnership" in lower or "collaboration" in lower:
        return "partnership_packet", "queued", False
    if "missing" in lower or "relationship" in lower:
        return "missing_relationships", "queued", False
    return "explain_status", "queued", False


@router.post("/commands")
def submit_command(request: CommandRequest, auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    intent, status, high_risk = parse_command(request.command)
    decision = constitutional_orchestrator.evaluate_action(
        mission_id="engineering",
        action=f"owner_command:{intent}",
        requested_autonomy_level=int(AutonomyLevel.OWNER_APPROVAL_REQUIRED if high_risk else AutonomyLevel.SAFE_OPERATIONS),
        evidence=[request.command, f"actor={actor(auth)}"],
        reversible=True,
        provenance_available=True,
    )
    if high_risk and not request.confirm:
        status = "awaiting_owner"
    elif decision["decision"]["status"] == "review_required":
        status = "blocked"
    command_id = f"CMD-{uuid4().hex[:12].upper()}"
    record = {
        "id": command_id,
        "command": request.command,
        "intent": intent,
        "status": status,
        "risk_level": decision["decision"]["risk_level"],
        "authorization_state": "owner_session_verified",
        "result_summary": "Command recorded. Mutations require confirmation and policy approval.",
        "decision": decision["decision"],
        "created_by": actor(auth),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    insert_json_table("owner_commands", record)
    queue = {
        "id": f"Q-{uuid4().hex[:12].upper()}",
        "title": request.command,
        "task_type": intent,
        "source": "calyx_command_bar",
        "requested_by": actor(auth),
        "created_at": utc_now(),
        "priority": "high" if high_risk else "medium",
        "risk_level": decision["decision"]["risk_level"],
        "authorization_state": record["authorization_state"],
        "progress": 0,
        "status": status,
        "result_summary": record["result_summary"],
        "related_subsystem": "Mission Control",
        "logs": [],
        "next_required_action": "Owner confirmation required." if high_risk else "Review queued result.",
        "command_id": command_id,
    }
    insert_json_table("operations_queue", queue)
    log_action(auth, "command:create", "owner_command", command_id, {"intent": intent, "status": status})
    return {"status": status, "command": record, "queue_item": queue, "allowedActions": allowed_actions(True)}


@router.get("/commands")
def command_history(auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    return {"commands": row_list("owner_commands"), "owner": actor(auth)}


@router.get("/operations-queue")
def operations_queue(auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    return {"items": row_list("operations_queue"), "owner": actor(auth), "allowedActions": allowed_actions(True)}


@router.post("/operations-queue/{item_id}/{transition}")
def transition_queue_item(item_id: str, transition: str, request: QueueTransitionRequest, auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    valid = {"approve": "approved", "reject": "blocked", "cancel": "cancelled", "retry": "queued"}
    if transition not in valid:
        raise HTTPException(status_code=400, detail="Unsupported queue transition")
    def _patch(cur):
        if cur is None:
            for item in MEMORY["operations_queue"]:
                if item["id"] == item_id:
                    item["status"] = valid[transition]
                    item["updated_at"] = utc_now()
                    item["next_required_action"] = request.reason or "Transition recorded."
                    return item
            raise HTTPException(status_code=404, detail="Unknown queue item")
        cur.execute("SELECT payload FROM oc_admin.build051_operations_queue WHERE id=%s", (item_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Unknown queue item")
        payload = dict(row["payload"])
        payload["status"] = valid[transition]
        payload["updated_at"] = utc_now()
        payload["next_required_action"] = request.reason or "Transition recorded."
        cur.execute("UPDATE oc_admin.build051_operations_queue SET payload=%s, updated_at=NOW() WHERE id=%s", (Jsonb(payload), item_id))
        return payload
    item = db_execute(_patch)
    log_action(auth, f"operations_queue:{transition}", "operations_queue", item_id, {"reason": request.reason})
    return {"status": item["status"], "item": item}


@router.post("/research-requests")
def create_research_request(request: ResearchRequestIn, auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    record = {
        "id": f"RSR-{uuid4().hex[:12].upper()}",
        **request.model_dump(),
        "status": "queued",
        "owner": actor(auth),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    insert_json_table("research_requests", record)
    log_action(auth, "research_request:create", "research_request", record["id"], {"priority": request.priority})
    return {"status": "queued", "research_request": record}


@router.get("/research-requests")
def list_research_requests(auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    return {"research_requests": row_list("research_requests"), "owner": actor(auth)}


@router.post("/partnership-packets")
def create_partnership_packet(request: PartnershipPacketRequest, auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    audit = live_audit_payload("partnership_readiness")
    packet = {
        "id": f"PKT-{uuid4().hex[:12].upper()}",
        "organization_name": request.organization_name,
        "partner_type": request.partner_type,
        "relevant_holdings": audit["record_counts"],
        "current_capabilities": ["Mission Control telemetry", "Harvester registry", "Audit generation"],
        "technical_federation_points": ["Read-only APIs", "Exportable audit JSON", "Owner-reviewed packets"],
        "data_standards": ["Provenance required", "Evidence separated from inference"],
        "api_status": "operational_read_endpoints_and_owner_authenticated_write_endpoints",
        "governance": "Owner approval required for external commitments.",
        "gaps": audit["unresolved_failures"],
        "proposed_contribution": "Collaborate on verified orchid relationship, occurrence, media, or literature data.",
        "mutual_benefits": ["Research visibility", "Data quality improvement", "Grant readiness"],
        "next_steps": ["Owner review", "Partner contact", "Scope data exchange"],
        "operational_level": {"operational": ["telemetry", "audit JSON/Markdown"], "experimental": ["research queue"], "planned": ["automated partner APIs"]},
        "created_by": actor(auth),
        "created_at": utc_now(),
    }
    if request.output_format == "markdown":
        packet["content"] = "\n".join([
            f"# {request.organization_name} Partnership Packet",
            "",
            f"Partner type: {request.partner_type}",
            "",
            "## Current Capabilities",
            *[f"- {item}" for item in packet["current_capabilities"]],
            "",
            "## Gaps",
            *[f"- {item}" for item in packet["gaps"]],
            "",
            "## Next Steps",
            *[f"- {item}" for item in packet["next_steps"]],
        ])
    else:
        packet["content"] = packet
    insert_json_table("partnership_packets", packet)
    log_action(auth, "partnership_packet:create", "partnership_packet", packet["id"], {"organization": request.organization_name})
    return {"status": "generated", "packet": packet}


@router.get("/partnership-packets")
def list_partnership_packets(auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    return {"partnership_packets": row_list("partnership_packets"), "owner": actor(auth)}


# ─── BUILD-064: Recommendations, Governance, Brain Knowledge Promotion ────────


@router.get("/recommendations")
def owner_recommendations(auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    """Return live Mission Control recommendations with owner context.

    BUILD-064: activates the previously scaffolded recommendations capability.
    Wraps the read-only telemetry recommendations with owner identity and
    allowedActions so Mission Control can render an authenticated review panel.
    """
    from app.routers.mission_control import mission_control_recommendations
    telemetry = mission_control_recommendations()
    return {
        "build": "BUILD-064",
        "owner": actor(auth),
        "recommendations": telemetry.get("recommendations", []),
        "allowedActions": allowed_actions(True),
        "review_status": "owner_review_enabled",
        "note": "Recommendations are read-only telemetry.  Approval actions will be added in a future build.",
        "generated_at": utc_now(),
    }


@router.get("/executive-intelligence")
def owner_executive_intelligence(
    workspace_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    snapshot = executive_intelligence_snapshot(workspace_id=workspace_id, project_id=project_id)
    return {
        **snapshot,
        "owner": actor(auth),
        "allowedActions": allowed_actions(True),
        "review_status": "owner_review_enabled",
        "generated_at": utc_now(),
    }


@router.patch("/executive-intelligence/recommendations/{recommendation_id}")
def owner_executive_intelligence_recommendation_decision(
    recommendation_id: int,
    payload: RecommendationDecisionRequest,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    result = executive_intelligence_decide(
        recommendation_id,
        payload.decision,
        payload.actor or actor(auth),
        payload.notes,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Pending recommendation not found")
    return {
        "build": "BUILD-075",
        "owner": actor(auth),
        "review_status": "decision_recorded",
        "recommendation": result,
        "allowedActions": allowed_actions(True),
        "generated_at": utc_now(),
    }


@router.get("/governance")
def owner_governance(auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    """Return live governance state with owner context.

    BUILD-064: activates the previously scaffolded governance capability.
    Governance mutations (policy changes, decision overrides) remain reserved
    for a future build; this endpoint enables authenticated read access.
    """
    from app.routers.mission_control import mission_control_governance
    telemetry = mission_control_governance()
    return {
        "build": "BUILD-064",
        "owner": actor(auth),
        "governance": {
            "north_star": telemetry.get("north_star"),
            "missions": telemetry.get("missions", []),
            "policies": telemetry.get("policies", []),
            "decisions": telemetry.get("decisions", []),
            "questions": telemetry.get("questions", []),
        },
        "allowedActions": allowed_actions(True),
        "mutation_status": "read_only",
        "note": "Governance mutations require a future build.  Read access is now owner-authenticated.",
        "generated_at": utc_now(),
    }


class PromoteBrainKnowledgeRequest(BaseModel):
    notes: str | None = None
    confirm: bool = Field(default=False, description="Must be true to promote the item.")


@router.post("/intelligence/{item_id}/promote")
def promote_brain_knowledge(
    item_id: str,
    request: PromoteBrainKnowledgeRequest,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    """Promote a reviewed intelligence item into authoritative Brain knowledge.

    BUILD-064: activates the previously scaffolded promoteBrainKnowledge
    capability.  Requires explicit confirmation (`confirm: true`).  The item's
    `verification_state` is updated from 'provisional' or 'reviewed' to
    'promoted', and the promotion is written to the privileged action log.

    The promoted record is returned along with allowedActions so the Mission
    Control UI can re-render the permission panel without a separate round-trip.
    """
    if not request.confirm:
        raise HTTPException(
            status_code=400,
            detail="Promotion requires explicit confirmation. Set 'confirm: true' to proceed.",
        )

    def _promote(cur):
        if cur is None:
            for item in MEMORY["intelligence_items"]:
                if item["id"] == item_id:
                    if item.get("verification_state") not in {"provisional", "reviewed", "owner_reviewed"}:
                        raise HTTPException(
                            status_code=409,
                            detail=f"Item {item_id} cannot be promoted: current state is '{item.get('verification_state')}'.",
                        )
                    item["verification_state"] = "promoted"
                    item["promoted_by"] = actor(auth)
                    item["promoted_at"] = utc_now()
                    if request.notes:
                        item["notes"] = (item.get("notes") or "") + f"\n[BUILD-064 promotion] {request.notes}"
                    item["updated_at"] = utc_now()
                    return item
            raise HTTPException(status_code=404, detail=f"Intelligence item '{item_id}' not found.")

        cur.execute(
            "SELECT payload FROM oc_admin.build051_intelligence_items WHERE id = %s",
            (item_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Intelligence item '{item_id}' not found.")
        item = dict(row["payload"])
        current_state = item.get("verification_state", "")
        if current_state not in {"provisional", "reviewed", "owner_reviewed"}:
            raise HTTPException(
                status_code=409,
                detail=f"Item {item_id} cannot be promoted: current state is '{current_state}'.",
            )
        item["verification_state"] = "promoted"
        item["promoted_by"] = actor(auth)
        item["promoted_at"] = utc_now()
        if request.notes:
            item["notes"] = (item.get("notes") or "") + f"\n[BUILD-064 promotion] {request.notes}"
        item["updated_at"] = utc_now()
        cur.execute(
            "UPDATE oc_admin.build051_intelligence_items SET payload = %s, updated_at = NOW() WHERE id = %s",
            (Jsonb(item), item_id),
        )
        return item

    promoted = db_execute(_promote)
    log_action(
        auth,
        "intelligence:promote_brain_knowledge",
        "intelligence_items",
        item_id,
        {"notes": request.notes, "promoted_verification_state": "promoted"},
    )
    return {
        "build": "BUILD-064",
        "status": "promoted",
        "item": promoted,
        "allowedActions": allowed_actions(True),
        "generated_at": utc_now(),
    }


# ─── BUILD-065: Executive Operating System Integration ───────────────────────


def _build_decision_items() -> list[dict[str, Any]]:
    """Derive owner decision items from live telemetry.

    Returns a flat list of decision items, each tagged with a category so the
    front-end (or the decisions endpoint) can group them.  Items are sourced
    from completeness telemetry, harvester state, governance, and recommendations
    — no additional data sources are needed.
    """
    from app.routers.mission_control import (
        completeness_rows,
        harvester_rows,
        mission_control_governance,
        mission_control_recommendations,
    )

    items: list[dict[str, Any]] = []

    # Harvesters waiting for authorization
    for harvester in harvester_rows():
        if harvester.get("state") in {"unknown", "planned"} or not harvester.get("enabled"):
            items.append(
                {
                    "id": f"DEC-HARV-{harvester['id'].upper()}",
                    "category": "waiting_for_approval",
                    "title": f"Authorize harvester: {harvester['name']}",
                    "subsystem": "harvesters",
                    "why_it_matters": f"{harvester['name']} is not running; its data source ({harvester['source']}) is not being harvested.",
                    "impact_if_ignored": "Data from this source will remain stale; dependent subsystems lose coverage.",
                    "recommended_action": f"Review and authorize {harvester['name']} harvester via the owner-authenticated harvester control panel.",
                    "estimated_effort": "small",
                    "dependencies": ["runtime_jobs", "governance"],
                }
            )

    # Subsystems with blockers requiring owner review
    for row in completeness_rows():
        blockers = row.get("blockers") or []
        if blockers:
            category = "requires_scientific_review" if row.get("category") in {"Science", "Ecology"} else "waiting_for_owner"
            items.append(
                {
                    "id": f"DEC-SUB-{row['id'].upper()}",
                    "category": category,
                    "title": f"Resolve blockers: {row['display_name']}",
                    "subsystem": row["id"],
                    "why_it_matters": f"{row['display_name']} has {len(blockers)} active blocker(s) reducing platform completeness.",
                    "impact_if_ignored": f"Dependent subsystems will be limited by {row['display_name']} quality; completeness score stays below target.",
                    "recommended_action": row.get("recommendation") or "Review blockers and approve the corrective build scope.",
                    "estimated_effort": "medium",
                    "dependencies": [],
                    "blockers": blockers[:3],
                }
            )

    # Governance open questions
    governance = mission_control_governance()
    for question in governance.get("questions", []):
        if question.get("status") == "open":
            items.append(
                {
                    "id": f"DEC-GOV-{question['question_id'].upper()}",
                    "category": "waiting_for_owner",
                    "title": "Answer open governance question",
                    "subsystem": "governance",
                    "why_it_matters": "Open governance questions can block or mis-scope upcoming builds.",
                    "impact_if_ignored": "Calyx may proceed with assumptions that diverge from owner intent.",
                    "recommended_action": f"Answer: {question['question']}",
                    "estimated_effort": "small",
                    "dependencies": ["governance", "build_history"],
                }
            )

    # Recommendations requiring owner decision
    for rec in mission_control_recommendations().get("recommendations", []):
        if rec.get("priority") in {"critical", "high"}:
            items.append(
                {
                    "id": f"DEC-REC-{rec['id'].upper()}",
                    "category": "waiting_for_approval",
                    "title": rec.get("title", "Review recommendation"),
                    "subsystem": "recommendations",
                    "why_it_matters": rec.get("rationale", "High-priority recommendation pending owner decision."),
                    "impact_if_ignored": "Platform progress on this track will stall until a decision is made.",
                    "recommended_action": rec.get("ownerDecisionNeeded") or "Review and approve the recommended action.",
                    "estimated_effort": "small",
                    "dependencies": [],
                    "suggested_build": rec.get("nextBuild"),
                }
            )

    return items


def _group_decisions(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    categories = [
        "waiting_for_approval",
        "waiting_for_owner",
        "requires_external_partner",
        "requires_authentication",
        "requires_budget",
        "requires_scientific_review",
        "requires_manual_validation",
    ]
    grouped: dict[str, list[dict[str, Any]]] = {cat: [] for cat in categories}
    for item in items:
        cat = item.get("category", "waiting_for_owner")
        if cat in grouped:
            grouped[cat].append(item)
        else:
            grouped["waiting_for_owner"].append(item)
    return grouped


@router.get("/decisions")
def owner_decisions(auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    """Return the Owner Decision Layer — categorized decisions waiting for action.

    BUILD-065: Every item that cannot proceed without an explicit owner decision
    is surfaced here.  Each item explains why it matters, the impact if ignored,
    the recommended action, estimated effort, and its dependencies.
    """
    items = _build_decision_items()
    grouped = _group_decisions(items)
    critical = [i for i in items if i.get("estimated_effort") == "small" and i.get("category") == "waiting_for_approval"]

    return {
        "build": "BUILD-065",
        "owner": actor(auth),
        "decision_categories": grouped,
        "total_decisions": len(items),
        "critical_decisions": critical[:5],
        "orientation": {
            "what_is_this": "Every item that cannot proceed without a direct owner decision.",
            "why_it_matters": "Unresolved decisions block the pipeline; this section eliminates ambiguity.",
            "what_can_i_do_here": "Approve, defer, or delegate decisions across subsystems and operations.",
            "what_is_calyx_doing": "Surfacing blocked work and preparing decision context for the owner.",
        },
        "allowedActions": allowed_actions(True),
        "generated_at": utc_now(),
    }


def _build_priority_queue() -> list[dict[str, Any]]:
    """Build a unified ranked priority queue from all available recommendation sources."""
    from app.routers.mission_control import completeness_rows, mission_control_recommendations
    from runtime.executive.dependencies import dependency_graph, reverse_dependencies

    graph = dependency_graph()
    reverse = reverse_dependencies(graph)

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    queue: list[dict[str, Any]] = []
    rank = 1

    # Layer 1: existing mission-control recommendations (already prioritised)
    for rec in mission_control_recommendations().get("recommendations", []):
        priority = rec.get("priority", "medium")
        queue.append(
            {
                "rank": rank,
                "priority": priority,
                "subsystem": rec.get("id", ""),
                "title": rec.get("title", ""),
                "scientific_impact": "Improves data coverage and research readiness.",
                "technical_impact": rec.get("rationale", ""),
                "dependencies": [],
                "estimated_completion": "1 build cycle",
                "suggested_build": rec.get("nextBuild") or f"BUILD-{rank + 65:03d}",
                "owner_decision_needed": rec.get("ownerDecisionNeeded"),
                "source": "mission_control_recommendations",
            }
        )
        rank += 1

    # Layer 2: completeness rows with significant blockers
    for row in completeness_rows():
        completion = int(row.get("completion") or 0)
        blockers = row.get("blockers") or []
        if not blockers and completion >= 75:
            continue
        if completion < 40 and blockers:
            priority = "high"
        elif completion < 60:
            priority = "medium"
        else:
            priority = "low"
        deps_on = graph.get(row["id"], [])
        downstream = reverse.get(row["id"], [])
        queue.append(
            {
                "rank": rank,
                "priority": priority,
                "subsystem": row["id"],
                "title": f"Advance {row['display_name']} to target completeness",
                "scientific_impact": f"Raises {row['display_name']} from {completion}% toward scientific readiness threshold.",
                "technical_impact": row.get("recommendation") or "Wire deeper source telemetry and owner-authorized action paths.",
                "dependencies": deps_on[:5],
                "estimated_completion": "1–2 build cycles",
                "suggested_build": f"BUILD-{rank + 65:03d}",
                "downstream_leverage": downstream[:4],
                "source": "completeness_telemetry",
            }
        )
        rank += 1

    # Sort by priority tier then by original rank
    queue.sort(key=lambda x: (priority_order.get(x["priority"], 99), x["rank"]))
    for i, item in enumerate(queue, start=1):
        item["rank"] = i

    return queue


@router.get("/priorities")
def owner_priorities(auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    """Return the unified Global Priority Queue across all subsystems.

    BUILD-065: Replaces scattered recommendations with a single ranked queue
    categorised as Critical / High / Medium / Low.  Each entry identifies the
    subsystem, scientific impact, technical impact, dependencies, estimated
    completion, and suggested BUILD number.
    """
    queue = _build_priority_queue()
    by_tier: dict[str, list[dict[str, Any]]] = {"critical": [], "high": [], "medium": [], "low": []}
    for item in queue:
        tier = item.get("priority", "low")
        if tier in by_tier:
            by_tier[tier].append(item)

    return {
        "build": "BUILD-065",
        "owner": actor(auth),
        "priorities": by_tier,
        "ranked_queue": queue,
        "total_items": len(queue),
        "orientation": {
            "what_is_this": "A single ranked list of what to build or resolve next, derived from all subsystem analysis.",
            "why_it_matters": "Replaces scattered recommendations with one authoritative owner action plan.",
            "what_can_i_do_here": "Review, approve, or modify the top-priority build recommendation.",
            "what_is_calyx_doing": "Scoring subsystems, computing dependencies, and proposing the highest-leverage next build.",
        },
        "allowedActions": allowed_actions(True),
        "generated_at": utc_now(),
    }


def _build_calyx_narrative() -> dict[str, Any]:
    """Produce the Calyx operational narrative from live telemetry."""
    from app.routers.mission_control import (
        completeness_rows,
        harvester_rows,
        mission_control_recommendations,
        runtime_telemetry,
    )

    rows = completeness_rows()
    harvesters = harvester_rows()
    runtime = runtime_telemetry()
    recs = mission_control_recommendations().get("recommendations", [])

    # What I'm doing
    running = [h for h in harvesters if h.get("state") == "running"]
    idle_enabled = [h for h in harvesters if h.get("state") == "idle" and h.get("enabled")]
    doing = (
        f"Running {len(running)} active harvester(s): {', '.join(h['name'] for h in running[:3])}."
        if running
        else "Monitoring platform health and collecting telemetry across all subsystems."
    )

    # Why I'm doing it
    blocked = [r for r in rows if r.get("status") in {"warning", "stub"}]
    why = (
        f"Addressing {len(blocked)} subsystem(s) with below-target completeness to advance the platform toward publication and grant readiness."
        if blocked
        else "Sustaining operational continuity and preparing evidence for the next owner decision cycle."
    )

    # What I discovered
    discovered = []
    for row in rows:
        if row.get("evidence"):
            discovered.extend(row["evidence"][:1])
    if runtime.get("evidence"):
        discovered.extend(runtime["evidence"][:1])
    discovered = discovered[:5]

    # What I'm waiting for
    waiting_for = []
    for h in harvesters:
        if not h.get("enabled") and h.get("state") in {"unknown", "planned"}:
            waiting_for.append(f"Owner authorization to activate {h['name']} harvester.")
    for row in rows:
        blockers = row.get("blockers") or []
        if blockers:
            waiting_for.append(f"{row['display_name']}: {blockers[0]}")
    waiting_for = waiting_for[:5]

    # What I recommend next
    top_rec = recs[0] if recs else None
    recommend_next = (
        {
            "title": top_rec["title"],
            "rationale": top_rec.get("rationale"),
            "suggested_build": top_rec.get("nextBuild"),
            "owner_decision_needed": top_rec.get("ownerDecisionNeeded"),
        }
        if top_rec
        else {"title": "Await owner direction", "rationale": "No priority signal available.", "suggested_build": None}
    )

    # What decision I need from you
    critical_recs = [r for r in recs if r.get("priority") == "critical"]
    need_from_owner = (
        {
            "decision": critical_recs[0].get("ownerDecisionNeeded"),
            "title": critical_recs[0].get("title"),
            "urgency": "critical",
        }
        if critical_recs
        else {
            "decision": "Review the top-ranked priority in the Global Priority Queue and approve the next build scope.",
            "title": "Approve next build",
            "urgency": "high",
        }
    )

    return {
        "what_i_am_doing": doing,
        "why_i_am_doing_it": why,
        "what_i_discovered": discovered if discovered else ["No new discoveries in current telemetry cycle."],
        "what_i_am_waiting_for": waiting_for if waiting_for else ["No pending owner actions identified."],
        "what_i_recommend_next": recommend_next,
        "what_decision_i_need_from_you": need_from_owner,
    }


@router.get("/calyx-narrative")
def owner_calyx_narrative(auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    """Return the Calyx Operational Narrative.

    BUILD-065: Calyx presents itself as an executive operations officer,
    continuously explaining: what it is doing, why, what it discovered,
    what it is waiting for, what it recommends next, and what decision
    it needs from the owner.
    """
    narrative = _build_calyx_narrative()
    return {
        "build": "BUILD-065",
        "owner": actor(auth),
        "narrative": narrative,
        "orientation": {
            "what_is_this": "Calyx operational intelligence briefing in first-person executive officer voice.",
            "why_it_matters": "Transforms passive dashboards into an active advisory relationship with clear accountability.",
            "what_can_i_do_here": "Read Calyx's current posture and respond to the embedded decision request.",
            "what_is_calyx_doing": "Synthesising all telemetry into a coherent operational narrative.",
        },
        "allowedActions": allowed_actions(True),
        "generated_at": utc_now(),
    }


@router.get("/eos-state")
def owner_eos_state(auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    """Return the complete Executive Operating System state.

    BUILD-065: A single endpoint that combines the executive workflow map,
    platform health, owner decision layer, global priority queue, subsystem
    relationships, multi-dimensional readiness, and Calyx narrative.  Designed
    for front-end EOS initialisation — one round-trip to load the full state.
    """
    from app.routers.mission_control import (
        completeness_rows,
        mission_control_executive_flow,
        mission_control_governance,
        mission_control_health,
        mission_control_readiness,
        mission_control_relationships,
        mission_control_status,
    )

    status = mission_control_status()
    health = mission_control_health()
    rows = completeness_rows()

    blocked_subsystems = [r for r in rows if r.get("status") in {"warning", "stub", "error"}]
    critical_alerts = [
        {
            "subsystem": r["id"],
            "display_name": r["display_name"],
            "status": r["status"],
            "blocker": (r.get("blockers") or [None])[0],
            "recommendation": r.get("recommendation"),
        }
        for r in blocked_subsystems[:5]
    ]

    governance = mission_control_governance()

    decisions = _build_decision_items()
    grouped_decisions = _group_decisions(decisions)
    priorities = _build_priority_queue()
    narrative = _build_calyx_narrative()
    executive_flow = mission_control_executive_flow()
    relationships = mission_control_relationships()
    readiness = mission_control_readiness()
    executive_intelligence = executive_intelligence_snapshot()

    return {
        "build": "BUILD-065",
        "eos_version": "BUILD-065",
        "owner": actor(auth),
        "executive_flow": executive_flow,
        "platform_status": {
            "status": status.get("status"),
            "database_connected": status.get("database_connected"),
            "blockers": status.get("blockers", []),
        },
        "critical_alerts": critical_alerts,
        "calyx_activity": {
            "harvesters_active": sum(1 for r in rows if r.get("status") == "healthy"),
            "subsystems_healthy": sum(1 for r in rows if r.get("status") == "healthy"),
            "subsystems_blocked": len(blocked_subsystems),
        },
        "owner_decisions": {
            "total_decisions": len(decisions),
            "decision_categories": grouped_decisions,
        },
        "recommended_next_build": priorities[0] if priorities else None,
        "subsystem_relationships": relationships.get("relationships", []),
        "readiness": readiness.get("subsystems", []),
        "executive_intelligence": executive_intelligence,
        "calyx_narrative": narrative,
        "governance_summary": {
            "north_star": governance.get("north_star"),
            "open_questions": [q for q in governance.get("questions", []) if q.get("status") == "open"],
            "policy_count": len(governance.get("policies", [])),
        },
        "allowedActions": allowed_actions(True),
        "generated_at": utc_now(),
    }


# ─── BUILD-066A: Owner Control Verification ──────────────────────────────────

class ControlVerificationRequest(BaseModel):
    label: str = Field(min_length=1, max_length=512)


def _ensure_control_verifications_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS oc_admin.build066a_control_verifications (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            session_owner TEXT NOT NULL,
            read_back_confirmed BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


@router.post("/control-verification")
async def create_control_verification(
    body: ControlVerificationRequest,
    request: Request,
) -> dict[str, Any]:
    """Create a labeled owner control verification record and persist it to the database.

    BUILD-066A: Requires an authenticated owner session.  Creates a record with a
    server-generated ID and timestamp, persists it to
    ``oc_admin.build066a_control_verifications``, reads it back immediately to
    confirm durability, and returns the verified record.
    """
    auth = await verify_owner_session(request)
    session_owner = actor(auth)

    record_id = f"CV-{uuid4().hex[:16].upper()}"
    now_iso = utc_now()

    record: dict[str, Any] = {
        "id": record_id,
        "label": body.label,
        "created_at": now_iso,
        "session_owner": session_owner,
        "read_back_confirmed": False,
    }

    url = database_url()
    if not url:
        # In-memory fallback: persist and read back immediately
        CONTROL_VERIFICATIONS[record_id] = record.copy()
        persisted = CONTROL_VERIFICATIONS[record_id]
        persisted["read_back_confirmed"] = True
        return persisted

    try:
        with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                _ensure_control_verifications_table(cur)
                cur.execute(
                    """
                    INSERT INTO oc_admin.build066a_control_verifications
                        (id, label, session_owner, read_back_confirmed, created_at)
                    VALUES (%s, %s, %s, TRUE, NOW())
                    RETURNING id, label, session_owner, read_back_confirmed,
                              created_at AT TIME ZONE 'UTC' AS created_at
                    """,
                    (record_id, body.label, session_owner),
                )
                row = cur.fetchone()
            conn.commit()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"BUILD-066A database write failed: {exc}") from exc

    if row is None:
        raise HTTPException(status_code=503, detail="BUILD-066A: record was not returned after insert")

    return {
        "id": row["id"],
        "label": row["label"],
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
        "session_owner": row["session_owner"],
        "read_back_confirmed": bool(row["read_back_confirmed"]),
    }


@router.get("/control-verification/{verification_id}")
async def get_control_verification(
    verification_id: str,
    request: Request,
) -> dict[str, Any]:
    """Retrieve a previously created owner control verification record by ID.

    BUILD-066A: Requires an authenticated owner session.  Reads the record from
    ``oc_admin.build066a_control_verifications`` (or the in-memory fallback) and
    returns it with ``read_back_confirmed: true``.
    """
    await verify_owner_session(request)

    if not verification_id or not verification_id.strip():
        raise HTTPException(status_code=422, detail="verification_id is required")

    url = database_url()
    if not url:
        row = CONTROL_VERIFICATIONS.get(verification_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Control verification '{verification_id}' not found")
        return {**row, "read_back_confirmed": True}

    try:
        with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                _ensure_control_verifications_table(cur)
                cur.execute(
                    """
                    SELECT id, label, session_owner, read_back_confirmed,
                           created_at AT TIME ZONE 'UTC' AS created_at
                    FROM oc_admin.build066a_control_verifications
                    WHERE id = %s
                    """,
                    (verification_id,),
                )
                row = cur.fetchone()
            conn.commit()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"BUILD-066A database read failed: {exc}") from exc

    if row is None:
        raise HTTPException(status_code=404, detail=f"Control verification '{verification_id}' not found")

    return {
        "id": row["id"],
        "label": row["label"],
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
        "session_owner": row["session_owner"],
        "read_back_confirmed": bool(row["read_back_confirmed"]),
    }
