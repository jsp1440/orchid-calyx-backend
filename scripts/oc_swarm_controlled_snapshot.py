"""Build a strictly scoped snapshot for the temporary R1 lifecycle proof."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from app.autonomy.module_lanes import assign_lane
from scripts.oc_swarm_dependency_graph import build_dependency_graph, dependencies
from scripts.oc_swarm_provider_free_worker import execution_plan
from scripts.oc_swarm_resource_locks import infer_resources

SCHEMA = "oc.swarm-controlled-snapshot.v1"
CONTROLLED_MARKER = re.compile(
    r"^OC-R1-CONTROLLED-TEST:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE
)
LANE_MARKER = re.compile(r"^OC-MODULE-LANE:\s*([a-z0-9][a-z0-9-]*)\s*$", re.IGNORECASE | re.MULTILINE)
MODE_MARKER = re.compile(
    r"^OC-SWARM-PROVIDER-FREE:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE
)
READ_RESOURCE_MARKER = re.compile(
    r"^OC-SWARM-READS:\s*(.*?)\s*$", re.IGNORECASE | re.MULTILINE
)
WRITE_RESOURCE_MARKER = re.compile(
    r"^OC-SWARM-WRITES:\s*.*$", re.IGNORECASE | re.MULTILINE
)
DISPOSITION_MARKER = re.compile(
    r"^OC-SWARM-DISPOSITION:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE
)
TITLE_PREFIX = "[R1 controlled test]"
ALLOWED_LANES = frozenset({"literature", "frontend-ux", "infrastructure-federation"})
VALIDATION_COMMAND = "control-plane-compiles"
PARKED = frozenset(
    {
        "oc-blocked",
        "oc-owner-gate",
        "oc-repair",
        "oc-repair-backoff",
        "oc-running",
        "oc-runtime-backoff",
        "oc-scientific-gate",
        "oc-validating",
    }
)


def parse_issue_numbers(value: str) -> list[int]:
    """Parse two or three distinct positive issue numbers from a CSV value."""
    parts = value.split(",")
    if not 2 <= len(parts) <= 3 or any(not re.fullmatch(r"[1-9][0-9]*", p.strip()) for p in parts):
        raise ValueError("controlled issue list must contain two or three positive CSV numbers")
    numbers = [int(part.strip()) for part in parts]
    if len(set(numbers)) != len(numbers):
        raise ValueError("controlled issue list contains duplicates")
    return numbers


def _labels(issue: Mapping[str, Any]) -> set[str]:
    return {
        label if isinstance(label, str) else str(label.get("name") or "")
        for label in issue.get("labels") or []
    }


def build_controlled_snapshot(
    snapshot: Mapping[str, Any], issue_numbers: Sequence[int]
) -> dict[str, Any]:
    """Return only authorized validation targets; refuse scope expansion."""
    numbers = list(issue_numbers)
    if not 2 <= len(numbers) <= 3 or len(set(numbers)) != len(numbers) or any(n <= 0 for n in numbers):
        raise ValueError("controlled snapshot requires two or three distinct positive issue numbers")

    indexed: dict[int, Mapping[str, Any]] = {}
    for issue in snapshot.get("issues") or []:
        number = int(issue.get("number") or 0)
        if number in numbers:
            if number in indexed:
                raise ValueError(f"controlled issue #{number} appears more than once")
            indexed[number] = issue
    if set(indexed) != set(numbers):
        raise ValueError("one or more controlled issues are missing from the snapshot")

    selected = [indexed[number] for number in numbers]
    lane_keys: set[str] = set()
    for issue in selected:
        number = int(issue["number"])
        labels = _labels(issue)
        body = str(issue.get("body") or "")
        if str(issue.get("state") or "").upper() != "OPEN":
            raise ValueError(f"controlled issue #{number} is not open")
        if not str(issue.get("title") or "").startswith(TITLE_PREFIX):
            raise ValueError(f"controlled issue #{number} lacks the controlled-test title prefix")
        if [value.lower() for value in CONTROLLED_MARKER.findall(body)] != ["true"]:
            raise ValueError(f"controlled issue #{number} lacks the explicit controlled-test marker")
        if "oc-r1-controlled-test" not in labels:
            raise ValueError(f"controlled issue #{number} lacks the isolating test label")
        if labels & PARKED or (("oc-queued" in labels) == ("oc-done" in labels)):
            raise ValueError(f"controlled issue #{number} is not exclusively queued")
        lane, how = assign_lane(issue)
        if (
            how != "declared"
            or lane not in ALLOWED_LANES
            or len(LANE_MARKER.findall(body)) != 1
        ):
            raise ValueError(f"controlled issue #{number} does not declare an allowed non-scientific lane")
        lane_keys.add(lane)

        plan = execution_plan(dict(issue))
        if plan["mode"] != "validate" or plan["commands"] != [VALIDATION_COMMAND]:
            raise ValueError(
                f"controlled issue #{number} must request only the registered "
                f"{VALIDATION_COMMAND} validation command"
            )
        if [value.lower() for value in DISPOSITION_MARKER.findall(body)] != ["done"]:
            raise ValueError(f"controlled issue #{number} must declare done only from validation evidence")
        if [value.lower() for value in MODE_MARKER.findall(body)] != ["validate"]:
            raise ValueError(f"controlled issue #{number} must use the provider-free validation executor")
        if (
            [value.strip().lower() for value in READ_RESOURCE_MARKER.findall(body)]
            != ["control-plane"]
            or WRITE_RESOURCE_MARKER.search(body)
            or infer_resources(dict(issue), lane) != {"reads": ["control-plane"], "writes": []}
        ):
            raise ValueError(
                f"controlled issue #{number} must declare only the control-plane read resource"
            )

    if len(lane_keys) < 2:
        raise ValueError("controlled issue list must exercise at least two independent module lanes")

    number_set = set(numbers)
    for issue in selected:
        number = int(issue["number"])
        if not set(dependencies(dict(issue))) <= number_set:
            raise ValueError(f"controlled issue #{number} depends on an issue outside the allowlist")
    graph = build_dependency_graph([dict(issue) for issue in selected])
    if graph["cycle_nodes"] or any(row.get("error") for row in graph["status"].values()):
        raise ValueError("controlled issue dependency graph is malformed or cyclic")

    isolated = dict(snapshot)
    isolated["issues"] = [dict(issue) for issue in selected]
    isolated["pull_requests"] = []
    return isolated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--issue-numbers", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        with open(args.input, encoding="utf-8") as source:
            snapshot = json.load(source)
        if not isinstance(snapshot, dict):
            raise TypeError("snapshot must be an object")
        isolated = build_controlled_snapshot(snapshot, parse_issue_numbers(args.issue_numbers))
        with open(args.output, "w", encoding="utf-8") as target:
            json.dump(isolated, target, sort_keys=True)
            target.write("\n")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        json.dump({"schema": SCHEMA, "error": str(exc)}, sys.stderr, sort_keys=True)
        sys.stderr.write("\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
