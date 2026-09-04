#!/usr/bin/env python3
"""Orchid Continuum work-lane manifest.

Produces a machine-readable status of the five canonical execution lanes
(defined in AGENTS.md) plus cross-cutting domain bands. The scheduler
(orchid-continuous-completion.yml) uses ``oc-queued`` labels for dispatch;
this manifest provides a human-readable and CI-readable view of how queued
work maps to lanes, what is blocked, and what is ready.

Run:
    python3 scripts/oc_lane_manifest.py

Or import ``build_lane_manifest(snapshot)`` where ``snapshot`` is a JSON
object from ``gh issue list --json number,title,labels,state``.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import Any

SCHEMA_VERSION = "oc-lane-manifest/v1"

# Five canonical execution lanes from AGENTS.md.
LANES: list[dict[str, Any]] = [
    {
        "lane_id": "L1",
        "name": "Brain / Reasoning Ledger",
        "description": "Brain mission, Reasoning Ledger integration, scientific-memory contracts.",
        "keyword_patterns": [
            "brain", "reasoning", "ledger", "synthesis", "calyx-synthesis",
            "calyx-recovery", "calyx-superstructure", "meta-orchestrator",
            "research-executor", "calyx-gh-research",
        ],
    },
    {
        "lane_id": "L2",
        "name": "Taxonomy / Occurrence",
        "description": "Taxonomy pipelines, occurrence ingestion, Hassler release lifecycle.",
        "keyword_patterns": [
            "taxonomy", "occurrence", "hassler", "oc-complete-002", "oc-complete-003",
            "coverage", "backfill", "world-orchids", "gbif",
        ],
    },
    {
        "lane_id": "L3",
        "name": "Images / Literature / Science",
        "description": "Licensed images, literature pipelines, pollination, mycorrhiza, traits.",
        "keyword_patterns": [
            "literature", "image", "media", "pollination", "pollinator",
            "mycorrhiza", "trait", "federation", "source", "corpus",
            "oc-complete-004", "oc-complete-009", "interaction", "science",
        ],
    },
    {
        "lane_id": "L4",
        "name": "Operator UI / API / Frontend",
        "description": "Operator interfaces, browser/API certification, show management, Atlas.",
        "keyword_patterns": [
            "ui", "frontend", "show", "atlas", "vision", "matrix", "glossary",
            "oc-complete-007", "oc-complete-008", "api", "browser", "calyx-verify",
        ],
    },
    {
        "lane_id": "L5",
        "name": "Deployment / Observability / Orchestration",
        "description": "Deployment QA, CI, provider routing, event dispatch, cost controls.",
        "keyword_patterns": [
            "deploy", "ci", "provider", "canary", "dispatch", "event", "orchestrat",
            "scheduler", "cost", "budget", "economy", "oc-cost", "oc-runtime",
            "orchestration-event", "calyx-evolve",
        ],
    },
]

# Label states used by the orchestrator.
LABEL_STATES = {
    "oc-running": "ACTIVE",
    "oc-validating": "WAITING_VALIDATION",
    "oc-queued": "READY",
    "oc-repair": "READY",
    "oc-blocked": "BLOCKED",
    "oc-repair-backoff": "BLOCKED",
    "oc-runtime-backoff": "BLOCKED",
    "oc-owner-gate": "WAITING_EXTERNAL",
    "oc-done": "COMPLETE",
}

# Label order for precedence when an issue has multiple orchestrator labels.
_LABEL_PRECEDENCE = [
    "oc-running", "oc-validating", "oc-repair", "oc-queued",
    "oc-repair-backoff", "oc-runtime-backoff", "oc-blocked",
    "oc-owner-gate", "oc-done",
]


def _label_names(issue: dict) -> list[str]:
    names = []
    for label in issue.get("labels") or []:
        if isinstance(label, str):
            names.append(label)
        elif isinstance(label, dict) and label.get("name"):
            names.append(str(label["name"]))
    return names


def _orchestrator_state(labels: list[str]) -> str:
    for key in _LABEL_PRECEDENCE:
        if key in labels:
            return LABEL_STATES.get(key, "UNKNOWN")
    return "UNKNOWN"


def _classify_lane(issue: dict) -> str:
    title_lower = (issue.get("title") or "").lower()
    body_lower = (issue.get("body") or "").lower()
    text = title_lower + " " + body_lower
    for lane in LANES:
        for pattern in lane["keyword_patterns"]:
            if pattern.lower() in text:
                return lane["lane_id"]
    return "UNASSIGNED"


def build_lane_manifest(issues: Sequence[dict]) -> dict[str, Any]:
    """Build a lane status manifest from a list of GitHub issues."""
    lane_map: dict[str, dict[str, Any]] = {}
    for lane in LANES:
        lane_map[lane["lane_id"]] = {
            "lane_id": lane["lane_id"],
            "name": lane["name"],
            "description": lane["description"],
            "active_task": None,
            "next_eligible": None,
            "blocked_count": 0,
            "ready_count": 0,
            "validating_count": 0,
            "completed_count": 0,
            "tasks": [],
        }
    unassigned: list[dict] = []

    for issue in issues:
        labels = _label_names(issue)
        state = _orchestrator_state(labels)
        lane_id = _classify_lane(issue)
        priority = next((lbl for lbl in labels if lbl.startswith("oc-p")), None)
        row = {
            "number": issue.get("number"),
            "title": issue.get("title") or "",
            "state": state,
            "lane": lane_id,
            "priority": priority,
        }
        if lane_id in lane_map:
            entry = lane_map[lane_id]
            entry["tasks"].append(row)
            if state == "ACTIVE" and entry["active_task"] is None:
                entry["active_task"] = row
            elif state == "READY" and entry["next_eligible"] is None:
                entry["next_eligible"] = row
            if state == "BLOCKED":
                entry["blocked_count"] += 1
            elif state in ("READY",):
                entry["ready_count"] += 1
            elif state == "WAITING_VALIDATION":
                entry["validating_count"] += 1
            elif state == "COMPLETE":
                entry["completed_count"] += 1
        else:
            unassigned.append(row)

    all_states = (
        [t["state"] for lane in lane_map.values() for t in lane["tasks"]]
        + [t["state"] for t in unassigned]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
        "lanes": list(lane_map.values()),
        "unassigned": unassigned,
        "summary": {
            "total_issues": len(issues),
            "active": all_states.count("ACTIVE"),
            "ready": all_states.count("READY"),
            "blocked": all_states.count("BLOCKED"),
            "validating": all_states.count("WAITING_VALIDATION"),
            "complete": all_states.count("COMPLETE"),
            "unassigned": len(unassigned),
        },
    }


def main() -> int:
    data = json.load(sys.stdin)
    issues = data if isinstance(data, list) else data.get("issues", [])
    manifest = build_lane_manifest(issues)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
