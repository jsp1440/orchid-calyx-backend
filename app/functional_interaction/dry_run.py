"""Deterministic dry-run execution of an admitted FIL workflow plan.

The dry run calls in-process handlers over fixture payloads. It holds no
provider client, opens no connection, writes no file and appends no event: the
events a step *would* emit are recorded on its receipt as ``would_emit``. Each
step yields an explicit receipt -- DELIVERED or BLOCKED with a reason code --
wrapping the existing :class:`app.calyx_orchestrator.executor.ExecutionReceipt`
so checksums and state/outcome consistency are verified by the existing rule.

A step is DELIVERED only when its handler ran, established every declared
effect, emitted only declared evidence states and events, and preserved a
provenance chain when its descriptor says it must. After the first BLOCKED
step every later step is BLOCKED ``UPSTREAM_BLOCKED`` and never runs.

Limits stated plainly: effects, events and provenance are *reported* by the
handler and checked against the descriptor, not independently re-derived. The
output payload itself is inspected only for evidence-state fields, so a handler
cannot place a human-only state (``VERIFIED``) in its artifact. The connection
guarantee above covers the dry-run machinery; a handler that imports code
which connects at import time is the handler's responsibility.

The supplied governance decision is not trusted: the plan is re-evaluated here
and a decision that does not reproduce blocks every step.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.calyx_orchestrator.engineering_core import TerminalOutcome
from app.calyx_orchestrator.executor import (
    ExecutionReceipt,
    ExecutionState,
    canonical_checksum,
)

from .contracts import HUMAN_ONLY_EVIDENCE_STATES, RECEIPT_SCHEMA, CapabilityDescriptor
from .governance import DRY_RUN_MODE, GovernanceDecision, evaluate_plan
from .planner import WorkflowPlan

EXECUTOR_KEY = "fil_dry_run_v1"


@dataclass(frozen=True)
class HandlerResult:
    """What a dry-run handler returns. ``output`` must be JSON-serializable."""

    output: Any
    established: tuple[str, ...] = ()
    evidence_states: tuple[str, ...] = ()
    events: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    notes: Mapping[str, Any] = field(default_factory=dict)


Handler = Callable[[Any], HandlerResult]


@dataclass(frozen=True)
class FunctionalReceipt:
    plan_id: str
    step_index: int
    descriptor: CapabilityDescriptor
    execution: ExecutionReceipt
    established: tuple[str, ...]
    would_emit: tuple[str, ...]
    evidence_states: tuple[str, ...]
    notes: Mapping[str, Any]

    @property
    def delivered(self) -> bool:
        return self.execution.state is ExecutionState.DELIVERED

    @property
    def failure_reason(self) -> str | None:
        return self.execution.blocker_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RECEIPT_SCHEMA,
            "plan_id": self.plan_id,
            "step_index": self.step_index,
            "capability_id": self.descriptor.capability_id,
            "capability_version": self.descriptor.version,
            "operator_class": self.descriptor.operator_class.value,
            "registry_capability": self.descriptor.registry_capability,
            "mode": "dry_run",
            "executor_key": self.execution.executor_key,
            "state": self.execution.state.value,
            "outcome": self.execution.outcome.value,
            "failure_reason": self.execution.blocker_code,
            "input_checksum": self.execution.input_checksum,
            "output_checksum": self.execution.output_checksum,
            "provenance": list(self.execution.evidence_uris),
            "established_conditions": list(self.established),
            "evidence_states": list(self.evidence_states),
            "would_emit": list(self.would_emit),
            "notes": dict(self.notes),
            "provider_calls": 0,
            "published": False,
            "promoted": False,
            "production_mutation": False,
        }


@dataclass(frozen=True)
class DryRunReport:
    plan: WorkflowPlan
    decision: GovernanceDecision
    receipts: tuple[FunctionalReceipt, ...]
    final_output: Any

    @property
    def succeeded(self) -> bool:
        return bool(self.receipts) and all(
            receipt.delivered for receipt in self.receipts
        )

    @property
    def run_digest(self) -> str:
        return canonical_checksum([receipt.to_dict() for receipt in self.receipts])

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "oc.fil.dry-run-report.v1",
            "plan_id": self.plan.plan_id,
            "succeeded": self.succeeded,
            "run_digest": self.run_digest,
            "governance": self.decision.to_dict(),
            "receipts": [receipt.to_dict() for receipt in self.receipts],
        }


def _receipt(
    plan_id: str,
    index: int,
    descriptor: CapabilityDescriptor,
    *,
    input_checksum: str,
    output: Any,
    provenance: tuple[str, ...],
    failure: str | None,
    result: HandlerResult | None = None,
) -> FunctionalReceipt:
    wrapped = {"artifact": output}
    execution = ExecutionReceipt(
        assignment_id=f"{plan_id}:{index}",
        program_id=plan_id,
        job_key=descriptor.capability_id,
        executor_key=EXECUTOR_KEY,
        state=ExecutionState.BLOCKED if failure else ExecutionState.DELIVERED,
        outcome=TerminalOutcome.BLOCKED if failure else TerminalOutcome.DELIVERED,
        input_checksum=input_checksum,
        output_checksum=canonical_checksum(wrapped),
        output=wrapped,
        evidence_uris=tuple(sorted(set(provenance))),
        blocker_code=failure,
    )
    execution.verify()
    notes = dict(result.notes) if result and not failure else {}
    # Notes must be recordable too; otherwise the step is not recordable.
    canonical_checksum({"notes": notes})
    return FunctionalReceipt(
        plan_id=plan_id,
        step_index=index,
        descriptor=descriptor,
        execution=execution,
        # A blocked step establishes nothing and carries no evidence state; what
        # it attempted is named in its failure reason, never recorded as state.
        established=tuple(sorted(set(result.established)))
        if result and not failure
        else (),
        would_emit=tuple(sorted(set(result.events))) if result and not failure else (),
        evidence_states=tuple(sorted(set(result.evidence_states)))
        if result and not failure
        else (),
        notes=notes,
    )


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    visible = "".join(ch for ch in normalized if unicodedata.category(ch) != "Cf")
    return visible.strip().casefold()


def _human_only_states(value: Any) -> set[str]:
    """Every human-only evidence state named anywhere in ``value``.

    Any string *value* equal to a human-only state counts, under any key: the
    scan does not depend on a field being spelled ``evidence_state``. Strings
    are compared after NFKC normalization, removal of format characters
    (zero-width and similar) and case folding, so lookalike spellings match.
    Keys are not scanned, so ``{"verified": false}`` is not mistaken for a
    state. Containers are visited once, so a self-referencing structure
    terminates. Prose that merely mentions a state is not a state.
    """

    wanted = {_fold(state): state for state in HUMAN_ONLY_EVIDENCE_STATES}
    found: set[str] = set()
    seen: set[int] = set()
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            state = wanted.get(_fold(item))
            if state is not None:
                found.add(state)
            continue
        if isinstance(item, Mapping | list | tuple | set | frozenset):
            if id(item) in seen:
                continue
            seen.add(id(item))
            if isinstance(item, Mapping):
                stack.extend(item.values())
            else:
                stack.extend(item)
    return found


def _violation(descriptor: CapabilityDescriptor, result: Any) -> str | None:
    if not isinstance(result, HandlerResult):
        return f"HANDLER_CONTRACT_RESULT_TYPE:{type(result).__name__}"
    human_only = sorted(
        _human_only_states(result.output) | _human_only_states(result.notes)
    )
    if human_only:
        return f"HUMAN_ONLY_EVIDENCE_STATE_IN_OUTPUT:{','.join(human_only)}"
    missing = sorted(set(descriptor.effects) - set(result.established))
    if missing:
        return f"EFFECT_NOT_ESTABLISHED:{','.join(missing)}"
    declared_states = set(descriptor.outputs[0].evidence_states)
    undeclared_states = sorted(set(result.evidence_states) - declared_states)
    if undeclared_states:
        return f"UNDECLARED_EVIDENCE_STATE:{','.join(undeclared_states)}"
    undeclared_events = sorted(set(result.events) - set(descriptor.emits))
    if undeclared_events:
        return f"UNDECLARED_EVENT:{','.join(undeclared_events)}"
    if descriptor.provenance.preserves_chain and not result.provenance:
        return "PROVENANCE_CHAIN_DROPPED"
    return None


def execute_dry_run(
    plan: WorkflowPlan,
    decision: GovernanceDecision,
    handlers: Mapping[str, Handler],
    source_payload: Any,
) -> DryRunReport:
    """Run an admitted plan step by step and return explicit receipts."""

    plan_id = plan.plan_id
    if decision.plan_id != plan_id:
        raise ValueError("GOVERNANCE_DECISION_PLAN_MISMATCH")

    receipts: list[FunctionalReceipt] = []
    payload = source_payload
    blocked_at: int | None = None
    # Authority comes from re-evaluating the plan, never from the caller's object.
    reproduced = evaluate_plan(plan, mode=DRY_RUN_MODE, no_api_mode=plan.no_api_mode)
    # A caller may always be stricter than the reproduced verdict, never looser.
    blocked_reason: str | None
    if not decision.dry_run_authorized:
        blocked_reason = f"GOVERNANCE_{decision.action.value.upper()}"
    elif not reproduced.dry_run_authorized:
        blocked_reason = f"GOVERNANCE_{reproduced.action.value.upper()}"
        decision = reproduced
    elif decision != reproduced:
        blocked_reason = "GOVERNANCE_DECISION_NOT_REPRODUCED"
        decision = reproduced
    else:
        blocked_reason = None

    for index, step in enumerate(plan.steps):
        input_checksum = canonical_checksum({"artifact": payload})
        if blocked_reason is not None or blocked_at is not None:
            reason = blocked_reason or f"UPSTREAM_BLOCKED:{blocked_at}"
            receipts.append(
                _receipt(
                    plan_id,
                    index,
                    step,
                    input_checksum=input_checksum,
                    output=None,
                    provenance=(),
                    failure=reason,
                )
            )
            continue
        handler = handlers.get(step.capability_id)
        if handler is None:
            failure: str | None = "NO_DRY_RUN_HANDLER"
            result = None
        else:
            try:
                result = handler(payload)
            # Any handler failure becomes a BLOCKED receipt; nothing escapes unrecorded.
            except Exception as exc:  # noqa: BLE001
                failure, result = f"HANDLER_ERROR:{type(exc).__name__}:{exc}", None
            else:
                try:
                    failure = _violation(step, result)
                except Exception as exc:  # noqa: BLE001
                    failure = f"HANDLER_CONTRACT_VIOLATION:{type(exc).__name__}"
        if failure is not None and not isinstance(result, HandlerResult):
            result = None
        output = result.output if result is not None and failure is None else None
        try:
            receipt = _receipt(
                plan_id,
                index,
                step,
                input_checksum=input_checksum,
                output=output,
                provenance=result.provenance if result else (),
                failure=failure,
                result=result,
            )
        # A malformed result still yields a BLOCKED receipt; nothing escapes unrecorded.
        except Exception as exc:  # noqa: BLE001
            failure, output = f"RESULT_NOT_RECORDABLE:{type(exc).__name__}", None
            receipt = _receipt(
                plan_id,
                index,
                step,
                input_checksum=input_checksum,
                output=None,
                provenance=(),
                failure=failure,
            )
        receipts.append(receipt)
        if failure is not None:
            blocked_at = index
        else:
            payload = output

    final = (
        payload if blocked_at is None and blocked_reason is None and receipts else None
    )
    return DryRunReport(
        plan=plan, decision=decision, receipts=tuple(receipts), final_output=final
    )
