"""The bounded set of validation commands the deterministic lane may run.

The provider-free lane had exactly one executor — ``reconcile`` — and that
executor deliberately performs no repository writes and runs no commands. It
reads GitHub state, checks a declared disposition marker, and relabels the
issue. That is bookkeeping, not work, so every completed provider-free cycle
produced a receipt and nothing else.

This registry is what gives that lane something to actually do. It is a list of
*commands that exist in this repository*, keyed by a short identifier an issue
may name. It is deliberately not a free-form command field: an issue body is
untrusted text, and a lane that ran whatever an issue asked for would be a
remote-execution surface with a GitHub token attached. Only identifiers resolve,
only to fixed argument vectors, and an unknown identifier fails closed rather
than falling back to a shell.

Every entry must satisfy three properties, which are the reason a command is
safe to run unattended:

* it reads the checked-out revision and writes nothing durable outside the
  runner's temporary space;
* it calls no model provider and spends nothing;
* its exit code is a truthful statement about the revision, so a pass is
  evidence and a failure is a finding rather than an error to route around.

Adding an entry is a deliberate act with the same rule the capability registry
uses: name a program that exists. An identifier without a working command
re-creates the failure the capability router was repaired to stop — admission
succeeds, execution cannot, and the issue is parked for lacking something it was
never given.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Identifiers an issue may name. Kept narrow on purpose: it is the token that
#: crosses the trust boundary from issue text into an argument vector.
COMMAND_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

#: Ceiling on how many commands one task may request. A validation task is a
#: bounded unit of work, not a way to run the whole suite under a lease that
#: another lane is waiting on.
MAX_COMMANDS_PER_TASK = 6

#: Per-command wall clock ceiling, in seconds. A command that has not finished
#: inside this window is recorded as a timeout, which is a failure, never an
#: unknown treated as a pass.
DEFAULT_TIMEOUT_SECONDS = 600


class UnknownValidationCommand(ValueError):
    """An issue named a validation command this repository does not implement.

    Raised rather than skipped. Skipping would let a task declare validation,
    execute none of it, and settle as complete on an empty result set — a false
    pass, which is the one outcome this lane must never produce.
    """


@dataclass(frozen=True)
class ValidationCommand:
    """One runnable check, and what its exit code is allowed to mean."""

    command_id: str
    argv: tuple[str, ...]
    summary: str
    #: What a zero exit proves. Written narrowly so a receipt cannot be read as
    #: a broader claim than the command supports: running the control-plane
    #: tests proves those tests pass on this revision, not that the control
    #: plane is healthy in production.
    proves: str

    def __post_init__(self) -> None:
        if not COMMAND_ID.fullmatch(self.command_id):
            raise ValueError(f"invalid validation command id: {self.command_id!r}")
        if not self.argv or not all(isinstance(part, str) and part for part in self.argv):
            raise ValueError(f"validation command {self.command_id!r} has no argument vector")


def _pytest(*targets: str) -> tuple[str, ...]:
    # ``-p no:cacheprovider`` keeps the run from writing .pytest_cache into the
    # checkout, so the command leaves the working tree exactly as it found it.
    return ("python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets)


_COMMANDS = (
    ValidationCommand(
        command_id="control-plane-tests",
        argv=_pytest(
            "tests/test_oc_blocked_reconcile.py",
            "tests/test_oc_denied_worker_settlement.py",
            "tests/test_oc_swarm_lease_reconcile.py",
            "tests/test_oc_swarm_provider_free_worker.py",
        ),
        summary="Run the autonomy control-plane test files.",
        proves=(
            "the blocked-work reconciler, denied-worker settlement, lease "
            "reconciliation and provider-free worker tests pass on this exact "
            "revision"
        ),
    ),
    ValidationCommand(
        command_id="provider-routing-tests",
        argv=_pytest(
            "tests/test_provider_reservoir.py",
            "tests/test_swarm_execution_governor.py",
        ),
        summary="Run the capability-routing and execution-governor test files.",
        proves=(
            "capability routing and the execution governor behave as their "
            "tests specify on this exact revision"
        ),
    ),
    ValidationCommand(
        command_id="health-contract-tests",
        argv=_pytest(
            "tests/test_oc_control_plane_health.py",
            "tests/test_oc_health_contract.py",
        ),
        summary="Run the control-plane health contract test files.",
        proves=(
            "the health contract rejects the unhealthy snapshots its tests "
            "describe on this exact revision"
        ),
    ),
    ValidationCommand(
        command_id="calyx-async-acceptance",
        argv=_pytest(
            "tests/test_calyx_brain_001_literature_e2e.py",
            "tests/test_calyx_brain_001a_literature_candidate_handoff.py",
            "tests/test_calyx_brain_001b_canonical_source_binding.py",
            "tests/test_calyx_brain_002_operational.py",
            "tests/test_calyx_brain_integration_acceptance.py",
            "tests/test_calyx_glossary_001_vocabulary_intake.py",
            "tests/test_calyx_syn_004_evidence_matrix.py",
            "tests/test_literature_extraction_pipeline.py",
        ),
        summary=(
            "Run the Calyx literature, glossary and evidence-matrix acceptance "
            "files, which are the async surface."
        ),
        proves=(
            "the Calyx literature-to-evidence acceptance tests actually execute "
            "and pass on this exact revision, rather than reporting unrun for "
            "want of an async plugin"
        ),
    ),
    ValidationCommand(
        command_id="control-plane-compiles",
        argv=("python3", "-m", "compileall", "-q", "scripts", "runtime/swarm"),
        summary="Byte-compile the control-plane Python sources.",
        proves=(
            "every control-plane source file parses under the runner's "
            "interpreter on this exact revision"
        ),
    ),
)

VALIDATION_COMMANDS: dict[str, ValidationCommand] = {
    command.command_id: command for command in _COMMANDS
}


def resolve(command_ids: list[str]) -> list[ValidationCommand]:
    """Resolve declared identifiers to commands, preserving declared order.

    Duplicates collapse: running the same suite twice under one lease proves
    nothing the first run did not, and it doubles the time another lane waits.
    An empty request raises, because a validation task that validates nothing
    must not be able to settle as validated.
    """
    if not command_ids:
        raise UnknownValidationCommand("no validation command was declared")
    if len(command_ids) > MAX_COMMANDS_PER_TASK:
        raise UnknownValidationCommand(
            f"at most {MAX_COMMANDS_PER_TASK} validation commands may run under one lease"
        )
    resolved: list[ValidationCommand] = []
    seen: set[str] = set()
    for raw in command_ids:
        name = str(raw).strip().lower()
        command = VALIDATION_COMMANDS.get(name)
        if command is None:
            raise UnknownValidationCommand(
                f"no validation command named {name!r} exists; this repository "
                f"implements {sorted(VALIDATION_COMMANDS)}"
            )
        if name in seen:
            continue
        seen.add(name)
        resolved.append(command)
    return resolved
