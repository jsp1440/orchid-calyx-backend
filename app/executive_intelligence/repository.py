from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.intake.repository import database_url
from .engine import ProviderCandidate, build_recommendations, choose_provider, evaluate_budget


MISSION_CONTROL_BUILD = "BUILD-075"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_exists(cur, fq_table: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (fq_table,))
    row = cur.fetchone()
    return bool(row and row[0] is not None)


def _provider_status(provider: dict[str, Any]) -> str:
    if not provider.get("enabled"):
        return "disabled"
    if provider.get("healthy"):
        return "healthy"
    return "degraded"


def _provider_availability(provider: dict[str, Any]) -> str:
    return "available" if provider.get("enabled") and provider.get("healthy") else "unavailable"


def _executive_intelligence_layout() -> dict[str, Any]:
    return {
        "primary_module": "executive_intelligence",
        "current_sections": [
            "provider_registry",
            "budgets",
            "recommendation_queue",
            "execution_history",
            "workflow_logs",
            "usage_ledger",
        ],
        "future_modules": [
            {"id": "skas", "title": "SKAS", "status": "planned"},
            {"id": "literature_acquisition", "title": "Literature Acquisition", "status": "planned"},
            {"id": "source_registry", "title": "Source Registry", "status": "planned"},
            {"id": "harvesters", "title": "Harvesters", "status": "planned"},
            {"id": "research_agents", "title": "Research Agents", "status": "planned"},
            {"id": "knowledge_object_generation", "title": "Knowledge Object Generation", "status": "planned"},
        ],
        "extensibility": {
            "pattern": "module_cards",
            "description": "Each module occupies a stable card/section contract so future autonomous systems can be added without redesigning Mission Control.",
        },
    }


def executive_intelligence_snapshot(
    workspace_id: str | None = None,
    project_id: str | None = None,
    *,
    recommendation_limit: int = 25,
    history_limit: int = 25,
    usage_limit: int = 25,
) -> dict[str, Any]:
    try:
        url = database_url()
    except RuntimeError:
        url = None
    base = {
        "build": MISSION_CONTROL_BUILD,
        "section_id": "executive_intelligence",
        "title": "Executive Intelligence",
        "status": "operational",
        "mode": "read_only_except_approval_reject",
        "database_connected": True,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "mutation_policy": {
            "default_mode": "read_only",
            "allowed_actions": ["approve_recommendation", "reject_recommendation"],
            "blocked_actions": ["provider_mutation", "budget_mutation", "workflow_routing", "usage_mutation"],
        },
        "action_endpoints": {
            "review": "/api/mission-control/owner/executive-intelligence/recommendations/{recommendation_id}",
        },
        "layout": _executive_intelligence_layout(),
        "generated_at": utc_now(),
    }
    if not url:
        return {
            **base,
            "status": "database_unavailable",
            "database_connected": False,
            "blockers": ["DATABASE_URL is not configured for Executive Intelligence Mission Control telemetry."],
            "providers": {
                "summary": {"total": 0, "healthy": 0, "available": 0, "managed": 0},
                "items": [],
            },
            "budgets": {
                "summary": {"scopes": 0, "tracked_calls": 0, "tracked_spend_usd": 0.0},
                "items": [],
            },
            "recommendation_queue": {"summary": {"total": 0, "pending": 0, "approved": 0, "rejected": 0, "routed": 0}, "items": []},
            "execution_history": {"summary": {"total_actions": 0, "completed": 0, "pending": 0}, "items": []},
            "workflow_logs": {"summary": {"events": 0}, "items": []},
            "usage_ledger": {
                "summary": {"entries": 0, "providers": 0, "estimated_or_actual_spend_usd": 0.0},
                "by_provider": [],
                "recent_entries": [],
            },
        }

    try:
        with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                source_table_exists = _table_exists(cur, "oc_intake.sources")
                workflow_actions_exists = _table_exists(cur, "oc_workflow.actions")
                workflow_history_exists = _table_exists(cur, "oc_workflow.routing_history")
                providers: list[dict[str, Any]] = []
                if _table_exists(cur, "oc_ai.providers"):
                    cur.execute(
                        """
                        SELECT provider_key, display_name, capabilities, priority, cost_rank, managed, enabled, healthy,
                               configuration, created_at, updated_at
                        FROM oc_ai.providers
                        ORDER BY priority, cost_rank, provider_key
                        """,
                    )
                    for row in cur.fetchall():
                        item = dict(row)
                        item["status"] = _provider_status(item)
                        item["availability"] = _provider_availability(item)
                        item["capability_count"] = len(item.get("capabilities") or [])
                        item["updated_at"] = item["updated_at"].isoformat() if item.get("updated_at") else None
                        item["created_at"] = item["created_at"].isoformat() if item.get("created_at") else None
                        providers.append(item)

                usage_groups: dict[tuple[str, str | None], dict[str, Any]] = {}
                if _table_exists(cur, "oc_ai.usage_ledger"):
                    usage_filter = "WHERE (%s IS NULL OR workspace_id = %s) AND (%s IS NULL OR project_id = %s)"
                    cur.execute(
                        f"""
                        SELECT workspace_id,
                               project_id,
                               COUNT(*) AS calls,
                               COALESCE(SUM(COALESCE(actual_cost_usd, estimated_cost_usd)), 0) AS spent_usd,
                               MAX(occurred_at) AS last_occurred_at
                        FROM oc_ai.usage_ledger
                        {usage_filter}
                        GROUP BY workspace_id, project_id
                        ORDER BY workspace_id, project_id NULLS FIRST
                        """,
                        (workspace_id, workspace_id, project_id, project_id),
                    )
                    for row in cur.fetchall():
                        key = (row["workspace_id"], row["project_id"])
                        usage_groups[key] = {
                            "workspace_id": row["workspace_id"],
                            "project_id": row["project_id"],
                            "calls": int(row["calls"] or 0),
                            "spent_usd": float(row["spent_usd"] or 0),
                            "last_occurred_at": row["last_occurred_at"].isoformat() if row["last_occurred_at"] else None,
                        }

                budgets: list[dict[str, Any]] = []
                seen_budget_scopes: set[tuple[str, str | None]] = set()
                if _table_exists(cur, "oc_ai.budget_policies"):
                    budget_filter = "WHERE (%s IS NULL OR workspace_id = %s) AND (%s IS NULL OR project_id = %s)"
                    cur.execute(
                        f"""
                        SELECT workspace_id, project_id, provider_key, soft_limit_usd, hard_limit_usd, policy_mode,
                               period, enabled, updated_at
                        FROM oc_ai.budget_policies
                        {budget_filter}
                        ORDER BY workspace_id, project_id NULLS FIRST, provider_key NULLS FIRST
                        """,
                        (workspace_id, workspace_id, project_id, project_id),
                    )
                    for row in cur.fetchall():
                        item = dict(row)
                        scope_key = (item["workspace_id"], item["project_id"])
                        seen_budget_scopes.add(scope_key)
                        usage = usage_groups.get(scope_key, {"calls": 0, "spent_usd": 0.0, "last_occurred_at": None})
                        soft_limit = float(item["soft_limit_usd"]) if item["soft_limit_usd"] is not None else None
                        hard_limit = float(item["hard_limit_usd"]) if item["hard_limit_usd"] is not None else None
                        budget_state = evaluate_budget(
                            spent_usd=float(usage["spent_usd"]),
                            proposed_usd=0.0,
                            soft_limit_usd=soft_limit,
                            hard_limit_usd=hard_limit,
                            policy_mode=item["policy_mode"],
                        )
                        item.update(
                            {
                                "soft_limit_usd": soft_limit,
                                "hard_limit_usd": hard_limit,
                                "spent_usd": float(usage["spent_usd"]),
                                "calls": int(usage["calls"]),
                                "remaining_usd": None if hard_limit is None else max(0.0, hard_limit - float(usage["spent_usd"])),
                                "budget_status": budget_state["decision"],
                                "last_occurred_at": usage["last_occurred_at"],
                                "updated_at": item["updated_at"].isoformat() if item.get("updated_at") else None,
                            }
                        )
                        budgets.append(item)
                for scope_key, usage in usage_groups.items():
                    if scope_key in seen_budget_scopes:
                        continue
                    budgets.append(
                        {
                            "workspace_id": usage["workspace_id"],
                            "project_id": usage["project_id"],
                            "provider_key": None,
                            "soft_limit_usd": None,
                            "hard_limit_usd": None,
                            "policy_mode": "WARN",
                            "period": "MONTHLY",
                            "enabled": False,
                            "spent_usd": float(usage["spent_usd"]),
                            "calls": int(usage["calls"]),
                            "remaining_usd": None,
                            "budget_status": "ALLOW",
                            "last_occurred_at": usage["last_occurred_at"],
                            "updated_at": None,
                        }
                    )
                budgets.sort(key=lambda item: (str(item["workspace_id"]), str(item.get("project_id") or ""), str(item.get("provider_key") or "")))

                recommendations: list[dict[str, Any]] = []
                recommendation_summary = {"total": 0, "pending": 0, "approved": 0, "rejected": 0, "routed": 0}
                if _table_exists(cur, "oc_ai.recommendations"):
                    recommendation_filter = "WHERE (%s IS NULL OR r.workspace_id = %s) AND (%s IS NULL OR r.project_id = %s)"
                    source_join = "LEFT JOIN oc_intake.sources s ON s.id = r.source_id" if source_table_exists else ""
                    source_title_select = ", s.title AS source_title" if source_table_exists else ""
                    cur.execute(
                        f"""
                        SELECT r.*{source_title_select}
                        FROM oc_ai.recommendations r
                        {source_join}
                        {recommendation_filter}
                        ORDER BY CASE r.status
                                   WHEN 'PENDING' THEN 0
                                   WHEN 'APPROVED' THEN 1
                                   WHEN 'ROUTED' THEN 2
                                   WHEN 'REJECTED' THEN 3
                                   ELSE 4
                                 END,
                                 CASE r.priority
                                   WHEN 'CRITICAL' THEN 0
                                   WHEN 'HIGH' THEN 1
                                   WHEN 'MEDIUM' THEN 2
                                   ELSE 3
                                 END,
                                 r.created_at DESC
                        LIMIT %s
                        """,
                        (workspace_id, workspace_id, project_id, project_id, recommendation_limit),
                    )
                    recommendations = [dict(row) for row in cur.fetchall()]
                    cur.execute(
                        f"""
                        SELECT status, COUNT(*) AS count
                        FROM oc_ai.recommendations r
                        {recommendation_filter}
                        GROUP BY status
                        """,
                        (workspace_id, workspace_id, project_id, project_id),
                    )
                    for row in cur.fetchall():
                        status_key = str(row["status"] or "").lower()
                        if status_key in recommendation_summary:
                            recommendation_summary[status_key] = int(row["count"] or 0)
                        recommendation_summary["total"] += int(row["count"] or 0)
                for item in recommendations:
                    for key in ("created_at", "updated_at", "decided_at"):
                        item[key] = item[key].isoformat() if item.get(key) else None
                    item["review_actions"] = {
                        "approve": {"method": "PATCH", "decision": "APPROVE"},
                        "reject": {"method": "PATCH", "decision": "REJECT"},
                    }
                execution_history: list[dict[str, Any]] = []
                workflow_logs: list[dict[str, Any]] = []
                execution_summary = {"total_actions": 0, "completed": 0, "pending": 0}
                execution_summary = {"total_actions": 0, "completed": 0, "pending": 0}
                if workflow_actions_exists:
                    source_join = "LEFT JOIN oc_intake.sources s ON s.id = a.source_id" if source_table_exists else ""
                    source_title_select = ", s.title AS source_title" if source_table_exists else ""
                    cur.execute(
                        f"""
                        SELECT a.*{source_title_select}
                        FROM oc_workflow.actions a
                        {source_join}
                        ORDER BY COALESCE(a.updated_at, a.completed_at, a.created_at) DESC
                        LIMIT %s
                        """,
                        (history_limit,),
                    )
                    execution_history = [dict(row) for row in cur.fetchall()]
                    cur.execute(
                        """
                        SELECT status, COUNT(*) AS count
                        FROM oc_workflow.actions
                        GROUP BY status
                        """,
                    )
                    for row in cur.fetchall():
                        status_key = str(row["status"] or "").upper()
                        count = int(row["count"] or 0)
                        execution_summary["total_actions"] += count
                        if status_key == "COMPLETED":
                            execution_summary["completed"] += count
                        else:
                            execution_summary["pending"] += count
                for item in execution_history:
                    for key in ("created_at", "updated_at", "completed_at", "due_at", "reminder_at"):
                        item[key] = item[key].isoformat() if item.get(key) else None

                if workflow_history_exists:
                    action_join = "LEFT JOIN oc_workflow.actions a ON a.id = h.action_id" if workflow_actions_exists else ""
                    action_title_select = ", a.title AS action_title" if workflow_actions_exists else ""
                    cur.execute(
                        f"""
                        SELECT h.*{action_title_select}
                        FROM oc_workflow.routing_history h
                        {action_join}
                        ORDER BY h.event_at DESC
                        LIMIT %s
                        """,
                        (history_limit,),
                    )
                    workflow_logs = [dict(row) for row in cur.fetchall()]
                for item in workflow_logs:
                    item["event_at"] = item["event_at"].isoformat() if item.get("event_at") else None

                usage_summary = {"entries": 0, "providers": 0, "estimated_or_actual_spend_usd": 0.0}
                usage_by_provider: list[dict[str, Any]] = []
                recent_usage: list[dict[str, Any]] = []
                if _table_exists(cur, "oc_ai.usage_ledger"):
                    usage_filter = "WHERE (%s IS NULL OR workspace_id = %s) AND (%s IS NULL OR project_id = %s)"
                    cur.execute(
                        f"""
                        SELECT COUNT(*) AS entries,
                               COUNT(DISTINCT provider_key) AS providers,
                               COALESCE(SUM(COALESCE(actual_cost_usd, estimated_cost_usd)), 0) AS spend_usd
                        FROM oc_ai.usage_ledger
                        {usage_filter}
                        """,
                        (workspace_id, workspace_id, project_id, project_id),
                    )
                    usage_totals = cur.fetchone()
                    if usage_totals:
                        usage_summary = {
                            "entries": int(usage_totals["entries"] or 0),
                            "providers": int(usage_totals["providers"] or 0),
                            "estimated_or_actual_spend_usd": float(usage_totals["spend_usd"] or 0),
                        }
                    cur.execute(
                        f"""
                        SELECT provider_key,
                               COUNT(*) AS entries,
                               COALESCE(SUM(COALESCE(actual_cost_usd, estimated_cost_usd)), 0) AS spend_usd,
                               MAX(occurred_at) AS last_occurred_at
                        FROM oc_ai.usage_ledger
                        {usage_filter}
                        GROUP BY provider_key
                        ORDER BY spend_usd DESC, provider_key
                        """,
                        (workspace_id, workspace_id, project_id, project_id),
                    )
                    usage_by_provider = [dict(row) for row in cur.fetchall()]
                    cur.execute(
                        f"""
                        SELECT *
                        FROM oc_ai.usage_ledger
                        {usage_filter}
                        ORDER BY occurred_at DESC
                        LIMIT %s
                        """,
                        (workspace_id, workspace_id, project_id, project_id, usage_limit),
                    )
                    recent_usage = [dict(row) for row in cur.fetchall()]
                for item in usage_by_provider:
                    item["entries"] = int(item["entries"] or 0)
                    item["spend_usd"] = float(item["spend_usd"] or 0)
                    item["last_occurred_at"] = item["last_occurred_at"].isoformat() if item.get("last_occurred_at") else None
                for item in recent_usage:
                    for key in ("occurred_at",):
                        item[key] = item[key].isoformat() if item.get(key) else None

                return {
                    **base,
                    "providers": {
                        "summary": {
                            "total": len(providers),
                            "healthy": sum(1 for item in providers if item["status"] == "healthy"),
                            "available": sum(1 for item in providers if item["availability"] == "available"),
                            "managed": sum(1 for item in providers if item.get("managed")),
                        },
                        "items": providers,
                    },
                    "budgets": {
                        "summary": {
                            "scopes": len(budgets),
                            "tracked_calls": sum(int(item.get("calls") or 0) for item in budgets),
                            "tracked_spend_usd": round(sum(float(item.get("spent_usd") or 0) for item in budgets), 8),
                        },
                        "items": budgets,
                    },
                    "recommendation_queue": {"summary": recommendation_summary, "items": recommendations},
                    "execution_history": {"summary": execution_summary, "items": execution_history},
                    "workflow_logs": {"summary": {"events": len(workflow_logs)}, "items": workflow_logs},
                    "usage_ledger": {
                        "summary": usage_summary,
                        "by_provider": usage_by_provider,
                        "recent_entries": recent_usage,
                    },
                }
    except Exception as exc:
        return {
            **base,
            "status": "telemetry_error",
            "database_connected": False,
            "blockers": [f"Executive Intelligence Mission Control telemetry unavailable: {exc}"],
            "providers": {"summary": {"total": 0, "healthy": 0, "available": 0, "managed": 0}, "items": []},
            "budgets": {"summary": {"scopes": 0, "tracked_calls": 0, "tracked_spend_usd": 0.0}, "items": []},
            "recommendation_queue": {"summary": {"total": 0, "pending": 0, "approved": 0, "rejected": 0, "routed": 0}, "items": []},
            "execution_history": {"summary": {"total_actions": 0, "completed": 0, "pending": 0}, "items": []},
            "workflow_logs": {"summary": {"events": 0}, "items": []},
            "usage_ledger": {
                "summary": {"entries": 0, "providers": 0, "estimated_or_actual_spend_usd": 0.0},
                "by_provider": [],
                "recent_entries": [],
            },
        }


def generate_for_source(source_id: int, workspace_id: str, project_id: str | None) -> list[dict[str, Any]] | None:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_intake.sources WHERE id=%s", (source_id,))
            source = cur.fetchone()
            if not source or source["status"] not in ("APPROVED", "PUBLISHED"):
                return None
            results = []
            for item in build_recommendations(source):
                cur.execute("""INSERT INTO oc_ai.recommendations
                  (source_id,workspace_id,project_id,recommendation_type,title,rationale,priority,
                   confidence,expected_benefit,estimated_effort_minutes,estimated_ai_cost_usd,
                   proposed_action_type,proposed_destination,required_capability,evidence)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                  ON CONFLICT (source_id,workspace_id,(COALESCE(project_id,'')),recommendation_type)
                  DO UPDATE SET title=EXCLUDED.title,rationale=EXCLUDED.rationale,priority=EXCLUDED.priority,
                   confidence=EXCLUDED.confidence,expected_benefit=EXCLUDED.expected_benefit,
                   estimated_effort_minutes=EXCLUDED.estimated_effort_minutes,
                   estimated_ai_cost_usd=EXCLUDED.estimated_ai_cost_usd,
                   proposed_action_type=EXCLUDED.proposed_action_type,
                   proposed_destination=EXCLUDED.proposed_destination,
                   required_capability=EXCLUDED.required_capability,evidence=EXCLUDED.evidence
                  RETURNING *""", (source_id,workspace_id,project_id,item["recommendation_type"],item["title"],
                  item["rationale"],item["priority"],item["confidence"],item["expected_benefit"],
                  item["estimated_effort_minutes"],item["estimated_ai_cost_usd"],item["proposed_action_type"],
                  item["proposed_destination"],item["required_capability"],Jsonb(item["evidence"])))
                results.append(cur.fetchone())
            return results


def list_recommendations(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    where = "WHERE r.status=%s" if status else ""
    params: list[Any] = [status] if status else []
    params.append(limit)
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"""SELECT r.*, s.title AS source_title FROM oc_ai.recommendations r
                JOIN oc_intake.sources s ON s.id=r.source_id {where}
                ORDER BY CASE r.priority WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                r.created_at DESC LIMIT %s""", params)
            return list(cur.fetchall())


def decide(recommendation_id: int, decision: str, actor: str | None, notes: str | None) -> dict[str, Any] | None:
    status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE oc_ai.recommendations SET status=%s,decision_actor=%s,decision_notes=%s,
                decided_at=NOW() WHERE id=%s AND status='PENDING' RETURNING *""",
                (status, actor, notes, recommendation_id))
            return cur.fetchone()


def route_recommendation(recommendation_id: int, payload: Any) -> dict[str, Any] | None:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM oc_ai.recommendations WHERE id=%s FOR UPDATE", (recommendation_id,))
                rec = cur.fetchone()
                if not rec or rec["status"] != "APPROVED":
                    return None
                cur.execute("""INSERT INTO oc_workflow.actions
                    (source_id,action_type,destination,title,description,owner,priority,due_at,reminder_at,metadata)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (rec["source_id"], rec["proposed_action_type"], rec["proposed_destination"], rec["title"],
                     rec["rationale"], payload.owner, rec["priority"], payload.due_at, payload.reminder_at,
                     Jsonb({"recommendation_id": recommendation_id, "required_capability": rec["required_capability"],
                            "estimated_ai_cost_usd": float(rec["estimated_ai_cost_usd"] or 0)})))
                action = cur.fetchone()
                cur.execute("""INSERT INTO oc_workflow.routing_history
                    (source_id,action_id,event_type,actor,notes) VALUES (%s,%s,'RECOMMENDATION_ROUTED',%s,%s)""",
                    (rec["source_id"], action["id"], payload.owner, payload.notes))
                cur.execute("""UPDATE oc_ai.recommendations SET status='ROUTED', workflow_action_id=%s
                    WHERE id=%s RETURNING *""", (action["id"], recommendation_id))
                updated = cur.fetchone()
                return {"recommendation": updated, "workflow_action": action, "canonical_records_mutated": False}


def list_providers() -> list[dict[str, Any]]:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_ai.providers ORDER BY priority,cost_rank,provider_key")
            return list(cur.fetchall())


def upsert_provider(payload: Any) -> dict[str, Any]:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO oc_ai.providers
                (provider_key,display_name,capabilities,priority,cost_rank,managed,enabled,healthy,configuration)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (provider_key) DO UPDATE SET display_name=EXCLUDED.display_name,
                capabilities=EXCLUDED.capabilities,priority=EXCLUDED.priority,cost_rank=EXCLUDED.cost_rank,
                managed=EXCLUDED.managed,enabled=EXCLUDED.enabled,healthy=EXCLUDED.healthy,
                configuration=EXCLUDED.configuration,updated_at=NOW() RETURNING *""",
                (payload.provider_key,payload.display_name,payload.capabilities,payload.priority,payload.cost_rank,
                 payload.managed,payload.enabled,payload.healthy,Jsonb(payload.configuration)))
            return cur.fetchone()


def upsert_budget_policy(payload: Any) -> dict[str, Any]:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO oc_ai.budget_policies
                (workspace_id,project_id,provider_key,soft_limit_usd,hard_limit_usd,policy_mode,period,enabled)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (workspace_id,(COALESCE(project_id,'')),(COALESCE(provider_key,'')),period)
                DO UPDATE SET soft_limit_usd=EXCLUDED.soft_limit_usd,hard_limit_usd=EXCLUDED.hard_limit_usd,
                policy_mode=EXCLUDED.policy_mode,enabled=EXCLUDED.enabled,updated_at=NOW() RETURNING *""",
                (payload.workspace_id,payload.project_id,payload.provider_key,payload.soft_limit_usd,
                 payload.hard_limit_usd,payload.policy_mode,payload.period,payload.enabled))
            return cur.fetchone()


def record_usage(payload: Any) -> dict[str, Any]:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO oc_ai.usage_ledger
                (workspace_id,project_id,provider_key,model_key,task_type,recommendation_id,workflow_action_id,
                 input_units,output_units,estimated_cost_usd,actual_cost_usd,metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (payload.workspace_id,payload.project_id,payload.provider_key,payload.model_key,payload.task_type,
                 payload.recommendation_id,payload.workflow_action_id,payload.input_units,payload.output_units,
                 payload.estimated_cost_usd,payload.actual_cost_usd,Jsonb(payload.metadata)))
            return cur.fetchone()


def budget_summary(workspace_id: str, project_id: str | None) -> dict[str, Any]:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT COALESCE(SUM(COALESCE(actual_cost_usd,estimated_cost_usd)),0) spent,
                COUNT(*) calls FROM oc_ai.usage_ledger WHERE workspace_id=%s AND (%s IS NULL OR project_id=%s)
                AND occurred_at>=date_trunc('month',NOW())""", (workspace_id,project_id,project_id))
            usage = cur.fetchone()
            cur.execute("""SELECT * FROM oc_ai.budget_policies WHERE enabled=TRUE AND workspace_id=%s
                AND (project_id=%s OR project_id IS NULL) ORDER BY project_id NULLS LAST LIMIT 1""",
                (workspace_id,project_id))
            policy = cur.fetchone()
            spent = float(usage["spent"])
            hard = float(policy["hard_limit_usd"]) if policy and policy["hard_limit_usd"] is not None else None
            return {"workspace_id": workspace_id, "project_id": project_id, "period": "MONTHLY",
                    "spent_usd": spent, "calls": usage["calls"], "hard_limit_usd": hard,
                    "remaining_usd": None if hard is None else max(0.0, hard-spent), "policy": policy}


def route_provider(capability: str, workspace_id: str, project_id: str | None,
                   estimated_cost_usd: float, preferred_provider: str | None) -> dict[str, Any]:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT provider_key,capabilities,priority,cost_rank,healthy,enabled,managed FROM oc_ai.providers")
            providers = [ProviderCandidate(row["provider_key"], frozenset(row["capabilities"] or []),
                row["priority"], row["cost_rank"], row["healthy"], row["enabled"], row["managed"])
                for row in cur.fetchall()]
            cur.execute("""SELECT COALESCE(SUM(COALESCE(actual_cost_usd,estimated_cost_usd)),0) AS spent
                FROM oc_ai.usage_ledger WHERE workspace_id=%s AND (%s IS NULL OR project_id=%s)
                AND occurred_at >= date_trunc('month', NOW())""", (workspace_id, project_id, project_id))
            spent = float(cur.fetchone()["spent"])
            cur.execute("""SELECT * FROM oc_ai.budget_policies WHERE enabled=TRUE AND workspace_id=%s
                AND (project_id=%s OR project_id IS NULL) ORDER BY project_id NULLS LAST LIMIT 1""",
                (workspace_id, project_id))
            policy = cur.fetchone()
    budget = evaluate_budget(spent_usd=spent, proposed_usd=estimated_cost_usd,
        soft_limit_usd=float(policy["soft_limit_usd"]) if policy and policy["soft_limit_usd"] is not None else None,
        hard_limit_usd=float(policy["hard_limit_usd"]) if policy and policy["hard_limit_usd"] is not None else None,
        policy_mode=policy["policy_mode"] if policy else "WARN")
    routing = choose_provider(capability=capability, providers=providers,
        preferred_provider=preferred_provider, budget_decision=budget["decision"])
    return {"budget": budget, "routing": routing}
