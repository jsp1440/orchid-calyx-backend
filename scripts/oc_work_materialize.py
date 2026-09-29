"""Turn discovered candidates into queued GitHub work, once each.

``oc_work_discovery`` reads the repository and returns candidates. This module
is the mutation half, kept separate for the same reason the blocked-work
reconciler and its applier are separate: a module that decides and writes in one
pass cannot be tested on its decisions alone, and the decision is the part that
must be reviewable.

The whole risk here is duplication. A discoverer that runs every five minutes
and files an issue each time is worse than no discoverer, so identity is a
property of the *condition*, not of the run: every issue carries

    OC-DISCOVERY-FINGERPRINT: <16 hex>

and no condition is ever filed twice. Closed issues count: a defect somebody
resolved does not come back on the next pulse under a new number.

What happens when a resolved condition *recurs* is decided by
``lineage_disposition`` and follows the factory's own rules rather than
convenience -- see its docstring. In short: a completed lineage is requeued, a
rejected one stays suppressed, and one still in flight is left alone.

Bounded by construction: at most ``--max-new`` queue insertions per pass --
new issues and requeued lineages together -- highest lane rank first, and
dry-run unless ``--apply`` is passed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

FINGERPRINT_MARKER = "OC-DISCOVERY-FINGERPRINT"

#: Every issue this module files carries it, which is what makes the
#: read-after-write consistent lookup below possible.
DISCOVERED_LABEL = "oc-discovered"

#: Page size for the exhaustive scan. A page size, not a limit: the scan follows
#: the cursor until the collection is exhausted, however large it grows.
PAGE_SIZE = 100

#: Ceiling on a *targeted* search for one fingerprint. A single condition's
#: fingerprint on this many issues is not a real state, so reaching it means the
#: result cannot be shown complete and the lookup fails closed rather than
#: reading a truncated answer as the whole one.
FINGERPRINT_SEARCH_CEILING = 100

#: A discovered issue whose labels are in this set is held by a person.
OWNER_HOLDS = frozenset({"oc-owner-gate", "blocked-on-owner"})
DONE_LABEL = "oc-done"
QUEUED_LABEL = "oc-queued"
NO_REQUEUE = re.compile(r"^OC-AUTO-REQUEUE:\s*false\s*$", re.IGNORECASE | re.MULTILINE)

#: Recorded on a resolved lineage when a discovery pass that evaluated its
#: source saw the condition absent. Recurrence is present -> resolved -> absent
#: -> present, and this label is the durable proof of the "absent" step.
CLEARED_LABEL = "oc-condition-cleared"
RECURRENCE_MARKER = "OC-DISCOVERY-RECURRENCE"
DISCOVERY_SOURCE = re.compile(r"^- Discovery source: `(?P<source>[a-z0-9-]+)`\s*$", re.MULTILINE)

#: Every label on a node is read; `labels.totalCount` is checked against it.
ISSUES_QUERY = """
query($owner: String!, $name: String!, $label: String!, $first: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(first: $first, after: $cursor, labels: [$label], states: [OPEN, CLOSED],
           orderBy: {field: CREATED_AT, direction: ASC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        state
        stateReason
        body
        labels(first: 100) { totalCount nodes { name } }
      }
    }
  }
}
""".strip()
FINGERPRINT = re.compile(rf"^{FINGERPRINT_MARKER}:\s*(?P<value>[a-f0-9]{{16}})\s*$", re.MULTILINE)
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

#: A pass may file at most this many, whatever the queue looks like. The cap is
#: about the blast radius of a discoverer defect, not about throughput: the next
#: pulse files the next few.
DEFAULT_MAX_NEW = 3

Transport = Callable[[list[str], dict | None], Any]


def github(args: list[str], payload: dict | None = None) -> Any:
    result = subprocess.run(
        ["gh", *args],
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    text = result.stdout.strip()
    return json.loads(text) if text.startswith(("{", "[")) else text



class IncompleteHistory(RuntimeError):
    """The lookup could not prove it read every filed issue.

    Raised rather than returning what was read. A partial read is a smaller
    known set, and a smaller known set is exactly how a condition gets filed a
    second time, so there is no degraded mode: the pass fails closed and the
    next pulse tries again.
    """


@dataclass(frozen=True)
class FiledIssue:
    """One issue carrying a discovery fingerprint, as GitHub reports it now."""

    number: int
    state: str
    state_reason: str
    labels: frozenset[str]
    body: str
    #: Found by the ``oc-discovered`` scan. False means only the targeted search
    #: found it: a discovered issue whose label a person removed.
    labelled: bool = True
    #: ``labels.totalCount`` agreed with the labels actually returned. An issue
    #: whose labels were not all read cannot be reasoned about.
    labels_complete: bool = True

    @property
    def fingerprint(self) -> str | None:
        match = FINGERPRINT.search(self.body)
        return match.group("value") if match else None

    @property
    def source(self) -> str | None:
        match = DISCOVERY_SOURCE.search(self.body)
        return match.group("source") if match else None


Index = Mapping[str, list[FiledIssue]]
Search = Callable[[str], list[FiledIssue]]


def _labels(raw: Any) -> tuple[frozenset[str], bool]:
    """Label names from either GraphQL (`{totalCount, nodes}`) or `gh --json`."""
    if isinstance(raw, dict):
        nodes = raw.get("nodes")
        total = raw.get("totalCount")
        if not isinstance(nodes, list) or not isinstance(total, int):
            raise IncompleteHistory("labels_unreadable")
        names = frozenset(str(node.get("name")) for node in nodes if isinstance(node, dict))
        return names, total == len(nodes)
    if isinstance(raw, list):
        return frozenset(str(item.get("name")) for item in raw if isinstance(item, dict)), True
    raise IncompleteHistory("labels_unreadable")


def _filed_issue(node: Any, *, labelled: bool | None = None) -> FiledIssue:
    if not isinstance(node, dict) or not isinstance(node.get("number"), int):
        # GraphQL returns a null node when it could not resolve one. Skipping
        # it would be the silent narrowing this module refuses.
        raise IncompleteHistory("unresolvable_issue_node")
    labels, complete = _labels(node.get("labels"))
    return FiledIssue(
        number=node["number"],
        state=str(node.get("state") or "").upper(),
        state_reason=str(node.get("stateReason") or "").upper(),
        labels=labels,
        body=str(node.get("body") or ""),
        labelled=DISCOVERED_LABEL in labels if labelled is None else labelled,
        labels_complete=complete,
    )


def scan_discovered_issues(repository: str, *, call: Transport = github) -> dict[str, list[FiledIssue]]:
    """Every issue labelled ``oc-discovered``, open and closed, indexed by fingerprint.

    Exhaustive, and provably so. The previous lookup asked `gh issue list` for
    at most 1,000 issues; the 1,001st discovered issue fell out of that window
    and its condition would have been filed again. Raising the number only
    moves the cliff. So this does not take a limit at all: it walks the GraphQL
    connection cursor by cursor until ``hasNextPage`` is false, and then checks
    the number of distinct issues it read against the ``totalCount`` the server
    reports for the same filtered collection. Only when those agree -- and the
    collection did not change size while it was being read -- is the result
    returned. Anything else raises :class:`IncompleteHistory`.

    Why this collection and not search: the GraphQL ``repository.issues``
    connection is served from the primary store, like the REST list, so it is
    read-after-write consistent -- an issue filed thirty seconds ago is in it.
    The search index is not, and a search-only lookup is the uncontrolled
    filing loop PR #1591 already removed once. Search also stops at 1,000
    results, so it could never be the exhaustive half.

    Closed issues are read too. Restricting this to open issues is the obvious
    shortcut and it re-files everything anybody ever resolved.
    """
    if not REPOSITORY.fullmatch(repository):
        raise ValueError("invalid repository")
    owner, name = repository.split("/", 1)
    index: dict[str, list[FiledIssue]] = {}
    numbers: set[int] = set()
    cursors: set[str] = set()
    totals: set[int] = set()
    cursor: str | None = None
    while True:
        args = ["api", "graphql", "-f", f"query={ISSUES_QUERY}",
                "-f", f"owner={owner}", "-f", f"name={name}",
                "-f", f"label={DISCOVERED_LABEL}", "-F", f"first={PAGE_SIZE}"]
        if cursor is not None:
            args += ["-f", f"cursor={cursor}"]
        response = call(args, None)
        if not isinstance(response, dict) or response.get("errors"):
            raise IncompleteHistory("graphql_error")
        issues = ((response.get("data") or {}).get("repository") or {}).get("issues")
        if not isinstance(issues, dict):
            raise IncompleteHistory("no_issue_connection")
        nodes, page, total = issues.get("nodes"), issues.get("pageInfo"), issues.get("totalCount")
        if not isinstance(nodes, list) or not isinstance(page, dict) or not isinstance(total, int):
            raise IncompleteHistory("malformed_page")
        totals.add(total)
        for node in nodes:
            issue = _filed_issue(node, labelled=True)
            numbers.add(issue.number)
            if issue.fingerprint:
                index.setdefault(issue.fingerprint, []).append(issue)
        if page.get("hasNextPage") is not True:
            if page.get("hasNextPage") is not False:
                raise IncompleteHistory("malformed_page")
            break
        following = page.get("endCursor")
        if not nodes or not isinstance(following, str) or not following or following in cursors:
            # A page that claims more but returns nothing, or a cursor that
            # does not advance, would loop forever or stop early. Neither is
            # a complete read.
            raise IncompleteHistory("cursor_did_not_advance")
        cursors.add(following)
        cursor = following
    if len(totals) != 1 or len(numbers) != totals.pop():
        # Either the collection changed size mid-read (a concurrent wave filed
        # or a person relabelled), or the pages did not cover it. Both mean
        # this read cannot be shown to be the whole collection.
        raise IncompleteHistory("count_mismatch")
    for issues_for_fingerprint in index.values():
        issues_for_fingerprint.sort(key=lambda issue: issue.number)
    return index


def search_fingerprint(repository: str, fingerprint: str, *, call: Transport = github) -> list[FiledIssue]:
    """Issues carrying one fingerprint, found by body text rather than label.

    The scan above cannot see a discovered issue whose ``oc-discovered`` label
    a person removed. This catches it. It is asked about one fingerprint at a
    time -- a sixteen-hex token -- so its result is a handful of issues, never a
    window over history, and the search API's 1,000-result cap is not in play.
    The search index lags, but only for issues filed moments ago, and those are
    labelled and already in the scan; what this exists to find is old.

    A result reaching :data:`FINGERPRINT_SEARCH_CEILING` cannot be shown to be
    complete, so it raises rather than being read as the whole answer.
    """
    if not re.fullmatch(r"[a-f0-9]{16}", fingerprint):
        raise ValueError("invalid fingerprint")
    rows = call(
        ["issue", "list", "--repo", repository, "--state", "all",
         "--search", f'"{fingerprint}" in:body',
         "--limit", str(FINGERPRINT_SEARCH_CEILING),
         "--json", "number,state,stateReason,body,labels"],
        None,
    )
    if not isinstance(rows, list):
        raise IncompleteHistory("search_unreadable")
    if len(rows) >= FINGERPRINT_SEARCH_CEILING:
        raise IncompleteHistory("search_ceiling_reached")
    found = [_filed_issue(row) for row in rows]
    # Search matches words, not lines; keep only issues that really carry it.
    return sorted((issue for issue in found if issue.fingerprint == fingerprint),
                  key=lambda issue: issue.number)


def lookup(repository: str, fingerprint: str, *, call: Transport = github) -> list[FiledIssue]:
    """Every issue for one fingerprint: the exhaustive scan, then the search."""
    return scan_discovered_issues(repository, call=call).get(fingerprint) or search_fingerprint(
        repository, fingerprint, call=call
    )


# -- Recurrence ---------------------------------------------------------------


@dataclass(frozen=True)
class Disposition:
    kind: str  # new | in_flight | rejected | resolved
    reason: str
    issue: FiledIssue | None = None

    @property
    def cleared(self) -> bool:
        return self.issue is not None and CLEARED_LABEL in self.issue.labels


def _is_resolved(issue: FiledIssue) -> bool:
    if issue.state == "CLOSED":
        return issue.state_reason == "COMPLETED"
    return DONE_LABEL in issue.labels


def lineage_disposition(issues: list[FiledIssue]) -> Disposition:
    """What an existing lineage means for a condition discovery sees again.

    The decision is B -- *requeue the historical issue* -- with the two limits
    that make it safe. It follows from the factory's rules, not taste:

    * **Not A (suppress forever).** A condition that was fixed and then came
      back is a real regression. Permanent suppression drops it silently, and
      silence is the one outcome this intake exists to remove.
    * **Not C (new occurrence identity).** One acceptance criterion has one
      authoritative lineage; the operating memory calls duplicate lineages the
      failure to avoid, and "an unchanged material fingerprint is a no-op".
      A second issue for the same fingerprint is exactly that duplicate, and
      it throws away the history of how the condition was resolved last time.
    * **B.** The lineage that already owns the condition carries it again. The
      swarm lane already accepts a requeued ``oc-done`` issue, so nothing new
      is invented downstream.

    The limits:

    1. **A rejection is final.** Closed *not planned*, ``OC-AUTO-REQUEUE:
       false``, an owner hold, or a person removing ``oc-discovered`` is a
       decision about the condition, and discovery does not overrule people.
       Closed *duplicate* is not a decision about the condition -- it defers to
       the issue it duplicates -- so it is set aside rather than counted.
    2. **Recurrence must be observed, not assumed.** A condition still present
       the pass after its issue closed was never gone: the lane closed the
       task while the evidence stayed, and requeueing that would loop
       validate/close/requeue every five minutes. So a resolved lineage is
       requeued only after a discovery pass that evaluated its source saw the
       condition *absent* -- recorded durably as ``oc-condition-cleared`` on
       the issue -- and then saw it present again. Until then it is reported
       as ``resolved_condition_persists``: visible, not re-filed, not looped.

    A closure whose reason is not *completed* (or unknown) is not a proven
    resolution and is treated as a rejection: the conservative reading, and one
    that files nothing.
    """
    if not issues:
        return Disposition("new", "never_filed")
    counted = [issue for issue in issues if issue.state_reason != "DUPLICATE" or issue.state != "CLOSED"]
    if not counted:
        return Disposition("rejected", "only_duplicates_remain", issues[-1])
    for issue in counted:
        if not issue.labels_complete:
            return Disposition("rejected", "labels_not_fully_read", issue)
        if not issue.labelled:
            return Disposition("rejected", "discovered_label_removed", issue)
        if issue.state == "CLOSED" and issue.state_reason == "NOT_PLANNED":
            return Disposition("rejected", "closed_not_planned", issue)
        if NO_REQUEUE.search(issue.body):
            return Disposition("rejected", "auto_requeue_disabled", issue)
        if issue.labels & OWNER_HOLDS:
            return Disposition("rejected", "owner_hold", issue)
        if issue.state == "CLOSED" and not _is_resolved(issue):
            return Disposition("rejected", "closure_not_proven_complete", issue)
    for issue in counted:
        if not _is_resolved(issue):
            return Disposition("in_flight", "lineage_open", issue)
    return Disposition("resolved", "lineage_resolved", counted[-1])


#: Colour and description for every label this module may apply. A label the
#: repository does not have makes `gh issue create` fail outright, which is how
#: the first live pass filed nothing while reporting success -- the failure was
#: masked by `continue-on-error` and the summary printed "0 filed".
LABEL_DEFINITIONS: dict[str, tuple[str, str]] = {
    "oc-queued": ("1d76db", "Eligible for autonomous Orchid Continuum execution"),
    "oc-discovered": ("5319e7", "Filed by work discovery from repository evidence, not by a person"),
    "oc-condition-cleared": ("c2e0c6", "Work discovery observed this resolved condition absent"),
    "oc-p0": ("b60205", "Portfolio priority P0"),
    "oc-p1": ("d93f0b", "Portfolio priority P1"),
    "oc-p2": ("e99695", "Portfolio priority P2"),
    "oc-p3": ("1d76db", "Portfolio priority P3"),
    "oc-p4": ("c5def5", "Portfolio priority P4"),
    "oc-p5": ("ededed", "Portfolio priority P5"),
}

LANE_LABEL = re.compile(r"^oc-lane:[a-z0-9][a-z0-9-]*$")


def ensure_labels(repository: str, labels: list[str], *, call: Transport = github) -> list[str]:
    """Create any label this pass needs that the repository does not have.

    ``gh label create --force`` is idempotent, so this is safe to run on every
    pass. A label outside the two shapes this module owns is refused rather
    than created: filing an issue is not authority to invent repository
    vocabulary, and a typo'd label would otherwise become a permanent fixture.
    """
    ensured: list[str] = []
    for label in labels:
        if label in LABEL_DEFINITIONS:
            colour, description = LABEL_DEFINITIONS[label]
        elif LANE_LABEL.fullmatch(label):
            colour, description = "0e8a16", f"Orchid Continuum product lane: {label.split(':', 1)[1]}"
        else:
            raise ValueError(f"refusing to create a label outside this module's vocabulary: {label!r}")
        call(
            ["label", "create", label, "--repo", repository, "--color", colour,
             "--description", description, "--force"],
            None,
        )
        ensured.append(label)
    return ensured


def is_mechanically_remediable(candidate: Mapping[str, Any]) -> bool:
    """True when the candidate carries a structured, single-line remedy.

    Judged from the record, not from the source name alone: a candidate from a
    mechanical source that arrived without its ``remedy`` block (an older
    discovery report, or a hand-written one) is not something an edit lane may
    act on.
    """
    remedy = candidate.get("remedy")
    return (
        isinstance(remedy, Mapping)
        and remedy.get("kind") == "declare-distribution"
        and bool(remedy.get("distribution"))
        and bool(remedy.get("requirements_file"))
    )


def issue_body(candidate: dict[str, Any]) -> str:
    """The issue text, including the machine-readable markers the lanes read."""
    lines = [
        candidate["summary"],
        "",
        "## Evidence",
        "",
        (
            "Every line below is a fact this discoverer read out of the repository. "
            "Nothing here was inferred from prose."
        ),
        "",
    ]
    for item in candidate.get("evidence") or []:
        lines.append(f"- `{item['where']}` — {item['detail']}")
    if candidate.get("proposed_remedy"):
        lines += [
            "",
            "## Proposed remedy",
            "",
            (
                "Derived mechanically from the evidence above. It is a proposal for a "
                "reviewer, not an instruction anything here executes."
            ),
            "",
            candidate["proposed_remedy"],
        ]
    lane = candidate.get("lane_name")
    lines += [
        "",
        "## Routing",
        "",
        f"- Product lane: {lane or 'UNBOUND — no path prefix matched, so none was assigned'}",
        f"- Discovery source: `{candidate['source']}`",
        "",
        (
            "This task was filed by `scripts/oc_work_materialize.py` from a "
            "`scripts/oc_work_discovery.py` pass. No person selected it."
        ),
        "",
    ]
    command = str(candidate.get("validation_command") or "")
    if command:
        lines += [
            "## Acceptance",
            "",
            (
                f"The deterministic lane settles this from `{command}`, which runs every "
                "affected path and nothing else. A non-zero exit, a timeout, or an "
                "unrunnable command settles this issue `oc-blocked` whatever this text "
                "says — the exit code decides, not the task."
            ),
            "",
        ]
    for capability in candidate.get("capabilities") or []:
        lines.append(f"OC-SWARM-CAPABILITY: {capability}")
    mechanical = is_mechanically_remediable(candidate)
    if command and mechanical:
        # The remedy is one line the evidence determines and a registered
        # command proves. The edit lane derives it, applies it on a branch,
        # re-runs the command, and opens a draft pull request; the issue then
        # waits on that PR through the blocked-work reconciler. It writes the
        # requirements file, which the write-set verifier files under
        # ``repo-global``, so the lease must carry that write.
        lines += [
            "OC-SWARM-PROVIDER-FREE: edit",
            f"OC-SWARM-VALIDATE: {command}",
            "OC-SWARM-DISPOSITION: done",
            "OC-SWARM-WRITES: repo-global",
        ]
    elif command:
        # Only when a registered command covers every affected path. Without
        # one the task is filed and ranked but not lane-executable, which is
        # the honest state: the factory found the work and has no executor for
        # it. Naming a command that does not cover the evidence would settle
        # the task on a run that proves something else.
        lines += [
            "OC-SWARM-PROVIDER-FREE: validate",
            f"OC-SWARM-VALIDATE: {command}",
            "OC-SWARM-DISPOSITION: done",
        ]
    lines += [
        "OC-SWARM-READS: control-plane",
        "",
        f"{FINGERPRINT_MARKER}: {candidate['fingerprint']}",
    ]
    return "\n".join(lines)


def plan(
    report: dict[str, Any],
    index: Index,
    *,
    max_new: int = DEFAULT_MAX_NEW,
    search: Search | None = None,
    max_cleared: int = DEFAULT_MAX_NEW,
) -> dict[str, Any]:
    """Decide what to file, requeue, and mark cleared, without doing any of it.

    ``index`` is :func:`scan_discovered_issues` output. ``search`` is consulted
    only for a candidate the index does not know, and only while the pass
    still has room for another insertion: a candidate that could not be filed
    this pass anyway costs no search.

    Candidates arrive ranked. Ties keep the discoverer's order rather than being
    re-sorted here, so two passes over one repository state file the same work.
    """
    if report.get("schema") != "oc.work-discovery.v1":
        raise ValueError("unrecognised discovery report")
    if max_new < 0 or max_cleared < 0:
        raise ValueError("bounds must not be negative")

    actions: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    present: set[str] = set()
    inserted = 0
    for candidate in report.get("candidates") or []:
        fingerprint = str(candidate.get("fingerprint") or "")
        if not re.fullmatch(r"[a-f0-9]{16}", fingerprint):
            skipped.append({"title": candidate.get("title"), "reason": "unusable_fingerprint"})
            continue
        present.add(fingerprint)
        issues = list(index.get(fingerprint) or [])
        if not issues and inserted >= max_new:
            skipped.append({"fingerprint": fingerprint, "reason": "bounded_by_max_new"})
            continue
        if not issues and search is not None:
            issues = search(fingerprint)
        disposition = lineage_disposition(issues)
        number = disposition.issue.number if disposition.issue else None
        if disposition.kind in {"rejected", "in_flight"}:
            skipped.append({"fingerprint": fingerprint, "reason": disposition.reason, "issue_number": number})
            continue
        if disposition.kind == "resolved" and not disposition.cleared:
            skipped.append(
                {"fingerprint": fingerprint, "reason": "resolved_condition_persists", "issue_number": number}
            )
            continue
        if inserted >= max_new:
            skipped.append({"fingerprint": fingerprint, "reason": "bounded_by_max_new"})
            continue
        inserted += 1
        if disposition.kind == "resolved":
            actions.append(
                {
                    "action": "requeue_issue",
                    "fingerprint": fingerprint,
                    "issue_number": number,
                    "lane": candidate.get("lane"),
                    "rank": candidate.get("rank"),
                }
            )
            continue
        actions.append(
            {
                "action": "create_issue",
                "fingerprint": fingerprint,
                "title": candidate["title"],
                "labels": list(candidate["labels"]),
                "body": issue_body(candidate),
                "lane": candidate.get("lane"),
                "rank": candidate.get("rank"),
            }
        )

    # Absence is only evidence when the source that would have reported the
    # condition actually ran. A report that does not say which sources it
    # evaluated proves no absence at all.
    evaluated = {str(source) for source in report.get("sources_evaluated") or []}
    cleared = 0
    for fingerprint in sorted(set(index) - present, key=lambda fp: index[fp][-1].number):
        disposition = lineage_disposition(list(index[fingerprint]))
        if disposition.kind != "resolved" or disposition.cleared or disposition.issue is None:
            continue
        if disposition.issue.source not in evaluated:
            continue
        if cleared >= max_cleared:
            skipped.append({"fingerprint": fingerprint, "reason": "clearance_bounded"})
            continue
        cleared += 1
        actions.append(
            {
                "action": "mark_condition_cleared",
                "fingerprint": fingerprint,
                "issue_number": disposition.issue.number,
            }
        )
    return {
        "schema": "oc.work-materialization-plan.v1",
        "mutates": False,
        "action_count": len(actions),
        "actions": actions,
        "skipped": skipped,
    }


def _requeue(repository: str, action: dict[str, Any], issue: FiledIssue, *, call: Transport) -> None:
    number = str(issue.number)
    ensure_labels(repository, [QUEUED_LABEL], call=call)
    # Reopen before relabelling. If the relabel then fails, the issue is open,
    # still ``oc-done`` and still cleared -- which the next pass reads as the
    # same requeue and finishes. The other order can strand a closed issue
    # carrying ``oc-queued`` that no lane will ever claim.
    if issue.state == "CLOSED":
        call(["issue", "reopen", number, "--repo", repository], None)
    call(["issue", "edit", number, "--repo", repository,
          "--remove-label", DONE_LABEL, "--remove-label", CLEARED_LABEL,
          "--add-label", QUEUED_LABEL], None)
    after = call(["issue", "view", number, "--repo", repository, "--json", "state,labels"], None)
    labels, _ = _labels((after or {}).get("labels") if isinstance(after, dict) else None)
    if not (isinstance(after, dict) and str(after.get("state")).upper() == "OPEN"
            and QUEUED_LABEL in labels and DONE_LABEL not in labels):
        raise ValueError("requeue not confirmed")
    receipt = (
        f"{RECURRENCE_MARKER}: {action['fingerprint']}\n\n"
        "Work discovery saw this condition absent after the issue was resolved, "
        "and has now seen it present again. The lineage is requeued rather than "
        "re-filed so the condition keeps one authoritative issue. No person "
        "selected it."
    )
    call(["issue", "comment", number, "--repo", repository, "--body", receipt], None)


def apply_plan(
    materialization: dict[str, Any],
    repository: str,
    *,
    dry_run: bool = True,
    call: Transport = github,
) -> dict[str, Any]:
    """Carry out the plan, re-reading the whole lineage immediately before each write."""
    if not REPOSITORY.fullmatch(repository):
        raise ValueError("invalid repository")
    if materialization.get("schema") != "oc.work-materialization-plan.v1":
        raise ValueError("invalid materialization plan")

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for action in materialization.get("actions") or []:
        fingerprint = action.get("fingerprint")
        if dry_run:
            results.append({"fingerprint": fingerprint, "action": action.get("action"), "outcome": "dry_run"})
            continue
        try:
            # Re-read rather than trusting the plan's snapshot. Two controller
            # waves can overlap, and the loser of that race must write nothing.
            # The scan is read-after-write consistent, so the winner's issue is
            # in it; if the collection moved during the read it raises instead.
            disposition = lineage_disposition(lookup(repository, fingerprint, call=call))
            kind = action.get("action")
            if kind == "create_issue":
                if disposition.kind != "new":
                    results.append({"fingerprint": fingerprint, "outcome": "already_filed",
                                    "reason": disposition.reason})
                    continue
                # Before the write, not after: a missing label fails the create
                # outright and the work is simply never filed.
                ensure_labels(repository, list(action["labels"]), call=call)
                args = ["issue", "create", "--repo", repository,
                        "--title", action["title"], "--body", action["body"]]
                for label in action["labels"]:
                    args += ["--label", label]
                url = str(call(args, None) or "").strip()
                match = re.search(r"/issues/(\d+)\s*$", url)
                if not match:
                    raise ValueError("issue creation returned no issue URL")
                results.append({"fingerprint": fingerprint, "outcome": "created",
                                "issue_number": int(match.group(1)), "url": url})
            elif kind == "requeue_issue":
                issue = disposition.issue
                if not (disposition.kind == "resolved" and disposition.cleared and issue is not None
                        and issue.number == action["issue_number"]):
                    results.append({"fingerprint": fingerprint, "outcome": "lineage_changed",
                                    "reason": disposition.reason})
                    continue
                _requeue(repository, action, issue, call=call)
                results.append({"fingerprint": fingerprint, "outcome": "requeued",
                                "issue_number": issue.number})
            elif kind == "mark_condition_cleared":
                issue = disposition.issue
                if not (disposition.kind == "resolved" and not disposition.cleared and issue is not None
                        and issue.number == action["issue_number"]):
                    results.append({"fingerprint": fingerprint, "outcome": "lineage_changed",
                                    "reason": disposition.reason})
                    continue
                ensure_labels(repository, [CLEARED_LABEL], call=call)
                call(["issue", "edit", str(issue.number), "--repo", repository,
                      "--add-label", CLEARED_LABEL], None)
                results.append({"fingerprint": fingerprint, "outcome": "marked_cleared",
                                "issue_number": issue.number})
            else:
                raise ValueError("unknown action")
        except (OSError, subprocess.SubprocessError, TypeError, ValueError, KeyError,
                IncompleteHistory) as exc:
            errors.append(
                {
                    "fingerprint": fingerprint,
                    "reason": "materialization_unconfirmed",
                    "error_type": type(exc).__name__,
                }
            )
    return {
        "schema": "oc.work-materialization-report.v1",
        "repository": repository,
        "dry_run": dry_run,
        "planned_count": len(materialization.get("actions") or []),
        "created_count": sum(row["outcome"] == "created" for row in results),
        "requeued_count": sum(row["outcome"] == "requeued" for row in results),
        "cleared_count": sum(row["outcome"] == "marked_cleared" for row in results),
        "results": results,
        "errors": errors,
        "safety": {"provider_calls": False, "merge": False, "deploy": False},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--report", required=True, help="oc.work-discovery.v1 JSON")
    parser.add_argument("--max-new", type=int, default=DEFAULT_MAX_NEW)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--github-output")
    args = parser.parse_args(argv)

    with open(args.report, encoding="utf-8") as handle:
        report = json.load(handle)
    if args.apply:
        # Not caught: an incomplete read must stop the pass, not shrink it.
        index: Index = scan_discovered_issues(args.repository, call=github)
        repository = args.repository

        def search(fingerprint: str) -> list[FiledIssue]:
            return search_fingerprint(repository, fingerprint, call=github)

        materialization = plan(report, index, max_new=args.max_new, search=search,
                               max_cleared=args.max_new)
    else:
        # Dry run reads nothing, so it can only describe first filings.
        materialization = plan(report, {}, max_new=args.max_new, max_cleared=args.max_new)
    outcome = apply_plan(materialization, args.repository, dry_run=not args.apply, call=github)
    if args.github_output:
        created = [row["issue_number"] for row in outcome["results"] if row["outcome"] == "created"]
        requeued = [row["issue_number"] for row in outcome["results"] if row["outcome"] == "requeued"]
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"created_count={outcome['created_count']}\n")
            handle.write("created_numbers=" + json.dumps(created, separators=(",", ":")) + "\n")
            handle.write(f"requeued_count={outcome['requeued_count']}\n")
            handle.write("requeued_numbers=" + json.dumps(requeued, separators=(",", ":")) + "\n")
    json.dump(outcome, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
