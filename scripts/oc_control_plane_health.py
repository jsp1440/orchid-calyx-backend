"""Build a truthful machine-readable Orchid control-plane health receipt."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from scripts.oc_health_contract import evaluate as evaluate_health_contract

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
    if latest.get("status") != "completed":
        # A queued or in-progress run has produced no failure or execution evidence
        # yet. Preserve UNKNOWN rather than fabricating a code failure every pulse.
        return {"state": UNKNOWN, "reason": "run_not_completed", "run_id": latest.get("id")}
    if latest.get("conclusion") == "success":
        if not any(job.get("runner_id") and job.get("steps") for job in jobs):
            return {"state": UNKNOWN, "reason": "execution_evidence_unavailable", "run_id": latest.get("id")}
        return {"state": "HEALTHY", "reason": "executed_success", "run_id": latest.get("id")}
    return {"state": "CODE_OR_CHECK_FAILURE", "reason": "runner_executed_non_success", "run_id": latest.get("id")}



def build_contract_snapshot(snapshot: dict) -> dict:
    """Normalize one observer pulse into the canonical health-contract shape.

    Missing collections become empty collections, while malformed records are
    retained so the contract checker can reject them. Provider state is kept
    separate from queue state and no UNKNOWN value is converted into a healthy
    or zero-valued claim.
    """
    raw_issues = snapshot.get("issues")
    issues = list(raw_issues) if isinstance(raw_issues, list) else raw_issues
    raw_leases = snapshot.get("leases", snapshot.get("active_leases"))
    leases = list(raw_leases) if isinstance(raw_leases, list) else raw_leases
    raw_fingerprints = snapshot.get(
        "dispatch_fingerprints", snapshot.get("material_change_fingerprints")
    )
    fingerprints = (
        list(raw_fingerprints)
        if isinstance(raw_fingerprints, list)
        else raw_fingerprints
    )

    provider = snapshot.get("provider")
    if not isinstance(provider, dict):
        provider = {
            "status": snapshot.get(
                "provider_chain_state",
                snapshot.get("provider_availability_state", UNKNOWN),
            )
        }
    integration = snapshot.get("integration")
    if not isinstance(integration, dict):
        integration = {
            "head_sha": snapshot.get("integration_head", UNKNOWN),
            "ready": snapshot.get("integration_ready", UNKNOWN),
        }

    return {
        "schema": "oc.completion-health-snapshot.v1",
        "generated_at": snapshot.get("generated_at")
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "issues": [] if raw_issues is None else issues,
        "leases": [] if raw_leases is None else leases,
        "dispatch_fingerprints": (
            [] if raw_fingerprints is None else fingerprints
        ),
        "autonomous_prs": snapshot.get("autonomous_prs") or [],
        "provider": provider,
        "integration": integration,
        "exceptions": snapshot.get("exceptions") or [],
        "exception_context": snapshot.get("exception_context") or {},
        "autonomous_repair_available": bool(
            snapshot.get("autonomous_repair_available", False)
        ),
        "independent_authorized_work_available": bool(
            snapshot.get("independent_authorized_work_available", False)
        ),
        "deterministic_work_available": bool(
            snapshot.get("deterministic_work_available", False)
        ),
    }


def evaluate_completion_pulse(snapshot: dict) -> dict:
    """Build and evaluate one pulse without mutating queue or provider state."""
    contract_snapshot = build_contract_snapshot(snapshot)
    return {
        "snapshot": contract_snapshot,
        "report": evaluate_health_contract(contract_snapshot),
    }

def build_health(snapshot: dict) -> dict:
    observation_errors = list(snapshot.get("observation_errors") or [])
    for field, aliases in (
        ("issues", ("issues",)),
        ("leases", ("leases", "active_leases")),
        ("dispatch_fingerprints", ("dispatch_fingerprints", "material_change_fingerprints")),
    ):
        if not any(isinstance(snapshot.get(key), list) for key in aliases):
            observation_errors.append({"source": field, "reason": "collection_unavailable"})
    issues_available = not any(error.get("source") == "issues" for error in observation_errors)
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
    contract = evaluate_completion_pulse(snapshot)
    return {
        "schema": "orchid.control-plane-health.v1",
        "healthy": contract["report"]["healthy"] and not observation_errors,
        "observation_complete": not bool(observation_errors),
        "observation_errors": observation_errors,
        "generated_at": snapshot.get("generated_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scheduler_heartbeat": snapshot.get("scheduler_heartbeat", UNKNOWN),
        "last_dispatch_time": snapshot.get("last_dispatch_time", UNKNOWN),
        "current_running_lease": (running[0].get("number") if len(running) == 1 else (None if not running else UNKNOWN)) if issues_available else UNKNOWN,
        "running_lease_count": len(running) if issues_available else UNKNOWN,
        "queued_p0_count": len(queued_p0) if issues_available else UNKNOWN,
        "validating_count": len(validating) if issues_available else UNKNOWN,
        "stale_lease_count": snapshot.get("stale_lease_count", UNKNOWN),
        "blocked_backoff_count": len(blocked) if issues_available else UNKNOWN,
        "provider_availability_state": snapshot.get("provider_availability_state", UNKNOWN),
        "ci_infrastructure_state": ci,
        "integration_head": snapshot.get("integration_head", UNKNOWN),
        "main_head": snapshot.get("main_head", UNKNOWN),
        "last_successful_exact_head_validation": exact_head,
        "last_integration_promotion": snapshot.get("last_integration_promotion", UNKNOWN),
        "last_main_promotion": snapshot.get("last_main_promotion", UNKNOWN),
        "duplicate_authoritative_mission_count": snapshot.get("duplicate_authoritative_mission_count", UNKNOWN),
        "reason_no_work_running": reason,
        "contract_snapshot": contract["snapshot"],
        "contract_health": contract["report"],
    }


MAX_READS = 80
MAX_PAGES = 5
# Diagnostic threshold only: the worker timeout is 70 minutes. Never release a
# lease on this basis; queued runners and a stale observation need reconciliation.
STALE_LEASE_SECONDS = 90 * 60
_CLAIM = re.compile(r"^\[OC-SWARM-V\d+\].*lease claimed:", re.IGNORECASE)
_RELEASE = re.compile(r"^\[OC-(?:AUTO|SWARM-V\d+)\].*(?:released|lease released)", re.IGNORECASE)
_PACKET = re.compile(r"\bpacket=([a-f0-9]{16,64})\b")
_ISSUE_LINK = re.compile(r"(?:OC-AUTO-ISSUE:\s*|(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+)#(\d+)\b", re.IGNORECASE)
# These are settlement branches after the lane removes oc-running. A generic
# mention of backoff/recovery, or a stale duplicate dispatch, is not settlement.
_SETTLEMENT_PREFIXES = (
    "[OC-AUTO] Provider execution did not produce verifiable model execution evidence",
    "[OC-AUTO] Claude reached the bounded task/turn ceiling",
    "[OC-AUTO] Worker settlement preserved authoritative repair backoff",
    "[OC-AUTO] Durable PR #",
    "[OC-AUTO] Claude was safely unavailable; Gemini completed without durable changes",
    "[OC-AUTO] Claude was unavailable and Gemini ended with classification=",
    "[OC-AUTO] Claude was safely unavailable but Gemini failed with non-substitutable classification=",
    "[OC-AUTO] Claude was unavailable, Gemini ended with classification=",
    "[OC-AUTO] Claude failed with non-fallback classification=",
    "[OC-AUTO] Preferred provider completed without a durable integration PR",
)


def _is_settlement(body: str) -> bool:
    return bool(_RELEASE.search(body)) or body.startswith(_SETTLEMENT_PREFIXES)


def _denied_release_matches(comment: dict, claim: dict, repository: str, number: int) -> bool:
    """Recognize only an authenticated denial bound to this exact claimed work."""
    if (comment.get("user") or {}).get("login") != "github-actions[bot]":
        return False
    claimed = claim["comment"]
    if (claimed.get("user") or {}).get("login") != "github-actions[bot]":
        return False
    try:
        payload = json.loads(re.search(r"`(\{[^\n]+\})`", claimed["body"])[1])
        if payload.get("schema") != "oc.swarm-claim.v1" or payload.get("issue_number") != number:
            return False
        if (not isinstance(payload.get("material_fingerprint"), str)
                or not re.fullmatch(r"[a-f0-9]{16,64}", payload["material_fingerprint"])
                or type(claimed.get("id")) is not int or claimed["id"] <= 0
                or claim.get("fingerprint") != payload.get("material_fingerprint")
                or not re.fullmatch(re.escape(repository) + r":[1-9]\d*:[1-9]\d*:" + str(number),
                                    payload.get("lease_id") or "")):
            return False
        body = comment["body"]
        if body.startswith("[OC-SWARM-V4] Provider admission denied;"):
            release = json.loads(re.search(r"`(\{[^\n]+\})`", body)[1])
            return (release.get("schema") == "oc.swarm-denied-release.v1"
                    and release.get("issue_number") == number
                    and release.get("lease_comment_id") == claimed.get("id")
                    and release.get("lease_id") == payload.get("lease_id")
                    and release.get("material_fingerprint") == payload.get("material_fingerprint")
                    and release.get("state") == "oc-blocked" and release.get("provider_called") is False)
        pattern = (r"^\[OC-AUTO\] Swarm governor blocked provider execution before credentials were initialized\. "
                   r"reason=[A-Z_]+; packet=([a-f0-9]{16,64})\. Run https://github\.com/"
                   + re.escape(repository) + r"/actions/runs/(\d+)\.$")
        match = re.fullmatch(pattern, body)
        return bool(match and payload.get("material_fingerprint") == match[1]
                    and re.fullmatch(re.escape(f"{repository}:{match[2]}:") + r"[1-9]\d*:" + str(number),
                                     payload.get("lease_id") or ""))
    except (KeyError, TypeError, ValueError):
        return False


def _github_get(endpoint: str):
    """The only transport: bounded GETs, no shell, no raw error/body logging."""
    result = subprocess.run(
        ["gh", "api", "--method", "GET", endpoint],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(result.stdout)


def collect_github_snapshot(repository: str, run_id: int, *, read_json=_github_get,
                            now: datetime | None = None, no_api_mode: str | None = None) -> dict:
    """Observe existing GitHub receipts; never synthesize a lease or readiness.

    Missing, truncated, ambiguous or changing evidence is an incomplete pulse.
    Comments are read as data and only recognized operational identifiers leave
    this function. No issue text, provider output or credential is published.
    """
    from scripts.oc_no_api_guard import evaluate as providers_blocked

    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or run_id < 1:
        raise ValueError("a repository and positive workflow run ID are required")
    now = now or datetime.now(timezone.utc)
    prefix = f"repos/{repository}/"
    errors: list[dict] = []
    reads = 0

    def get(path, source):
        nonlocal reads
        if reads >= MAX_READS:
            errors.append({"source": source, "reason": "read_budget_exhausted"})
            return None
        reads += 1
        try:
            return read_json(prefix + path)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            errors.append({"source": source, "reason": "evidence_unavailable"})
            return None

    def pages(path, source, field=None):
        items = []
        for page in range(1, MAX_PAGES + 1):
            sep = "&" if "?" in path else "?"
            raw = get(f"{path}{sep}per_page=100&page={page}", source)
            batch = raw.get(field) if field and isinstance(raw, dict) else raw
            if not isinstance(batch, list) or any(not isinstance(x, dict) for x in batch):
                errors.append({"source": source, "reason": "collection_unavailable"})
                return items
            items.extend(batch)
            if len(batch) < 100:
                return items
        errors.append({"source": source, "reason": "pagination_limit"})
        return items

    def head(branch):
        raw = get(f"git/ref/heads/{branch}", f"head:{branch}")
        sha = (raw or {}).get("object", {}).get("sha") if isinstance(raw, dict) else None
        if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha):
            errors.append({"source": f"head:{branch}", "reason": "exact_head_unavailable"})
            return UNKNOWN
        return sha

    def recent_comments(raw):
        number = raw["number"]
        count = raw.get("comments")
        if not isinstance(count, int) or count < 0:
            errors.append({"source": f"comments:{number}", "reason": "comment_count_unavailable"})
            return []
        last_page = max(1, (count + 99) // 100)
        first_page = max(1, last_page - MAX_PAGES + 1)
        comments = []
        for page in range(first_page, last_page + 1):
            batch = get(f"issues/{number}/comments?per_page=100&page={page}", f"comments:{number}")
            expected = min(100, max(0, count - (page - 1) * 100))
            if not isinstance(batch, list) or len(batch) != expected or any(not isinstance(x, dict) for x in batch):
                errors.append({"source": f"comments:{number}", "reason": "comment_window_incomplete"})
                return []
            comments.extend(batch)
        # A known settlement within a bounded recent window supersedes older
        # claims. Without one, missing history must remain UNKNOWN, not healthy.
        if first_page > 1 and not any(_is_settlement(str(x.get("body") or "")) for x in comments):
            errors.append({"source": f"comments:{number}", "reason": "lease_history_incomplete"})
        return comments

    integration_head = head("oc-autonomous-integration")
    main_head = head("main")
    raw_issues = pages("issues?state=open", "issues")
    raw_prs = pages("pulls?state=open&base=oc-autonomous-integration", "pull_requests")
    prs = []
    linked = {}
    for pr in raw_prs:
        sha = (pr.get("head") or {}).get("sha")
        number = pr.get("number")
        if not isinstance(number, int) or not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha):
            errors.append({"source": "pull_requests", "reason": "invalid_pr_identity"})
            continue
        # A PR head is a validation target, never proof that required checks ran.
        prs.append({"number": number, "head_sha": sha, "ci_state": UNKNOWN})
        for issue in set(_ISSUE_LINK.findall(str(pr.get("body") or ""))):
            linked.setdefault(int(issue), []).append({"pr": number, "head_sha": sha})

    issues, leases, fingerprints, exceptions = [], [], [], []
    for raw in raw_issues:
        if raw.get("pull_request"):
            continue
        number = raw.get("number")
        if not isinstance(number, int):
            errors.append({"source": "issues", "reason": "invalid_issue_identity"})
            continue
        labels = sorted(_labels(raw))
        issue = {"number": number, "labels": labels}
        if "oc-validating" in labels:
            targets = linked.get(number, [])
            if len(targets) == 1:
                issue["validation_target"] = targets[0]
            elif len(targets) > 1:
                errors.append({"source": f"issue:{number}", "reason": "ambiguous_validation_target"})
        if "oc-owner-gate" in labels:
            exceptions.append({"issue": number, "owner_approval_required": True})
        issues.append(issue)
        # Running and parked work can carry orphan receipts. Historical done
        # work is not resurrected, and a missing receipt is never manufactured.
        if not set(labels) & {"oc-running", "oc-blocked", "oc-runtime-backoff", "oc-repair-backoff"}:
            continue
        comments = recent_comments(raw)
        claims = []
        for comment in comments:
            body = str(comment.get("body") or "")
            if body.startswith(("[OC-AUTO] Swarm governor blocked provider execution before credentials were initialized.",
                                "[OC-SWARM-V4] Provider admission denied;")):
                matched = [claim for claim in claims if _denied_release_matches(comment, claim, repository, number)]
                if len(matched) == 1:
                    claims.remove(matched[0])
                else:
                    errors.append({"source": f"comments:{number}", "reason": "governor_release_unconfirmed"})
            elif _is_settlement(body):
                claims = []
            elif _CLAIM.search(body):
                packet = _PACKET.search(body)
                claims.append({"comment": comment, "fingerprint": packet.group(1) if packet else None})
            elif body.startswith("[OC-AUTO] Completion worker started") and claims:
                packet = _PACKET.search(body)
                if packet:
                    if claims[-1]["fingerprint"] not in {None, packet.group(1)}:
                        errors.append({"source": f"comments:{number}", "reason": "claim_worker_fingerprint_mismatch"})
                    claims[-1]["fingerprint"] = packet.group(1)
        for claim in claims:
            comment = claim["comment"]
            try:
                claimed_at = datetime.fromisoformat(comment["created_at"].replace("Z", "+00:00"))
                age = max(0, int((now - claimed_at).total_seconds()))
            except (KeyError, TypeError, ValueError):
                errors.append({"source": f"comments:{number}", "reason": "lease_time_unavailable"})
                age = None
            lease = {
                "issue": number, "id": comment.get("id"),
                "owner": (comment.get("user") or {}).get("login"),
                "material_fingerprint": claim["fingerprint"],
                "active": True, "age_seconds": age,
                "stale": age is not None and age > STALE_LEASE_SECONDS,
            }
            leases.append(lease)
            if claim["fingerprint"]:
                fingerprints.append(claim["fingerprint"])
        # Detect state changes while reading comments/PRs instead of combining
        # different issue revisions into a misleading healthy receipt.
        current = get(f"issues/{number}", f"issue:{number}:recheck")
        if not isinstance(current, dict) or current.get("updated_at") != raw.get("updated_at") or current.get("state") != "open":
            errors.append({"source": f"issue:{number}", "reason": "issue_changed_during_observation"})

    run = get(f"actions/runs/{run_id}", "scheduler_run")
    jobs = pages(f"actions/runs/{run_id}/jobs", "scheduler_jobs", "jobs")
    run = run if isinstance(run, dict) else {}
    if run.get("id") != run_id or (run.get("repository") or {}).get("full_name") != repository:
        errors.append({"source": "scheduler_run", "reason": "run_identity_unavailable"})
    if run.get("head_branch") != "oc-autonomous-integration" or run.get("path") not in {
        ".github/workflows/orchid-swarm-controller.yml",
        ".github/workflows/orchid-continuous-completion.yml",
    }:
        errors.append({"source": "scheduler_run", "reason": "not_an_integration_controller_run"})
    scheduler = {key: run.get(key) for key in ("id", "status", "conclusion", "head_sha")}
    scheduler["jobs"] = [
        {key: job.get(key) for key in ("runner_id", "conclusion", "steps")}
        for job in jobs
    ]
    ci = classify_ci([scheduler])
    if ci["state"] != "HEALTHY":
        errors.append({"source": "scheduler_run", "reason": ci["reason"]})
    # A snapshot is advisory even when consistent. Re-read the two inventories
    # so a concurrent PR update or queue transition cannot silently supply stale
    # validation targets. Reconciliation must take its own fresh snapshot.
    current_issues = pages("issues?state=open", "issues")
    if [(x.get("number"), x.get("updated_at"), x.get("state"), sorted(_labels(x))) for x in current_issues] != [
        (x.get("number"), x.get("updated_at"), x.get("state"), sorted(_labels(x))) for x in raw_issues
    ]:
        errors.append({"source": "issues", "reason": "inventory_changed_during_observation"})
    current_prs = pages("pulls?state=open&base=oc-autonomous-integration", "pull_requests")
    if [(x.get("number"), x.get("head"), x.get("body")) for x in current_prs] != [
        (x.get("number"), x.get("head"), x.get("body")) for x in raw_prs
    ]:
        errors.append({"source": "pull_requests", "reason": "inventory_changed_during_observation"})
    if head("oc-autonomous-integration") != integration_head:
        errors.append({"source": "integration", "reason": "head_changed_during_observation"})
    blocked = providers_blocked(no_api_mode)
    return {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "issues": issues, "leases": leases, "dispatch_fingerprints": fingerprints,
        "autonomous_prs": prs, "exceptions": exceptions,
        "scheduler_runs": [scheduler], "scheduler_heartbeat": run.get("updated_at", UNKNOWN),
        "integration_head": integration_head, "main_head": main_head,
        "integration_ready": UNKNOWN,
        "provider": {"status": "no_api" if blocked else UNKNOWN, "disabled": blocked},
        "provider_availability_state": "no_api" if blocked else UNKNOWN,
        "observation_errors": errors,
        "stale_lease_count": sum(lease["stale"] for lease in leases) if not errors else UNKNOWN,
    }


def write_summary(receipt: dict, path: str) -> None:
    """Summarize only generated enums/counts, never untrusted issue content."""
    verdict = "CONSISTENT" if receipt["healthy"] else "INCONSISTENT OR INCOMPLETE"
    report = receipt["contract_health"]
    text = (
        f"## Completion health: {verdict}\n\n"
        f"- Contract violations: {len(report['violations'])}\n"
        f"- Observation errors: {len(receipt['observation_errors'])}\n"
        "- Full machine-readable evidence: completion-health artifact.\n"
        "- This read-only observation grants no dispatch, repair, integration or publication authority.\n"
    )
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input", default="-")
    source.add_argument("--repository")
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--check", action="store_true", help="exit 2 for inconsistent/incomplete evidence")
    parser.add_argument("--summary")
    args = parser.parse_args()
    if args.repository and not args.run_id:
        parser.error("--repository requires --run-id")
    try:
        snapshot = collect_github_snapshot(
            args.repository, args.run_id, no_api_mode=os.environ.get("NO_API_MODE")
        ) if args.repository else json.loads(
            sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        )
        if not isinstance(snapshot, dict):
            raise TypeError("snapshot must be an object")
        receipt = build_health(snapshot)
    except (OSError, ValueError, TypeError, AttributeError):
        receipt = build_health({"observation_errors": [{"source": "input", "reason": "invalid_snapshot"}]})
    json.dump(receipt, sys.stdout, indent=2)
    sys.stdout.write("\n")
    if args.summary:
        write_summary(receipt, args.summary)
    return 2 if args.check and not receipt["healthy"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
