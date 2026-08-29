"""Build a truthful machine-readable Orchid control-plane health receipt."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from datetime import datetime, timezone

UNKNOWN = "UNKNOWN"


def _labels(item: dict) -> set[str]:
    return {
        str(label.get("name") if isinstance(label, dict) else label)
        for label in item.get("labels") or []
    }


def classify_ci(runs: Iterable[dict]) -> dict:
    runs = list(runs or [])
    if not runs:
        return {"state": UNKNOWN, "reason": "no_run_evidence"}
    latest = runs[0]
    jobs = latest.get("jobs")
    if jobs is None:
        return {"state": UNKNOWN, "reason": "job_evidence_unavailable", "run_id": latest.get("id")}
    failed_without_runner = [
        job for job in jobs
        if job.get("conclusion") == "failure"
        and job.get("runner_id") in (0, None)
        and not (job.get("steps") or [])
    ]
    if failed_without_runner:
        return {
            "state": "EXTERNAL_INFRASTRUCTURE_BLOCKED",
            "reason": "runner_allocation_failure",
            "run_id": latest.get("id"),
            "runner_id": failed_without_runner[0].get("runner_id"),
            "executed_step_count": 0,
        }
    if latest.get("status") == "completed" and latest.get("conclusion") == "success":
        return {"state": "HEALTHY", "reason": "executed_success", "run_id": latest.get("id")}
    return {"state": "CODE_OR_CHECK_FAILURE", "reason": "runner_executed_non_success", "run_id": latest.get("id")}


def build_health(snapshot: dict) -> dict:
    issues = list(snapshot.get("issues") or [])
    running = [i for i in issues if "oc-running" in _labels(i)]
    queued_p0 = [i for i in issues if {"oc-queued", "oc-p0"} <= _labels(i)]
    validating = [i for i in issues if "oc-validating" in _labels(i)]
    blocked = [i for i in issues if {"oc-blocked", "oc-runtime-backoff", "oc-repair-backoff"} & _labels(i)]
    ci = classify_ci(snapshot.get("scheduler_runs") or [])
    reason = None
    if not running:
        if ci["state"] == "EXTERNAL_INFRASTRUCTURE_BLOCKED":
            reason = "scheduler_job_never_received_a_runner"
        elif snapshot.get("provider_chain_state") == "BLOCKED":
            reason = "all_authorized_providers_blocked"
        elif queued_p0:
            reason = "eligible_p0_waiting_for_scheduler"
        else:
            reason = UNKNOWN
    exact_head = snapshot.get("last_successful_exact_head_validation", UNKNOWN)
    return {
        "schema": "orchid.control-plane-health.v1",
        "generated_at": snapshot.get("generated_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scheduler_heartbeat": snapshot.get("scheduler_heartbeat", UNKNOWN),
        "last_dispatch_time": snapshot.get("last_dispatch_time", UNKNOWN),
        "current_running_lease": running[0].get("number") if len(running) == 1 else (None if not running else UNKNOWN),
        "running_lease_count": len(running),
        "queued_p0_count": len(queued_p0),
        "validating_count": len(validating),
        "stale_lease_count": snapshot.get("stale_lease_count", UNKNOWN),
        "blocked_backoff_count": len(blocked),
        "provider_availability_state": snapshot.get("provider_availability_state", UNKNOWN),
        "ci_infrastructure_state": ci,
        "integration_head": snapshot.get("integration_head", UNKNOWN),
        "main_head": snapshot.get("main_head", UNKNOWN),
        "last_successful_exact_head_validation": exact_head,
        "last_integration_promotion": snapshot.get("last_integration_promotion", UNKNOWN),
        "last_main_promotion": snapshot.get("last_main_promotion", UNKNOWN),
        "duplicate_authoritative_mission_count": snapshot.get("duplicate_authoritative_mission_count", UNKNOWN),
        "reason_no_work_running": reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="-")
    args = parser.parse_args()
    if args.input == "-":
        raw = sys.stdin.read()
    else:
        with open(args.input, encoding="utf-8") as handle:
            raw = handle.read()
    json.dump(build_health(json.loads(raw)), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
