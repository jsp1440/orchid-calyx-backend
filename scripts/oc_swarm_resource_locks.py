#!/usr/bin/env python3
"""Deterministic resource locking for Orchid Continuum swarm execution.

The first swarm controller bounded concurrency by the five coarse product lanes.
This module adds finer-grained resource claims so independent work within the
same coarse lane can run concurrently without allowing overlapping write sets.

Lock semantics
--------------
* write/write conflicts block;
* read/write conflicts block;
* read/read is allowed;
* explicit issue markers win over inferred resources;
* unclassified work falls back to an exclusive coarse-lane resource;
* protected/global control-plane work uses an exclusive ``control-plane`` lock;
* the planner is pure and provider-free; GitHub mutation is handled elsewhere.

Issue authors may provide stable machine-readable markers in the body:

    OC-SWARM-READS: taxonomy, literature
    OC-SWARM-WRITES: atlas, geospatial

or labels of the form ``oc-resource-<name>`` (treated as writes unless an
explicit marker says otherwise).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

READ_MARKER = re.compile(r"^OC-SWARM-READS:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
WRITE_MARKER = re.compile(r"^OC-SWARM-WRITES:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
RESOURCE_LABEL_PREFIX = "oc-resource-"

# Stable resource vocabulary. Unknown explicit resources are accepted after
# normalization so a new subsystem does not require a controller release.
RESOURCE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("control-plane", ("orchestrat", "scheduler", "dispatch", "queue", "worker", "swarm", "provider", "canary", "ci ", "github actions", "github-actions")),
    ("taxonomy", ("taxonomy", "hassler", "world orchids", "world-orchids", "accepted name", "synonym")),
    ("occurrence", ("occurrence", "gbif", "idigbio", "inat", "inaturalist", "distribution")),
    ("literature", ("literature", "document intelligence", "citation", "bibliograph", "provenance resolver", "source binding")),
    ("images", ("image", "vision", "media", "photo")),
    ("molecular", ("molecular", "genbank", "sequence", "accession", "its ", "dna")),
    ("habitat", ("habitat", "elevation", "climate", "environment")),
    ("geospatial", ("geospatial", "mapbox", "google earth", "coordinate", "locality", "mapping")),
    ("atlas", ("atlas", "tour", "planetary")),
    ("knowledge-graph", ("knowledge graph", "knowledge_graph", "kg ", "materialization", "graph edge")),
    ("brain-reasoning", ("brain", "reasoning", "synthesis", "calyx", "cognitive loop")),
    ("scientific-memory", ("scientific memory", "memory ledger", "ledger", "remember")),
    ("research-station", ("research station", "research executor", "research-executor")),
    ("frontend-api", ("frontend", "operator ui", "browser", "api route", "router", "showos", "show companion")),
    ("security-observability", ("security", "observability", "telemetry", "sbom", "zero-day", "audit")),
    ("pollinator", ("pollinator", "pollination")),
    ("mycorrhiza", ("mycorrhiza", "fungal")),
    ("traits", ("trait", "phenotype")),
    ("conservation", ("conservation", "iucn", "cites")),
)


def _labels(issue: dict) -> list[str]:
    result: list[str] = []
    for label in issue.get("labels") or []:
        if isinstance(label, str):
            result.append(label)
        elif isinstance(label, dict) and label.get("name"):
            result.append(str(label["name"]))
    return result


def _normalise_resource(value: str) -> str:
    value = value.strip().lower().replace("_", "-")
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value


def _split_resources(raw: str) -> list[str]:
    values = [_normalise_resource(part) for part in raw.split(",")]
    return sorted({value for value in values if value})


def _marker(body: str, regex: re.Pattern[str]) -> list[str] | None:
    match = regex.search(body or "")
    if not match:
        return None
    return _split_resources(match.group(1))


def infer_resources(issue: dict, lane_id: str = "UNASSIGNED") -> dict[str, list[str]]:
    """Return deterministic read/write resources for one issue."""
    body = str(issue.get("body") or "")
    explicit_reads = _marker(body, READ_MARKER)
    explicit_writes = _marker(body, WRITE_MARKER)

    if explicit_reads is not None or explicit_writes is not None:
        reads = explicit_reads or []
        writes = explicit_writes or []
        # A write claim dominates a read claim on the same resource.
        reads = [resource for resource in reads if resource not in set(writes)]
        return {"reads": reads, "writes": writes}

    label_resources = sorted(
        {
            _normalise_resource(label[len(RESOURCE_LABEL_PREFIX) :])
            for label in _labels(issue)
            if label.startswith(RESOURCE_LABEL_PREFIX)
            and _normalise_resource(label[len(RESOURCE_LABEL_PREFIX) :])
        }
    )
    if label_resources:
        return {"reads": [], "writes": label_resources}

    text = f"{issue.get('title') or ''} {body}".lower()
    inferred = [resource for resource, patterns in RESOURCE_PATTERNS if any(pattern in text for pattern in patterns)]
    inferred = sorted(set(inferred))
    if inferred:
        # Control-plane changes are intentionally globally exclusive.
        if "control-plane" in inferred:
            return {"reads": [], "writes": ["control-plane"]}
        return {"reads": [], "writes": inferred}

    fallback = f"lane-{str(lane_id or 'UNASSIGNED').lower()}"
    return {"reads": [], "writes": [fallback]}


def conflicts(left: dict[str, list[str]], right: dict[str, list[str]]) -> list[str]:
    """Return resources that make two claims mutually exclusive."""
    left_reads = set(left.get("reads") or [])
    left_writes = set(left.get("writes") or [])
    right_reads = set(right.get("reads") or [])
    right_writes = set(right.get("writes") or [])
    return sorted(
        (left_writes & right_writes)
        | (left_writes & right_reads)
        | (left_reads & right_writes)
    )


def held_locks(active_issues: Iterable[tuple[dict, str]]) -> list[dict[str, Any]]:
    """Build lock records from active issues and their canonical lane IDs."""
    records: list[dict[str, Any]] = []
    for issue, lane_id in active_issues:
        if issue.get("number") is None:
            continue
        records.append(
            {
                "issue_number": int(issue["number"]),
                "lane_id": lane_id,
                **infer_resources(issue, lane_id),
            }
        )
    return records


def select_with_resource_locks(
    candidates: Iterable[tuple[dict, str, dict]],
    *,
    active_locks: list[dict],
    capacity: int,
) -> tuple[list[dict], list[dict]]:
    """Greedily select already-priority-ordered candidates without lock conflict.

    ``candidates`` contains ``(issue, lane_id, public_candidate)`` tuples where
    ``public_candidate`` is the canonical scheduler's ranked metadata.
    """
    selected: list[dict] = []
    suppressed: list[dict] = []
    acquired = list(active_locks)

    for issue, lane_id, public in candidates:
        if len(selected) >= max(0, capacity):
            break
        claim = infer_resources(issue, lane_id)
        blockers = []
        for held in acquired:
            overlap = conflicts(claim, held)
            if overlap:
                blockers.append(
                    {
                        "issue_number": held.get("issue_number"),
                        "resources": overlap,
                    }
                )
        if blockers:
            suppressed.append(
                {
                    "issue_number": int(issue["number"]),
                    "lane_id": lane_id,
                    "reason": "resource-lock-conflict",
                    "claim": claim,
                    "blockers": blockers,
                }
            )
            continue

        worker = {
            **public,
            "issue_number": int(issue["number"]),
            "lane_id": lane_id,
            "reads": claim["reads"],
            "writes": claim["writes"],
        }
        selected.append(worker)
        acquired.append(
            {
                "issue_number": int(issue["number"]),
                "lane_id": lane_id,
                **claim,
            }
        )

    return selected, suppressed
