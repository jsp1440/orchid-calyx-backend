"""Shared canonical Swarm disposition and durable lease release.

This is the label/comment completion previously in the controller workflow.
The GitHub control plane remains the only queue and refill owner.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from scripts.oc_swarm_claim import github, verify_worker_claim
from scripts.oc_swarm_lease_reconcile import _latest_claim, _parse_time

WORKER_CLAIM_MAX_AGE_SECONDS = 90 * 60
WORKER_EXECUTION_BUDGET_SECONDS = 75 * 60


def _utc_now():
    return datetime.now(UTC)


def _validate_comment(comment, *, repository, issue_number):
    if (not isinstance(comment, dict)
            or type(comment.get("id")) is not int or comment["id"] < 1
            or not isinstance(comment.get("user"), dict)
            or not isinstance(comment.get("body"), str)
            or comment.get("issue_url") != f"https://api.github.com/repos/{repository}/issues/{issue_number}"
            or _parse_time(comment.get("created_at")) is None):
        raise ValueError("worker claim history malformed")
    if (not isinstance(comment.get("created_at"), str)
            or datetime.fromisoformat(comment["created_at"]).tzinfo is None):
        raise ValueError("worker claim timestamp malformed")


def current_claim(*, repository, issue_number, comment_id, call):
    comments = []
    for page in range(1, 101):
        batch = call([
            "api", "--method", "GET",
            f"repos/{repository}/issues/{issue_number}/comments?per_page=100&page={page}",
        ])
        if not isinstance(batch, list) or not all(isinstance(row, dict) for row in batch):
            raise ValueError("worker claim history unavailable")
        for row in batch:
            _validate_comment(row, repository=repository, issue_number=issue_number)
            if (row["user"].get("login") == "github-actions[bot]"
                    and "Dependency/resource lease claimed:" in row["body"]
                    and _latest_claim([row], repository=repository, number=issue_number) is None):
                raise ValueError("worker claim history malformed")
        comments.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise ValueError("worker claim history incomplete")
    latest = _latest_claim(comments, repository=repository, number=issue_number)
    if latest is None or latest["comment_id"] != comment_id:
        raise ValueError("worker claim superseded")


def verified_issue(*, repository, issue_number, run_id, run_attempt, comment_id,
                   call=github, now=None, min_remaining_seconds=0):
    if any(type(value) is not int or value < 1
           for value in (issue_number, run_id, run_attempt, comment_id)):
        raise ValueError("positive worker claim identity required")
    if (type(min_remaining_seconds) is not int
            or not 0 <= min_remaining_seconds < WORKER_CLAIM_MAX_AGE_SECONDS):
        raise ValueError("worker execution budget invalid")
    issue = call(["issue", "view", str(issue_number), "--repo", repository,
                  "--json", "number,title,body,state,labels"])
    receipt = call(["api", "--method", "GET", f"repos/{repository}/issues/comments/{comment_id}"])
    _validate_comment(receipt, repository=repository, issue_number=issue_number)
    if (not isinstance(issue, dict) or issue.get("number") != issue_number
            or receipt.get("user", {}).get("login") != "github-actions[bot]"
            or receipt.get("issue_url") != f"https://api.github.com/repos/{repository}/issues/{issue_number}"):
        raise ValueError("worker claim origin invalid")
    moment = _utc_now() if now is None else now
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ValueError("worker claim clock invalid")
    age = (moment - _parse_time(receipt["created_at"])).total_seconds()
    if age < 0 or age >= WORKER_CLAIM_MAX_AGE_SECONDS:
        raise ValueError("worker claim expired or timestamp in future")
    if WORKER_CLAIM_MAX_AGE_SECONDS - age < min_remaining_seconds:
        raise ValueError("worker claim insufficient execution lifetime")
    try:
        verify_worker_claim(issue, receipt, repository=repository, run_id=run_id,
                            run_attempt=run_attempt, comment_id=comment_id)
    except (AttributeError, KeyError, TypeError) as exc:
        raise ValueError("worker claim malformed") from exc
    current_claim(repository=repository, issue_number=issue_number,
                  comment_id=comment_id, call=call)
    return issue


def settle_worker(*, result, repository, issue_number, run_id, run_attempt,
                  comment_id, call=github, now=None):
    """Release an unchanged owned lease using the existing canonical labels."""
    identity = {"repository": repository, "issue_number": issue_number, "run_id": run_id,
                "run_attempt": run_attempt, "comment_id": comment_id}
    verified_issue(**identity, call=call, now=now)
    disposition = result.get("disposition")
    if disposition not in {"done", "blocked", "owner-gate", "queued", "validating",
                           "repair", "runtime-backoff"}:
        raise ValueError("unknown worker disposition")
    target = f"oc-{disposition}"
    added = {target}
    if result.get("repair_queued") is True:
        if disposition != "queued":
            raise ValueError("repair queue requires queued disposition")
        added.add("oc-repair")
    removed = {"oc-running", "oc-queued", "oc-validating", "oc-repair", "oc-blocked",
               "oc-owner-gate", "oc-runtime-backoff"} - added
    edit = ["issue", "edit", str(issue_number), "--repo", repository]
    for label in sorted(removed):
        edit += ["--remove-label", label]
    receipt = {**result, "lease_comment_id": comment_id, "lease_id": f"{repository}:{run_id}:{run_attempt}:{issue_number}",
               "replenishment_signal": "canonical-controller-refill"}
    body = "[OC-SWARM-V4] Worker result validated; requested lease disposition: `" + json.dumps(receipt, sort_keys=True) + "`."
    if result.get("schema") == "oc.swarm-denied-release.v1":
        routing = "rerouted to the deterministic lane; " if disposition == "queued" else ""
        body = ("[OC-SWARM-V4] Provider admission denied; " + routing
                + "requested lease disposition: `" + json.dumps(receipt, sort_keys=True) + "`.")
    if disposition == "blocked" and result.get("blocked_on"):
        body += "\nOC-BLOCKED-ON: " + str(result["blocked_on"])
    saved = call(["api", "--method", "POST", f"repos/{repository}/issues/{issue_number}/comments", "--input", "-"], {"body": body})
    if not saved or not saved.get("id") or saved.get("body") != body:
        raise ValueError("worker completion receipt unconfirmed")
    confirmed = call(["api", "--method", "GET", f"repos/{repository}/issues/comments/{saved['id']}"])
    if (not confirmed or confirmed.get("body") != body
            or confirmed.get("user", {}).get("login") != "github-actions[bot]"
            or confirmed.get("issue_url") != f"https://api.github.com/repos/{repository}/issues/{issue_number}"):
        raise ValueError("worker completion receipt readback failed")
    # Persist and confirm evidence before terminal labels. A receipt failure
    # leaves the running lease available to canonical denial/recovery, rather
    # than marking work done without a durable result. Recheck ownership after
    # the separate comment writes so an intervening owner gate wins.
    # Separate GitHub reads/writes still have a check/write race, not an atomic fence.
    verified_issue(**identity, call=call, now=now)
    for label in sorted(added):
        edit += ["--add-label", label]
    call(edit)
    current = call(["issue", "view", str(issue_number), "--repo", repository,
                    "--json", "number,title,body,state,labels"])
    labels = {label if isinstance(label, str) else label["name"] for label in current["labels"]}
    if not added <= labels or labels & removed:
        raise ValueError("worker settlement unconfirmed")
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--result")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--min-remaining-seconds", type=int, default=0)
    parser.add_argument("--disposition")
    parser.add_argument("--message")
    parser.add_argument("--blocked-on")
    parser.add_argument("--repair-queued", action="store_true")
    parser.add_argument("--repository", required=True)
    for name in ("issue-number", "run-id", "run-attempt", "comment-id"):
        parser.add_argument("--" + name, required=True, type=int)
    args = vars(parser.parse_args())
    result_path = args.pop("result")
    verify_only = args.pop("verify_only")
    budget = args.pop("min_remaining_seconds")
    disposition = args.pop("disposition")
    message = args.pop("message")
    blocked_on = args.pop("blocked_on")
    repair_queued = args.pop("repair_queued")
    if verify_only:
        verified_issue(**args, min_remaining_seconds=budget)
        print('{"execute":true}')
        return
    if budget:
        parser.error("execution budget applies only to --verify-only")
    if not result_path and not disposition:
        parser.error("settlement requires --result or --disposition")
    result = {}
    if result_path:
        with open(result_path, encoding="utf-8") as handle:
            result = json.load(handle)
    if not isinstance(result, dict):
        raise TypeError("worker result malformed")
    for key, value in (("disposition", disposition), ("message", message),
                       ("blocked_on", blocked_on)):
        if value is not None:
            result[key] = value
    if repair_queued:
        result["repair_queued"] = True
    print(json.dumps(settle_worker(result=result, **args), sort_keys=True))


if __name__ == "__main__":
    main()
