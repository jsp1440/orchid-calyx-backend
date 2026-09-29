"""Bridge safe canonical Calyx tasks into the shared reserve planner.

The durable task table remains the source of truth. This module only projects
eligible task rows into provider-free reserve proposals; it does not execute a
task, create an issue, or write to the database.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from scripts.oc_backlog_refiller import plan_refill

_SCHEMA = "oc.durable-task-reserve-source.v1"
_MAX_TASK_BYTES = 8192
_TASK_SOURCE_KINDS = {
    "platform_self_audit_followup": "self-audit",
    "source_federation_adapter_evaluation": "connector-queue",
}


def _normalized_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if any(ord(character) < 32 for character in normalized):
        return None
    return normalized


def _payload_reason(task_type: str, payload: dict[str, Any]) -> str | None:
    if task_type == "platform_self_audit_followup":
        if payload.get("execution_mode") != "draft_only":
            return "authority_escalation"
        if any(
            payload.get(field) is not False
            for field in (
                "automatic_merge",
                "automatic_deploy",
                "automatic_publication",
            )
        ):
            return "authority_escalation"
        return None

    if task_type == "source_federation_adapter_evaluation":
        if payload.get("schema") != "oc.source-federation-task.v1":
            return "invalid_task_payload"
        if payload.get("execution_mode") != "draft_only":
            return "authority_escalation"
        if any(
            payload.get(field) is not False
            for field in (
                "network_fetch_authorized",
                "scientific_publication_authorized",
                "knowledge_graph_mutation_authorized",
                "taxonomy_mutation_authorized",
                "automatic_merge",
                "automatic_deploy",
            )
        ):
            return "authority_escalation"
        return None

    return "unsupported_task_type"


def _priority(value: Any) -> int:
    try:
        durable_priority = int(value)
    except (TypeError, ValueError):
        return 5
    return max(0, min(5, 5 - durable_priority // 20))


def _candidate(task: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    task_type = _normalized_text(task.get("task_type"))
    task_key = _normalized_text(task.get("task_key"))
    title = _normalized_text(task.get("title"))
    payload = task.get("payload")

    if not task_type or task_type not in _TASK_SOURCE_KINDS:
        return None, "unsupported_task_type"
    if not task_key or not title or not isinstance(payload, dict):
        return None, "invalid_task_contract"
    if task.get("status") != "pending":
        return None, "task_not_pending"
    if task.get("required_approval") is not False:
        return None, "protected_task"

    payload_reason = _payload_reason(task_type, payload)
    if payload_reason:
        return None, payload_reason

    material = {
        "schema": _SCHEMA,
        "task_key": task_key,
        "task_type": task_type,
        "title": title,
        "payload": payload,
    }
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    if len(encoded) > _MAX_TASK_BYTES:
        return None, "task_payload_too_large"

    fingerprint = hashlib.sha256(encoded).hexdigest()
    return {
        "source_kind": "issue",
        "queue_source_kind": _TASK_SOURCE_KINDS[task_type],
        "source_ref": task_key,
        "title": title,
        "material_fingerprint": fingerprint,
        "semantic_key": f"calyx-task:{task_key.casefold()}",
        "priority": _priority(task.get("priority")),
        "dependencies": [],
        "protected_boundaries": [],
    }, None


def plan_durable_task_refill(
    snapshot: dict[str, Any],
    tasks: Iterable[dict[str, Any]],
    *,
    reserve_depth: int = 2,
    planner_ok: bool = True,
) -> dict[str, Any]:
    """Project safe pending task rows into deterministic reserve work."""

    candidates: list[dict[str, Any]] = []
    source_rejections: list[dict[str, Any]] = []

    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            source_rejections.append(
                {"task_index": index, "reason": "invalid_task_contract"}
            )
            continue
        candidate, reason = _candidate(task)
        if candidate is not None:
            candidates.append(candidate)
            continue
        source_rejections.append(
            {
                "task_index": index,
                "task_key": task.get("task_key"),
                "reason": reason,
            }
        )

    result = plan_refill(
        snapshot,
        candidates,
        reserve_depth=reserve_depth,
        planner_ok=planner_ok,
    )
    result.update(
        {
            "source_schema": _SCHEMA,
            "source_candidate_count": len(candidates),
            "source_rejections": source_rejections,
            "provider_launch_authorized": False,
            "no_api_mode": True,
        }
    )
    return result
