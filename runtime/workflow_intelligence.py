"""Advisory workflow intelligence for the Mission Control panel.

`src/components/mission-control/WorkflowIntelligencePanel.tsx` is rendered on
the Mission Control page and reads
``GET /api/scientific-observability/workflow-intelligence``. That endpoint did
not exist, so the panel was permanently empty -- and because the dashboard only
reports ``live`` when all seventeen of its parallel fetches succeed, one missing
endpoint held the entire view in ``mixed`` mode.

Source of truth
---------------
Real autonomous workflow state from the durable reservoir: the tasks the
autonomy engine has queued, leased, executed, parked, or completed. Nothing is
synthesized. When the reservoir cannot be read the endpoint reports an empty
workflow list rather than inventing one.

What this surface may and may not do
------------------------------------
It is advisory, and the consumer enforces that. The payload must declare
``advisory_only`` and ``human_review_required`` true, and dispatch, mutation,
publication and spending authority all false, at the root, on every ranking,
and on every agent context. A payload that fails any of those is rejected
wholesale by the frontend parser, which is the correct behavior: a panel that
cannot prove it is advisory should show nothing.

Redaction is a hard requirement, not a nicety
---------------------------------------------
The consumer walks the entire payload and discards all of it if any key
anywhere contains ``api_key``, ``password``, ``secret``, ``token``,
``raw_prompt``, ``prompt_text``, ``latitude``, ``longitude``, ``coordinate`` or
``exact_locality``, or if any string contains a secret marker. Two of those
are locality fields, because orchid locality data is conservation-sensitive.
:func:`assert_publishable` enforces the same rule here, so a future field that
would blank the panel fails a test instead of shipping.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

CONTRACT_VERSION = "workflow-intelligence-mission-control-v1"
RANKING_FORMULA_VERSION = "automation-opportunity-ranking-v1"
AGENT_CONTEXT_VERSION = "governed-agent-context-v1"
RUNBOOK_VERSION = "reviewable-runbook-v1"

# The consumer caps the list; sending more discards the whole payload.
MAX_WORKFLOWS = 50

MEASUREMENT_CLASSES = ("MEASURED", "CALCULATED", "ESTIMATED", "UNAVAILABLE")
DISPLAY_STATES = ("ACTIVE", "BLOCKED", "RECENTLY_FAILED", "AWAITING_REVIEW", "TERMINAL")
CAPABILITY_STATES = (
    "BACKEND_ONLY",
    "INTEGRATED",
    "TESTED",
    "BLOCKED",
    "AWAITING_REVIEW",
    "UNAVAILABLE",
)

# Mirrors FORBIDDEN_KEYS in src/lib/workflowIntelligence.ts. Kept in sync
# deliberately: if the consumer's list grows, this one must grow with it or the
# panel silently blanks in production.
FORBIDDEN_KEY_FRAGMENTS = (
    "api_key",
    "password",
    "secret",
    "token",
    "raw_prompt",
    "prompt_text",
    "latitude",
    "longitude",
    "coordinate",
    "exact_locality",
)
SECRET_MARKERS = ("sk-", "BEGIN PRIVATE KEY", "Bearer ")

# Reservoir state -> what the operator should see.
_DISPLAY_STATE_BY_TASK_STATE = {
    "ready": "ACTIVE",
    "leased": "ACTIVE",
    "running": "ACTIVE",
    "validating": "ACTIVE",
    "blocked": "BLOCKED",
    "repair_backoff": "RECENTLY_FAILED",
    "owner_gated": "AWAITING_REVIEW",
    "completed": "TERMINAL",
}

_CAPABILITY_STATE_BY_TASK_STATE = {
    "ready": "BACKEND_ONLY",
    "leased": "INTEGRATED",
    "running": "INTEGRATED",
    "validating": "INTEGRATED",
    "blocked": "BLOCKED",
    "repair_backoff": "BLOCKED",
    "owner_gated": "AWAITING_REVIEW",
    "completed": "TESTED",
}

# The ranking factors. Coverage is reported against this list, so a factor that
# could not be measured lowers the reported coverage instead of silently
# defaulting to zero and flattering the score.
RANKING_FACTORS = (
    "retry_pressure",
    "rework_pressure",
    "blocked_state",
    "evidence_present",
    "owner_gate_required",
)


class SensitiveFieldError(AssertionError):
    """A payload carried a field the consumer would reject the whole page over."""


def _forbidden_key(key: str) -> str | None:
    lowered = key.lower()
    for fragment in FORBIDDEN_KEY_FRAGMENTS:
        if fragment in lowered:
            return fragment
    return None


def assert_publishable(payload: Any, *, path: str = "$") -> None:
    """Raise if any part of the payload would make the consumer discard it.

    The frontend's rejection is all-or-nothing and silent: one offending key
    anywhere and the operator sees an empty panel with no explanation. Failing
    loudly here, in a test, is the only way that stays visible.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            fragment = _forbidden_key(str(key))
            if fragment:
                raise SensitiveFieldError(
                    f"{path}.{key} contains forbidden fragment {fragment!r}; "
                    "the Mission Control consumer would discard the entire payload"
                )
            assert_publishable(value, path=f"{path}.{key}")
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            assert_publishable(value, path=f"{path}[{index}]")
    elif isinstance(payload, str):
        for marker in SECRET_MARKERS:
            if marker in payload:
                raise SensitiveFieldError(f"{path} contains secret marker {marker!r}")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any, *, limit: int = 200) -> str:
    """Reduce arbitrary text to something safe to publish.

    Blocker reasons and evidence keys are operational strings that can pick up
    anything upstream put in them, so they are truncated and scrubbed of
    secret-shaped content before they reach an operator's browser.
    """
    text = str(value or "").strip()
    for marker in SECRET_MARKERS:
        text = text.replace(marker, "[redacted]")
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


@dataclass(frozen=True, slots=True)
class WorkflowObservation:
    """Reservoir tasks that were readable, and why they might not be."""

    tasks: tuple[dict[str, Any], ...] = ()
    source_error: str | None = None
    source: str = "durable-reservoir"


# ---------------------------------------------------------------------------
# Ranking (pure, advisory)
# ---------------------------------------------------------------------------


def rank_workflow(task: dict[str, Any]) -> dict[str, Any]:
    """Score one workflow's automation-attention opportunity.

    Advisory only. A higher score means "an operator should look at this
    sooner", never "dispatch this". Factors that could not be measured are
    named rather than defaulted, and a workflow with no measurable factor gets
    a null score instead of a fabricated zero.
    """
    available: list[str] = []
    unavailable: list[str] = []
    reasons: list[str] = []
    score = 0.0

    state = str(task.get("state") or "").strip().casefold()

    retry = task.get("retry_count")
    if isinstance(retry, int) and not isinstance(retry, bool) and retry >= 0:
        available.append("retry_pressure")
        if retry:
            score += min(retry, 5) * 8.0
            reasons.append(f"RETRIED_{min(retry, 5)}X")
    else:
        unavailable.append("retry_pressure")

    rework = task.get("rework_count")
    if isinstance(rework, int) and not isinstance(rework, bool) and rework >= 0:
        available.append("rework_pressure")
        if rework:
            score += min(rework, 5) * 6.0
            reasons.append(f"REWORKED_{min(rework, 5)}X")
    else:
        unavailable.append("rework_pressure")

    if state:
        available.append("blocked_state")
        if state in ("blocked", "repair_backoff"):
            score += 25.0
            reasons.append("BLOCKED_OR_PARKED")
    else:
        unavailable.append("blocked_state")

    evidence = task.get("evidence")
    if isinstance(evidence, dict):
        available.append("evidence_present")
        if not evidence and state == "completed":
            score += 15.0
            reasons.append("COMPLETED_WITHOUT_EVIDENCE")
    else:
        unavailable.append("evidence_present")

    authority = str(task.get("authority_class") or "").strip()
    if authority:
        available.append("owner_gate_required")
        if state == "owner_gated":
            reasons.append("AWAITING_OWNER_AUTHORIZATION")
    else:
        unavailable.append("owner_gate_required")

    total = len(RANKING_FACTORS)
    ratio = round(len(available) / total, 4) if total else 0.0
    if not reasons:
        reasons.append("NO_ATTENTION_SIGNAL")

    return {
        "formula_version": RANKING_FORMULA_VERSION,
        # Never a confident 0 when nothing could be measured.
        "score": round(score, 2) if available else None,
        "factor_coverage": {
            "available": len(available),
            "total": total,
            "ratio": ratio,
        },
        "unavailable_factors": unavailable,
        "reason_codes": reasons,
        "requires_human_approval": state == "owner_gated",
        # Authority declarations the consumer verifies.
        "advisory_only": True,
        "dispatch_authority": False,
        "mutation_authority": False,
        "publication_authority": False,
        "spending_authority": False,
    }


def build_agent_context(task: dict[str, Any]) -> dict[str, Any]:
    """The governed context envelope the consumer requires on every workflow."""
    evidence = task.get("evidence")
    # Cost is not instrumented on the reservoir, and guessing it would be a
    # fabricated measurement. UNAVAILABLE is the honest class.
    cost_state = "UNAVAILABLE"
    if isinstance(evidence, dict) and isinstance(
        evidence.get("provider_call_count"), int
    ):
        cost_state = "MEASURED"
    return {
        "contract_version": AGENT_CONTEXT_VERSION,
        "risk_cost_constraints": {
            "cost_state": cost_state,
            "consequence_risk": _safe_text(
                task.get("consequence_risk") or "unknown", limit=32
            ),
        },
        "dispatch_authority": False,
        "credential_authority": False,
        "mutation_authority": False,
        "publication_authority": False,
        "spending_authority": False,
    }


def build_findings(task: dict[str, Any]) -> list[dict[str, Any]]:
    """Machine-readable reasons this workflow is where it is."""
    findings: list[dict[str, Any]] = []
    state = str(task.get("state") or "").strip().casefold()
    blocked_reason = task.get("blocked_reason")

    if blocked_reason:
        reason = _safe_text(blocked_reason)
        code = reason.split(":", 1)[0].upper().replace(" ", "_")[:64] or "BLOCKED"
        findings.append({"reason_code": code, "detail": reason})
    if state == "owner_gated":
        findings.append(
            {
                "reason_code": "OWNER_AUTHORIZATION_REQUIRED",
                "detail": "This workflow class cannot execute without owner authorization.",
            }
        )
    if state == "completed" and not task.get("evidence"):
        findings.append(
            {
                "reason_code": "COMPLETED_WITHOUT_EVIDENCE",
                "detail": "Terminal state reached with no recorded completion evidence.",
            }
        )
    return findings


def build_workflow_item(task: dict[str, Any]) -> dict[str, Any] | None:
    """Map one reservoir task to a panel row, or None if it has no identity."""
    workflow_id = _safe_text(task.get("task_key") or task.get("key"), limit=120)
    if not workflow_id:
        return None

    state = str(task.get("state") or "").strip().casefold()
    evidence = task.get("evidence") if isinstance(task.get("evidence"), dict) else {}

    evidence_refs = [
        _safe_text(key, limit=64)
        for key in sorted(evidence)[:20]
        if _safe_text(key, limit=64)
    ]
    blocker_refs = []
    if task.get("blocked_reason"):
        blocker_refs.append(_safe_text(task["blocked_reason"], limit=120))

    retry = task.get("retry_count")
    rework = task.get("rework_count")

    return {
        "workflow_id": workflow_id,
        "workflow_type": _safe_text(task.get("module") or "autonomy-task", limit=64),
        "correlation_id": _safe_text(
            task.get("run_id") or task.get("correlation_id") or workflow_id, limit=120
        ),
        "display_state": _DISPLAY_STATE_BY_TASK_STATE.get(state, "BLOCKED"),
        "current_state": _safe_text(state or "unknown", limit=32),
        "retry_count": retry
        if isinstance(retry, int) and not isinstance(retry, bool) and retry >= 0
        else 0,
        "rework_count": rework
        if isinstance(rework, int) and not isinstance(rework, bool) and rework >= 0
        else 0,
        "evidence_refs": evidence_refs,
        "blocker_refs": blocker_refs,
        "findings": build_findings(task),
        "stale": {
            # Staleness needs a lease clock the reservoir does not expose here.
            # UNAVAILABLE with a null value is honest; false would be a claim.
            "classification": "UNAVAILABLE",
            "value": None,
        },
        "ranking": rank_workflow(task),
        "agent_context": build_agent_context(task),
        "capability_state": _CAPABILITY_STATE_BY_TASK_STATE.get(state, "UNAVAILABLE"),
        # Runbook generation is not wired; null is the contract's own "none".
        "runbook": None,
    }


def build_workflow_intelligence(observation: WorkflowObservation) -> dict[str, Any]:
    """Compose the payload the Mission Control consumer parses."""
    items: list[dict[str, Any]] = []
    for task in observation.tasks:
        if len(items) >= MAX_WORKFLOWS:
            break
        if not isinstance(task, dict):
            continue
        item = build_workflow_item(task)
        if item is not None:
            items.append(item)

    # Most-attention-first, deterministic on ties so the panel does not shuffle.
    items.sort(
        key=lambda i: (-(i["ranking"]["score"] or 0.0), i["workflow_id"]),
    )

    payload = {
        "contract_version": CONTRACT_VERSION,
        "generated_at": _utc_now_iso(),
        "workflows": items,
        "source": observation.source,
        "source_available": observation.source_error is None,
        "advisory_only": True,
        "human_review_required": True,
        "dispatch_authority": False,
        "mutation_authority": False,
        "publication_authority": False,
        "spending_authority": False,
    }
    # Fail here rather than let the operator see a blank panel.
    assert_publishable(payload)
    return payload


def observe_workflows(
    read_tasks: Callable[[], Iterable[Any]],
    *,
    source: str = "durable-reservoir",
) -> WorkflowObservation:
    """Read reservoir tasks, degrading to an empty list instead of raising."""
    try:
        raw = read_tasks()
    except Exception as exc:  # noqa: BLE001 - an unreadable source is not a crash
        return WorkflowObservation(
            tasks=(), source_error=type(exc).__name__, source=source
        )
    tasks = tuple(item for item in (raw or ()) if isinstance(item, dict))
    return WorkflowObservation(tasks=tasks, source=source)
