from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.intake.repository import database_url
from .engine import ProviderCandidate, build_recommendations, choose_provider, evaluate_budget


def generate_for_source(source_id: int, workspace_id: str, project_id: str | None) -> list[dict[str, Any]] | None:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_intake.sources WHERE id=%s", (source_id,))
            source = cur.fetchone()
            if not source or source["status"] not in ("APPROVED", "PUBLISHED"):
                return None
            results: list[dict[str, Any]] = []
            for item in build_recommendations(source):
                cur.execute(
                    """
                    INSERT INTO oc_ai.recommendations
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
                    RETURNING *
                    """,
                    (source_id, workspace_id, project_id, item["recommendation_type"], item["title"],
                     item["rationale"], item["priority"], item["confidence"], item["expected_benefit"],
                     item["estimated_effort_minutes"], item["estimated_ai_cost_usd"],
                     item["proposed_action_type"], item["proposed_destination"],
                     item["required_capability"], Jsonb(item["evidence"])),
                )
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


def route_provider(capability: str, workspace_id: str, project_id: str | None,
                   estimated_cost_usd: float, preferred_provider: str | None) -> dict[str, Any]:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT provider_key,capabilities,priority,cost_rank,healthy,enabled,managed
                FROM oc_ai.providers""")
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
