"""Calyx-side observers for the Brain autonomy loop (module health, repair).

``calyx_brain.autonomy_loop`` observes repository, scientific and governance
signals. Calyx owns two more, both read from its own durable records:

* recurring unhealthy cycle receipts: the same defect category and reason
  code in several of the recent scheduled cycles, e.g. a missing executor, a
  configuration fault or undelivered execution;
* blocked program jobs: jobs whose execution stopped with a blocker,
  including failed static validation, from any lane, not only the loop's.

Both yield ``system_repair`` candidates without a packet. The loop's policy
makes them durable proposals that need human approval, and Calyx has no
autonomous repair executor, so they are reported and never executed.
Fingerprints are stable per defect, so a recurring defect is one proposal,
not one per cycle.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .program_models import CalyxAutonomyCycle, CalyxProgram, CalyxProgramJob

UNHEALTHY_WINDOW = 50
RECURRENCE_THRESHOLD = 3
MAX_BLOCKED_JOBS = 50


def _fingerprint(*parts: object) -> str:
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class CalyxHealthObserver:
    """Turns recurring defects and blocked jobs into repair candidates."""

    name = "calyx_health"

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        owner: str,
        window: int = UNHEALTHY_WINDOW,
        threshold: int = RECURRENCE_THRESHOLD,
    ) -> None:
        self.session_factory = session_factory
        self.owner = owner
        self.window = window
        self.threshold = threshold

    def observe(self, state: Mapping[str, Any]) -> list[Any]:
        from calyx_brain.autonomy_loop import REPAIR, Candidate

        candidates: list[Any] = []
        with self.session_factory() as db:
            rows = db.scalars(
                select(CalyxAutonomyCycle)
                .where(CalyxAutonomyCycle.owner == self.owner)
                .order_by(CalyxAutonomyCycle.finished_at.desc())
                .limit(self.window)
            ).all()
            recurring = Counter(
                (row.category, row.reason_code or "UNSPECIFIED")
                for row in rows
                if not row.productive and not row.healthy
            )
            for (category, reason), count in sorted(recurring.items()):
                if count < self.threshold:
                    continue
                candidates.append(
                    Candidate(
                        REPAIR,
                        self.name,
                        _fingerprint("cycle-defect", self.owner, category, reason),
                        f"{count} of the last {len(rows)} scheduled cycles were "
                        f"unhealthy with {category} / {reason}.",
                        evidence=(f"category:{category}", f"reason:{reason}"),
                    )
                )
            blocked = db.execute(
                select(CalyxProgramJob)
                .join(
                    CalyxProgram, CalyxProgram.program_id == CalyxProgramJob.program_id
                )
                .where(
                    CalyxProgram.owner == self.owner,
                    CalyxProgramJob.status == "blocked",
                )
                .order_by(CalyxProgramJob.updated_at.desc())
                .limit(MAX_BLOCKED_JOBS)
            ).scalars()
            for job in blocked:
                blocker = (job.blocker or "UNSPECIFIED_BLOCKER")[:160]
                candidates.append(
                    Candidate(
                        REPAIR,
                        self.name,
                        _fingerprint("blocked-job", job.program_job_id, blocker),
                        f"Program job {job.job_key} ({job.role_key}) is blocked: "
                        f"{blocker}.",
                        evidence=(
                            f"program:{job.program_id}",
                            f"job:{job.program_job_id}",
                            f"repository:{job.repository}",
                        ),
                    )
                )
        return candidates


def proposals_summary(db: Session, *, limit: int = 20) -> dict[str, Any] | None:
    """Read-only view of the loop's proposals in database-backed ledgers.

    Approving a proposal stays a reviewed change: add its ``fingerprint`` to
    the approvals file named by ``OC_BRAIN_LOOP_APPROVALS``. Nothing here
    approves, edits or executes anything.
    """
    from .program_models import CalyxBrainPulseLedger

    try:
        ledgers = db.scalars(select(CalyxBrainPulseLedger)).all()
    except Exception:  # noqa: BLE001 - table absent before the first ledger write
        db.rollback()
        return None
    states: Counter[str] = Counter()
    classes: Counter[str] = Counter()
    items: list[dict[str, Any]] = []
    for ledger in ledgers:
        try:
            state = json.loads(ledger.state_json)
        except (TypeError, ValueError):
            continue
        for proposal in ((state.get("loop") or {}).get("proposals") or {}).values():
            states[str(proposal.get("state"))] += 1
            classes[str(proposal.get("work_class"))] += 1
            items.append({"ledger_key": ledger.ledger_key, **proposal})
    if not items:
        return {"total": 0, "by_state": {}, "by_class": {}, "pending": []}
    pending = sorted(
        (item for item in items if item.get("state") != "approved"),
        key=lambda item: item.get("first_seen") or "",
    )[:limit]
    return {
        "total": len(items),
        "by_state": dict(sorted(states.items())),
        "by_class": dict(sorted(classes.items())),
        "pending": [
            {
                key: item.get(key)
                for key in (
                    "ledger_key",
                    "fingerprint",
                    "work_class",
                    "origin",
                    "state",
                    "rationale",
                    "first_seen",
                    "last_seen",
                )
            }
            for item in pending
        ],
        "how_to_approve": (
            "Add the proposal fingerprint, approved_by and reason to the reviewed "
            "approvals file named by OC_BRAIN_LOOP_APPROVALS "
            "(schema oc-autonomy-approvals.v1)."
        ),
    }


#: Work classes whose approved work is executed by Calyx's governed coding
#: route (``app.autonomy.coding_executor`` -> ``orchid-completion-lane``).
CODING_LANE = "orchid-completion-lane"
CODING_LANE_CLASSES = ("engineering_development", "system_repair")


def coding_lane_status(env: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    """The coding lane's gate as this worker's own configuration states it.

    Mirrors the completion lane's own guards (``scripts/oc_no_api_guard.py``,
    ``scripts/swarm_governor_precheck.py``): an unset or true ``NO_API_MODE``,
    an engaged kill switch, or paid execution not explicitly enabled all block
    the paid coding executor. It reports configuration; it never dispatches,
    calls a provider or spends anything. The repository variables that gate
    the lane in GitHub Actions remain authoritative for the lane itself.
    """
    truthy = {"1", "true", "yes", "on"}
    no_api = str(env.get("NO_API_MODE", "")).strip().lower()
    if no_api == "" or no_api in truthy:
        gate = "no-api-mode"
    elif (
        str(env.get("OC_GOVERNOR_EMERGENCY_KILL_SWITCH", "")).strip().lower() in truthy
    ):
        gate = "governor-kill-switch"
    elif (
        str(env.get("OC_GOVERNOR_PAID_EXECUTION_ENABLED", "")).strip().lower()
        not in truthy
    ):
        gate = "no-authorised-coding-executor"
    elif str(env.get("OC_GOVERNOR_PROVIDER", "")).strip() not in {
        item.strip()
        for item in str(env.get("OC_GOVERNOR_PROVIDER_ALLOWLIST", "")).split(",")
        if item.strip()
    }:
        gate = "provider-not-allowlisted"
    else:
        gate = None
    status = {
        "lane": CODING_LANE,
        "state": "provider_blocked" if gate else "queued",
        "gate": gate,
        "source": "worker_environment",
    }
    return {work_class: dict(status) for work_class in CODING_LANE_CLASSES}
