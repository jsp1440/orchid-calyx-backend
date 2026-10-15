"""Build ``acceptance-report.json`` for the governed engineering demonstration.

Read-only. It inspects the durable GitHub records the existing engine already
writes -- the swarm controller's lease claim, the completion lane's worker
receipt, the maker's pull request, ``orchid-autonomous-validation`` at the PR
head, the independent checker's ``OC-CHECKER-EVIDENCE-V1`` record and the
hosted settlement receipt -- and decides, per issue, whether that issue was a
completed engineering cycle:

1. ``acquired``: a governed lease claim (``oc.swarm-claim.v1``) by the bot;
2. ``dispatched``: an authorized provider worker started for that claim and
   admission was not denied afterwards (provider and model are recorded);
3. ``engineered``: a maker pull request with a non-empty diff whose head is
   the head the settlement names;
4. ``independently_validated``: validation succeeded at exactly that head, and
   a PASS checker record names that head, a different identity from the maker,
   and required checks passed;
5. ``receipted``: an ``OC-HOSTED-SETTLEMENT-V1`` receipt by the bot with a
   verified merge SHA, and the issue closed ``completed`` with ``oc-done``.

Cycles are ordered by settlement time. The demonstration is certified only by
ten consecutive passing cycles, with at least one recovered lease
(``oc.swarm-lease-recovery.v1``) among them. Zero-execution outcomes (admission
denied, runtime backoff, repair) are listed with the engine's own reason; an
outcome with no reason is itself a failure. The report never grants authority
and never infers a success from a missing record.

    python3 scripts/oc_engineering_acceptance_report.py \\
        --repository jsp1440/orchid-calyx-backend --issues 2001,2002,... \\
        --output acceptance-report.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.calyx_orchestrator.checker_dispatch import parse_evidence
from app.calyx_orchestrator.factory_policy import CheckerVerdict
from app.calyx_orchestrator.head_bound_integration import same_actor

SCHEMA = "oc.engineering-acceptance-report.v1"
TARGET = 10
BOT = "github-actions[bot]"
SHA40 = re.compile(r"[0-9a-f]{40}")
CLAIM = re.compile(
    r"^\[OC-SWARM-V4\] Dependency/resource lease claimed: `(\{[^\n]+\})`"
)
WORKER = re.compile(
    r"^\[OC-AUTO\] Completion worker started .*?route=tier=(?P<tier>[^;]*); "
    r"model=(?P<model>[^;]*);.*?Run (?P<run>https://\S+?)\.?$",
    re.DOTALL,
)
DENIED = "[OC-SWARM-V4] Provider admission denied"
RECOVERY_SCHEMA = "oc.swarm-lease-recovery.v1"
SETTLEMENT_TAG = "OC-HOSTED-SETTLEMENT-V1"
SETTLED_RESULT = re.compile(
    r"^\[OC-SWARM-V4\] (?:Worker result validated|Provider admission denied)[^`]*`(\{.*\})`",
    re.DOTALL,
)
ZERO_DISPOSITIONS = frozenset({"runtime-backoff", "repair", "blocked", "queued"})
VALIDATION_WORKFLOW = "orchid-autonomous-validation.yml"
INTEGRATION_BRANCH = "oc-autonomous-integration"
RUN_URL = re.compile(r"/actions/runs/(\d+)(?:/|$)")
MAKER_BRANCH = re.compile(r"claude-direct/issue-\d+-\d+")
RECOVERY_PREFIX = "[OC-SWARM-V4] Stale lease recovered: `"
RECOVERY = re.compile(r"^\[OC-SWARM-V4\] Stale lease recovered: `(\{[^\n]+\})`")


def _json_after(pattern: re.Pattern, body: str) -> dict | None:
    match = pattern.search(body or "")
    if not match:
        return None
    try:
        value = json.loads(match.group(1))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _tagged(body: str, tag: str) -> dict | None:
    found = re.findall(
        r"<!-- " + re.escape(tag) + r"\s+(.*?)\s*-->", body or "", re.DOTALL
    )
    if len(found) != 1:
        return None
    try:
        value = json.loads(found[0])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _by_bot(comment: Mapping[str, Any]) -> bool:
    return (comment.get("user") or {}).get("login") == BOT


def _run_id(url: str) -> int | None:
    match = RUN_URL.search(url or "")
    return int(match.group(1)) if match else None


def _newest(runs: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The latest validation attempt; GitHub lists runs newest-first, but never rely on it."""
    if not runs:
        return None
    return max(
        runs,
        key=lambda r: (
            str(r.get("created_at") or ""),
            int(r.get("run_attempt") or 1),
            int(r.get("id") or 0),
        ),
    )


def evaluate_cycle(record: Mapping[str, Any]) -> dict[str, Any]:
    """Judge one issue from its fetched records (pure; see ``fetch_record``)."""
    issue = record["issue"]
    number = int(issue["number"])
    comments = sorted(
        record.get("comments") or [],
        key=lambda c: (c.get("created_at") or "", c.get("id") or 0),
    )
    failures: list[str] = []
    evidence: dict[str, Any] = {"issue": number}

    claims = [
        (c, claim)
        for c in comments
        if _by_bot(c)
        and (claim := _json_after(CLAIM, c.get("body", "")))
        and claim.get("schema") == "oc.swarm-claim.v1"
        and claim.get("issue_number") == number
        and claim.get("lease_id")
    ]
    settlements = [
        (c, s)
        for c in comments
        if _by_bot(c) and (s := _tagged(c.get("body", ""), SETTLEMENT_TAG))
    ]
    settlement_comment, settlement = settlements[-1] if settlements else (None, None)
    context = (settlement or {}).get("context") or {}
    repository = record.get("repository") or context.get("repository") or ""
    worker_run, worker_attempt = (
        context.get("worker_run"),
        context.get("worker_attempt"),
    )

    # 1. acquisition: the claim the settlement names, for the attempt that did the work
    final = next(
        ((c, k) for c, k in claims if c.get("id") == context.get("lease")), None
    )
    if final is None and claims and settlement is None:
        final = claims[-1]
    acquired = final is not None and (
        settlement is None
        or final[1]["lease_id"]
        == f"{repository}:{worker_run}:{worker_attempt}:{number}"
    )
    if final is not None:
        evidence["lease_id"] = final[1]["lease_id"]
        evidence["claim_comment"] = final[0].get("html_url")
    if not acquired:
        failures.append(
            "CLAIM_NOT_BOUND_TO_SETTLED_ATTEMPT"
            if final is not None
            else "NO_GOVERNED_CLAIM_FOR_SETTLED_LEASE"
            if settlement
            else "NO_GOVERNED_CLAIM"
        )

    # 2. dispatch: that attempt's provider worker started, and was never denied after the claim
    after = [
        c
        for c in comments
        if final is not None
        and (c.get("created_at") or "") >= (final[0].get("created_at") or "")
    ]
    worker = next(
        (m for c in after if _by_bot(c) and (m := WORKER.search(c.get("body", "")))),
        None,
    )
    denied = any(_by_bot(c) and c.get("body", "").startswith(DENIED) for c in after)
    worker_bound = worker is not None and (
        settlement is None or _run_id(worker.group("run")) == worker_run
    )
    dispatched = (
        worker_bound
        and not denied
        and bool(worker.group("model").strip())
        and worker.group("model") != "unknown"
    )
    if worker is not None:
        evidence["provider_model"] = worker.group("model")
        evidence["route_tier"] = worker.group("tier")
        evidence["worker_run"] = worker.group("run")
    if not dispatched:
        failures.append(
            "PROVIDER_ADMISSION_DENIED"
            if denied
            else "WORKER_NOT_BOUND_TO_SETTLED_ATTEMPT"
            if worker is not None
            else "NO_AUTHORIZED_PROVIDER_WORKER"
        )

    # 3. engineering work: the maker's own PR for this issue, at the settled head
    pr = record.get("pull_request") or {}
    head = context.get("head", "")
    engineered = (
        bool(pr)
        and pr.get("number") == context.get("pr")
        and (pr.get("user") or {}).get("login") == BOT
        and bool(MAKER_BRANCH.fullmatch((pr.get("head") or {}).get("ref") or ""))
        and (pr.get("head") or {})
        .get("ref", "")
        .startswith(f"claude-direct/issue-{number}-")
        and f"OC-AUTO-ISSUE: #{number}" in (pr.get("body") or "")
        and (pr.get("head") or {}).get("sha") == head
        and bool(SHA40.fullmatch(head or ""))
        and int(pr.get("changed_files") or 0) > 0
    )
    if pr:
        evidence["pull_request"] = pr.get("html_url")
        evidence["head_sha"] = (pr.get("head") or {}).get("sha")
        evidence["changed_files"] = pr.get("changed_files")
    if not engineered:
        failures.append("NO_MAKER_PR_AT_SETTLED_HEAD")

    # 4. independent validation at exactly that head; the newest attempt decides
    latest = _newest(
        [r for r in record.get("validation_runs") or [] if r.get("head_sha") == head]
    )
    validation_green = latest is not None and latest.get("conclusion") == "success"
    checks = [
        e
        for c in record.get("pr_comments") or []
        if _by_bot(c) and (e := parse_evidence(c.get("body", "")))
    ]
    checker = next(
        (
            e
            for e in reversed(checks)
            if e.checked_head_sha == head
            and e.checks_head_sha in ("", head)
            and e.pr_number == pr.get("number")
            and e.issue_number == number
        ),
        None,
    )
    independent = (
        checker is not None
        and checker.verdict is CheckerVerdict.PASS
        and checker.required_checks_passed
        and bool(checker.checker_id.strip())
        and not same_actor(checker.checker_id, checker.maker_id)
    )
    if latest is not None:
        evidence["validation_run"] = latest.get("html_url")
    if checker is not None:
        evidence["maker_id"] = checker.maker_id
        evidence["checker_id"] = checker.checker_id
        evidence["checker_verdict"] = checker.verdict.value
    if not validation_green:
        failures.append("NO_GREEN_VALIDATION_AT_EXACT_HEAD")
    if not independent:
        failures.append("NO_INDEPENDENT_PASS_AT_EXACT_HEAD")

    # 5. receipt, and the merge it claims verified against GitHub itself
    merge_sha = (settlement or {}).get("merge_sha", "")
    final_labels = set(
        ((settlement or {}).get("final_state") or {}).get("labels") or []
    )
    issue_labels = {label.get("name") for label in issue.get("labels") or []}
    receipted = (
        settlement is not None
        and bool(SHA40.fullmatch(merge_sha or ""))
        and merge_sha != head
        and "oc-done" in final_labels
        and issue.get("state") == "closed"
        and issue.get("state_reason") == "completed"
        and "oc-done" in issue_labels
    )
    merge_verified = (
        receipted
        and pr.get("merged") is True
        and pr.get("merge_commit_sha") == merge_sha
        and (pr.get("base") or {}).get("ref") == INTEGRATION_BRANCH
        and record.get("merge_on_target") is True
        # A real merge commit of the settled head into the target branch.
        and len(record.get("merge_parents") or []) == 2
        and head in (record.get("merge_parents") or [])
    )
    if settlement_comment is not None:
        evidence["settlement_receipt"] = settlement_comment.get("html_url")
        evidence["settled_at"] = settlement_comment.get("created_at")
        evidence["merge_sha"] = merge_sha
    if not receipted:
        failures.append("NO_DURABLE_SETTLEMENT_RECEIPT")
    elif not merge_verified:
        failures.append("SETTLED_MERGE_NOT_VERIFIED_ON_TARGET")

    # Recovery counts only for an earlier lease of this issue, recovered before
    # the settled claim, naming that lease's own run.
    earlier = {
        c.get("id"): k
        for c, k in claims
        if final is None or c.get("id") != final[0].get("id")
    }
    recovered = []
    for c in comments:
        if not (_by_bot(c) and c.get("body", "").startswith(RECOVERY_PREFIX)):
            continue
        rec = _json_after(RECOVERY, c.get("body", ""))
        if (
            not rec
            or rec.get("schema") != RECOVERY_SCHEMA
            or rec.get("action") != "recover"
        ):
            continue
        claim = earlier.get(rec.get("lease_comment_id"))
        if (
            claim is not None
            and rec.get("lease_id") == claim["lease_id"]
            and str(rec.get("run_id")) == claim["lease_id"].split(":")[-3]
            and final is not None
            and (c.get("created_at") or "") < (final[0].get("created_at") or "")
        ):
            recovered.append(c.get("html_url"))
    evidence["recovered_leases"] = len(recovered)
    evidence["recovery_receipts"] = recovered

    zero = []
    for c in comments:
        if not _by_bot(c):
            continue
        result = _json_after(SETTLED_RESULT, c.get("body", ""))
        if c.get("body", "").startswith(DENIED) or (
            result and result.get("disposition") in ZERO_DISPOSITIONS
        ):
            reason = (result or {}).get("message") or (result or {}).get("reason") or ""
            if c.get("body", "").startswith(DENIED):
                reason = reason or "PROVIDER_ADMISSION_DENIED"
            zero.append(
                {
                    "comment": c.get("html_url"),
                    "at": c.get("created_at"),
                    "reason": reason or None,
                }
            )
    evidence["zero_execution"] = zero

    return {
        "issue": number,
        "passed": not failures,
        "criteria": {
            "acquired": acquired,
            "dispatched": dispatched,
            "engineered": engineered,
            "independently_validated": validation_green and independent,
            "receipted": receipted and merge_verified,
        },
        "failures": failures,
        "evidence": evidence,
    }


def evaluate(
    records: Iterable[Mapping[str, Any]], target: int = TARGET
) -> dict[str, Any]:
    cycles = [evaluate_cycle(r) for r in records]
    # Settlement order; unsettled cycles sort last and break the streak there.
    cycles.sort(
        key=lambda c: (
            c["evidence"].get("settled_at") is None,
            c["evidence"].get("settled_at") or "",
        )
    )
    streak, recovered, seen = (
        0,
        False,
        {
            "head_sha": set(),
            "merge_sha": set(),
            "lease_id": set(),
            "pull_request": set(),
        },
    )
    stop = None
    for cycle in cycles:
        reused = [
            k
            for k in seen
            if cycle["evidence"].get(k) and cycle["evidence"][k] in seen[k]
        ]
        if reused:
            cycle["passed"] = False
            cycle["failures"].append("REUSED_" + "_".join(sorted(reused)).upper())
        unexplained = [
            z for z in cycle["evidence"]["zero_execution"] if not z["reason"]
        ]
        if unexplained:
            cycle["passed"] = False
            cycle["failures"].append("ZERO_EXECUTION_WITHOUT_REASON")
        if not cycle["passed"]:
            stop = stop or f"issue {cycle['issue']}: {', '.join(cycle['failures'])}"
            break
        for k, values in seen.items():
            if cycle["evidence"].get(k):
                values.add(cycle["evidence"][k])
        streak += 1
        recovered = recovered or cycle["evidence"]["recovered_leases"] > 0
    certified = streak >= target and recovered
    if certified:
        reason = "certified"
    elif streak >= target:
        reason = "no recovered lease among the consecutive cycles"
    else:
        reason = stop or f"need {target - streak} more consecutive completed cycles"
    return {
        "schema": SCHEMA,
        "target": target,
        "consecutive_completed": streak,
        "recovery_proven": recovered,
        "certified": certified,
        "reason": reason,
        "cycles": cycles,
    }


# ---------------------------------------------------------------------------
# GitHub reads (gh api, the caller's GH_TOKEN; read-only)
# ---------------------------------------------------------------------------


def _gh(path: str) -> Any:
    out = subprocess.run(
        ["gh", "api", path],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout
    return json.loads(out)


def gh_api(path: str, max_pages: int = 50) -> Any:
    """GET one object, or every page of a list.

    Pages are requested explicitly with ``page=N`` on the same
    ``repos/{owner}/{repo}`` path rather than by following GitHub's ``Link``
    headers, which name numeric ``repositories/{id}`` paths that some
    egress proxies refuse.
    """
    if "per_page=" not in path:
        return _gh(path)
    items: list = []
    sep = "&" if "?" in path else "?"
    for page in range(1, max_pages + 1):
        batch = _gh(f"{path}{sep}page={page}")
        if isinstance(
            batch, dict
        ):  # e.g. {"workflow_runs": [...]} -- one page is enough here
            return batch
        items.extend(batch)
        per_page = int(re.search(r"per_page=(\d+)", path).group(1))
        if len(batch) < per_page:
            return items
    raise RuntimeError(f"PAGINATION_LIMIT_EXCEEDED: {path}")


def fetch_record(
    repository: str, number: int, api: Callable[[str], Any] = gh_api
) -> dict[str, Any]:
    issue = api(f"repos/{repository}/issues/{number}")
    comments = api(f"repos/{repository}/issues/{number}/comments?per_page=100")
    record: dict[str, Any] = {
        "repository": repository,
        "issue": issue,
        "comments": comments,
    }
    settlement = next(
        (
            s
            for c in reversed(comments)
            if _by_bot(c) and (s := _tagged(c.get("body", ""), SETTLEMENT_TAG))
        ),
        None,
    )
    pr_number = ((settlement or {}).get("context") or {}).get("pr")
    if isinstance(pr_number, int) and pr_number > 0:
        pr = api(f"repos/{repository}/pulls/{pr_number}")
        record["pull_request"] = pr
        record["pr_comments"] = api(
            f"repos/{repository}/issues/{pr_number}/comments?per_page=100"
        )
        head = (pr.get("head") or {}).get("sha", "")
        if SHA40.fullmatch(head):
            runs = api(
                f"repos/{repository}/actions/workflows/{VALIDATION_WORKFLOW}/runs?head_sha={head}&per_page=20"
            )
            record["validation_runs"] = (
                (runs or {}).get("workflow_runs", [])
                if isinstance(runs, dict)
                else runs
            )
    merge_sha = (settlement or {}).get("merge_sha", "")
    if isinstance(merge_sha, str) and SHA40.fullmatch(merge_sha):
        commit = api(f"repos/{repository}/git/commits/{merge_sha}")
        record["merge_parents"] = [
            p.get("sha") for p in (commit or {}).get("parents") or []
        ]
        # The target branch contains the merge iff comparing merge...branch is
        # "identical" or "ahead" (the branch has the merge and maybe more).
        compare = api(f"repos/{repository}/compare/{merge_sha}...{INTEGRATION_BRANCH}")
        record["merge_on_target"] = (compare or {}).get("status") in {
            "identical",
            "ahead",
        }
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repository", required=True)
    parser.add_argument(
        "--issues", required=True, help="comma-separated demonstration issue numbers"
    )
    parser.add_argument("--target", type=int, default=TARGET)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    numbers = [int(n) for n in args.issues.split(",") if n.strip()]
    report = evaluate(
        (fetch_record(args.repository, n) for n in numbers), target=args.target
    )
    report.update(
        repository=args.repository,
        issues=numbers,
        generated_at=datetime.now(UTC).isoformat(),
    )
    Path(args.output).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "certified",
                    "consecutive_completed",
                    "recovery_proven",
                    "reason",
                )
            }
        )
    )
    return 0 if report["certified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
