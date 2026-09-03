"""Deep Orchestrate — machine-readable task reservoir for Orchid Continuum.

Implements the continuous rolling-lane queue described in issue #1024:
- Thousands of bounded task leaves without one GitHub issue per leaf.
- Priority-ordered READY reservoir; keeps all configured slots filled.
- Lease exclusivity: one worker per task at a time.
- Dependency gating: only tasks with all deps completed become READY.
- Owner-gate isolation: high-consequence tasks never auto-dispatch.
- Backoff exclusion: tasks in repair-backoff are not executable.
- Refill immediately when any lane completes, blocks, or owner-gates.

Thread-safe for concurrent workers. Serializable for persistence/restart.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "deep-orchestrate/v1"

# Authority classes (from CALYX-SUPERSTRUCTURE-004)
AUTH_READ_ONLY = "read_only"
AUTH_WORKSPACE = "bounded_workspace_mutation"
AUTH_REPO_EXEC = "repository_code_execution"
AUTH_PRODUCTION = "production_change"
AUTH_SCIENCE_PUB = "scientific_publication"
AUTH_SECURITY = "restricted_data_or_security"
AUTH_GOVERNANCE = "governance_change"

# Owner-gate required for any of these
_OWNER_GATE_CLASSES = frozenset(
    {AUTH_PRODUCTION, AUTH_SCIENCE_PUB, AUTH_SECURITY, AUTH_GOVERNANCE}
)


class Priority(IntEnum):
    P0 = 0
    P1 = 1
    P2 = 2
    P3 = 3
    P4 = 4


class TaskState:
    READY = "ready"
    LEASED = "leased"
    RUNNING = "running"
    VALIDATING = "validating"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    OWNER_GATED = "owner_gated"
    REPAIR_BACKOFF = "repair_backoff"


_TERMINAL = frozenset({TaskState.COMPLETED, TaskState.BLOCKED})
_ACTIVE = frozenset({TaskState.LEASED, TaskState.RUNNING, TaskState.VALIDATING})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class TaskLeaf:
    """One bounded, deduplicable unit of work in the reservoir.

    Keys are stable identifiers; GitHub issues are materialized only when the
    leaf is admitted for execution or needs human-visible tracking.
    """

    key: str  # globally unique, e.g. "backend:calyx:research-executor:bind"
    title: str
    repo: str  # e.g. "orchid-calyx-backend"
    module: str  # e.g. "app/calyx_orchestrator"
    priority: int  # Priority.P0–P4
    authority_class: str  # one of AUTH_* constants
    consequence_risk: str  # "low" | "medium" | "high"
    providers: list[str] = field(default_factory=lambda: ["claude"])
    estimated_size: str = "m"  # "xs" | "s" | "m" | "l" | "xl"
    dependencies: list[str] = field(default_factory=list)  # task keys
    acceptance_criteria: list[str] = field(default_factory=list)
    issue_number: int | None = None  # GitHub issue if materialized
    pr_number: int | None = None
    # Mutable execution state (managed by DeepOrchestrate)
    state: str = TaskState.READY
    leased_at: float | None = None
    lease_holder: str | None = None
    blocked_reason: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def requires_owner_gate(self) -> bool:
        return self.authority_class in _OWNER_GATE_CLASSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "repo": self.repo,
            "module": self.module,
            "priority": self.priority,
            "authority_class": self.authority_class,
            "consequence_risk": self.consequence_risk,
            "providers": self.providers,
            "estimated_size": self.estimated_size,
            "dependencies": self.dependencies,
            "acceptance_criteria": self.acceptance_criteria,
            "issue_number": self.issue_number,
            "pr_number": self.pr_number,
            "state": self.state,
            "leased_at": self.leased_at,
            "lease_holder": self.lease_holder,
            "blocked_reason": self.blocked_reason,
            "evidence": self.evidence,
            "requires_owner_gate": self.requires_owner_gate,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TaskLeaf:
        leaf = cls(
            key=d["key"],
            title=d["title"],
            repo=d.get("repo", ""),
            module=d.get("module", ""),
            priority=d.get("priority", Priority.P2),
            authority_class=d.get("authority_class", AUTH_WORKSPACE),
            consequence_risk=d.get("consequence_risk", "low"),
            providers=d.get("providers", ["claude"]),
            estimated_size=d.get("estimated_size", "m"),
            dependencies=d.get("dependencies", []),
            acceptance_criteria=d.get("acceptance_criteria", []),
            issue_number=d.get("issue_number"),
            pr_number=d.get("pr_number"),
        )
        leaf.state = d.get("state", TaskState.READY)
        leaf.leased_at = d.get("leased_at")
        leaf.lease_holder = d.get("lease_holder")
        leaf.blocked_reason = d.get("blocked_reason")
        leaf.evidence = d.get("evidence", {})
        leaf.created_at = d.get("created_at", leaf.created_at)
        leaf.updated_at = d.get("updated_at", leaf.updated_at)
        return leaf


# ---------------------------------------------------------------------------
# Reservoir
# ---------------------------------------------------------------------------


class DeepOrchestrate:
    """Priority-ordered task reservoir with lease exclusivity.

    Design constraints:
    - Owner-gated tasks (production_change, scientific_publication,
      restricted_data_or_security, governance_change) are never auto-dispatched.
    - Tasks in repair_backoff state are not executable until explicitly recovered.
    - Completing a task exposes its dependents for READY consideration.
    - Blocking a task does NOT block the program; capacity refills from the
      next eligible leaf.
    """

    def __init__(self, *, configured_width: int = 5) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, TaskLeaf] = {}
        self.configured_width = configured_width

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, leaf: TaskLeaf) -> bool:
        """Add a task leaf to the reservoir.

        Returns True if newly registered, False if key already exists (dedupe).
        """
        with self._lock:
            if leaf.key in self._tasks:
                return False
            # Auto-gate owner-required tasks.
            if leaf.requires_owner_gate and leaf.state == TaskState.READY:
                leaf.state = TaskState.OWNER_GATED
                leaf.updated_at = time.time()
            self._tasks[leaf.key] = leaf
            return True

    def register_many(self, leaves: list[TaskLeaf]) -> int:
        """Register multiple leaves; returns count of newly registered."""
        return sum(1 for leaf in leaves if self.register(leaf))

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def _is_ready(self, leaf: TaskLeaf) -> bool:
        """A leaf is READY iff its state is READY and all deps are completed."""
        if leaf.state != TaskState.READY:
            return False
        return all(
            self._tasks.get(dep, TaskLeaf(
                key=dep, title="", repo="", module="",
                priority=Priority.P0, authority_class=AUTH_WORKSPACE,
                consequence_risk="low", state=TaskState.BLOCKED,
            )).state == TaskState.COMPLETED
            for dep in leaf.dependencies
        )

    def ready_tasks(self, *, limit: int | None = None) -> list[TaskLeaf]:
        """Return ready tasks ordered by (priority asc, created_at asc)."""
        with self._lock:
            candidates = [t for t in self._tasks.values() if self._is_ready(t)]
            candidates.sort(key=lambda t: (t.priority, t.created_at))
            return candidates[:limit] if limit is not None else candidates

    def active_tasks(self) -> list[TaskLeaf]:
        """Tasks currently leased, running, or validating."""
        with self._lock:
            return [t for t in self._tasks.values() if t.state in _ACTIVE]

    def owner_gated_tasks(self) -> list[TaskLeaf]:
        with self._lock:
            return [t for t in self._tasks.values()
                    if t.state == TaskState.OWNER_GATED]

    def blocked_tasks(self) -> list[TaskLeaf]:
        with self._lock:
            return [t for t in self._tasks.values()
                    if t.state == TaskState.BLOCKED]

    def get(self, key: str) -> TaskLeaf | None:
        with self._lock:
            return self._tasks.get(key)

    # ------------------------------------------------------------------
    # Lease / state transitions
    # ------------------------------------------------------------------

    def lease(self, key: str, *, holder: str = "claude") -> TaskLeaf:
        """Atomically lease a task.

        Raises:
            LookupError: task not found.
            ValueError: task not in READY state or deps unmet.
        """
        with self._lock:
            leaf = self._tasks.get(key)
            if leaf is None:
                raise LookupError(f"TASK_NOT_FOUND:{key}")
            if not self._is_ready(leaf):
                raise ValueError(
                    f"TASK_NOT_READY:{key}:state={leaf.state}"
                )
            leaf.state = TaskState.LEASED
            leaf.leased_at = time.time()
            leaf.lease_holder = holder
            leaf.updated_at = leaf.leased_at
            return leaf

    def advance(self, key: str, *, state: str) -> TaskLeaf:
        """Move a leased task to running or validating."""
        with self._lock:
            leaf = self._tasks.get(key)
            if leaf is None:
                raise LookupError(f"TASK_NOT_FOUND:{key}")
            if state not in (TaskState.RUNNING, TaskState.VALIDATING):
                raise ValueError(f"INVALID_ADVANCE_STATE:{state}")
            leaf.state = state
            leaf.updated_at = time.time()
            return leaf

    def complete(
        self,
        key: str,
        *,
        evidence: dict[str, Any] | None = None,
        pr_number: int | None = None,
    ) -> TaskLeaf:
        """Mark a task completed and expose its dependents.

        After completion, any task whose only blocking dependency was this key
        may become READY automatically.
        """
        with self._lock:
            leaf = self._tasks.get(key)
            if leaf is None:
                raise LookupError(f"TASK_NOT_FOUND:{key}")
            leaf.state = TaskState.COMPLETED
            leaf.updated_at = time.time()
            if evidence:
                leaf.evidence.update(evidence)
            if pr_number is not None:
                leaf.pr_number = pr_number
            # Re-evaluate blocked/owner-gated tasks that depended on this key.
            self._propagate_completion(key)
            return leaf

    def _propagate_completion(self, completed_key: str) -> None:
        """Unblock BLOCKED tasks whose only blocker was `completed_key`."""
        for leaf in self._tasks.values():
            if completed_key not in leaf.dependencies:
                continue
            if leaf.state not in (TaskState.BLOCKED,):
                continue
            # Check if all deps are now met.
            if all(
                self._tasks.get(d, TaskLeaf(
                    key=d, title="", repo="", module="",
                    priority=Priority.P0, authority_class=AUTH_WORKSPACE,
                    consequence_risk="low", state=TaskState.BLOCKED,
                )).state == TaskState.COMPLETED
                for d in leaf.dependencies
            ):
                # Still owner-gated if applicable.
                leaf.state = (
                    TaskState.OWNER_GATED if leaf.requires_owner_gate
                    else TaskState.READY
                )
                leaf.blocked_reason = None
                leaf.updated_at = time.time()

    def block(self, key: str, *, reason: str) -> TaskLeaf:
        """Mark a task blocked without killing the program.

        The lease is released; capacity refills from the next eligible leaf.
        """
        with self._lock:
            leaf = self._tasks.get(key)
            if leaf is None:
                raise LookupError(f"TASK_NOT_FOUND:{key}")
            leaf.state = TaskState.BLOCKED
            leaf.blocked_reason = reason
            leaf.leased_at = None
            leaf.lease_holder = None
            leaf.updated_at = time.time()
            return leaf

    def enter_repair_backoff(self, key: str, *, reason: str) -> TaskLeaf:
        """Transition to repair_backoff; task is not executable until recovered."""
        with self._lock:
            leaf = self._tasks.get(key)
            if leaf is None:
                raise LookupError(f"TASK_NOT_FOUND:{key}")
            leaf.state = TaskState.REPAIR_BACKOFF
            leaf.blocked_reason = reason
            leaf.leased_at = None
            leaf.lease_holder = None
            leaf.updated_at = time.time()
            return leaf

    def recover_from_backoff(self, key: str) -> TaskLeaf:
        """Restore a repair-backoff task to READY after a real recovery event."""
        with self._lock:
            leaf = self._tasks.get(key)
            if leaf is None:
                raise LookupError(f"TASK_NOT_FOUND:{key}")
            if leaf.state != TaskState.REPAIR_BACKOFF:
                raise ValueError(f"NOT_IN_BACKOFF:{key}:state={leaf.state}")
            target = (
                TaskState.OWNER_GATED if leaf.requires_owner_gate
                else TaskState.READY
            )
            leaf.state = target
            leaf.blocked_reason = None
            leaf.updated_at = time.time()
            return leaf

    def authorize(self, key: str) -> TaskLeaf:
        """Move an owner-gated task to READY after explicit owner approval."""
        with self._lock:
            leaf = self._tasks.get(key)
            if leaf is None:
                raise LookupError(f"TASK_NOT_FOUND:{key}")
            if leaf.state != TaskState.OWNER_GATED:
                raise ValueError(f"NOT_OWNER_GATED:{key}:state={leaf.state}")
            leaf.state = TaskState.READY
            leaf.updated_at = time.time()
            return leaf

    # ------------------------------------------------------------------
    # Refill
    # ------------------------------------------------------------------

    def refill(self, *, width: int | None = None) -> list[TaskLeaf]:
        """Return up to `width` tasks to admit into active lanes.

        Does NOT auto-lease them; caller leases each individually via `lease()`.
        Returns the ordered candidate list for the dispatcher.
        """
        w = width if width is not None else self.configured_width
        active = len(self.active_tasks())
        slots = max(0, w - active)
        if slots == 0:
            return []
        return self.ready_tasks(limit=slots)

    # ------------------------------------------------------------------
    # Mission Control snapshot
    # ------------------------------------------------------------------

    def snapshot(self, *, next_n: int = 5) -> dict[str, Any]:
        """Return a Mission Control–ready status snapshot."""
        with self._lock:
            active = [t for t in self._tasks.values() if t.state in _ACTIVE]
            ready = sorted(
                [t for t in self._tasks.values() if self._is_ready(t)],
                key=lambda t: (t.priority, t.created_at),
            )
            blocked = [t for t in self._tasks.values()
                       if t.state == TaskState.BLOCKED]
            backoff = [t for t in self._tasks.values()
                       if t.state == TaskState.REPAIR_BACKOFF]
            owner_gated = [t for t in self._tasks.values()
                           if t.state == TaskState.OWNER_GATED]
            completed = [t for t in self._tasks.values()
                         if t.state == TaskState.COMPLETED]

        blocked_reasons = {
            t.key: t.blocked_reason for t in blocked if t.blocked_reason
        }

        return {
            "schema_version": SCHEMA_VERSION,
            "configured_width": self.configured_width,
            "active_count": len(active),
            "active_lanes": [t.to_dict() for t in active],
            "ready_depth": len(ready),
            "blocked_depth": len(blocked),
            "backoff_depth": len(backoff),
            "blocked_reasons": blocked_reasons,
            "owner_gate_count": len(owner_gated),
            "completed_count": len(completed),
            "total_task_count": len(self._tasks),
            "next_tasks": [t.to_dict() for t in ready[:next_n]],
            "owner_gates": [t.to_dict() for t in owner_gated],
            "capacity_idle": max(0, self.configured_width - len(active)),
        }

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema_version": SCHEMA_VERSION,
                "configured_width": self.configured_width,
                "tasks": {k: v.to_dict() for k, v in self._tasks.items()},
            }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DeepOrchestrate:
        orch = cls(configured_width=d.get("configured_width", 5))
        for task_dict in d.get("tasks", {}).values():
            orch._tasks[task_dict["key"]] = TaskLeaf.from_dict(task_dict)
        return orch


# ---------------------------------------------------------------------------
# Canonical seed: P0–P4 task leaves from #1024 priority backlog
# ---------------------------------------------------------------------------


def seed_from_1024() -> list[TaskLeaf]:
    """Seed task leaves from the #1024 canonical priority backlog.

    These represent the decomposed leaves for the rolling-lane queue.
    Leaves are materialized into GitHub issues only when admitted for execution.
    """
    return [
        # P0 — Calyx owner finish line
        TaskLeaf(
            key="backend:calyx:recovery:gate-7-proposal-endpoint",
            title="#1129 CALYX-SUPERSTRUCTURE-004: wire governed proposal endpoint in routes",
            repo="orchid-calyx-backend",
            module="app/calyx_orchestrator",
            priority=Priority.P0,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            dependencies=["backend:calyx:recovery:gates-3-6"],
            acceptance_criteria=[
                "POST /orchestrate/plan accepts structured request",
                "Returns governed plan JSON, no execution side effects",
                "Owner-authenticated; 401 on unauthenticated",
            ],
            issue_number=1129,
        ),
        TaskLeaf(
            key="backend:calyx:recovery:gates-3-6",
            title="#1187/#1179 CALYX-RECOVERY-001 Gates 3–6 + executor binding",
            repo="orchid-calyx-backend",
            module="app/calyx_orchestrator",
            priority=Priority.P0,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            acceptance_criteria=[
                "GovervedResearchExecutor passes 25 focused tests",
                "Arbitrary orchid taxa work end-to-end",
                "Fail-closed: unavailable → BLOCKED, not fabricated",
                "PR #1238 merged into oc-autonomous-integration",
            ],
            issue_number=1187,
            pr_number=1238,
            state=TaskState.COMPLETED,
            evidence={"pr": 1238, "sha": "38cc123", "tests": 106},
        ),
        TaskLeaf(
            key="backend:calyx:agent-gov:task-intent",
            title="#1239/PR#1241 CALYX-AGENT-GOV-001: TaskIntentContract + LeastAgencyGuard",
            repo="orchid-calyx-backend",
            module="app/calyx_orchestrator",
            priority=Priority.P0,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            acceptance_criteria=[
                "TaskIntentContract with material-change fingerprint",
                "AgentBehaviorLedger append-only",
                "LeastAgencyGuard enforcement rules",
                "15 focused tests",
                "PR #1241 merged",
            ],
            issue_number=1239,
            pr_number=1241,
            state=TaskState.COMPLETED,
            evidence={"pr": 1241, "tests": 15},
        ),
        TaskLeaf(
            key="backend:orchestrate:deep-orchestrate:reservoir",
            title="#1024 DEEP ORCHESTRATE: machine-readable task reservoir",
            repo="orchid-calyx-backend",
            module="app/calyx_orchestrator",
            priority=Priority.P0,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            acceptance_criteria=[
                "DeepOrchestrate reservoir with lease exclusivity",
                "Priority ordering, dependency gating, dedupe",
                "Refill after completion/block/CI wait",
                "Owner-gate isolation",
                "Repair-backoff exclusion",
                "Tests for all invariants",
                "Mission Control snapshot",
            ],
            issue_number=1024,
        ),
        # P0 — Research executor (in PR #1238, now merged)
        TaskLeaf(
            key="backend:calyx:research-executor:state-machine",
            title="#1179 BUILD-051 research request state machine",
            repo="orchid-calyx-backend",
            module="app/calyx_orchestrator",
            priority=Priority.P0,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            dependencies=["backend:calyx:recovery:gates-3-6"],
            acceptance_criteria=[
                "queued_waiting_for_executor → queued → running → completed|blocked",
                "Idempotent: same request_id → same project_id and artifact",
                "Fail-closed: literature unavailable → BLOCKED",
            ],
            issue_number=1179,
            pr_number=1238,
            state=TaskState.COMPLETED,
            evidence={"pr": 1238, "tests": 25},
        ),
        # P0 — Literature ingest
        TaskLeaf(
            key="backend:literature:odontalliance:corpus-intake",
            title="CALYX-LIT-IOA-001: governed Odontoglossum Alliance corpus intake",
            repo="orchid-calyx-backend",
            module="app/literature_extraction",
            priority=Priority.P0,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            acceptance_criteria=[
                "Corpus intake from Odontoglossum Alliance HTML",
                "Extraction pipeline runs",
                "Tests pass",
                "PR merged",
            ],
            pr_number=1237,
            state=TaskState.COMPLETED,
            evidence={"pr": 1237},
        ),
        # P1 — Calyx flywheel
        TaskLeaf(
            key="backend:calyx:flywheel:scientific-simulation",
            title="#1139 Calyx Flywheel 2/6 — scientific simulation and regression library",
            repo="orchid-calyx-backend",
            module="app/calyx_flywheel",
            priority=Priority.P1,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            acceptance_criteria=[
                "Simulation contracts for scientific regression testing",
                "Focused tests",
                "Draft PR on oc-autonomous-integration",
            ],
            issue_number=1139,
        ),
        # P1 — Cost/provider
        TaskLeaf(
            key="backend:orchestrate:cost:adaptive-budgeting",
            title="#1136 P1 OC-COST-001: adaptive model/turn budgeting",
            repo="orchid-calyx-backend",
            module="app/calyx_orchestrator",
            priority=Priority.P1,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            acceptance_criteria=[
                "Budget-aware routing in meta-orchestrator",
                "Cache reuse heuristics",
                "Batched low-risk planning",
            ],
            issue_number=1136,
        ),
        # P1 — NAOCC conservation reasoning
        TaskLeaf(
            key="backend:calyx:naocc:conservation-reasoning",
            title="#1096 P1 CALYX-NAOCC-POC-001: public-corpus conservation reasoning",
            repo="orchid-calyx-backend",
            module="app/calyx_conversation",
            priority=Priority.P1,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            acceptance_criteria=[
                "Conservation reasoning from public corpus without KG mutation",
                "Evidence state distinctions preserved",
                "Proof-of-concept tests",
            ],
            issue_number=1096,
        ),
        # P2 — KG materialization readiness
        TaskLeaf(
            key="backend:kg:materialization:dry-run",
            title="#1085 P0 OC-COMPLETE-003: scientific coverage and backfill matrix",
            repo="orchid-calyx-backend",
            module="app/literature_extraction",
            priority=Priority.P0,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="medium",
            acceptance_criteria=[
                "Coverage matrix across canonical taxa",
                "Dry-run reviewed publication plan",
                "No production KG mutation",
            ],
            issue_number=1085,
        ),
        # P2 — Literature corpus correction
        TaskLeaf(
            key="backend:literature:corpus:source-correction",
            title="#1030 TWO-DAY-SLICE-E: canonical literature corpus and extraction coverage telemetry",
            repo="orchid-calyx-backend",
            module="app/literature_extraction",
            priority=Priority.P2,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            acceptance_criteria=[
                "Stop masking ~6,725 research_documents behind tiny subsets",
                "Document discovery vs scientific evidence distinction preserved",
                "Coverage telemetry exposed",
            ],
            issue_number=1030,
        ),
        # P2 — Engineering memory
        TaskLeaf(
            key="backend:engineering-memory:activation",
            title="BUILD-1184 Engineering memory activation and evaluation",
            repo="orchid-calyx-backend",
            module="app/engineering_memory",
            priority=Priority.P2,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            acceptance_criteria=[
                "Engineering memory service activated",
                "Savings evaluation script passes",
                "API routes registered",
            ],
        ),
        # P3 — Harvester productivity
        TaskLeaf(
            key="backend:harvester:productivity-dashboard",
            title="P3 Harvester productivity dashboard (backend #1008)",
            repo="orchid-calyx-backend",
            module="app",
            priority=Priority.P3,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            acceptance_criteria=[
                "24h/7d/30d fetched/accepted/new/deduped/linked/graph yield/failures/staleness/cost-value",
                "Exposed via Mission Control API",
            ],
        ),
        # P4 — Event-driven continuation
        TaskLeaf(
            key="backend:orchestrate:event-driven:continuation",
            title="#1023 ORCHESTRATION-EVENT-DRIVEN-001: trigger follow-through on completion",
            repo="orchid-calyx-backend",
            module="app/calyx_orchestrator",
            priority=Priority.P4,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            acceptance_criteria=[
                "CI/Claude completion triggers next safe task",
                "Webhook or polling continuation path",
            ],
            issue_number=1023,
        ),
        # Production/owner-gated — never auto-dispatched
        TaskLeaf(
            key="backend:production:db-migration:apply",
            title="Apply pending DB migrations to production",
            repo="orchid-calyx-backend",
            module="migrations",
            priority=Priority.P0,
            authority_class=AUTH_PRODUCTION,
            consequence_risk="high",
            acceptance_criteria=[
                "Migrations reviewed and approved by owner",
                "Staging run validated",
                "Production apply with rollback plan",
            ],
        ),
        TaskLeaf(
            key="backend:science:kg-mutation:publish",
            title="Scientific knowledge publication to production KG",
            repo="orchid-calyx-backend",
            module="app/literature_extraction",
            priority=Priority.P2,
            authority_class=AUTH_SCIENCE_PUB,
            consequence_risk="high",
            acceptance_criteria=[
                "Publication plan reviewed by owner",
                "Exact evidence provenance preserved",
                "Review gate cleared",
            ],
        ),
    ]
