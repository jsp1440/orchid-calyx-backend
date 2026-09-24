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

and a candidate whose fingerprint is already on an issue — open or closed — is
skipped. Closed counts. A defect somebody looked at and closed must not come
back on the next pulse under a new number; if it recurs, the evidence changes
and so does the fingerprint.

Bounded by construction: at most ``--max-new`` issues per pass, highest lane
rank first, and dry-run unless ``--apply`` is passed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from typing import Any

FINGERPRINT_MARKER = "OC-DISCOVERY-FINGERPRINT"
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


def existing_fingerprints(repository: str, *, call: Transport = github) -> set[str]:
    """Every discovery fingerprint already on an issue in this repository.

    Reads closed issues too. Restricting this to open issues is the obvious
    shortcut and it re-files everything anybody ever resolved.
    """
    found: set[str] = set()
    rows = call(
        [
            "issue",
            "list",
            "--repo",
            repository,
            "--state",
            "all",
            "--search",
            FINGERPRINT_MARKER,
            "--limit",
            "200",
            "--json",
            "number,body",
        ],
        None,
    )
    for row in rows or []:
        match = FINGERPRINT.search(str(row.get("body") or ""))
        if match:
            found.add(match.group("value"))
    return found


#: Colour and description for every label this module may apply. A label the
#: repository does not have makes `gh issue create` fail outright, which is how
#: the first live pass filed nothing while reporting success -- the failure was
#: masked by `continue-on-error` and the summary printed "0 filed".
LABEL_DEFINITIONS: dict[str, tuple[str, str]] = {
    "oc-queued": ("1d76db", "Eligible for autonomous Orchid Continuum execution"),
    "oc-discovered": ("5319e7", "Filed by work discovery from repository evidence, not by a person"),
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
    if command:
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


def plan(report: dict[str, Any], known: set[str], *, max_new: int = DEFAULT_MAX_NEW) -> dict[str, Any]:
    """Decide what to file, without filing it.

    Candidates arrive ranked. Ties keep the discoverer's order rather than being
    re-sorted here, so two passes over one repository state file the same work.
    """
    if report.get("schema") != "oc.work-discovery.v1":
        raise ValueError("unrecognised discovery report")
    if max_new < 0:
        raise ValueError("max_new must not be negative")

    actions: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for candidate in report.get("candidates") or []:
        fingerprint = str(candidate.get("fingerprint") or "")
        if not re.fullmatch(r"[a-f0-9]{16}", fingerprint):
            skipped.append({"title": candidate.get("title"), "reason": "unusable_fingerprint"})
            continue
        if fingerprint in known:
            skipped.append({"fingerprint": fingerprint, "reason": "already_filed"})
            continue
        if len(actions) >= max_new:
            skipped.append({"fingerprint": fingerprint, "reason": "bounded_by_max_new"})
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
    return {
        "schema": "oc.work-materialization-plan.v1",
        "mutates": False,
        "action_count": len(actions),
        "actions": actions,
        "skipped": skipped,
    }


def apply_plan(
    materialization: dict[str, Any],
    repository: str,
    *,
    dry_run: bool = True,
    call: Transport = github,
) -> dict[str, Any]:
    """File the planned issues, re-checking identity immediately before each write."""
    if not REPOSITORY.fullmatch(repository):
        raise ValueError("invalid repository")
    if materialization.get("schema") != "oc.work-materialization-plan.v1":
        raise ValueError("invalid materialization plan")

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for action in materialization.get("actions") or []:
        if dry_run:
            results.append({"fingerprint": action["fingerprint"], "outcome": "dry_run"})
            continue
        try:
            # Re-read rather than trusting the plan's snapshot. Two controller
            # waves can overlap, and the loser of that race must file nothing.
            if action["fingerprint"] in existing_fingerprints(repository, call=call):
                results.append({"fingerprint": action["fingerprint"], "outcome": "already_filed"})
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
            results.append(
                {
                    "fingerprint": action["fingerprint"],
                    "outcome": "created",
                    "issue_number": int(match.group(1)),
                    "url": url,
                }
            )
        except (OSError, subprocess.SubprocessError, TypeError, ValueError, KeyError) as exc:
            errors.append(
                {
                    "fingerprint": action.get("fingerprint"),
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
    known = existing_fingerprints(args.repository) if args.apply else set()
    materialization = plan(report, known, max_new=args.max_new)
    outcome = apply_plan(
        materialization, args.repository, dry_run=not args.apply
    )
    if args.github_output:
        created = [row["issue_number"] for row in outcome["results"] if row["outcome"] == "created"]
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"created_count={outcome['created_count']}\n")
            handle.write("created_numbers=" + json.dumps(created, separators=(",", ":")) + "\n")
    json.dump(outcome, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
