"""Governed coding-executor dispatch path for the swarm controller.

The controller used to meet engineering work whose declared capabilities say
what to build but name nobody who can build it (``open-ended-code-authoring``)
and withdraw it as ``lane_refused``. That is an honest refusal for the
deterministic worker, but it left code-authoring work with no route: the paid
completion lane (``orchid-completion-lane.yml``, a governed Claude Code
executor) never saw it. A missing deterministic executor is still a capability
gap, not evidence that a provider is unavailable.

This module is the pure decision layer. It never calls a provider, never opens
a branch and never writes to GitHub. It answers three questions:

* does this issue need a coding executor at all (:func:`needs_coding_executor`)?
* may one be dispatched right now, and if not, which named gate says no
  (:func:`coding_dispatch_record`)?
* what lifecycle state is a mission in, and is a claimed transition legal
  (:func:`advance`)? Receipts carry a checksum so a state can be inspected, not
  merely asserted.

Nothing here fakes an executor. Code-authoring work remains ``provider_blocked``
when no coding executor is authorised. An unsupported deterministic executor
alone remains ``capability_gap`` even when providers are authorised; an explicit
blocking code-authoring capability may use the authorised coding route instead.
These are planning records, not evidence that work ran.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

SCHEMA = "oc.coding-dispatch.v1"
RECEIPT_SCHEMA = "oc.coding-receipt.v1"

#: Every state a coding mission can be evidenced in. Nothing else is recordable.
STATES: tuple[str, ...] = (
    "queued",
    "leased",
    "executing",
    "implementation_complete",
    "testing",
    "certification",
    "integration_ready",
    "integrated",
    "replenished",
    "provider_blocked",
    "owner_gated",
    "scientific_gated",
    "dependency_blocked",
    "capability_gap",
    "failed",
)

#: Gate states: the mission is parked by a named condition, not by the factory.
GATE_STATES = frozenset(
    {
        "provider_blocked",
        "owner_gated",
        "scientific_gated",
        "dependency_blocked",
        "capability_gap",
    }
)

#: The forward path. A mission can leave any non-terminal state for ``failed``
#: or a gate, and a gate releases back to ``queued`` only.
_FORWARD: dict[str, frozenset[str]] = {
    "queued": frozenset({"leased"}),
    "leased": frozenset({"executing"}),
    "executing": frozenset({"implementation_complete"}),
    "implementation_complete": frozenset({"testing"}),
    "testing": frozenset({"certification", "executing"}),
    "certification": frozenset({"integration_ready", "executing"}),
    "integration_ready": frozenset({"integrated"}),
    "integrated": frozenset({"replenished"}),
    "replenished": frozenset(),
    "failed": frozenset({"queued"}),
}
TERMINAL_STATES = frozenset({"replenished"})

#: Branches a coding mission may never integrate into. Integration to ``main``
#: is an owner action, not a lifecycle step.
PROTECTED_TARGETS = frozenset({"main", "master"})

OWNER_GATE_LABELS = frozenset({"oc-owner-gate", "blocked-on-owner"})
SCIENTIFIC_GATE_LABELS = frozenset({"oc-scientific-gate"})

_CODE_AUTHORING = "open-ended-code-authoring"


class LifecycleError(ValueError):
    """A claimed transition or receipt violates the coding-executor contract."""


def _label_names(issue: Mapping[str, Any]) -> set[str]:
    return {
        label if isinstance(label, str) else str(label.get("name"))
        for label in issue.get("labels") or []
    }


def needs_coding_executor(routing: Any) -> bool:
    """True when the task's own work is writing code nobody deterministic can write.

    ``routing`` is :class:`app.provider_reservoir.routing.TaskRouting`. A task a
    deterministic executor already runs, one whose acquisition lane owns it, and
    one that declares no work at all are all excluded. An explicit deterministic
    executor marker alone is not a request for open-ended code authoring.
    An explicit blocking code-authoring capability still needs a coding executor
    when the named deterministic executor is unsupported.
    """
    if getattr(routing, "lane_executable", False):
        return False
    if "firecrawl-acquisition" in getattr(routing, "blocking_provider_capabilities", ()):
        return False
    if _CODE_AUTHORING in getattr(routing, "blocking_provider_capabilities", ()):
        return True
    if getattr(routing, "provider_free_task", None):
        return False
    return bool(getattr(routing, "deterministic_capabilities", ()))


def coding_dispatch_record(
    issue: Mapping[str, Any],
    routing: Any,
    *,
    provider_blocked: bool,
    dependency_blocked: bool = False,
) -> dict[str, Any]:
    """Decide the state of a coding-executor mission, naming the gate if any.

    Gates are checked in a fixed order so the record is deterministic. A human
    gate outranks a provider gate: lifting the provider gate must not release
    work a person is holding. Provider availability cannot repair a capability
    mismatch or make an inapplicable coding route dispatchable.
    """
    names = _label_names(issue)
    needs_executor = needs_coding_executor(routing)
    if names & SCIENTIFIC_GATE_LABELS:
        state, gate = "scientific_gated", "oc-scientific-gate"
    elif names & OWNER_GATE_LABELS:
        state, gate = "owner_gated", min(names & OWNER_GATE_LABELS)
    elif dependency_blocked:
        state, gate = "dependency_blocked", "unfinished-dependency"
    elif not needs_executor:
        state = "capability_gap"
        gate = (
            "unsupported-deterministic-executor"
            if getattr(routing, "provider_free_task", None)
            and not getattr(routing, "lane_executable", False)
            else "coding-executor-not-applicable"
        )
    elif provider_blocked:
        state, gate = "provider_blocked", "no-authorised-coding-executor"
    else:
        state, gate = "queued", None
    return {
        "schema": SCHEMA,
        "issue_number": int(issue.get("number") or 0),
        "needs_coding_executor": needs_executor,
        "capability": _CODE_AUTHORING if needs_executor else None,
        "declared_executor": getattr(routing, "provider_free_task", None),
        "declared_deterministic_capabilities": list(
            getattr(routing, "deterministic_capabilities", [])
        ),
        "state": state,
        "gate": gate,
        "dispatchable": state == "queued",
        "executor": "orchid-completion-lane" if state == "queued" else None,
        "provider_called": False,
    }


def _checksum(payload: Mapping[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def new_mission(issue_number: int, *, base_branch: str, maker: str) -> dict[str, Any]:
    if base_branch.strip().lower() in PROTECTED_TARGETS:
        raise LifecycleError("CODING_MISSION_BASE_PROTECTED")
    if not maker.strip():
        raise LifecycleError("CODING_MISSION_MAKER_REQUIRED")
    mission = {
        "schema": RECEIPT_SCHEMA,
        "issue_number": int(issue_number),
        "base_branch": base_branch,
        "maker": maker,
        "state": "queued",
        "history": [],
    }
    mission["history"].append(_entry(mission, None, "queued", {}))
    return mission


def _entry(
    mission: Mapping[str, Any], previous: str | None, state: str, evidence: Mapping[str, Any]
) -> dict[str, Any]:
    prior = mission["history"][-1]["checksum"] if mission.get("history") else ""
    entry = {
        "from": previous,
        "to": state,
        "evidence": dict(evidence),
        "previous_checksum": prior,
    }
    entry["checksum"] = _checksum(entry)
    return entry


def _require(evidence: Mapping[str, Any], keys: Iterable[str], state: str) -> None:
    missing = [key for key in keys if not evidence.get(key)]
    if missing:
        raise LifecycleError(f"EVIDENCE_REQUIRED_FOR_{state.upper()}:{','.join(missing)}")


def advance(mission: dict[str, Any], to: str, **evidence: Any) -> dict[str, Any]:
    """Return a new mission advanced to ``to``, or raise :class:`LifecycleError`.

    Evidence is required where a state asserts something happened. The checker
    must be a different logical identity from the maker, and certification must
    name the exact head SHA that implementation produced; a later push voids it.
    """
    if to not in STATES:
        raise LifecycleError(f"UNKNOWN_STATE:{to}")
    current = mission["state"]
    if current in TERMINAL_STATES:
        raise LifecycleError("MISSION_ALREADY_TERMINAL")
    allowed = set(_FORWARD.get(current, ()))
    if current in GATE_STATES:
        allowed = {"queued"}
    else:
        allowed |= GATE_STATES | {"failed"}
    if to not in allowed:
        raise LifecycleError(f"ILLEGAL_TRANSITION:{current}->{to}")

    if to == "leased":
        _require(evidence, ["lease_id"], to)
    elif to == "executing":
        _require(evidence, ["run_id"], to)
    elif to == "implementation_complete":
        _require(evidence, ["head_sha", "pull_request"], to)
    elif to == "testing":
        _require(evidence, ["head_sha"], to)
        if evidence["head_sha"] != _last_evidence(mission, "head_sha"):
            raise LifecycleError("TESTING_HEAD_MISMATCH")
    elif to == "certification":
        _require(evidence, ["head_sha", "checks_passed"], to)
        if evidence["head_sha"] != _last_evidence(mission, "head_sha"):
            raise LifecycleError("CERTIFICATION_HEAD_MISMATCH")
    elif to == "integration_ready":
        _require(evidence, ["head_sha", "checker", "target_branch"], to)
        if evidence["head_sha"] != _last_evidence(mission, "head_sha"):
            raise LifecycleError("CERTIFIED_HEAD_STALE")
        if str(evidence["checker"]).strip() == mission["maker"]:
            raise LifecycleError("CHECKER_MUST_DIFFER_FROM_MAKER")
        if str(evidence["target_branch"]).strip().lower() in PROTECTED_TARGETS:
            raise LifecycleError("INTEGRATION_TARGET_PROTECTED")
    elif to == "integrated":
        _require(evidence, ["merge_commit", "target_branch"], to)
        if str(evidence["target_branch"]).strip().lower() in PROTECTED_TARGETS:
            raise LifecycleError("INTEGRATION_TARGET_PROTECTED")
    elif to == "replenished":
        _require(evidence, ["next_issue"], to)
    elif to == "failed":
        _require(evidence, ["reason"], to)
    elif to in GATE_STATES:
        _require(evidence, ["gate"], to)

    updated = dict(mission)
    updated["history"] = [*mission["history"], _entry(mission, current, to, evidence)]
    updated["state"] = to
    return updated


def _last_evidence(mission: Mapping[str, Any], key: str) -> Any:
    for entry in reversed(mission["history"]):
        if key in entry["evidence"]:
            return entry["evidence"][key]
    return None


def verify_chain(mission: Mapping[str, Any]) -> bool:
    """True when the history is an unbroken, untampered checksum chain."""
    previous = ""
    for entry in mission.get("history", []):
        body = {k: v for k, v in entry.items() if k != "checksum"}
        if entry.get("previous_checksum") != previous or _checksum(body) != entry.get("checksum"):
            return False
        previous = entry["checksum"]
    return bool(mission.get("history")) and mission["history"][-1]["to"] == mission["state"]
