"""CALYX-AUTO for the GitHub coding-agent role.

The durable mission/lease/dependency-continuation substrate, the generic
multi-role autonomous loop (`program_cycle.run_deterministic_program_cycle`,
this same pattern's `program_autonomy_worker.py`), and the full observe/
reconcile/repair dispatch chain for `github_coding_agent` missions
(`GitHubCodingAgentDispatchCycle`, closed out by backend issue #973) already
exist on main. What was missing - confirmed by a repository-wide search
finding zero callers of `GitHubCodingAgentDispatchCycle.run_once()` or
`build_production_github_coding_agent_dispatch_cycle()` outside their own
module and tests - was any automatic/scheduled caller at all. This module is
that caller, and nothing else: it does not re-implement the queue,
scheduler, lease, or dispatch logic.

Deliberately narrower than `program_autonomy_worker.py`: this worker only
ever calls `run_once(execute=False)`. Automatic mode here means "the loop is
permitted to run and preflight," never "the loop is permitted to execute a
live GitHub dispatch." Live execution remains gated by the separate,
already-existing `GitHubCodingRuntimePolicy` (disabled by default, owner
allowlist, repository allowlist, exact confirmation string) and by whether a
real `GitHubTransport` credential exists at all - which, per
Orchid-Continuum-Brain OPS-0011, it currently does not: no production code
anywhere constructs one. This module therefore takes `transport`,
`runtime_policy`, and `required_checks` as caller-supplied arguments rather
than building them from environment variables itself; inventing an
environ-based credential constructor here would be exactly the separate,
still-missing, owner-gated activation step OPS-0011 describes, not something
to add silently as a side effect of wiring up automation.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from app.calyx_orchestrator.github_agent_autonomy_policy import (
    GitHubCodingAgentAutonomyPolicy,
)
from app.calyx_orchestrator.github_agent_ci_policy import RequiredCiCheckPolicy
from app.calyx_orchestrator.github_agent_composition import (
    build_production_github_coding_agent_dispatch_cycle,
)
from app.calyx_orchestrator.github_agent_dispatch_cycle import GitHubCodingRuntimePolicy
from app.calyx_orchestrator.github_proposal_mutation_adapter import GitHubTransport
from app.database import get_session_local


def run_once(
    *,
    transport: GitHubTransport,
    runtime_policy: GitHubCodingRuntimePolicy,
    required_checks: RequiredCiCheckPolicy,
    policy: GitHubCodingAgentAutonomyPolicy | None = None,
) -> dict[str, Any]:
    active_policy = (policy or GitHubCodingAgentAutonomyPolicy.from_environ()).validated()
    state = active_policy.status()
    if not state["authorized"]:
        return {
            "executed": False,
            "reason": "disabled_or_owner_not_configured",
            "policy": state,
        }

    SessionLocal = get_session_local()
    with SessionLocal() as db:
        cycle = build_production_github_coding_agent_dispatch_cycle(
            db=db,
            transport=transport,
            policy=runtime_policy,
            required_checks=required_checks,
        )
        result = cycle.run_once(owner=active_policy.owner, execute=False)
    return {"executed": True, "policy": state, "cycle": asdict(result)}


def run_forever(
    *,
    transport: GitHubTransport,
    runtime_policy: GitHubCodingRuntimePolicy,
    required_checks: RequiredCiCheckPolicy,
    policy: GitHubCodingAgentAutonomyPolicy | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    on_cycle: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    active_policy = (policy or GitHubCodingAgentAutonomyPolicy.from_environ()).validated()
    if not active_policy.status()["authorized"]:
        raise PermissionError("GITHUB_CODING_AGENT_AUTONOMY_NOT_AUTHORIZED")

    while True:
        result = run_once(
            transport=transport,
            runtime_policy=runtime_policy,
            required_checks=required_checks,
            policy=active_policy,
        )
        if on_cycle is not None:
            on_cycle(result)
        sleeper(active_policy.poll_seconds)


def main(
    *,
    transport: GitHubTransport,
    runtime_policy: GitHubCodingRuntimePolicy,
    required_checks: RequiredCiCheckPolicy,
) -> int:
    policy = GitHubCodingAgentAutonomyPolicy.from_environ()
    if not policy.status()["authorized"]:
        print(json.dumps({"worker": "calyx-github-coding-agent-autonomy", "policy": policy.status()}, sort_keys=True))
        return 0

    def emit(result: dict[str, Any]) -> None:
        print(json.dumps(result, sort_keys=True, default=str), flush=True)

    run_forever(
        transport=transport,
        runtime_policy=runtime_policy,
        required_checks=required_checks,
        policy=policy,
        on_cycle=emit,
    )
    return 0
