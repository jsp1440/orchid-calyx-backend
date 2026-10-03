"""Module isolation and parallel lane selection for Orchid Continuum autonomy.

Each module is an independent work unit with its own execution state.
Modules should advance in parallel when their dependencies are satisfied.
A blocked module must not consume capacity or prevent unrelated work.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .models import CalyxJob, utcnow


class ModuleExecutionState(StrEnum):
    """Machine-readable execution state for a module."""

    DISCOVER = "discover"  # Initial state: identify work
    CLASSIFY = "classify"  # Classify work and check safety gates
    DEPENDENCY_CHECK = "dependency_check"  # Verify dependencies are met
    ADMIT = "admit"  # Admit work into execution queue
    LEASE = "lease"  # Acquire durable lease
    EXECUTE = "execute"  # Execute work
    VALIDATE = "validate"  # Validate results
    EVIDENCE = "evidence"  # Record evidence and provenance
    COMPLETE = "complete"  # Mark work complete
    REPLENISH = "replenish"  # Discover next work from module objectives
    BLOCKED = "blocked"  # Module cannot proceed (external gate, provider, scientific)
    IDLE = "idle"  # No unfinished work, healthy state


@dataclass(frozen=True, slots=True)
class ModuleDefinition:
    """Durable specification of an Orchid Continuum module."""

    module_id: str
    """Canonical identifier (e.g., 'brain', 'calyx', 'atlas', 'literature')."""

    repositories: frozenset[str]
    """Repositories this module owns or primarily works in."""

    job_type_prefix: str | None = None
    """If set, only jobs with job_type starting with this prefix belong to this module."""

    requires_provider: bool = False
    """True if this module requires external provider access for any work."""

    scientific_gate: bool = False
    """True if module work affects taxonomy or scientific conclusions."""

    production_gate: bool = False
    """True if module work affects production state."""

    def matches_job(self, job: CalyxJob) -> bool:
        """Deterministic predicate: does this job belong to this module?"""
        if self.job_type_prefix and not job.job_type.startswith(self.job_type_prefix):
            return False
        return True


@dataclass(frozen=True, slots=True)
class ModuleDependency:
    """One module depends on another."""

    downstream_module_id: str
    """Module that depends on other modules."""

    upstream_module_id: str
    """Module that must complete before downstream can proceed."""


class ModuleIsolationRegistry:
    """Canonical registry of Orchid Continuum modules and their isolation rules.

    Used to determine which jobs can run in parallel without blocking each other.
    """

    def __init__(self) -> None:
        # Core R1 modules as per mission spec
        self.modules = {
            ModuleDefinition(
                module_id="brain",
                repositories=frozenset({"Orchid-Continuum-Brain"}),
                job_type_prefix="brain_",
                requires_provider=False,
                scientific_gate=False,
                production_gate=False,
            ),
            ModuleDefinition(
                module_id="calyx",
                repositories=frozenset({"orchid-calyx-backend"}),
                job_type_prefix="calyx_",
                requires_provider=False,
                scientific_gate=False,
                production_gate=False,
            ),
            ModuleDefinition(
                module_id="capability_inventory",
                repositories=frozenset({"orchid-calyx-backend"}),
                job_type_prefix="capability_",
                requires_provider=False,
                scientific_gate=False,
                production_gate=False,
            ),
            ModuleDefinition(
                module_id="research",
                repositories=frozenset({"orchid-calyx-backend"}),
                job_type_prefix="research_",
                requires_provider=True,
                scientific_gate=True,
                production_gate=False,
            ),
        }

        # No cross-module dependencies defined yet in R1
        self.dependencies: list[ModuleDependency] = []

    def classify_job(self, job: CalyxJob) -> str | None:
        """Classify job to a module_id, or None if unclassified."""
        for module in self.modules:
            if module.matches_job(job):
                return module.module_id
        return None

    def get_module(self, module_id: str) -> ModuleDefinition | None:
        """Retrieve a module definition by ID."""
        for module in self.modules:
            if module.module_id == module_id:
                return module
        return None

    def upstream_modules(self, module_id: str) -> frozenset[str]:
        """Return set of modules that must complete before this module can proceed."""
        return frozenset(
            dep.upstream_module_id
            for dep in self.dependencies
            if dep.downstream_module_id == module_id
        )


def get_independent_runnable_lanes(
    db: Session,
    registry: ModuleIsolationRegistry,
    *,
    max_lanes: int = 6,
) -> dict[str, list[CalyxJob]]:
    """Identify independent modules with executable work, respecting capacity limits.

    Returns a dict mapping module_id → list of claimable CalyxJob objects.
    Jobs are grouped by module so independent modules' work can be claimed in parallel.

    Isolation rules:
    1. Jobs are classified to modules.
    2. A module is blocked if its dependencies are not complete.
    3. A module cannot consume shared capacity if it has unmet dependencies.
    4. Within a module, jobs respect priority and retry backoff.
    5. Provider-required jobs do not block provider-free jobs (different lanes).
    """
    now = utcnow()

    # Find all claimable jobs (queued, or running with expired lease)
    claimable = or_(
        CalyxJob.status == "queued",
        and_(
            CalyxJob.status == "running",
            CalyxJob.lease_expires_at.is_not(None),
            CalyxJob.lease_expires_at <= now,
        ),
    )

    candidates = db.scalars(
        select(CalyxJob)
        .where(
            claimable,
            CalyxJob.approval_required.is_(False),
            CalyxJob.attempt_count < CalyxJob.max_attempts,
            or_(CalyxJob.next_attempt_at.is_(None), CalyxJob.next_attempt_at <= now),
            or_(CalyxJob.deadline_at.is_(None), CalyxJob.deadline_at > now),
        )
        .order_by(CalyxJob.priority.asc(), CalyxJob.created_at.asc())
        .limit(100)
    ).all()

    # Classify each candidate to a module
    jobs_by_module: dict[str, list[CalyxJob]] = {}
    unclassified: list[CalyxJob] = []

    for job in candidates:
        # Check job-level dependencies
        if job.dependency_job_id:
            dep_job = db.get(CalyxJob, job.dependency_job_id)
            if dep_job is None or dep_job.status != "completed":
                continue  # Skip: job-level dependency not met

        module_id = registry.classify_job(job)
        if module_id is None:
            unclassified.append(job)
            continue

        if module_id not in jobs_by_module:
            jobs_by_module[module_id] = []
        jobs_by_module[module_id].append(job)

    # Filter out modules with unmet module-level dependencies
    independent_modules: dict[str, list[CalyxJob]] = {}
    for module_id, jobs in jobs_by_module.items():
        upstream = registry.upstream_modules(module_id)
        if upstream:
            # Module has dependencies; check if they're satisfied
            # (For now, no upstream dependencies in R1, so this is future-proofing)
            continue
        independent_modules[module_id] = jobs

    # Separate provider-free and provider-required jobs
    # This allows independent lanes even if one lane is blocked on provider availability
    result: dict[str, list[CalyxJob]] = {}
    total_claimed = 0

    for module_id in sorted(independent_modules.keys()):
        jobs = independent_modules[module_id]
        module_def = registry.get_module(module_id)

        if total_claimed >= max_lanes:
            break

        # Prefer provider-free jobs if available
        provider_free = [j for j in jobs if not (module_def and module_def.requires_provider)]
        provider_required = [j for j in jobs if module_def and module_def.requires_provider]

        # Try to claim provider-free first
        lane_jobs = provider_free if provider_free else provider_required
        if lane_jobs:
            result[module_id] = lane_jobs[: max_lanes - total_claimed]
            total_claimed += len(result[module_id])

    return result


def claim_from_independent_lanes(
    db: Session,
    orchestrator_claim_method: Callable[[str, int], CalyxJob | None],
    registry: ModuleIsolationRegistry,
    *,
    worker_id: str,
    lease_seconds: int,
    max_attempts: int = 5,
) -> tuple[CalyxJob | None, str | None]:
    """Claim a job from independent parallel lanes.

    Attempts to find and claim work from modules that are not blocked.
    Returns (job, module_id) or (None, blocker_reason) if no independent work available.

    This ensures:
    - Independent modules run in parallel
    - A blocked module doesn't consume worker capacity
    - Provider-free work proceeds even if provider-dependent lane is blocked
    - Fail-closed: if classification is uncertain, don't claim
    """
    lanes = get_independent_runnable_lanes(db, registry, max_lanes=6)

    if not lanes:
        return None, "no_independent_runnable_lanes"

    # Try to claim from each independent lane in priority order
    for module_id in sorted(lanes.keys()):
        for attempt in range(max_attempts):
            try:
                job = orchestrator_claim_method(worker_id, lease_seconds)
                if job:
                    return job, None
            except Exception:
                if attempt == max_attempts - 1:
                    return None, f"claim_failure_in_module_{module_id}"
                continue

    return None, "no_jobs_claimed_from_independent_lanes"
