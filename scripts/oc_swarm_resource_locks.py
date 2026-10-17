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

Path-disjoint relaxation
------------------------
Semantic keys are a heuristic: a keyword such as ``control-plane`` or the coarse
lane fallback serializes two tasks even when they touch different files. A
conflict is lifted for one pair of tasks ONLY when every condition holds:

1. every conflicting resource of BOTH claims was *inferred* (keyword inference
   or the lane fallback). A resource from an explicit ``OC-SWARM-READS`` /
   ``OC-SWARM-WRITES`` marker or an ``oc-resource-*`` label stays authoritative
   and is never relaxed, on either side;
2. BOTH tasks run on an executor that enforces the declared paths on every
   write. The controller sets ``path_relaxation_executor`` (on the candidate's
   ranked metadata, and on active lock records) only for governed paid-lane
   coding work, whose executor (``swarm_anthropic_direct``) refuses any write
   outside ``Allowed paths:``. Provider-free (``lane_executable``) workers and
   acquisition workers do NOT enforce the declaration -- their write set is
   verified against resource categories, not the issue's paths -- so they are
   never relaxed. A missing or non-True flag is treated as not enforced;
3. BOTH tasks declare exactly one well-formed ``Allowed paths:`` block
   (``parse_allowed_paths``): at most ``MAX_ALLOWED_PATHS`` entries, each a
   relative POSIX path of plain ``[A-Za-z0-9._-]`` segments, optionally ending
   in ``/``. Absolute paths, ``..``/``.``/empty segments, backslashes, glob
   characters, whitespace, bare ``/`` or ``.``, duplicated declarations and
   oversize sets make the whole set invalid. Any invalid, empty or missing set
   means no relaxation (today's behaviour);
4. no path of one set equals, or is an ancestor or descendant of, a path of the
   other. The test compares whole path segments (``app/a`` vs ``app/ab`` are
   disjoint, ``app/a`` vs ``app/a/b.py`` overlap) and is case-insensitive.

Why this is safe: the paid-lane executor (``swarm_anthropic_direct``) only lets
a worker write files named in its ``Allowed paths:`` and the hosted scope check
rejects anything else, so two such tasks with provably disjoint declared sets cannot write
the same file. The relaxation is evaluated pair-wise against every *conflicting*
held lock, so a candidate must be disjoint from each task it conflicts with.
Active locks that carry no path data (older records) are never relaxed.
Capacity and the paid concurrency cap are untouched and still bound the wave,
and selection order (priority order, greedy) is unchanged and deterministic.

Auditing: pass ``report={}`` to ``select_with_resource_locks`` to receive
``path_disjoint_allowed`` (pairs run together because their paths are disjoint,
with the resources and paths compared) and ``serialized`` (each suppressed task
with, per blocker, a ``path_checks`` row giving the reason the relaxation did not
apply). Selected workers that relied on the relaxation carry
``path_disjoint_allowed`` (the same rows), which the controller records.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

READ_MARKER = re.compile(r"^OC-SWARM-READS:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
WRITE_MARKER = re.compile(r"^OC-SWARM-WRITES:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
RESOURCE_LABEL_PREFIX = "oc-resource-"

MAX_ALLOWED_PATHS = 12
MAX_PATH_LENGTH = 200
_ALLOWED_HEADER = re.compile(r"^\s*Allowed paths:(?P<rest>.*)$", re.IGNORECASE)
# Same item grammar as the executor's parser so both read the same set.
_LIST_PATH = re.compile(
    r"^\s*[-*]\s+(?:`(?P<quoted>[^`]+)`(?:\s.*)?|(?P<bare>[\w./-]+))\s*$"
)
_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
# Set by the controller on a claim whose executor is known to enforce the
# declared ``Allowed paths:`` on every write. Absent or not exactly True means
# not enforced, so the relaxation never applies (fail closed).
EXECUTOR_FLAG = "path_relaxation_executor"
# Claim sources whose conflicts may be lifted by path disjointness.
_INFERRED = ("keyword", "lane")

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


def _infer(issue: dict, lane_id: str = "UNASSIGNED") -> tuple[dict[str, list[str]], str]:
    """Return ``(claim, source)``; source is marker, label, keyword or lane."""
    body = str(issue.get("body") or "")
    explicit_reads = _marker(body, READ_MARKER)
    explicit_writes = _marker(body, WRITE_MARKER)

    if explicit_reads is not None or explicit_writes is not None:
        reads = explicit_reads or []
        writes = explicit_writes or []
        # A write claim dominates a read claim on the same resource.
        reads = [resource for resource in reads if resource not in set(writes)]
        return {"reads": reads, "writes": writes}, "marker"

    label_resources = sorted(
        {
            _normalise_resource(label[len(RESOURCE_LABEL_PREFIX) :])
            for label in _labels(issue)
            if label.startswith(RESOURCE_LABEL_PREFIX)
            and _normalise_resource(label[len(RESOURCE_LABEL_PREFIX) :])
        }
    )
    if label_resources:
        return {"reads": [], "writes": label_resources}, "label"

    text = f"{issue.get('title') or ''} {body}".lower()
    inferred = [resource for resource, patterns in RESOURCE_PATTERNS if any(pattern in text for pattern in patterns)]
    inferred = sorted(set(inferred))
    if inferred:
        # Control-plane changes are intentionally globally exclusive.
        if "control-plane" in inferred:
            return {"reads": [], "writes": ["control-plane"]}, "keyword"
        return {"reads": [], "writes": inferred}, "keyword"

    fallback = f"lane-{str(lane_id or 'UNASSIGNED').lower()}"
    return {"reads": [], "writes": [fallback]}, "lane"


def infer_resources(issue: dict, lane_id: str = "UNASSIGNED") -> dict[str, list[str]]:
    """Return deterministic read/write resources for one issue."""
    return _infer(issue, lane_id)[0]


def _normalise_path(raw: str) -> str | None:
    """A canonical relative POSIX path, or ``None`` when not provably plain."""
    if not isinstance(raw, str) or not raw or len(raw) > MAX_PATH_LENGTH:
        return None
    path = raw.removesuffix("/")
    if not path:  # bare "/"
        return None
    segments = path.split("/")
    for segment in segments:
        if segment in ("", ".", "..") or not _SEGMENT.match(segment):
            return None
    return "/".join(segments)


def parse_allowed_paths(body: str) -> list[str] | None:
    """Strictly parse one ``Allowed paths:`` block; ``None`` fails closed.

    Accepts a bullet list or inline backtick-quoted paths. Anything missing,
    duplicated, empty, malformed, glob-like or larger than
    ``MAX_ALLOWED_PATHS`` yields ``None``.
    """
    lines = str(body or "").splitlines()
    headers = [i for i, line in enumerate(lines) if _ALLOWED_HEADER.match(line)]
    if len(headers) != 1:
        return None
    index = headers[0]
    header = _ALLOWED_HEADER.match(lines[index])
    rest = header.group("rest") if header else ""
    raw: list[str] = []
    if rest.strip():
        quoted = re.findall(r"`([^`]+)`", rest)
        leftover = re.sub(r"`[^`]+`", "", rest)
        if not quoted or re.sub(r"\band\b|[\s,]", "", leftover, flags=re.IGNORECASE):
            return None
        raw = quoted
    else:
        for line in lines[index + 1 :]:
            listed = _LIST_PATH.match(line)
            if not listed:
                break
            raw.append(listed.group("quoted") or listed.group("bare"))
            if len(raw) > MAX_ALLOWED_PATHS:
                return None
    if not raw or len(raw) > MAX_ALLOWED_PATHS:
        return None
    normalised: list[str] = []
    for item in raw:
        path = _normalise_path(item)
        if path is None:
            return None
        normalised.append(path)
    return sorted(set(normalised))


def _paths_overlap(left: str, right: str) -> bool:
    """Equal, ancestor or descendant, compared by whole segments, casefolded."""
    a = left.casefold().split("/")
    b = right.casefold().split("/")
    n = min(len(a), len(b))
    return a[:n] == b[:n]


def _path_check(claim: dict, held: dict, overlap: list[str]) -> dict[str, Any]:
    """Decide whether a resource conflict may be lifted by path disjointness."""
    if claim.get("source") not in _INFERRED or held.get("source") not in _INFERRED:
        return {
            "relaxed": False,
            "reason": "explicit-resource-authoritative:" + ",".join(overlap),
        }
    for who, record in (("candidate", claim), ("blocker", held)):
        if record.get(EXECUTOR_FLAG) is not True:
            return {
                "relaxed": False,
                "reason": f"{who}-executor-does-not-enforce-declared-paths",
            }
    mine, theirs = claim.get("paths"), held.get("paths")
    if not mine:
        return {"relaxed": False, "reason": "candidate-allowed-paths-missing-or-invalid"}
    if not theirs:
        return {"relaxed": False, "reason": "blocker-allowed-paths-missing-or-invalid"}
    for left in mine:
        for right in theirs:
            if _paths_overlap(left, right):
                return {"relaxed": False, "reason": f"paths-overlap:{left}~{right}"}
    return {"relaxed": True, "reason": "allowed-paths-disjoint"}


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
        claim, source = _infer(issue, lane_id)
        records.append(
            {
                "issue_number": int(issue["number"]),
                "lane_id": lane_id,
                **claim,
                "source": source,
                "paths": parse_allowed_paths(str(issue.get("body") or "")),
            }
        )
    return records


def select_with_resource_locks(
    candidates: Iterable[tuple[dict, str, dict]],
    *,
    active_locks: list[dict],
    capacity: int,
    report: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """Greedily select already-priority-ordered candidates without lock conflict.

    ``candidates`` contains ``(issue, lane_id, public_candidate)`` tuples where
    ``public_candidate`` is the canonical scheduler's ranked metadata. A
    resource conflict is lifted only under the path-disjoint rule in the module
    docstring. When ``report`` is a dict it is filled with the audit trail.
    """
    selected: list[dict] = []
    suppressed: list[dict] = []
    allowed_pairs: list[dict] = []
    acquired = list(active_locks)

    for issue, lane_id, public in candidates:
        if len(selected) >= max(0, capacity):
            break
        claim, source = _infer(issue, lane_id)
        paths = parse_allowed_paths(str(issue.get("body") or ""))
        full_claim = {
            **claim,
            "source": source,
            "paths": paths,
            EXECUTOR_FLAG: public.get(EXECUTOR_FLAG) is True,
        }
        blockers = []
        path_checks = []
        relaxed = []
        for held in acquired:
            overlap = conflicts(claim, held)
            if not overlap:
                continue
            check = _path_check(full_claim, held, overlap)
            if check["relaxed"]:
                relaxed.append(
                    {
                        "issue_number": int(issue["number"]),
                        "with_issue_number": held.get("issue_number"),
                        "resources": overlap,
                        "paths": paths,
                        "with_paths": held.get("paths"),
                        "reason": check["reason"],
                    }
                )
                continue
            # ``blockers`` keeps its historical shape; the reason the path
            # relaxation did not apply is recorded beside it.
            blockers.append({"issue_number": held.get("issue_number"), "resources": overlap})
            path_checks.append({"issue_number": held.get("issue_number"), **check})
        if blockers:
            suppressed.append(
                {
                    "issue_number": int(issue["number"]),
                    "lane_id": lane_id,
                    "reason": "resource-lock-conflict",
                    "claim": claim,
                    "blockers": blockers,
                    "path_checks": path_checks,
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
        if relaxed:
            worker["path_disjoint_allowed"] = relaxed
            allowed_pairs.extend(relaxed)
        selected.append(worker)
        acquired.append(
            {
                "issue_number": int(issue["number"]),
                "lane_id": lane_id,
                **full_claim,
            }
        )

    if report is not None:
        report["path_disjoint_allowed"] = allowed_pairs
        report["serialized"] = suppressed
    return selected, suppressed
