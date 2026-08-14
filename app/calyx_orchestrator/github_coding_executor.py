from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Protocol, Sequence

from .engineering_core import TerminalOutcome
from .executor import ExecutionReceipt, ExecutionState, GovernedAssignment, canonical_checksum

GITHUB_CODING_ROLE = "github_coding_agent"
MAX_SAME_FAILURE_RETRIES = 3


class ConvergenceClass(StrEnum):
    NEW = "NEW"
    CONTINUE = "CONTINUE"
    CONVERGE = "CONVERGE"
    SUPERSEDE = "SUPERSEDE"
    ALREADY_DONE = "ALREADY_DONE"


class BudgetClass(StrEnum):
    TINY = "TINY"
    SMALL = "SMALL"
    NORMAL = "NORMAL"
    DEEP = "DEEP"
    EXCEPTIONAL = "EXCEPTIONAL"


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    repository: str
    base_ref: str
    base_sha: str
    related_issue_numbers: tuple[int, ...] = ()
    overlapping_pr_numbers: tuple[int, ...] = ()
    continuation_pr_numbers: tuple[int, ...] = ()
    convergence_pr_numbers: tuple[int, ...] = ()
    superseded_pr_numbers: tuple[int, ...] = ()
    implementation_complete: bool = False


@dataclass(frozen=True, slots=True)
class DispatchRequest:
    mission_id: str
    repository: str
    objective: str
    acceptance_criteria: tuple[str, ...]
    validation_commands: tuple[str, ...]
    budget_class: BudgetClass
    convergence_class: ConvergenceClass
    base_ref: str
    base_sha: str
    related_issue_numbers: tuple[int, ...]
    overlapping_pr_numbers: tuple[int, ...]
    continuation_pr_numbers: tuple[int, ...]
    convergence_pr_numbers: tuple[int, ...]
    superseded_pr_numbers: tuple[int, ...]
    retry_count: int


@dataclass(frozen=True, slots=True)
class DispatchResult:
    provider: str
    executor_class: str
    repository: str
    base_sha: str
    branch: str | None
    issue_number: int | None
    pull_request_number: int | None
    pull_request_url: str | None
    draft: bool
    head_sha: str | None = None
    state: str = "dispatched"
    validation_evidence: tuple[str, ...] = ()
    blocker_code: str | None = None


class RepositoryInspectionGateway(Protocol):
    def inspect(
        self,
        *,
        repository: str,
        objective: str,
        mission_id: str,
    ) -> RepositorySnapshot: ...


class CodingAgentProvider(Protocol):
    provider_name: str
    executor_class: str

    def dispatch(self, request: DispatchRequest) -> DispatchResult: ...


def classify_convergence(snapshot: RepositorySnapshot) -> ConvergenceClass:
    if snapshot.implementation_complete:
        return ConvergenceClass.ALREADY_DONE
    if snapshot.convergence_pr_numbers:
        return ConvergenceClass.CONVERGE
    if snapshot.continuation_pr_numbers:
        return ConvergenceClass.CONTINUE
    if snapshot.superseded_pr_numbers:
        return ConvergenceClass.SUPERSEDE
    return ConvergenceClass.NEW


def _tuple_of_strings(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field}_MUST_BE_SEQUENCE")
    return tuple(str(item).strip() for item in value if str(item).strip())


def _parse_budget(value: object) -> BudgetClass:
    raw = str(value or BudgetClass.NORMAL.value).strip().upper()
    try:
        return BudgetClass(raw)
    except ValueError as exc:
        raise ValueError("GITHUB_CODING_BUDGET_CLASS_INVALID") from exc


def _nonnegative_retry_count(value: object) -> int:
    try:
        count = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("GITHUB_CODING_RETRY_COUNT_INVALID") from exc
    if count < 0:
        raise ValueError("GITHUB_CODING_RETRY_COUNT_INVALID")
    return count


class GitHubCodingAgentExecutor:
    """Provider-neutral dispatcher for governed GitHub coding-agent work.

    Mission identity stays in Calyx/Brain; provider identity is receipt metadata.
    Credentials live only behind injected adapters. This executor grants no merge,
    deployment, production mutation, publication, taxonomy activation, credential,
    spending, force-push, branch-deletion, or repository-deletion authority.
    """

    executor_key = "github_coding_agent_v1"

    def __init__(
        self,
        *,
        inspector: RepositoryInspectionGateway,
        provider: CodingAgentProvider,
    ) -> None:
        self.inspector = inspector
        self.provider = provider

    def execute(self, assignment: GovernedAssignment) -> ExecutionReceipt:
        if assignment.role_key != GITHUB_CODING_ROLE:
            raise PermissionError("GITHUB_CODING_ROLE_REQUIRED")
        job = assignment.inputs.get("job")
        if not isinstance(job, Mapping):
            raise TypeError("GITHUB_CODING_JOB_INPUT_REQUIRED")
        if assignment.cancelled:
            return self._blocked_receipt(
                assignment,
                "ASSIGNMENT_CANCELLED",
                {"status": "cancelled", "executed": False},
                state=ExecutionState.CANCELLED,
                outcome=TerminalOutcome.CANCELLED,
            )

        repository = str(job.get("repository") or "").strip()
        objective = str(job.get("objective") or assignment.objective or "").strip()
        mission_id = str(job.get("mission_id") or assignment.job_key).strip()
        if not repository:
            raise ValueError("GITHUB_CODING_REPOSITORY_REQUIRED")
        if not objective:
            raise ValueError("GITHUB_CODING_OBJECTIVE_REQUIRED")
        if not mission_id:
            raise ValueError("GITHUB_CODING_MISSION_ID_REQUIRED")

        retry_count = _nonnegative_retry_count(job.get("same_failure_retry_count"))
        if retry_count >= MAX_SAME_FAILURE_RETRIES:
            return self._blocked_receipt(
                assignment,
                "RETRY_BUDGET_EXHAUSTED",
                {
                    "status": "blocked",
                    "executed": False,
                    "mission_id": mission_id,
                    "repository": repository,
                    "retry_count": retry_count,
                    "max_same_failure_retries": MAX_SAME_FAILURE_RETRIES,
                    "escalation": "integrator_or_reviewer",
                },
            )

        snapshot = self.inspector.inspect(
            repository=repository,
            objective=objective,
            mission_id=mission_id,
        )
        if snapshot.repository != repository:
            raise PermissionError("GITHUB_CODING_INSPECTION_REPOSITORY_MISMATCH")
        if not snapshot.base_sha or len(snapshot.base_sha) != 40:
            raise ValueError("GITHUB_CODING_BASE_SHA_INVALID")

        convergence = classify_convergence(snapshot)
        if convergence == ConvergenceClass.ALREADY_DONE:
            output = {
                "status": "already_done",
                "executed": False,
                "mission_id": mission_id,
                "repository": repository,
                "convergence_class": convergence.value,
                "base_ref": snapshot.base_ref,
                "base_sha": snapshot.base_sha,
                "related_issue_numbers": list(snapshot.related_issue_numbers),
                "overlapping_pr_numbers": list(snapshot.overlapping_pr_numbers),
                "branch_created": False,
                "pull_request_created": False,
                "side_effects": [],
            }
            return self._delivered_receipt(assignment, output)

        request = DispatchRequest(
            mission_id=mission_id,
            repository=repository,
            objective=objective,
            acceptance_criteria=_tuple_of_strings(job.get("acceptance_criteria"), "ACCEPTANCE_CRITERIA"),
            validation_commands=_tuple_of_strings(job.get("validation_commands"), "VALIDATION_COMMANDS"),
            budget_class=_parse_budget(job.get("budget_class")),
            convergence_class=convergence,
            base_ref=snapshot.base_ref,
            base_sha=snapshot.base_sha,
            related_issue_numbers=snapshot.related_issue_numbers,
            overlapping_pr_numbers=snapshot.overlapping_pr_numbers,
            continuation_pr_numbers=snapshot.continuation_pr_numbers,
            convergence_pr_numbers=snapshot.convergence_pr_numbers,
            superseded_pr_numbers=snapshot.superseded_pr_numbers,
            retry_count=retry_count,
        )
        result = self.provider.dispatch(request)
        if result.repository != repository or result.base_sha != snapshot.base_sha:
            raise PermissionError("GITHUB_CODING_DISPATCH_IDENTITY_MISMATCH")
        if not result.draft:
            raise PermissionError("GITHUB_CODING_NON_DRAFT_PR_PROHIBITED")
        if result.state == "dispatched" and result.pull_request_number is None:
            raise ValueError("GITHUB_CODING_DISPATCH_PR_REQUIRED")

        output = {
            "status": result.state,
            "executed": True,
            "mission_id": mission_id,
            "repository": repository,
            "convergence_class": convergence.value,
            "base_ref": snapshot.base_ref,
            "base_sha": snapshot.base_sha,
            "related_issue_numbers": list(snapshot.related_issue_numbers),
            "overlapping_pr_numbers": list(snapshot.overlapping_pr_numbers),
            "provider": result.provider,
            "executor_class": result.executor_class,
            "branch": result.branch,
            "issue_number": result.issue_number,
            "pull_request_number": result.pull_request_number,
            "pull_request_url": result.pull_request_url,
            "draft": result.draft,
            "head_sha": result.head_sha,
            "retry_count": retry_count,
            "max_same_failure_retries": MAX_SAME_FAILURE_RETRIES,
            "validation_evidence": list(result.validation_evidence),
            "blocker_code": result.blocker_code,
            "automatic_merge": False,
            "automatic_deployment": False,
            "production_mutation": False,
            "publication": False,
        }
        evidence = tuple(
            item
            for item in (
                *assignment.evidence_uris,
                f"repo-commit:{repository}@{snapshot.base_sha}",
                result.pull_request_url,
                *result.validation_evidence,
            )
            if item
        )
        return self._delivered_receipt(assignment, output, evidence_uris=evidence)

    def _delivered_receipt(
        self,
        assignment: GovernedAssignment,
        output: Mapping[str, object],
        *,
        evidence_uris: tuple[str, ...] | None = None,
    ) -> ExecutionReceipt:
        receipt = ExecutionReceipt(
            assignment_id=assignment.assignment_id,
            program_id=assignment.program_id,
            job_key=assignment.job_key,
            executor_key=self.executor_key,
            state=ExecutionState.DELIVERED,
            outcome=TerminalOutcome.DELIVERED,
            input_checksum=assignment.verified_input_checksum(),
            output_checksum=canonical_checksum(output),
            output=output,
            evidence_uris=evidence_uris or assignment.evidence_uris,
        )
        receipt.verify()
        return receipt

    def _blocked_receipt(
        self,
        assignment: GovernedAssignment,
        blocker_code: str,
        output: Mapping[str, object],
        *,
        state: ExecutionState = ExecutionState.BLOCKED,
        outcome: TerminalOutcome = TerminalOutcome.BLOCKED,
    ) -> ExecutionReceipt:
        receipt = ExecutionReceipt(
            assignment_id=assignment.assignment_id,
            program_id=assignment.program_id,
            job_key=assignment.job_key,
            executor_key=self.executor_key,
            state=state,
            outcome=outcome,
            input_checksum=assignment.verified_input_checksum(),
            output_checksum=canonical_checksum(output),
            output=output,
            evidence_uris=assignment.evidence_uris,
            blocker_code=blocker_code,
        )
        receipt.verify()
        return receipt
