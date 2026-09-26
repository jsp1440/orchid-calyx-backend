"""Confirm the existing Swarm GitHub claim before admitting a worker.

GitHub labels and comments are separate writes, not an atomic lock. A partial
write is retained as an explicit error for the observer; it never authorizes a
worker and is never compensated by overwriting another actor's queue state.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess

from runtime.swarm.work_packet import build_work_packet
from scripts.oc_budget_blocker import is_budget_denial
from scripts.oc_budget_denial_route import decide_denial_route
from scripts.oc_health_contract import evaluate
from scripts.oc_swarm_dependency_graph import build_dependency_graph, dependencies

PARKED = {"oc-running", "oc-validating", "oc-blocked", "oc-owner-gate",
          "oc-runtime-backoff", "oc-repair-backoff", "oc-done"}
BLOCKER_FINGERPRINT = re.compile(r"^[a-f0-9]{24}$")


def _labels(issue):
    return {x if isinstance(x, str) else x["name"] for x in issue["labels"]}


def _material(issue):
    return (issue["title"], issue.get("body") or "", sorted(_labels(issue)))


def github(args, payload=None):
    result = subprocess.run(
        ["gh", *args], input=json.dumps(payload) if payload is not None else None,
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip().startswith(("{", "[")) else None


def verify_worker_claim(issue, receipt, *, repository, run_id, run_attempt, comment_id):
    """Bind the Swarm handoff to its issue, run, attempt, and current packet."""
    labels = _labels(issue)
    if (issue["state"].upper() != "OPEN" or "oc-running" not in labels
            or labels & ((PARKED - {"oc-running"}) | {"oc-queued"})):
        raise ValueError("worker no longer owns exclusive running state")
    body = receipt.get("body") or ""
    match = re.match(r"^\[OC-SWARM-V4\] Dependency/resource lease claimed: `(\{[^\n]+\})`\.", body)
    if receipt.get("id") != comment_id or not match or not receipt.get("user", {}).get("login"):
        raise ValueError("worker lease receipt unavailable")
    claim = json.loads(match.group(1))
    number = issue["number"]
    packet = build_work_packet(issue_number=str(number), title=issue["title"],
                               body=issue.get("body") or "", labels=labels)
    if (claim.get("schema") != "oc.swarm-claim.v1" or claim.get("issue_number") != number
            or claim.get("lease_id") != f"{repository}:{run_id}:{run_attempt}:{number}"
            or claim.get("material_fingerprint") != packet.fingerprint):
        raise ValueError("worker lease identity or material changed")
    return True


def claim_workers(plan, snapshot, *, repository, run_id, run_attempt=1, call=github):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid repository")
    if run_id < 1 or run_attempt < 1:
        raise ValueError("positive run identity required")
    workers = plan["workers"]
    numbers = [w["issue_number"] for w in workers]
    if len(workers) > 12 or len(set(numbers)) != len(numbers):
        raise ValueError("invalid bounded worker plan")
    original = {i["number"]: i for i in snapshot["issues"]}
    confirmed, skipped, errors = [], [], []

    def view(number):
        return call(["issue", "view", str(number), "--repo", repository,
                     "--json", "number,title,body,state,labels"])

    for worker in workers:
        number = worker["issue_number"]
        phase = "precheck"
        try:
            current = view(number)
            labels = _labels(current)
            if (current["number"] != number or current["state"].upper() != "OPEN"
                    or "oc-queued" not in labels or labels & PARKED):
                skipped.append({"issue": number, "reason": "not_exclusively_queued"})
                continue
            if _material(current) != _material(original[number]):
                skipped.append({"issue": number, "reason": "issue_changed_since_plan"})
                continue
            deps = dependencies(current)
            if deps != worker["dependencies"]:
                raise ValueError("planned dependencies differ")
            graph = build_dependency_graph([current, *(view(n) for n in deps)])
            if not graph["status"][number]["ready"]:
                skipped.append({"issue": number, "reason": "dependency_changed_since_plan"})
                continue

            # Remove queued in the same label edit that acquires running. Keep
            # unrelated labels; do not replace the complete label collection.
            phase = "label_write"
            call(["issue", "edit", str(number), "--repo", repository,
                  "--remove-label", "oc-queued", "--add-label", "oc-running"])
            expected = dict(current, labels=sorted((labels - {"oc-queued"}) | {"oc-running"}))
            current = view(number)
            if current["state"].upper() != "OPEN" or _material(current) != _material(expected):
                raise ValueError("claim state changed")
            packet = build_work_packet(issue_number=str(number), title=current["title"],
                                       body=current.get("body") or "", labels=_labels(current))
            claim = {key: worker[key] for key in ("reads", "writes", "dependencies")}
            claim.update(schema="oc.swarm-claim.v1", issue_number=number,
                         lease_id=f"{repository}:{run_id}:{run_attempt}:{number}",
                         material_fingerprint=packet.fingerprint)
            body = ("[OC-SWARM-V4] Dependency/resource lease claimed: `"
                    + json.dumps(claim, sort_keys=True, separators=(",", ":"))
                    + f"`. packet={packet.fingerprint}. Controller run: "
                    + f"https://github.com/{repository}/actions/runs/{run_id}.")
            phase = "receipt_write"
            receipt = call(["api", "--method", "POST",
                            f"repos/{repository}/issues/{number}/comments", "--input", "-"],
                           {"body": body})
            if not receipt or receipt.get("body") != body or not receipt.get("id"):
                raise ValueError("durable receipt unconfirmed")
            phase = "confirmation"
            current = view(number)
            if current["state"].upper() != "OPEN" or _material(current) != _material(expected):
                raise ValueError("claim changed before handoff")
            health = evaluate({
                "issues": [current],
                "leases": [{"issue": number, "id": receipt["id"], "active": True,
                            "owner": receipt.get("user", {}).get("login"),
                            "material_fingerprint": packet.fingerprint}],
                "dispatch_fingerprints": [packet.fingerprint],
            })
            if not health["healthy"]:
                raise ValueError("claim violates health contract")
            confirmed.append({**worker, "lease_comment_id": receipt["id"],
                              "material_fingerprint": packet.fingerprint})
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError):
            # Do not expose issue text, credentials, or raw API errors. A write
            # timeout can mean the write succeeded: observe, never blindly retry.
            errors.append({"issue": number, "phase": phase, "reason": "claim_unconfirmed"})

    # The confirmed claims keep the planner's lane classification so the
    # workflow can hand provider-free work to the deterministic worker job and
    # provider-dependent work to the governed completion lane independently.
    provider_free = [w for w in confirmed if w.get("provider_free")]
    provider = [w for w in confirmed if not w.get("provider_free")]
    return {"schema": "oc.swarm-claim-handoff.v1", "run_id": run_id,
            "run_attempt": run_attempt, "healthy": not errors,
            "planned_count": len(workers), "launch_count": len(confirmed),
            "matrix": {"include": confirmed}, "confirmed": confirmed,
            "provider_free_matrix": {"include": provider_free},
            "provider_matrix": {"include": provider},
            "provider_free_launch_count": len(provider_free),
            "provider_launch_count": len(provider),
            "skipped": skipped, "errors": errors}


def park_denied_worker(*, repository, issue_number, run_id, run_attempt,
                      comment_id, reason, blocker_fingerprint=None,
                      denied_provider=None, providers=None, shared_budget=None,
                      call=github):
    """Settle a confirmed claim after denial, at the disposition the denial earns.

    Releasing the lease is not in question — a denied worker never keeps one.
    What changed is that the disposition is now decided rather than assumed. A
    task with deterministic work an executor can run returns to ``oc-queued``,
    where the planner hands it to the deterministic lane instead of back to the
    provider that refused it. Everything else parks with its durable blocker
    exactly as before, and nothing here ever restores paid eligibility.
    """
    args = ["issue", "view", str(issue_number), "--repo", repository,
            "--json", "number,title,body,state,labels"]
    issue = call(args)
    receipt = call(["api", "--method", "GET",
                    f"repos/{repository}/issues/comments/{comment_id}"])
    if (issue.get("number") != issue_number
            or (receipt.get("user") or {}).get("login") != "github-actions[bot]"
            or receipt.get("issue_url") != f"https://api.github.com/repos/{repository}/issues/{issue_number}"):
        raise ValueError("denied worker claim origin invalid")
    verify_worker_claim(issue, receipt, repository=repository, run_id=run_id,
                        run_attempt=run_attempt, comment_id=comment_id)

    # Decided from the issue GitHub is serving right now, not from the planner's
    # snapshot: the body is what says whether a deterministic executor can take
    # this, and settling on a stale copy of it would route on a claim nobody
    # re-checked after the lease was taken.
    route = decide_denial_route(
        issue,
        reason=reason,
        blocker_fingerprint=blocker_fingerprint,
        denied_provider=denied_provider,
        providers=providers,
        shared_budget=shared_budget,
    )
    budget_denial = is_budget_denial(reason)
    durable_blocker = route.blocker
    removed = ["oc-running"] if route.requeues else ["oc-running", "oc-queued"]

    expected = dict(issue, labels=sorted((_labels(issue) - set(removed)) | {route.target_label}))
    edit = ["issue", "edit", str(issue_number), "--repo", repository]
    for label in removed:
        edit += ["--remove-label", label]
    call(edit + ["--add-label", route.target_label])
    current = call(args)
    if current["state"].upper() != "OPEN" or _material(current) != _material(expected):
        raise ValueError("denied worker parking unconfirmed")
    packet = build_work_packet(issue_number=str(issue_number), title=issue["title"],
                               body=issue.get("body") or "", labels=_labels(issue))
    release = {"schema": "oc.swarm-denied-release.v1", "issue_number": issue_number,
               "lease_id": f"{repository}:{run_id}:{run_attempt}:{issue_number}",
               "lease_comment_id": comment_id, "material_fingerprint": packet.fingerprint,
               "reason": reason,
               "blocker_fingerprint": (blocker_fingerprint
                                       if budget_denial and route.records_blocker else None),
               "blocker": durable_blocker if route.records_blocker else None,
               "state": route.target_label, "provider_called": False,
               "route": route.to_record()}
    if route.requeues:
        # No OC-BLOCKED-ON line: this task is not blocked on anything. Writing
        # one would make the next reconciliation hold work that is running.
        body = ("[OC-SWARM-V4] Provider admission denied; execution lease released and work "
                "rerouted to the deterministic lane: `"
                + json.dumps(release, sort_keys=True) + "`.")
    else:
        body = ("[OC-SWARM-V4] Provider admission denied; execution lease released: `"
                + json.dumps(release, sort_keys=True) + "`.\n"
                + f"OC-BLOCKED-ON: {durable_blocker}")
    saved = call(["api", "--method", "POST", f"repos/{repository}/issues/{issue_number}/comments",
                  "--input", "-"], {"body": body})
    if not saved or saved.get("body") != body or not saved.get("id"):
        raise ValueError("denied worker receipt unconfirmed")
    confirmed = call(["api", "--method", "GET", f"repos/{repository}/issues/comments/{saved['id']}"])
    if confirmed.get("body") != body:
        raise ValueError("denied worker receipt readback failed")
    return release


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan")
    parser.add_argument("--snapshot")
    parser.add_argument("--verify-issue", type=int)
    parser.add_argument("--lease-comment-id", type=int)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--run-attempt", type=int, default=1)
    parser.add_argument("--github-output")
    parser.add_argument("--park-denied", help="Governor denial reason; settle the verified worker")
    parser.add_argument("--blocker-fingerprint", help="Stable budget condition fingerprint")
    parser.add_argument("--denied-provider", help="Provider the governor refused, for the route record")
    args = parser.parse_args()
    if args.verify_issue is not None:
        try:
            if args.park_denied:
                result = park_denied_worker(repository=args.repository, issue_number=args.verify_issue,
                                            run_id=args.run_id, run_attempt=args.run_attempt,
                                            comment_id=args.lease_comment_id, reason=args.park_denied,
                                            blocker_fingerprint=args.blocker_fingerprint,
                                            denied_provider=args.denied_provider)
                print(json.dumps(result, sort_keys=True))
                return 0
            issue = github(["issue", "view", str(args.verify_issue), "--repo", args.repository,
                            "--json", "number,title,body,state,labels"])
            receipt = github(["api", "--method", "GET",
                              f"repos/{args.repository}/issues/comments/{args.lease_comment_id}"])
            verify_worker_claim(issue, receipt, repository=args.repository, run_id=args.run_id,
                                run_attempt=args.run_attempt, comment_id=args.lease_comment_id)
        except (OSError, subprocess.SubprocessError, TypeError, ValueError, KeyError):
            print('{"execute":false,"reason":"worker_claim_unconfirmed"}')
            return 2
        print('{"execute":true}')
        return 0
    if not args.plan or not args.snapshot or not args.github_output:
        parser.error("claim requires --plan, --snapshot, and --github-output")
    with open(args.plan, encoding="utf-8") as handle:
        plan = json.load(handle)
    with open(args.snapshot, encoding="utf-8") as handle:
        snapshot = json.load(handle)
    result = claim_workers(plan, snapshot, repository=args.repository,
                           run_id=args.run_id, run_attempt=args.run_attempt)
    with open(args.github_output, "a", encoding="utf-8") as handle:
        handle.write(f"launch_count={result['launch_count']}\n")
        handle.write("matrix=" + json.dumps(result["matrix"], separators=(",", ":")) + "\n")
        handle.write(f"provider_free_launch_count={result['provider_free_launch_count']}\n")
        handle.write(f"provider_launch_count={result['provider_launch_count']}\n")
        handle.write("provider_free_matrix="
                     + json.dumps(result["provider_free_matrix"], separators=(",", ":")) + "\n")
        handle.write("provider_matrix="
                     + json.dumps(result["provider_matrix"], separators=(",", ":")) + "\n")
    print(json.dumps(result, sort_keys=True))
    # Confirmed claims may proceed even when a different candidate was skipped
    # or failed. The artifact reports those failures independently of job status.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
