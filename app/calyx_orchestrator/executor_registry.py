from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .engineering_core import TerminalOutcome
from .executor import (
    ExecutionReceipt,
    ExecutionState,
    ExecutorAdapter,
    GovernedAssignment,
    canonical_checksum,
)
from .isolated_patch_executor import ISOLATED_PATCH_ROLE, IsolatedWorkspacePatchExecutor
from .repository_evidence_executor import (
    REPOSITORY_EVIDENCE_ROLE,
    RepositoryEvidenceExecutor,
)
from .static_validation_executor import (
    STATIC_VALIDATION_ROLE,
    IsolatedWorkspaceStaticValidationExecutor,
)

AUTONOMY_PROBE_ROLE = "autonomy_probe"


class AutonomyProbeExecutor:
    """Authoritative only for explicit non-mutating orchestration probe jobs."""

    executor_key = "autonomy_probe_v1"

    def execute(self, assignment: GovernedAssignment) -> ExecutionReceipt:
        job = assignment.inputs.get("job")
        if not isinstance(job, dict):
            raise TypeError("AUTONOMY_PROBE_JOB_INPUT_REQUIRED")
        if assignment.role_key != AUTONOMY_PROBE_ROLE:
            raise PermissionError("AUTONOMY_PROBE_ROLE_REQUIRED")
        if bool(job.get("mutating_intent")):
            raise PermissionError("AUTONOMY_PROBE_MUTATION_PROHIBITED")
        input_checksum = assignment.verified_input_checksum()
        output = {
            "status": "delivered",
            "executed": True,
            "mode": "authoritative_internal_probe",
            "probe": "scheduler_claim_receipt_dependency_chain",
            "side_effects": [],
        }
        receipt = ExecutionReceipt(
            assignment_id=assignment.assignment_id,
            program_id=assignment.program_id,
            job_key=assignment.job_key,
            executor_key=self.executor_key,
            state=ExecutionState.DELIVERED,
            outcome=TerminalOutcome.DELIVERED,
            input_checksum=input_checksum,
            output_checksum=canonical_checksum(output),
            output=output,
            evidence_uris=assignment.evidence_uris,
        )
        receipt.verify()
        return receipt


@dataclass(frozen=True, slots=True)
class RegisteredExecutor:
    role_key: str
    executor: ExecutorAdapter
    authoritative: bool
    external_side_effects: bool
    workspace_mutation: bool = False
    repository_code_execution: bool = False


class AuthoritativeExecutorRegistry:
    """Explicit allowlist of job roles that autonomous workers may complete."""

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        repository_name: str | None = None,
    ) -> None:
        probe = AutonomyProbeExecutor()
        repository_reader = RepositoryEvidenceExecutor(
            workspace_root=workspace_root,
            repository_name=repository_name,
        )
        isolated_patcher = IsolatedWorkspacePatchExecutor(
            workspace_root=workspace_root,
            repository_name=repository_name,
        )
        static_validator = IsolatedWorkspaceStaticValidationExecutor(
            workspace_root=workspace_root,
            repository_name=repository_name,
        )
        self._by_role = {
            AUTONOMY_PROBE_ROLE: RegisteredExecutor(
                role_key=AUTONOMY_PROBE_ROLE,
                executor=probe,
                authoritative=True,
                external_side_effects=False,
            ),
            REPOSITORY_EVIDENCE_ROLE: RegisteredExecutor(
                role_key=REPOSITORY_EVIDENCE_ROLE,
                executor=repository_reader,
                authoritative=True,
                external_side_effects=False,
            ),
            ISOLATED_PATCH_ROLE: RegisteredExecutor(
                role_key=ISOLATED_PATCH_ROLE,
                executor=isolated_patcher,
                authoritative=True,
                external_side_effects=False,
                workspace_mutation=True,
            ),
            STATIC_VALIDATION_ROLE: RegisteredExecutor(
                role_key=STATIC_VALIDATION_ROLE,
                executor=static_validator,
                authoritative=True,
                external_side_effects=False,
                workspace_mutation=False,
                repository_code_execution=False,
            ),
        }

    @property
    def eligible_role_keys(self) -> frozenset[str]:
        return frozenset(
            role_key
            for role_key, registered in self._by_role.items()
            if registered.authoritative
        )

    def require_authoritative(self, role_key: str) -> RegisteredExecutor:
        registered = self._by_role.get(role_key)
        if registered is None or not registered.authoritative:
            raise LookupError("AUTHORITATIVE_EXECUTOR_NOT_REGISTERED")
        if registered.external_side_effects:
            raise PermissionError("EXTERNAL_SIDE_EFFECT_EXECUTOR_NOT_ALLOWED")
        return registered

    def status(self) -> dict[str, object]:
        return {
            "authoritative_roles": sorted(self.eligible_role_keys),
            "sandboxed_repository_code_execution_authorized": False,
            "executors": [
                {
                    "role_key": registered.role_key,
                    "executor_key": registered.executor.executor_key,
                    "authoritative": registered.authoritative,
                    "external_side_effects": registered.external_side_effects,
                    "workspace_mutation": registered.workspace_mutation,
                    "repository_code_execution": registered.repository_code_execution,
                }
                for registered in sorted(self._by_role.values(), key=lambda item: item.role_key)
            ],
        }
