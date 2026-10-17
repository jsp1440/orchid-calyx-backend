"""One rule for which controller runs are trusted to have run paid workers.

Hosted completion (before the checker), the control-plane health observer
(after the merge) and the planner's paid guard must agree, or a paid worker
is either integrated and then reported unhealthy, or launched and then never
integrated (#1848 review, findings B1/B2).

A run is on a trusted ref when it is either
* on ``oc-autonomous-integration`` (dispatched waves), or
* a ``schedule`` run recorded on the repository's default branch: GitHub runs
  schedules from the default branch, and the controller then checks out the
  integration head itself and only plans paid work when that checkout is the
  integration head.

Any other trigger (a PR closing, an issue event, a dispatch on another ref)
runs from its own SHA and is never trusted.
"""

from __future__ import annotations

INTEGRATION_BRANCH = "oc-autonomous-integration"


def on_trusted_controller_ref(
    run: dict, default_branch: str | None, *, repository: str | None = None
) -> bool:
    head_repository = (run.get("head_repository") or {}).get("full_name")
    if repository and head_repository and head_repository != repository:
        return False
    branch = run.get("head_branch")
    if branch == INTEGRATION_BRANCH:
        return run.get("event") != "pull_request"
    return (
        run.get("event") == "schedule"
        and bool(default_branch)
        and branch == default_branch
    )
