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
SETTLEMENT_TAG = "OC-HOSTED-SETTLEMENT-V1"
SETTLED_RESULT = re.compile(
    r"^\[OC-SWARM-V4\] (?:Worker result validated|Provider admission denied)"
    r"[^`]*`(\{.*\})`",
    re.DOTALL,
)
ZERO_DISPOSITIONS = frozenset({"runtime-backoff", "repair", "blocked", "queued"})
VALIDATION_WORKFLOW = "orchid-autonomous-validation.yml"
INTEGRATION_BRANCH = "oc-autonomous-integration"
RUN_URL = re.compile(r"/actions/runs/(\d+)(?:/|$)")
MAKER_BRANCH = re.compile(r"claude-direct/issue-\d+-\d+")
CHECKER_ID = re.compile(r"anthropic:checker:\d+:\d+")
# oc_swarm_lease_reconcile: the receipt drops "action" and adds "released_state".
RECOVERY_SCHEMA = "oc.swarm-lease-recovery.v1"
RECOVERY_PREFIX = "[OC-SWARM-V4] Stale lease recovered: `"
RECOVERY = re.compile(r"^\[OC-SWARM-V4\] Stale lease recovered: `(\{[^\n]+\})`")
RECOVER_REASONS = frozenset(
    {
        "running_label_beside_parked_state",
        "settled_without_label_release",
        "worker_run_terminated_without_settlement",
        "manual_lease_expired",
    }
)


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


def _order(comment: Mapping[str, Any]) -> tuple:
    """Comment order. Ids only increase, so they break same-second ties."""
    return (str(comment.get("created_at") or ""), int(comment.get("id") or 0))


def _run_id(url: str) -> int | None:
    match = RUN_URL.search(url or "")
    return int(match.group(1)) if match else None


def _settled_validation(
    runs: list[Mapping[str, Any]], *, head: str, branch: str, after: str
) -> Mapping[str, Any] | None:
    """The validation run the settlement relied on.

    Chosen as ``oc_hosted_completion.validation`` chooses it: runs of the
    validation workflow dispatched by the bot on the PR's own branch at this
    head, created after the worker started, highest run id. Never GitHub's list
    order (newest-first) and never a run someone else started.
    """
    matches = [
        r
        for r in runs
        if r.get("head_sha") == head
        and r.get("head_branch") == branch
        and r.get("event") == "workflow_dispatch"
        and (r.get("actor") or {}).get("login") == BOT
        and str(r.get("path") or "").endswith(
            f".github/workflows/{VALIDATION_WORKFLOW}"
        )
        and str(r.get("created_at") or "") >= after
    ]
    return max(matches, key=lambda r: int(r.get("id") or 0)) if matches else None


def evaluate_cycle(record: Mapping[str, Any]) -> dict[str, Any]:
    """Judge one issue from its fetched records (pure; see ``fetch_record``)."""
    issue = record["issue"]
    number = int(issue["number"])
    comments = sorted(record.get("comments") or [], key=_order)
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
    # One receipt. Several distinct bot-tagged receipts are ambiguity, not evidence.
    distinct = {json.dumps(s, sort_keys=True) for _, s in settlements}
    settlement_comment, settlement = (
        settlements[0] if len(distinct) == 1 else (None, None)
    )
    if len(distinct) > 1:
        failures.append("AMBIGUOUS_SETTLEMENT_RECEIPTS")
    context = (settlement or {}).get("context") or {}
    repository = str(record.get("repository") or context.get("repository") or "")
    repository = repository.lower()
    worker_run = context.get("worker_run")
    worker_attempt = context.get("worker_attempt")

    # 1. acquisition: the claim the settlement names, for the attempt that did the work
    final = next(
        ((c, k) for c, k in claims if c.get("id") == context.get("lease")), None
    )
    if final is None and claims and settlement is None:
        final = claims[-1]
    acquired = final is not None and (
        settlement_comment is None
        or (
            str(final[1]["lease_id"]).lower()
            == f"{repository}:{worker_run}:{worker_attempt}:{number}"
            and _order(final[0]) < _order(settlement_comment)
        )
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

    # 2. dispatch: that attempt's provider worker started; no denial names this lease
    after = [c for c in comments if final is not None and _order(c) > _order(final[0])]
    worker_comment, worker = next(
        (
            (c, m)
            for c in after
            if _by_bot(c) and (m := WORKER.search(c.get("body", "")))
        ),
        (None, None),
    )
    denied = any(
        _by_bot(c)
        and c.get("body", "").startswith(DENIED)
        and (_json_after(SETTLED_RESULT, c.get("body", "")) or {}).get(
            "lease_comment_id"
        )
        in (None, final[0].get("id"))
        for c in after
    )
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
    branch = (pr.get("head") or {}).get("ref") or ""
    engineered = (
        bool(pr)
        and pr.get("number") == context.get("pr")
        and (pr.get("user") or {}).get("login") == BOT
        and bool(MAKER_BRANCH.fullmatch(branch))
        and branch.startswith(f"claude-direct/issue-{number}-")
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

    # 4. independent validation at exactly that head
    validation = _settled_validation(
        list(record.get("validation_runs") or []),
        head=head,
        branch=branch,
        after=str((worker_comment or {}).get("created_at") or "~"),
    )
    validation_green = (
        validation is not None and validation.get("conclusion") == "success"
    )
    checks = [
        e
        for c in sorted(record.get("pr_comments") or [], key=_order)
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
            and e.repository.lower() == repository
        ),
        None,
    )
    independent = (
        checker is not None
        and checker.verdict is CheckerVerdict.PASS
        and checker.required_checks_passed
        and not same_actor(checker.checker_id, checker.maker_id)
        # The identities oc_hosted_completion assigns: the maker is this
        # worker run; the checker is a completion run, both for this issue.
        and checker.maker_id == f"anthropic:maker:{worker_run}:{number}"
        and bool(CHECKER_ID.fullmatch(checker.checker_id))
        and checker.checker_id.endswith(f":{number}")
    )
    if validation is not None:
        evidence["validation_run"] = validation.get("html_url")
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
    parents = record.get("merge_parents") or []
    merge_verified = (
        receipted
        and pr.get("merged") is True
        and pr.get("merge_commit_sha") == merge_sha
        and (pr.get("base") or {}).get("ref") == INTEGRATION_BRANCH
        and record.get("merge_on_target") is True
        # A real two-parent merge of the settled head into the target branch.
        and len(parents) == 2
        and head in parents
    )
    if settlement_comment is not None:
        evidence["settlement_receipt"] = settlement_comment.get("html_url")
        evidence["settled_at"] = settlement_comment.get("created_at")
        evidence["merge_sha"] = merge_sha
    if not receipted:
        failures.append("NO_DURABLE_SETTLEMENT_RECEIPT")
    elif not merge_verified:
        failures.append("SETTLED_MERGE_NOT_VERIFIED_ON_TARGET")

    # Recovery: the reconciler's own receipt for an earlier lease of this issue,
    # naming that lease's run, released off oc-running, before the settled claim.
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
            or rec.get("issue_number") != number
            or rec.get("reason") not in RECOVER_REASONS
            or not isinstance(rec.get("released_state"), list)
            or "oc-running" in rec["released_state"]
        ):
            continue
        claim = earlier.get(rec.get("lease_comment_id"))
        if (
            claim is not None
            and rec.get("lease_id") == claim["lease_id"]
            and str(rec.get("run_id")) == str(claim["lease_id"]).split(":")[-3]
            and final is not None
            and _order(c) < _order(final[0])
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
    if final is not None:
        evidence["claimed_at"] = final[0].get("created_at")

    # What kind of record this is. A claim whose latest attempt never reached a
    # provider (provider-free or acquisition lanes, or an admission denied for
    # that lease) is not an engineering cycle at all: it is reported as zero
    # execution with the engine's reason, never as a pass and never as a break.
    # An executed attempt still running is "in_progress", not yet judged.
    # Judge every attempt in the issue's history, not only the latest claim:
    # an attempt executed when its worker started and no denial named its lease.
    executed = []
    for i, (claim_comment, _) in enumerate(claims):
        upper = claims[i + 1][0] if i + 1 < len(claims) else None
        segment = [
            c
            for c in comments
            if _order(c) > _order(claim_comment)
            and (upper is None or _order(c) < _order(upper))
            and _by_bot(c)
        ]
        started = any(WORKER.search(c.get("body", "")) for c in segment)
        refused = any(
            c.get("body", "").startswith(DENIED)
            and (_json_after(SETTLED_RESULT, c.get("body", "")) or {}).get(
                "lease_comment_id"
            )
            in (None, claim_comment.get("id"))
            for c in segment
        )
        executed.append(started and not refused)
    evidence["executed_attempts"] = sum(executed)
    labels_now = {label.get("name") for label in issue.get("labels") or []}
    if settlement is None and not any(executed):
        status = "zero_execution"
    elif (
        settlement is None
        and executed
        and executed[-1]
        and issue.get("state") == "open"
        and labels_now & {"oc-running", "oc-validating"}
    ):
        status = "in_progress"
    else:
        status = "passed" if not failures else "failed"

    return {
        "issue": number,
        "status": status,
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
    records: Iterable[Mapping[str, Any]],
    target: int = TARGET,
    *,
    window_complete: bool = False,
) -> dict[str, Any]:
    """Judge every cycle, then the most recent run of consecutive passes.

    Certification additionally requires ``window_complete``: the cycles must be
    every claimed issue in a window GitHub enumerated (``--window-start``), not
    a list a caller chose, so failures cannot be left out of "consecutive".
    """
    judged = [evaluate_cycle(r) for r in records]
    zero_issues = [c for c in judged if c["status"] == "zero_execution"]
    cycles = [c for c in judged if c["status"] != "zero_execution"]
    # Settlement time, else the claim time of the attempt (in-progress or failed).
    cycles.sort(
        key=lambda c: (
            c["evidence"].get("settled_at") or c["evidence"].get("claimed_at") or "",
            c["issue"],
        )
    )
    seen: dict[str, set] = {
        "head_sha": set(),
        "merge_sha": set(),
        "lease_id": set(),
        "pull_request": set(),
    }
    for cycle in cycles:
        if cycle["status"] == "in_progress":
            continue
        reused = [
            k
            for k, values in seen.items()
            if cycle["evidence"].get(k) and cycle["evidence"][k] in values
        ]
        if reused:
            cycle["passed"] = False
            cycle["failures"].append("REUSED_" + "_".join(sorted(reused)).upper())
        if any(not z["reason"] for z in cycle["evidence"]["zero_execution"]):
            cycle["passed"] = False
            cycle["failures"].append("ZERO_EXECUTION_WITHOUT_REASON")
        cycle["status"] = "passed" if cycle["passed"] else "failed"
        for k, values in seen.items():
            if cycle["evidence"].get(k):
                values.add(cycle["evidence"][k])
    # The most recent unbroken run of passing cycles; running ones are skipped.
    streak, recovered, stop = 0, False, None
    for cycle in reversed(cycles):
        # Only the newest attempts may still be running; an in-progress cycle
        # older than a finished one is stuck and breaks the streak.
        if cycle["status"] == "in_progress" and streak == 0 and stop is None:
            continue
        if cycle["status"] == "in_progress":
            stop = f"issue {cycle['issue']}: STALE_IN_PROGRESS"
            break
        if not cycle["passed"]:
            stop = f"issue {cycle['issue']}: {', '.join(cycle['failures'])}"
            break
        streak += 1
        recovered = recovered or cycle["evidence"]["recovered_leases"] > 0
    certified = streak >= target and recovered and window_complete
    if certified:
        reason = "certified"
    elif streak >= target and not recovered:
        reason = "no recovered lease among the consecutive cycles"
    elif streak >= target:
        reason = "cycles were chosen by the caller, not enumerated from a window"
    else:
        reason = stop or f"need {target - streak} more consecutive completed cycles"
    return {
        "schema": SCHEMA,
        "target": target,
        "consecutive_completed": streak,
        "recovery_proven": recovered,
        "window_complete": window_complete,
        "certified": certified,
        "reason": reason,
        "cycles": cycles,
        "in_progress": [c["issue"] for c in cycles if c["status"] == "in_progress"],
        "zero_execution_issues": [
            {
                "issue": c["issue"],
                # The engine's own reasons, else why no provider attempt exists
                # (e.g. a provider-free or acquisition lane served the claim).
                "reasons": [z["reason"] for z in c["evidence"]["zero_execution"]]
                or c["failures"][:1],
            }
            for c in zero_issues
        ],
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
        if isinstance(batch, dict):
            # Object-wrapped lists ({"workflow_runs": [...]}) return their first
            # page only. The one caller filters runs by head_sha with
            # per_page=20; a head validated more than 20 times would need paging.
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


def _utc(value: str) -> datetime:
    """Parse an ISO timestamp (Z, offset, fractional seconds) to aware UTC."""
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp needs a timezone: {value!r}")
    return parsed.astimezone(UTC)


def window_records(
    repository: str, start: str, api: Callable[[str], Any] = gh_api
) -> list[dict[str, Any]]:
    """Every issue with a bot lease claim at or after ``start``, from GitHub.

    The issues endpoint's ``since`` filters on last update, which any claim
    bumps, so no claimed issue in the window can be missed; pull requests are
    skipped. The claim time, not the update time, decides membership.
    """
    since = _utc(start)
    rows = api(f"repos/{repository}/issues?state=all&since={start}&per_page=100")
    records = []
    for row in rows:
        if "pull_request" in row:
            continue
        record = fetch_record(repository, int(row["number"]), api=api)
        if any(
            _by_bot(c)
            and c.get("created_at")
            and _utc(str(c["created_at"])) >= since
            and (_json_after(CLAIM, c.get("body", "")) or {}).get("schema")
            == "oc.swarm-claim.v1"
            for c in record["comments"]
        ):
            records.append(record)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repository", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--window-start",
        help="UTC ISO time; judge every issue claimed since then (certifiable)",
    )
    source.add_argument(
        "--issues", help="comma-separated issue numbers (inspection only)"
    )
    parser.add_argument("--target", type=int, default=TARGET)
    parser.add_argument(
        "--first-cycle",
        action="store_true",
        help="exit 0 when the most recent cycle in the window passed (no certification)",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.window_start:
        records = window_records(args.repository, args.window_start)
        numbers = [int(r["issue"]["number"]) for r in records]
    else:
        numbers = [int(n) for n in args.issues.split(",") if n.strip()]
        records = [fetch_record(args.repository, n) for n in numbers]
    report = evaluate(
        records, target=args.target, window_complete=bool(args.window_start)
    )
    report.update(
        repository=args.repository,
        issues=numbers,
        window_start=args.window_start,
        generated_at=datetime.now(UTC).isoformat(),
    )
    Path(args.output).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    keys = (
        "certified",
        "consecutive_completed",
        "recovery_proven",
        "window_complete",
        "reason",
    )
    print(json.dumps({k: report[k] for k in keys}))
    if args.first_cycle:
        finished = [c for c in report["cycles"] if c["status"] != "in_progress"]
        latest = finished[-1] if finished else None
        return 0 if args.window_start and latest is not None and latest["passed"] else 1
    return 0 if report["certified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
