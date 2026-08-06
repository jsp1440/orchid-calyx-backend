from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class AgentRole(StrEnum):
    ENGINEERING_DIRECTOR = "engineering_director"
    BUILD_DEVOPS_ENGINEER = "build_devops_engineer"
    FRONTEND_ENGINEER = "frontend_engineer"
    BACKEND_ENGINEER = "backend_engineer"
    KNOWLEDGE_GRAPH_ENGINEER = "knowledge_graph_engineer"
    BRAIN_ENGINEER = "brain_engineer"


class TerminalOutcome(StrEnum):
    DELIVERED = "DELIVERED"
    BLOCKED = "BLOCKED"
    NO_OP = "NO_OP"
    CANCELLED = "CANCELLED"
    DEAD_LETTER = "DEAD_LETTER"


@dataclass(frozen=True)
class AgentRoleSpec:
    role: AgentRole
    title: str
    mission: str
    may_mutate_code: bool
    requires_human_merge: bool = True


AGENT_ROLE_REGISTRY: dict[AgentRole, AgentRoleSpec] = {
    AgentRole.ENGINEERING_DIRECTOR: AgentRoleSpec(
        role=AgentRole.ENGINEERING_DIRECTOR,
        title="Engineering Director",
        mission="Plan bounded programs, coordinate dependencies, and consolidate evidence.",
        may_mutate_code=False,
    ),
    AgentRole.BUILD_DEVOPS_ENGINEER: AgentRoleSpec(
        role=AgentRole.BUILD_DEVOPS_ENGINEER,
        title="Build and DevOps Engineer",
        mission="Repair CI, validate releases, and report deployment blockers without deploying.",
        may_mutate_code=True,
    ),
    AgentRole.FRONTEND_ENGINEER: AgentRoleSpec(
        role=AgentRole.FRONTEND_ENGINEER,
        title="Frontend Engineer",
        mission="Repair and extend governed user interfaces and live-data presentation.",
        may_mutate_code=True,
    ),
    AgentRole.BACKEND_ENGINEER: AgentRoleSpec(
        role=AgentRole.BACKEND_ENGINEER,
        title="Backend Engineer",
        mission="Implement protected APIs, persistence, and service integrations.",
        may_mutate_code=True,
    ),
    AgentRole.KNOWLEDGE_GRAPH_ENGINEER: AgentRoleSpec(
        role=AgentRole.KNOWLEDGE_GRAPH_ENGINEER,
        title="Knowledge Graph Engineer",
        mission="Advance bounded staging, validation, and graph-readiness work without publication.",
        may_mutate_code=True,
    ),
    AgentRole.BRAIN_ENGINEER: AgentRoleSpec(
        role=AgentRole.BRAIN_ENGINEER,
        title="Brain Engineer",
        mission="Advance evidence-to-ledger reasoning while preserving review and publication gates.",
        may_mutate_code=True,
    ),
}


@dataclass(frozen=True)
class EngineeringWorkIdentity:
    job_id: str
    role: AgentRole
    repository: str
    branch: str | None = None
    mutates_code: bool = False
    status: str = "queued"


@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    code: str
    message: str


class EngineeringAdmissionPolicy:
    """Deterministic concurrency policy for governed engineering jobs."""

    def __init__(
        self,
        *,
        max_global_active: int = 6,
        max_repository_active: int = 2,
        max_mutating_per_branch: int = 1,
    ) -> None:
        if min(max_global_active, max_repository_active, max_mutating_per_branch) < 1:
            raise ValueError("CONCURRENCY_LIMITS_MUST_BE_POSITIVE")
        self.max_global_active = max_global_active
        self.max_repository_active = max_repository_active
        self.max_mutating_per_branch = max_mutating_per_branch

    def evaluate(
        self,
        candidate: EngineeringWorkIdentity,
        active: Iterable[EngineeringWorkIdentity],
    ) -> AdmissionDecision:
        active_jobs = tuple(item for item in active if item.status == "running")
        if any(item.job_id == candidate.job_id for item in active_jobs):
            return AdmissionDecision(False, "DUPLICATE_ACTIVE_JOB", "The job is already active.")
        if len(active_jobs) >= self.max_global_active:
            return AdmissionDecision(False, "GLOBAL_CAPACITY_REACHED", "All global engineering slots are occupied.")

        repository_jobs = tuple(item for item in active_jobs if item.repository == candidate.repository)
        if len(repository_jobs) >= self.max_repository_active:
            return AdmissionDecision(False, "REPOSITORY_CAPACITY_REACHED", "The repository active-job limit is reached.")

        if candidate.mutates_code:
            if not candidate.branch:
                return AdmissionDecision(False, "MUTATING_JOB_REQUIRES_BRANCH", "A mutating job must name its authoritative branch.")
            branch_mutators = tuple(
                item
                for item in repository_jobs
                if item.mutates_code and item.branch == candidate.branch
            )
            if len(branch_mutators) >= self.max_mutating_per_branch:
                return AdmissionDecision(False, "BRANCH_MUTATION_LOCKED", "Another mutating job owns this branch.")

        return AdmissionDecision(True, "ADMITTED", "Capacity and branch constraints permit execution.")


def get_agent_role_spec(role: AgentRole | str) -> AgentRoleSpec:
    normalized = role if isinstance(role, AgentRole) else AgentRole(role)
    return AGENT_ROLE_REGISTRY[normalized]
