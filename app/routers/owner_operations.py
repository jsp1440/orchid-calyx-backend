"""BUILD-051 / BUILD-064 authenticated Owner Operations Console API.

These endpoints are the server-side control plane for Mission Control. Browser
unlock is intentionally separate: privileged writes require a signed owner
session or backend API key and are logged.

BUILD-064 additions:
- Persistent session revocation (DB-backed nonce table with in-memory fallback)
- Owner recommendations endpoint (GET /recommendations)
- Owner governance endpoint (GET /governance)
- Brain knowledge promotion endpoint (POST /intelligence/{item_id}/promote)
- Updated allowed_actions: recommendations and governance marked as implemented
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
    """Run a DB callback, silently absorbing errors (used for best-effort persistence)."""
    url = database_url()
    if not url:
        callback(None)
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
        if cur is None:
            return
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
            "version": "BUILD-064",
            "build": "BUILD-064",
            "repository_revision": _repo_revision(),
            "runtime_available": True,
            "runtime_enabled": _runtime_env_enabled(),
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
