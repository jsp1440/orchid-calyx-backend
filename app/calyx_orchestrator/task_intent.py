from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from enum import StrEnum


class IntentDecision(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    REVIEW = "review"


class BehaviorKind(StrEnum):
    EXTERNAL_CONTENT_READ = "external_content_read"
    SENSITIVE_READ = "sensitive_read"
    FILE_WRITE = "file_write"
    TOOL_CALL = "tool_call"
    OUTBOUND_NETWORK = "outbound_network"
    AUTHORITY_CHANGE = "authority_change"


PROTECTED_PATH_MARKERS = (
    "claude.md",
    "agents.md",
    ".cursor/rules",
    ".claude/",
    ".github/workflows/",
    "agent_security_gateway.py",
    "constitutional_orchestrator.py",
    "autonomy_policy.py",
    "task_intent.py",
)

SENSITIVE_PATH_MARKERS = (
    ".env",
    "credentials",
    "secrets",
    ".ssh/",
    "id_rsa",
    "token",
)


@dataclass(frozen=True, slots=True)
class TaskIntentContract:
    task_id: str
    mission_id: str
    repository: str
    base_ref: str
    base_sha: str
    objective: str
    allowed_paths: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    validation_commands: tuple[str, ...] = ()
    issue_numbers: tuple[int, ...] = ()
    pr_numbers: tuple[int, ...] = ()
    max_cost_units: int = 25
    owner_approval_required: bool = False
    contract_version: str = "calyx-task-intent-v1"

    def __post_init__(self) -> None:
        required = {
            "task_id": self.task_id,
            "mission_id": self.mission_id,
            "repository": self.repository,
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "objective": self.objective,
        }
        for field_name, value in required.items():
            if not str(value).strip():
                raise ValueError(f"TASK_INTENT_{field_name.upper()}_REQUIRED")
        if len(self.base_sha) != 40:
            raise ValueError("TASK_INTENT_BASE_SHA_INVALID")
        if self.max_cost_units < 0:
            raise ValueError("TASK_INTENT_COST_LIMIT_INVALID")

    def material_payload(self) -> dict[str, object]:
        """Provider-independent material state used for replay suppression."""
        return {
            "contract_version": self.contract_version,
            "task_id": self.task_id,
            "mission_id": self.mission_id,
            "repository": self.repository,
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "objective": self.objective,
            "allowed_paths": sorted(set(self.allowed_paths)),
            "allowed_tools": sorted(set(self.allowed_tools)),
            "forbidden_actions": sorted(set(self.forbidden_actions)),
            "validation_commands": list(self.validation_commands),
            "issue_numbers": sorted(set(self.issue_numbers)),
            "pr_numbers": sorted(set(self.pr_numbers)),
            "max_cost_units": self.max_cost_units,
            "owner_approval_required": self.owner_approval_required,
        }

    def fingerprint(self, *, head_sha: str | None = None) -> str:
        payload = self.material_payload()
        payload["head_sha"] = head_sha or self.base_sha
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class BehaviorEvent:
    event_id: str
    task_fingerprint: str
    task_id: str
    mission_id: str
    agent_id: str
    provider: str | None
    kind: BehaviorKind
    action: str
    resource: str | None
    tool_name: str | None
    external_context: bool
    allowed: bool
    decision: IntentDecision
    reason: str
    cost_units: int = 0
    metadata: tuple[tuple[str, str], ...] = ()

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["decision"] = self.decision.value
        data["metadata"] = dict(self.metadata)
        return data


class AgentBehaviorLedger:
    """Append-only safe behavioral record without prompts, secrets, or chain-of-thought."""

    def __init__(self) -> None:
        self._events: list[BehaviorEvent] = []

    def append(self, event: BehaviorEvent) -> None:
        if any(existing.event_id == event.event_id for existing in self._events):
            return
        self._events.append(event)

    def events(self) -> tuple[BehaviorEvent, ...]:
        return tuple(self._events)

    def for_task(self, task_fingerprint: str) -> tuple[BehaviorEvent, ...]:
        return tuple(event for event in self._events if event.task_fingerprint == task_fingerprint)


@dataclass(frozen=True, slots=True)
class BehaviorRequest:
    kind: BehaviorKind
    action: str
    resource: str | None = None
    tool_name: str | None = None
    external_context: bool = False
    cost_units: int = 0
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class BehaviorDecision:
    decision: IntentDecision
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision == IntentDecision.ALLOW


class LeastAgencyGuard:
    """Deterministic task-scoped least-agency enforcement.

    Provider/model identity never affects authority. The contract is the source
    of authority; provider is provenance only.
    """

    def __init__(
        self,
        contract: TaskIntentContract,
        *,
        ledger: AgentBehaviorLedger | None = None,
    ) -> None:
        self.contract = contract
        self.ledger = ledger or AgentBehaviorLedger()
        self._saw_external_content = False
        self._saw_sensitive_read = False
        self._spent_cost_units = 0

    def evaluate(self, request: BehaviorRequest) -> BehaviorDecision:
        action_lower = request.action.lower()
        resource_lower = (request.resource or "").lower()

        if request.cost_units < 0:
            return BehaviorDecision(IntentDecision.BLOCK, "INVALID_COST")
        if self._spent_cost_units + request.cost_units > self.contract.max_cost_units:
            return BehaviorDecision(IntentDecision.BLOCK, "TASK_COST_LIMIT_EXCEEDED")
        if any(term.lower() in action_lower for term in self.contract.forbidden_actions):
            return BehaviorDecision(IntentDecision.BLOCK, "FORBIDDEN_ACTION")
        if request.kind == BehaviorKind.AUTHORITY_CHANGE:
            return BehaviorDecision(IntentDecision.BLOCK, "SELF_AUTHORITY_EXPANSION_PROHIBITED")
        if request.kind == BehaviorKind.FILE_WRITE and self._protected_path(resource_lower):
            return BehaviorDecision(IntentDecision.BLOCK, "PROTECTED_GOVERNANCE_PATH_WRITE")
        if request.tool_name and self.contract.allowed_tools and request.tool_name not in self.contract.allowed_tools:
            return BehaviorDecision(IntentDecision.BLOCK, "TOOL_OUTSIDE_TASK_SCOPE")
        if (
            request.kind == BehaviorKind.FILE_WRITE
            and self.contract.allowed_paths
            and not self._path_allowed(resource_lower)
        ):
            return BehaviorDecision(IntentDecision.BLOCK, "PATH_OUTSIDE_TASK_SCOPE")

        privileged = request.kind in {
            BehaviorKind.FILE_WRITE,
            BehaviorKind.OUTBOUND_NETWORK,
            BehaviorKind.AUTHORITY_CHANGE,
        }
        if (self._saw_external_content or request.external_context) and privileged:
            return BehaviorDecision(IntentDecision.BLOCK, "POST_INGESTION_PRIVILEGED_ACTION_BLOCKED")
        if self._saw_sensitive_read and request.kind == BehaviorKind.OUTBOUND_NETWORK:
            return BehaviorDecision(IntentDecision.BLOCK, "SENSITIVE_READ_TO_OUTBOUND_BLOCKED")
        return BehaviorDecision(IntentDecision.ALLOW, "ALLOW")

    def record(
        self,
        request: BehaviorRequest,
        *,
        agent_id: str,
        provider: str | None = None,
        head_sha: str | None = None,
    ) -> BehaviorEvent:
        decision = self.evaluate(request)
        fingerprint = self.contract.fingerprint(head_sha=head_sha)
        stable = {
            "task_fingerprint": fingerprint,
            "agent_id": agent_id,
            "kind": request.kind.value,
            "action": request.action,
            "resource": request.resource,
            "tool_name": request.tool_name,
            "decision": decision.decision.value,
            "reason": decision.reason,
            "event_index": len(self.ledger.events()),
        }
        event_id = hashlib.sha256(
            json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:24]
        event = BehaviorEvent(
            event_id=event_id,
            task_fingerprint=fingerprint,
            task_id=self.contract.task_id,
            mission_id=self.contract.mission_id,
            agent_id=agent_id,
            provider=provider,
            kind=request.kind,
            action=request.action,
            resource=request.resource,
            tool_name=request.tool_name,
            external_context=request.external_context,
            allowed=decision.allowed,
            decision=decision.decision,
            reason=decision.reason,
            cost_units=request.cost_units,
            metadata=request.metadata,
        )
        self.ledger.append(event)
        if decision.allowed:
            self._spent_cost_units += request.cost_units
            if request.kind == BehaviorKind.EXTERNAL_CONTENT_READ or request.external_context:
                self._saw_external_content = True
            if request.kind == BehaviorKind.SENSITIVE_READ or self._sensitive_path(request.resource):
                self._saw_sensitive_read = True
        return event

    @staticmethod
    def _protected_path(resource_lower: str) -> bool:
        return any(marker in resource_lower for marker in PROTECTED_PATH_MARKERS)

    @staticmethod
    def _sensitive_path(resource: str | None) -> bool:
        value = (resource or "").lower()
        return any(marker in value for marker in SENSITIVE_PATH_MARKERS)

    def _path_allowed(self, resource_lower: str) -> bool:
        normalized = resource_lower.lstrip("./")
        for allowed in self.contract.allowed_paths:
            prefix = allowed.lower().lstrip("./")
            if normalized == prefix or normalized.startswith(prefix.rstrip("/") + "/"):
                return True
        return False


def canonical_task_fingerprint(
    contract: TaskIntentContract,
    *,
    head_sha: str | None = None,
) -> str:
    return contract.fingerprint(head_sha=head_sha)


def duplicate_material_state(fingerprints: Iterable[str], candidate: str) -> bool:
    return candidate in set(fingerprints)
