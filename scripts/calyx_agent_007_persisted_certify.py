"""Drive the AGENT-007 certification through the persisted completion path.

``scripts/calyx_engineering_certify.py`` exercises the *direct* repair endpoint:
one HTTP call in, one patch out. That is not what AGENT-007 certifies. The
certification is about the durable governor - a job row that is enqueued,
claimed under a lease, advanced one bounded step at a time, and parked back in
``queued`` between CI polls. A direct repair call proves the provider works; it
proves nothing about claim/lease integrity, attempt accounting, or termination.

So this driver speaks only to the persisted endpoints:

    GET  /brain/engineering/completion-jobs                     discover/reuse
    POST /brain/engineering/pull-requests/{pr}/completion-jobs   enqueue
    POST /brain/engineering/completion-jobs/run-once             one bounded step
    GET  /brain/engineering/completion-jobs/{job_id}             observe

and records the job's persisted state after every step. Nothing here decides
anything. It cannot merge, cannot deploy, and cannot repair - the governor
inside the service does all of that. If this driver were removed the governor
would behave identically; only the evidence would be lost.

Exit status is deliberately blunt: 0 only when the governor reached
``ready_for_merge``. A certification that reports success on a governor that
stalled is worse than no certification.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TERMINAL_SUCCESS = "ready_for_merge"
TERMINAL_HALTS = (
    "halted_repair_limit",
    "halted_unsafe_pr_state",
)
CERTIFICATION_MARKER = "CALYX-AGENT-007_CERTIFICATION_EXPECTED_FAILURE"
ACTIVE_JOB_STATUSES = {"queued", "running"}


@dataclass
class Evidence:
    """Append-only. Every transition is written as it is observed."""

    transitions: list[dict] = field(default_factory=list)

    def record(self, label: str, payload: dict) -> None:
        entry = {
            "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "step": label,
            **payload,
        }
        self.transitions.append(entry)
        print(json.dumps(entry, sort_keys=True, default=str), flush=True)


def _call(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    payload: dict | None = None,
) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "User-Agent": "calyx-agent-007-persisted-certification",
        },
    )
    try:
        with urlopen(request, timeout=180) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:4000]
        raise RuntimeError(f"HTTP_{exc.code}:{detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"CERTIFICATION_ENDPOINT_UNREACHABLE:{exc.reason}") from exc


def _active_job_for_pr(
    *,
    base_url: str,
    api_key: str,
    pull_request: int,
) -> dict | None:
    listing = _call(
        base_url,
        api_key,
        "GET",
        f"/brain/engineering/completion-jobs?pull_request_number={pull_request}&limit=10",
    )
    for job in listing.get("jobs") or []:
        if job.get("status") in ACTIVE_JOB_STATUSES:
            return job
    return None


def _job_matches_authorization(
    job: dict,
    *,
    paths: list[str],
    required_checks: list[str],
    objective: str,
) -> bool:
    """Reuse only a job carrying the same bounded certification authority.

    The exact prose of the objective changed during debugging, so marker-equivalent
    objectives are accepted only when the repair path and required-check roster are
    exact matches and the persisted job explicitly records repair authorization.
    """
    job_paths = sorted(str(value) for value in (job.get("repair_paths") or []))
    requested_paths = sorted(str(value) for value in paths)
    job_checks = sorted(str(value) for value in (job.get("required_checks") or []))
    requested_checks = sorted(str(value) for value in required_checks)
    job_objective = str(job.get("objective") or "")
    objective_matches = job_objective == objective or (
        CERTIFICATION_MARKER in job_objective and CERTIFICATION_MARKER in objective
    )
    return (
        bool(job.get("repairs_authorized"))
        and job_paths == requested_paths
        and job_checks == requested_checks
        and objective_matches
    )


def _resolve_job(
    *,
    base_url: str,
    api_key: str,
    pull_request: int,
    paths: list[str],
    required_checks: list[str],
    objective: str,
    evidence: Evidence,
) -> tuple[str, int | None]:
    """Return a safe existing/new job id, or a terminal driver code.

    A GitHub workflow can fail while the durable backend governor remains alive.
    Re-enqueuing in that state previously produced
    ENGINEERING_COMPLETION_RUNNING_JOB_CONFLICT and the certification mislabeled
    it as a transport failure. We now observe first and reuse the live job only
    when its persisted authority is equivalent to this certification request.
    """
    active = _active_job_for_pr(
        base_url=base_url,
        api_key=api_key,
        pull_request=pull_request,
    )
    if active is not None:
        if not _job_matches_authorization(
            active,
            paths=paths,
            required_checks=required_checks,
            objective=objective,
        ):
            evidence.record(
                "active_job_authorization_conflict",
                {
                    "job": active,
                    "reason": "existing active job does not match certification authority",
                },
            )
            return "", 3
        job_id = str(active.get("job_id") or "")
        if not job_id:
            evidence.record("active_job_invalid", {"job": active})
            return "", 2
        evidence.record("reused_active_job", {"job": active})
        return job_id, None

    payload = {
        "paths": paths,
        "objective": objective,
        "required_checks": required_checks,
        "repairs_authorized": True,
    }
    try:
        created = _call(
            base_url,
            api_key,
            "POST",
            f"/brain/engineering/pull-requests/{pull_request}/completion-jobs",
            payload,
        )
    except RuntimeError as exc:
        # A worker may claim the job between our read and enqueue. That race is
        # recoverable: re-read the persisted row and reuse it if the authority
        # still matches. Other HTTP/transport failures remain genuine failures.
        if "ENGINEERING_COMPLETION_RUNNING_JOB_CONFLICT" not in str(exc):
            raise
        active = _active_job_for_pr(
            base_url=base_url,
            api_key=api_key,
            pull_request=pull_request,
        )
        if active is None or not _job_matches_authorization(
            active,
            paths=paths,
            required_checks=required_checks,
            objective=objective,
        ):
            evidence.record(
                "running_job_conflict",
                {"error": str(exc), "job": active},
            )
            return "", 3
        job_id = str(active.get("job_id") or "")
        if not job_id:
            evidence.record("active_job_invalid", {"job": active})
            return "", 2
        evidence.record(
            "reused_active_job_after_enqueue_race",
            {"job": active, "enqueue_error": str(exc)},
        )
        return job_id, None

    job_id = str(created.get("job_id") or "")
    if not job_id:
        evidence.record("enqueue_failed", {"response": created})
        return "", 2
    evidence.record("enqueued", {"job": created})
    return job_id, None


def certify(
    *,
    base_url: str,
    api_key: str,
    pull_request: int,
    paths: list[str],
    required_checks: list[str],
    objective: str,
    max_steps: int,
    poll_seconds: int,
) -> tuple[int, Evidence]:
    evidence = Evidence()

    evidence.record(
        "service_status",
        {"status": _call(base_url, api_key, "GET", "/brain/engineering/status")},
    )

    job_id, terminal_code = _resolve_job(
        base_url=base_url,
        api_key=api_key,
        pull_request=pull_request,
        paths=paths,
        required_checks=required_checks,
        objective=objective,
        evidence=evidence,
    )
    if terminal_code is not None:
        return terminal_code, evidence

    state = None
    for step in range(1, max_steps + 1):
        outcome = _call(
            base_url,
            api_key,
            "POST",
            "/brain/engineering/completion-jobs/run-once",
            {},
        )
        observed = _call(
            base_url,
            api_key,
            "GET",
            f"/brain/engineering/completion-jobs/{job_id}",
        )
        state = observed.get("state")
        evidence.record(
            f"step_{step}",
            {
                "run_once": outcome,
                "persisted_job": observed,
                "state": state,
                "attempt_count": observed.get("attempt_count"),
            },
        )

        if state == TERMINAL_SUCCESS:
            evidence.record(
                "terminated",
                {
                    "state": state,
                    "autonomous_merge": observed.get("autonomous_merge"),
                    "deployment": observed.get("deployment"),
                },
            )
            return 0, evidence
        if state in TERMINAL_HALTS or observed.get("status") in (
            "dead_letter",
            "blocked_approval",
        ):
            evidence.record(
                "halted",
                {
                    "state": state,
                    "status": observed.get("status"),
                    "error_code": observed.get("error_code"),
                },
            )
            return 3, evidence

        time.sleep(poll_seconds)

    evidence.record("exhausted", {"state": state, "max_steps": max_steps})
    return 4, evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("CALYX_BACKEND_URL", ""))
    parser.add_argument("--api-key", default=os.getenv("CALYX_API_KEY", ""))
    parser.add_argument("--pull-request", type=int, required=True)
    parser.add_argument("--path", action="append", required=True, dest="paths")
    parser.add_argument(
        "--required-check",
        action="append",
        required=True,
        dest="required_checks",
    )
    parser.add_argument(
        "--objective",
        default=(
            "Repair only the deterministic certification failure marked "
            "CALYX-AGENT-007_CERTIFICATION_EXPECTED_FAILURE. Change no other line or file."
        ),
    )
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--evidence-out", default="")
    args = parser.parse_args()

    if not args.base_url or not args.api_key:
        parser.error(
            "--base-url and --api-key (or CALYX_BACKEND_URL / CALYX_API_KEY) are required"
        )

    try:
        code, evidence = certify(
            base_url=args.base_url,
            api_key=args.api_key,
            pull_request=args.pull_request,
            paths=args.paths,
            required_checks=args.required_checks,
            objective=args.objective,
            max_steps=args.max_steps,
            poll_seconds=args.poll_seconds,
        )
    except RuntimeError as exc:
        print(
            json.dumps({"step": "transport_error", "error": str(exc)}),
            file=sys.stderr,
            flush=True,
        )
        return 5

    if args.evidence_out:
        with open(args.evidence_out, "w", encoding="utf-8") as handle:
            json.dump(
                {"transitions": evidence.transitions},
                handle,
                indent=2,
                sort_keys=True,
                default=str,
            )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
