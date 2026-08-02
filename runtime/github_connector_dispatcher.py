"""Audited, idempotent dispatcher for governed draft-only GitHub commands."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Callable, ClassVar


@dataclass(frozen=True)
class GitHubDispatchCommand:
    repository: str
    operation: str
    payload: dict[str, Any]
    draft: bool = True


@dataclass(frozen=True)
class DispatchReceipt:
    receipt_id: str
    command_id: str
    repository: str
    operation: str
    status: str
    result: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuditedGitHubDispatcher:
    """Execute only allowlisted draft operations and retain immutable receipts."""

    allowed_operations: ClassVar[set[str]] = {
        "create_branch",
        "create_draft_pull_request",
    }

    def __init__(self, repository_allowlist: tuple[str, ...]) -> None:
        self._repository_allowlist = frozenset(repository_allowlist)
        self._receipts: dict[str, DispatchReceipt] = {}

    def dispatch(
        self,
        command: GitHubDispatchCommand,
        executor: Callable[[GitHubDispatchCommand], dict[str, Any]],
    ) -> DispatchReceipt:
        self._validate(command)
        command_id = self._command_id(command)
        existing = self._receipts.get(command_id)
        if existing is not None:
            return existing

        result = executor(command)
        if not isinstance(result, dict):
            raise TypeError("connector executor must return a dictionary")
        receipt = DispatchReceipt(
            receipt_id=f"receipt-{command_id.removeprefix('cmd-')}",
            command_id=command_id,
            repository=command.repository,
            operation=command.operation,
            status="executed",
            result=dict(result),
        )
        self._receipts[command_id] = receipt
        return receipt

    def get_receipt(self, command_id: str) -> DispatchReceipt | None:
        return self._receipts.get(command_id)

    def status(self) -> dict[str, Any]:
        return {
            "allowed_operations": sorted(self.allowed_operations),
            "automatic_merge": False,
            "automatic_deploy": False,
            "scientific_publication": False,
            "production_deletion": False,
            "external_communication": False,
            "receipt_count": len(self._receipts),
        }

    def _validate(self, command: GitHubDispatchCommand) -> None:
        if command.repository not in self._repository_allowlist:
            raise PermissionError("repository is not allowlisted")
        if command.operation not in self.allowed_operations:
            raise PermissionError(f"operation is not permitted: {command.operation}")
        if command.operation == "create_draft_pull_request" and not command.draft:
            raise PermissionError("pull requests must remain drafts")
        if command.operation == "create_draft_pull_request":
            if command.payload.get("base") != "main":
                raise PermissionError("draft pull requests must target main")
            if command.payload.get("draft") is not True:
                raise PermissionError("draft flag is required")

    @staticmethod
    def _command_id(command: GitHubDispatchCommand) -> str:
        canonical_payload = "|".join(
            f"{key}={command.payload[key]!r}" for key in sorted(command.payload)
        )
        raw = (
            f"{command.repository}|{command.operation}|{command.draft}|"
            f"{canonical_payload}"
        )
        return f"cmd-{sha256(raw.encode('utf-8')).hexdigest()[:24]}"
