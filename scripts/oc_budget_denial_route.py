"""Decide where denied provider work goes, not only that it stopped.

A governor denial used to have exactly one consequence: release the lease, mark
the issue ``oc-blocked``, record the blocker. Nothing asked whether the task
could have proceeded another way. Issue #1401 spent 2026-09-23 in the resulting
shape —

    oc-queued → lease → Claude route → BLOCKED_MONTHLY_BUDGET_EXCEEDED
    → lease released → oc-blocked → requeued → the same Claude route

— three full cycles in eight minutes, ``provider_called=false`` every time, and
no work done. The requeue half of that loop is now held by
``oc_blocked_reconcile``, which refuses to release a budget blocker until its
fingerprint changes. This module is the other half: at the moment of denial,
decide deterministically what happens next.

Three dispositions, tried in order, which is the order of decreasing certainty
that the next step is real work:

``provider-free``
    The task has deterministic work and this repository has an executor that can
    run it. The deterministic lane spends nothing and calls nobody, so a
    provider denial — budget, kill switch, or allowlist — says nothing about
    whether that lane may proceed. The issue returns to ``oc-queued`` and the
    planner routes it to the deterministic worker, not back to the provider that
    just refused it.

``alternate-provider``
    A per-run ceiling can refuse one route while the shared daily and monthly
    pools still have headroom. When that is the case and another already-
    authorized provider's own estimated cost clears *all three* of the
    governor's ceilings, that route is genuinely eligible and is named here.
    The arithmetic is the governor's own, re-evaluated for a different route —
    not a way around it. A daily or monthly exhaustion is a shared-pool
    condition: no route clears it, and this disposition cannot fire.

    This disposition names the route; it does not take it. Returning the issue
    to the queue would hand it straight back to the primary route that just
    refused it, which is the loop this module exists to end, and dispatching a
    second paid provider from here would activate paid execution on a route no
    owner authorised — an owner gate under ``AGENTS.md``. So the lease is
    released and the issue parks with the eligible route recorded, which is a
    checkable statement someone can act on rather than a silent hold.

``park``
    Everything else. The lease is released, the issue is parked with the durable
    blocker, and it stays parked until that blocker's condition changes. No
    timer releases it, and nothing here invents budget that was not observed.

Nothing in this module spends, calls a provider, reads a credential, or mutates
GitHub. It returns a decision; ``oc_swarm_claim`` applies one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from app.provider_reservoir.capabilities import CapabilityUnknown
from app.provider_reservoir.routing import DETERMINISTIC_EXECUTORS, route_task
from scripts.oc_budget_blocker import is_budget_denial

#: The governor's own reason vocabulary: uppercase words and underscores.
DENIAL_REASON = re.compile(r"^[A-Z_]+$")

#: Produced by ``oc_budget_blocker.budget_blocker_fingerprint``.
BLOCKER_FINGERPRINT = re.compile(r"^[a-f0-9]{24}$")

PROVIDER_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")

#: The one budget denial that is about a single route rather than a shared pool.
PER_RUN_DENIAL = "BLOCKED_PER_RUN_BUDGET_EXCEEDED"


class Disposition(StrEnum):
    """What happens to the task now that its provider route was refused."""

    PROVIDER_FREE = "provider-free"
    ALTERNATE_PROVIDER = "alternate-provider"
    PARK = "park"


def _money(value: Any) -> Decimal | None:
    """Parse an observed amount, returning ``None`` for anything unobserved.

    Unobserved is not zero and it is not "probably fine". A missing, malformed,
    or negative amount means this module has not seen the budget it would have
    to spend, so the route it would authorise does not exist.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, ArithmeticError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return amount


@dataclass(frozen=True)
class SharedBudget:
    """The governor's ceilings and the spend already observed against them.

    Every field is optional and every absent field is disqualifying. The whole
    disposition this feeds exists to answer "does another route fit inside the
    policy we already have", and an unobserved ceiling cannot be fitted inside.
    """

    per_run_budget_usd: Decimal | None = None
    daily_budget_usd: Decimal | None = None
    monthly_budget_usd: Decimal | None = None
    daily_spend_usd: Decimal | None = None
    monthly_spend_usd: Decimal | None = None

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> SharedBudget:
        raw = raw or {}
        return cls(
            per_run_budget_usd=_money(raw.get("per_run_budget_usd")),
            daily_budget_usd=_money(raw.get("daily_budget_usd")),
            monthly_budget_usd=_money(raw.get("monthly_budget_usd")),
            daily_spend_usd=_money(raw.get("daily_spend_usd")),
            monthly_spend_usd=_money(raw.get("monthly_spend_usd")),
        )

    @property
    def observed(self) -> bool:
        return all(
            value is not None
            for value in (
                self.per_run_budget_usd,
                self.daily_budget_usd,
                self.monthly_budget_usd,
                self.daily_spend_usd,
                self.monthly_spend_usd,
            )
        )

    def admits(self, estimated_cost_usd: Decimal | None) -> bool:
        """Whether a route costing this much clears every ceiling.

        Deliberately the same three comparisons ``swarm_governor_precheck``
        makes, in the same order. If they ever diverge, the precheck is
        authoritative — this is a pre-filter that avoids proposing a route the
        governor would refuse, never a substitute for asking it.
        """
        if estimated_cost_usd is None or not self.observed:
            return False
        if estimated_cost_usd > self.per_run_budget_usd:
            return False
        if (self.daily_spend_usd + estimated_cost_usd) > self.daily_budget_usd:
            return False
        return (self.monthly_spend_usd + estimated_cost_usd) <= self.monthly_budget_usd


@dataclass(frozen=True)
class ProviderCandidate:
    """One governed provider the caller has already established is authorized.

    ``authorized`` is the caller's statement, derived from the governor's
    allowlist and switches. This module never promotes a provider to authorized
    on its own; it only declines to consider one that is not.
    """

    name: str
    authorized: bool = False
    estimated_cost_usd: Decimal | None = None

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> ProviderCandidate:
        name = str(raw.get("name") or "").strip().lower()
        if not PROVIDER_NAME.fullmatch(name):
            raise ValueError("invalid provider candidate name")
        return cls(
            name=name,
            authorized=raw.get("authorized") is True,
            estimated_cost_usd=_money(raw.get("estimated_cost_usd")),
        )


@dataclass(frozen=True)
class DenialRoute:
    """Where the task goes, and the exact reason it goes there."""

    issue_number: int
    disposition: Disposition
    reason: str
    blocker: str
    blocker_fingerprint: str | None = None
    denied_provider: str | None = None
    executor: str | None = None
    provider: str | None = None
    parked_capabilities: list[str] = field(default_factory=list)

    @property
    def requeues(self) -> bool:
        """Whether the issue returns to the canonical queue in this pass.

        Only the deterministic disposition does. A requeue is safe exactly when
        the planner will route the issue somewhere other than the provider that
        just refused it, and ``lane_executable`` is what makes that true.
        """
        return self.disposition is Disposition.PROVIDER_FREE

    @property
    def target_label(self) -> str:
        return "oc-queued" if self.requeues else "oc-blocked"

    @property
    def records_blocker(self) -> bool:
        """Only a parked task writes a durable ``OC-BLOCKED-ON`` line.

        A requeued task is not blocked on anything, and recording a blocker for
        it would make the next reconciliation hold work that is running.
        """
        return not self.requeues

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": "oc.budget-denial-route.v1",
            "issue_number": self.issue_number,
            "disposition": str(self.disposition),
            "reason": self.reason,
            "blocker": self.blocker if self.records_blocker else None,
            "blocker_fingerprint": self.blocker_fingerprint if self.records_blocker else None,
            "denied_provider": self.denied_provider,
            "executor": self.executor,
            "provider": self.provider,
            "parked_capabilities": list(self.parked_capabilities),
            "requeues": self.requeues,
            "target_label": self.target_label,
            "provider_called": False,
        }


def _candidates(providers: Iterable[Any] | None) -> list[ProviderCandidate]:
    rows: list[ProviderCandidate] = []
    for entry in providers or ():
        if isinstance(entry, ProviderCandidate):
            rows.append(entry)
            continue
        if not isinstance(entry, dict):
            raise TypeError("invalid provider candidate")
        rows.append(ProviderCandidate.from_mapping(entry))
    return rows


def decide_denial_route(
    issue: dict[str, Any],
    *,
    reason: str,
    blocker_fingerprint: str | None = None,
    denied_provider: str | None = None,
    providers: Iterable[Any] | None = None,
    shared_budget: SharedBudget | dict[str, Any] | None = None,
) -> DenialRoute:
    """Return the deterministic disposition for one denied task.

    Raises rather than guessing when the denial itself is malformed: a reason
    outside the governor's vocabulary, or a budget denial with no fingerprint,
    means the caller does not actually know what refused this work, and parking
    it under an unidentified blocker would produce a hold nothing can ever clear.
    """
    number = int(issue.get("number") or 0)
    reason = str(reason or "").strip()
    if not DENIAL_REASON.fullmatch(reason):
        raise ValueError("invalid governor denial reason")

    budget_denial = is_budget_denial(reason)
    fingerprint = str(blocker_fingerprint or "").strip().lower()
    if budget_denial and not BLOCKER_FINGERPRINT.fullmatch(fingerprint):
        raise ValueError("budget blocker fingerprint unavailable")
    blocker = f"budget:{fingerprint}" if budget_denial else f"governor:{reason}"
    denied = str(denied_provider or "").strip().lower() or None

    try:
        routing = route_task(issue)
    except (CapabilityUnknown, ValueError):
        # An unclassifiable capability is exactly the case where guessing a
        # lane is most expensive. Fall through to the park, which is visible
        # and reversible, rather than admitting the task to a worker whose
        # ability to run it is unknown.
        routing = None

    if routing is not None and routing.lane_executable:
        return DenialRoute(
            issue_number=number,
            disposition=Disposition.PROVIDER_FREE,
            reason=(
                f"{reason} refused a provider route, and this task declares "
                f"deterministic work the {routing.executable_task!r} executor can run; "
                "the deterministic lane spends nothing, so the denial does not reach it"
            ),
            blocker=blocker,
            blocker_fingerprint=fingerprint or None,
            denied_provider=denied,
            executor=routing.executable_task,
            parked_capabilities=list(routing.parked_capabilities),
        )

    budget = (
        shared_budget
        if isinstance(shared_budget, SharedBudget)
        else SharedBudget.from_mapping(shared_budget)
    )
    if reason == PER_RUN_DENIAL:
        for candidate in sorted(_candidates(providers), key=lambda row: row.name):
            if candidate.name == denied or not candidate.authorized:
                continue
            if not budget.admits(candidate.estimated_cost_usd):
                continue
            return DenialRoute(
                issue_number=number,
                disposition=Disposition.ALTERNATE_PROVIDER,
                reason=(
                    f"{reason} refused {denied or 'the primary route'}; the already-authorized "
                    f"{candidate.name!r} route costs {candidate.estimated_cost_usd} USD, which "
                    "clears the observed per-run, daily and monthly ceilings"
                ),
                blocker=blocker,
                blocker_fingerprint=fingerprint or None,
                denied_provider=denied,
                provider=candidate.name,
            )

    if routing is None:
        park_reason = (
            f"{reason} refused the provider route and this task declares a capability "
            "outside the registry, so no lane can be chosen for it without guessing"
        )
    elif routing.has_deterministic_work:
        park_reason = (
            f"{reason} refused the provider route; the task declares deterministic work "
            f"but no executor implements it ({routing.unexecutable_reason})"
        )
    else:
        park_reason = (
            f"{reason} refused the provider route and the task has no deterministic work; "
            "it stays parked until the recorded blocker condition changes"
        )

    return DenialRoute(
        issue_number=number,
        disposition=Disposition.PARK,
        reason=park_reason,
        blocker=blocker,
        blocker_fingerprint=fingerprint or None,
        denied_provider=denied,
        parked_capabilities=list(routing.parked_capabilities) if routing else [],
    )


__all__ = [
    "BLOCKER_FINGERPRINT",
    "DETERMINISTIC_EXECUTORS",
    "DenialRoute",
    "Disposition",
    "ProviderCandidate",
    "SharedBudget",
    "decide_denial_route",
]
