"""BUILD-051 authenticated Owner Operations Console API.

These endpoints are the server-side control plane for Mission Control. Browser
unlock is intentionally separate: privileged writes require a signed owner
session or backend API key and are logged.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import verify_owner_access_code, verify_owner_or_api_key, verify_owner_session
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
    output_format: str = Field(default="markdown", pattern="^(json|markdown)$")


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
    def action(label: str, *, risk: str = "low", writes: bool = True, high_risk: bool = False) -> dict[str, Any]:
        return {
            "allowed": authenticated and not high_risk,
            "state": "owner_authorized_action" if authenticated and not high_risk else "requires_owner_authorization",
            "auth": "owner_session_or_api_key",
            "risk": risk,
            "writesDatabase": writes,
            "requiresConfirmation": high_risk,
            "reason": label,
        }

    return {
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
        "promoteBrainKnowledge": action("Promote reviewed intelligence into authoritative Brain knowledge.", risk="high", high_risk=True),
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
def create_session(request: OwnerLoginRequest) -> dict[str, Any]:
    session = verify_owner_access_code(request.access_code, request.owner)
    return {
        "status": "authenticated",
        **session,
        "allowedActions": allowed_actions(True),
        "secretDisclosure": "No API key or privileged backend secret is returned.",
    }


@router.get("/session")
def inspect_session(auth: dict[str, object] = Depends(verify_owner_session)) -> dict[str, Any]:
    return {"status": "authenticated", "owner": actor(auth), "allowedActions": allowed_actions(True)}


@router.get("/permissions")
def permissions(auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    return {"owner": actor(auth), "allowedActions": allowed_actions(True), "generated_at": utc_now()}


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


@router.post("/audits")
def generate_audit(request: AuditRequest, auth: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict[str, Any]:
    payload = live_audit_payload(request.audit_type)
    content = payload if request.output_format == "json" else audit_markdown(payload)
    record = {
        "id": payload["audit_id"],
        "audit_type": request.audit_type,
        "output_format": request.output_format,
        "content": content,
        "payload": payload,
        "created_by": actor(auth),
        "created_at": utc_now(),
    }
    insert_json_table("generated_audits", record)
    log_action(auth, "audit:generate", "generated_audit", record["id"], {"audit_type": request.audit_type})
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
