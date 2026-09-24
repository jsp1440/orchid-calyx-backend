"""The denial loop #1401 ran on 2026-09-23, reproduced and then closed.

The loop was: queued → lease → Claude → BLOCKED_MONTHLY_BUDGET_EXCEEDED →
release → oc-blocked → requeue → the same Claude route, three times in eight
minutes with ``provider_called=false`` each time. These tests pin both halves of
the repair — what a denial decides now, and that a parked budget blocker is not
handed back to the queue until its condition changes.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from scripts import oc_blocked_reconcile as reconciler
from scripts.oc_budget_denial_route import (
    Disposition,
    ProviderCandidate,
    SharedBudget,
    decide_denial_route,
)

FINGERPRINT = "2354e80553d26812687946a6"
CHANGED_FINGERPRINT = "b" * 24
MONTHLY = "BLOCKED_MONTHLY_BUDGET_EXCEEDED"
PER_RUN = "BLOCKED_PER_RUN_BUDGET_EXCEEDED"


def issue(body: str, *, number: int = 1401) -> dict:
    return {"number": number, "state": "OPEN", "title": "t", "body": body}


# The shape of #1401: it declares a queue capability in its own vocabulary and
# no OC-SWARM capability at all, so nothing classifies it as deterministic.
UNDECLARED = "OC-QUEUE-CAPABILITY: runtime:bounded-autonomous-lanes:v1"
RECONCILABLE = "OC-SWARM-PROVIDER-FREE: reconcile\nOC-SWARM-DISPOSITION: done"
VALIDATABLE = (
    "OC-SWARM-PROVIDER-FREE: validate\n"
    "OC-SWARM-VALIDATE: control-plane-tests\n"
    "OC-SWARM-DISPOSITION: done"
)
# Deterministic work that no executor implements: provider-free, unstaffed.
UNSTAFFED = "OC-SWARM-CAPABILITY: taxonomy-resolution"


class TestDeterministicReroute:
    def test_task_with_an_existing_executor_returns_to_the_queue(self) -> None:
        route = decide_denial_route(
            issue(VALIDATABLE), reason=MONTHLY, blocker_fingerprint=FINGERPRINT
        )
        assert route.disposition is Disposition.PROVIDER_FREE
        assert route.executor == "validate"
        assert route.requeues is True
        assert route.target_label == "oc-queued"

    def test_a_reroute_records_no_blocker(self) -> None:
        """A rerouted task is not blocked on anything.

        Recording a blocker for work that is about to run is how the next
        reconciliation pass would hold it, which is the loop wearing the other
        mask.
        """
        route = decide_denial_route(
            issue(RECONCILABLE), reason=MONTHLY, blocker_fingerprint=FINGERPRINT
        )
        record = route.to_record()
        assert route.records_blocker is False
        assert record["blocker"] is None
        assert record["blocker_fingerprint"] is None

    def test_reroute_applies_to_non_budget_denials_too(self) -> None:
        # A kill switch stops paid execution. It says nothing about a lane that
        # cannot spend, so deterministic work is not collateral damage.
        route = decide_denial_route(issue(RECONCILABLE), reason="BLOCKED_KILL_SWITCH")
        assert route.disposition is Disposition.PROVIDER_FREE

    def test_rerouted_work_is_not_handed_back_to_the_provider_lane(self) -> None:
        """The property that makes a requeue safe rather than a new loop.

        The planner splits lanes on ``is_lane_executable``. Every task this
        module returns to the queue must satisfy that predicate, or the next
        wave hands it straight back to the provider that refused it.
        """
        from scripts import oc_swarm_controller as controller

        for body in (RECONCILABLE, VALIDATABLE):
            rerouted = issue(body)
            route = decide_denial_route(
                rerouted, reason=MONTHLY, blocker_fingerprint=FINGERPRINT
            )
            assert route.requeues is True
            assert controller.is_lane_executable(rerouted) is True

        for body in (UNDECLARED, UNSTAFFED):
            parked = issue(body)
            route = decide_denial_route(
                parked, reason=MONTHLY, blocker_fingerprint=FINGERPRINT
            )
            assert route.requeues is False
            assert controller.is_lane_executable(parked) is False


class TestPark:
    def test_issue_1401_shape_parks_instead_of_requeueing(self) -> None:
        route = decide_denial_route(
            issue(UNDECLARED), reason=MONTHLY, blocker_fingerprint=FINGERPRINT
        )
        assert route.disposition is Disposition.PARK
        assert route.requeues is False
        assert route.target_label == "oc-blocked"
        assert route.blocker == f"budget:{FINGERPRINT}"
        assert "no deterministic work" in route.reason

    def test_provider_free_but_unstaffed_work_parks_and_says_why(self) -> None:
        route = decide_denial_route(
            issue(UNSTAFFED), reason=MONTHLY, blocker_fingerprint=FINGERPRINT
        )
        assert route.disposition is Disposition.PARK
        assert "no executor implements it" in route.reason

    def test_unclassifiable_capability_parks_rather_than_guessing_a_lane(self) -> None:
        route = decide_denial_route(
            issue("OC-SWARM-CAPABILITY: teleport-the-corpus"),
            reason=MONTHLY,
            blocker_fingerprint=FINGERPRINT,
        )
        assert route.disposition is Disposition.PARK
        assert "outside the registry" in route.reason

    def test_a_budget_denial_without_a_fingerprint_is_refused(self) -> None:
        with pytest.raises(ValueError, match="fingerprint"):
            decide_denial_route(issue(UNDECLARED), reason=MONTHLY)

    def test_a_reason_outside_the_governor_vocabulary_is_refused(self) -> None:
        with pytest.raises(ValueError, match="denial reason"):
            decide_denial_route(issue(UNDECLARED), reason="budget exceeded")

    def test_non_budget_denial_parks_under_a_governor_blocker(self) -> None:
        route = decide_denial_route(issue(UNDECLARED), reason="BLOCKED_KILL_SWITCH")
        assert route.blocker == "governor:BLOCKED_KILL_SWITCH"
        assert route.to_record()["blocker_fingerprint"] is None


class TestAlternateProvider:
    HEADROOM = SharedBudget(
        per_run_budget_usd=Decimal("1.00"),
        daily_budget_usd=Decimal("50.00"),
        monthly_budget_usd=Decimal("500.00"),
        daily_spend_usd=Decimal("2.00"),
        monthly_spend_usd=Decimal("120.00"),
    )

    def test_a_cheaper_authorized_route_is_named_when_it_clears_every_ceiling(self) -> None:
        route = decide_denial_route(
            issue(UNDECLARED),
            reason=PER_RUN,
            blocker_fingerprint=FINGERPRINT,
            denied_provider="anthropic",
            providers=[
                ProviderCandidate("gemini", authorized=True, estimated_cost_usd=Decimal("0.40")),
            ],
            shared_budget=self.HEADROOM,
        )
        assert route.disposition is Disposition.ALTERNATE_PROVIDER
        assert route.provider == "gemini"

    def test_a_named_alternate_still_releases_the_lease_without_requeueing(self) -> None:
        """Naming a route is not taking it.

        Requeueing here would hand the issue back to the primary route that just
        refused it, and dispatching a second paid provider is an owner gate. The
        eligible route is recorded so it is actionable, and the issue parks.
        """
        route = decide_denial_route(
            issue(UNDECLARED),
            reason=PER_RUN,
            blocker_fingerprint=FINGERPRINT,
            denied_provider="anthropic",
            providers=[
                ProviderCandidate("gemini", authorized=True, estimated_cost_usd=Decimal("0.40")),
            ],
            shared_budget=self.HEADROOM,
        )
        assert route.requeues is False
        assert route.records_blocker is True
        assert route.to_record()["provider"] == "gemini"

    def test_a_shared_pool_exhaustion_admits_no_alternate(self) -> None:
        # A monthly denial is not about one route. Offering another provider
        # would be manufacturing budget that does not exist.
        route = decide_denial_route(
            issue(UNDECLARED),
            reason=MONTHLY,
            blocker_fingerprint=FINGERPRINT,
            denied_provider="anthropic",
            providers=[
                ProviderCandidate("gemini", authorized=True, estimated_cost_usd=Decimal("0.01")),
            ],
            shared_budget=self.HEADROOM,
        )
        assert route.disposition is Disposition.PARK

    def test_an_unauthorized_provider_is_never_promoted(self) -> None:
        route = decide_denial_route(
            issue(UNDECLARED),
            reason=PER_RUN,
            blocker_fingerprint=FINGERPRINT,
            denied_provider="anthropic",
            providers=[ProviderCandidate("gemini", estimated_cost_usd=Decimal("0.01"))],
            shared_budget=self.HEADROOM,
        )
        assert route.disposition is Disposition.PARK

    def test_an_unobserved_budget_is_not_spendable(self) -> None:
        route = decide_denial_route(
            issue(UNDECLARED),
            reason=PER_RUN,
            blocker_fingerprint=FINGERPRINT,
            denied_provider="anthropic",
            providers=[
                ProviderCandidate("gemini", authorized=True, estimated_cost_usd=Decimal("0.01")),
            ],
            shared_budget=None,
        )
        assert route.disposition is Disposition.PARK

    def test_an_alternate_that_would_breach_the_monthly_pool_is_refused(self) -> None:
        tight = SharedBudget(
            per_run_budget_usd=Decimal("1.00"),
            daily_budget_usd=Decimal("50.00"),
            monthly_budget_usd=Decimal("120.50"),
            daily_spend_usd=Decimal("2.00"),
            monthly_spend_usd=Decimal("120.00"),
        )
        route = decide_denial_route(
            issue(UNDECLARED),
            reason=PER_RUN,
            blocker_fingerprint=FINGERPRINT,
            denied_provider="anthropic",
            providers=[
                ProviderCandidate("gemini", authorized=True, estimated_cost_usd=Decimal("0.90")),
            ],
            shared_budget=tight,
        )
        assert route.disposition is Disposition.PARK

    def test_the_denied_provider_is_never_proposed_back_to_itself(self) -> None:
        route = decide_denial_route(
            issue(UNDECLARED),
            reason=PER_RUN,
            blocker_fingerprint=FINGERPRINT,
            denied_provider="anthropic",
            providers=[
                ProviderCandidate("anthropic", authorized=True, estimated_cost_usd=Decimal("0.10")),
            ],
            shared_budget=self.HEADROOM,
        )
        assert route.disposition is Disposition.PARK


class TestTheLoopIsClosed:
    """Park and requeue are the two halves; this checks they agree."""

    def blocked_issue(self, blocker: str) -> dict:
        return {
            "number": 1401,
            "state": "OPEN",
            "body": UNDECLARED,
            "labels": [{"name": "oc-blocked"}, {"name": "oc-p1"}],
            "comments": [
                {"id": 1, "body": "[OC-SWARM-V4] ...\nOC-BLOCKED-ON: pr#1464"},
                {"id": 2, "body": f"[OC-SWARM-V4] ...\nOC-BLOCKED-ON: {blocker}"},
            ],
        }

    def test_a_parked_budget_blocker_is_held_while_the_condition_stands(self) -> None:
        route = decide_denial_route(
            issue(UNDECLARED), reason=MONTHLY, blocker_fingerprint=FINGERPRINT
        )
        world = reconciler.WorldState(
            open_issues={1401},
            merged_prs={1464},
            budget_fingerprints={1401: FINGERPRINT},
        )
        results = reconciler.reconcile([self.blocked_issue(route.blocker)], world)
        assert [r.disposition for r in results] == [reconciler.Disposition.HOLD]
        # The merged PR #1464 is the stale marker that released this issue three
        # times on 2026-09-23. The newest blocker is the budget one and it wins.
        assert results[0].blocker == f"budget:{FINGERPRINT}"
        assert reconciler.release_plan(results)["action_count"] == 0

    def test_the_same_blocker_still_holds_on_a_later_pass(self) -> None:
        route = decide_denial_route(
            issue(UNDECLARED), reason=MONTHLY, blocker_fingerprint=FINGERPRINT
        )
        world = reconciler.WorldState(
            open_issues={1401},
            merged_prs={1464},
            budget_fingerprints={1401: FINGERPRINT},
        )
        for _ in range(3):
            results = reconciler.reconcile([self.blocked_issue(route.blocker)], world)
            assert reconciler.release_plan(results)["action_count"] == 0

    def test_a_materially_changed_condition_releases_exactly_once(self) -> None:
        route = decide_denial_route(
            issue(UNDECLARED), reason=MONTHLY, blocker_fingerprint=FINGERPRINT
        )
        world = reconciler.WorldState(
            open_issues={1401},
            merged_prs=set(),
            budget_fingerprints={1401: CHANGED_FINGERPRINT},
        )
        results = reconciler.reconcile([self.blocked_issue(route.blocker)], world)
        assert [r.disposition for r in results] == [reconciler.Disposition.RELEASE]
        plan = reconciler.release_plan(results)
        assert plan["action_count"] == 1
        assert plan["actions"][0]["idempotency_key"] == (
            f"blocked-release:1401:budget:{FINGERPRINT}"
        )
