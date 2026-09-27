"""Shared canonical Swarm disposition and durable lease release.

This is the label/comment completion previously in the controller workflow.
The GitHub control plane remains the only queue and refill owner.
"""
from __future__ import annotations

import argparse
import json

from scripts.oc_swarm_claim import github, verify_worker_claim


def verified_issue(*, repository, issue_number, run_id, run_attempt, comment_id, call=github):
    issue = call(["issue", "view", str(issue_number), "--repo", repository,
                  "--json", "number,title,body,state,labels"])
    receipt = call(["api", "--method", "GET", f"repos/{repository}/issues/comments/{comment_id}"])
    if (issue.get("number") != issue_number
            or receipt.get("user", {}).get("login") != "github-actions[bot]"
            or receipt.get("issue_url") != f"https://api.github.com/repos/{repository}/issues/{issue_number}"):
        raise ValueError("worker claim origin invalid")
    verify_worker_claim(issue, receipt, repository=repository, run_id=run_id,
                        run_attempt=run_attempt, comment_id=comment_id)
    return issue


def settle_worker(*, result, repository, issue_number, run_id, run_attempt, comment_id, call=github):
    """Release an unchanged owned lease using the existing canonical labels."""
    identity = {"repository": repository, "issue_number": issue_number, "run_id": run_id,
                "run_attempt": run_attempt, "comment_id": comment_id}
    verified_issue(**identity, call=call)
    disposition = result.get("disposition")
    if disposition not in {"done", "blocked", "owner-gate"}:
        raise ValueError("unknown worker disposition")
    target = f"oc-{disposition}"
    removed = {"oc-running", "oc-queued", "oc-validating", "oc-repair", "oc-blocked", "oc-owner-gate"} - {target}
    edit = ["issue", "edit", str(issue_number), "--repo", repository]
    for label in sorted(removed):
        edit += ["--remove-label", label]
    call(edit + ["--add-label", target])
    current = call(["issue", "view", str(issue_number), "--repo", repository,
                    "--json", "number,title,body,state,labels"])
    labels = {label if isinstance(label, str) else label["name"] for label in current["labels"]}
    if target not in labels or labels & removed:
        raise ValueError("worker settlement unconfirmed")
    receipt = {**result, "lease_comment_id": comment_id, "lease_id": f"{repository}:{run_id}:{run_attempt}:{issue_number}",
               "replenishment_signal": "canonical-controller-refill"}
    body = "[OC-SWARM-V4] Worker completed and lease released: `" + json.dumps(receipt, sort_keys=True) + "`."
    if disposition == "blocked" and result.get("blocked_on"):
        body += "\nOC-BLOCKED-ON: " + str(result["blocked_on"])
    saved = call(["api", "--method", "POST", f"repos/{repository}/issues/{issue_number}/comments", "--input", "-"], {"body": body})
    if not saved or not saved.get("id") or saved.get("body") != body:
        raise ValueError("worker completion receipt unconfirmed")
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True)
    parser.add_argument("--repository", required=True)
    for name in ("issue-number", "run-id", "run-attempt", "comment-id"):
        parser.add_argument("--" + name, required=True, type=int)
    args = vars(parser.parse_args())
    with open(args.pop("result"), encoding="utf-8") as handle:
        result = json.load(handle)
    print(json.dumps(settle_worker(result=result, **args), sort_keys=True))


if __name__ == "__main__":
    main()
