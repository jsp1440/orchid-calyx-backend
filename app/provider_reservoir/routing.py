"""Decide which lane a task belongs in, from capability rather than difficulty.

The controller previously asked one question — does the body contain the exact
line ``OC-SWARM-PROVIDER-FREE: reconcile`` — and sent everything else to a paid
provider lane. Issue #1502 declared in its own acceptance criteria that its
fixture "must run without external AI credentials", lacked that one literal, and
was routed to the most expensive model available because its body contained the
word "architecture".

Routing now asks what the task needs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .capabilities import (
    CapabilityUnknown,
    classify_capabilities,
    is_provider_capability,
)

#: Legacy opt-in, kept working. Any task name is accepted now, not only
#: ``reconcile``: the value names the deterministic executor to run, and
#: restricting it to one literal is what misrouted every other provider-free task.
PROVIDER_FREE_MARKER = re.compile(
    r"^OC-SWARM-PROVIDER-FREE:\s*(?P<task>[a-z0-9][a-z0-9-]*)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

#: Capability declaration, repeatable. This is the signal routing prefers.
CAPABILITY_MARKER = re.compile(
    r"^OC-SWARM-CAPABILITY:\s*(?P<name>[a-z0-9][a-z0-9-]*)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

#: Marks a declared provider capability as optional enrichment rather than a
#: precondition. Optional enrichment may never stop deterministic work.
OPTIONAL_MARKER = re.compile(
    r"^OC-SWARM-PROVIDER-OPTIONAL:\s*(?P<name>[a-z0-9][a-z0-9-]*)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class TaskRouting:
    """Where a task's work goes, split by what each part actually needs."""

    issue_number: int
    provider_free_task: str | None
    deterministic_capabilities: list[str]
    blocking_provider_capabilities: list[str]
    optional_provider_capabilities: list[str]
    reasons: list[str] = field(default_factory=list)

    @property
    def has_deterministic_work(self) -> bool:
        return bool(self.provider_free_task or self.deterministic_capabilities)

    @property
    def provider_free(self) -> bool:
        """True when deterministic work can run now, whatever the provider budget says.

        Optional provider enrichment does not make a task provider-dependent.
        That is the whole point: an unavailable enrichment parks by itself and
        the deterministic work proceeds.
        """
        return self.has_deterministic_work and not self.blocking_provider_capabilities

    @property
    def fully_blocked(self) -> bool:
        """True only when the task has no deterministic work at all."""
        return not self.has_deterministic_work and bool(self.blocking_provider_capabilities)

    @property
    def parked_capabilities(self) -> list[str]:
        """Capabilities that need a provider and so do not run in this pass."""
        return sorted({*self.blocking_provider_capabilities, *self.optional_provider_capabilities})


def route_task(issue: dict) -> TaskRouting:
    """Classify one issue by the capabilities it declares.

    Raises :class:`CapabilityUnknown` when a declared capability is not in the
    registry, rather than guessing a lane for it.
    """
    body = str(issue.get("body") or "")
    number = int(issue.get("number") or 0)
    reasons: list[str] = []

    free_match = PROVIDER_FREE_MARKER.search(body)
    provider_free_task = free_match.group("task").lower() if free_match else None
    if provider_free_task:
        reasons.append(f"explicit-provider-free-task={provider_free_task}")

    declared = [m.group("name").lower() for m in CAPABILITY_MARKER.finditer(body)]
    optional_names = {m.group("name").lower() for m in OPTIONAL_MARKER.finditer(body)}

    deterministic, provider = classify_capabilities(declared) if declared else ([], [])
    if declared:
        reasons.append(f"declared-capabilities={len(set(declared))}")

    # An optional marker naming something deterministic is a contradiction: a
    # deterministic capability is never optional enrichment, it just runs.
    for name in sorted(optional_names):
        if not is_provider_capability(name):
            raise ValueError(
                f"capability {name!r} is deterministic, so marking it "
                "OC-SWARM-PROVIDER-OPTIONAL is meaningless; it runs either way"
            )

    blocking = [c for c in provider if c not in optional_names]
    optional = [c for c in provider if c in optional_names]
    if optional:
        reasons.append(f"optional-enrichment={len(optional)}")
    if blocking:
        reasons.append(f"blocking-provider-capabilities={len(blocking)}")
    if not declared and not provider_free_task:
        reasons.append("undeclared: no capability stated, so no lane is inferred")

    return TaskRouting(
        issue_number=number,
        provider_free_task=provider_free_task,
        deterministic_capabilities=deterministic,
        blocking_provider_capabilities=sorted(blocking),
        optional_provider_capabilities=sorted(optional),
        reasons=reasons,
    )


def is_provider_free(issue: dict) -> bool:
    """Back-compatible predicate for the swarm controller.

    Differs from the old one in exactly the way that matters: a task is
    provider-free when it has deterministic work to do, not when it carries one
    particular literal. An unclassified capability raises rather than being
    quietly routed to a paid lane.
    """
    try:
        return route_task(issue).provider_free
    except CapabilityUnknown:
        return False
