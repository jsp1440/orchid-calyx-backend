"""Independently replenishable module lanes (R1 Parallel Module Autonomy).

The portfolio scheduler's L1-L5 lanes bound concurrency. These module lanes are
the finer unit R1 reasons about: each Orchid Continuum module has its own queue,
its own gates and its own next mission, and the state of one never decides the
state of another. If Atlas is gated, Literature still has a next mission; if a
lane needs a coding executor nobody is authorised to run, the others continue.

This layer is pure and read-only. It classifies and reports; it does not select
slots, label issues or call a provider, so it cannot starve or overrule the
scheduler. An issue belongs to a lane only by explicit declaration
(``oc-lane:<key>`` label or ``OC-MODULE-LANE: <key>`` marker) or by a single
unambiguous title keyword; anything else is ``unassigned`` and is reported as
such rather than guessed into a lane.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

#: Mirror ``oc_portfolio_scheduler.OWNER_GATE`` / ``SCIENTIFIC_GATE``. Kept local so
#: this module stays importable on its own; a test pins them to the scheduler.
OWNER_GATE_LABELS = frozenset({"oc-owner-gate", "blocked-on-owner"})
SCIENTIFIC_GATE_LABELS = frozenset({"oc-scientific-gate"})

SCHEMA = "oc.module-lanes.v1"
UNASSIGNED = "unassigned"
LANE_LABEL_PREFIX = "oc-lane:"
_MARKER = re.compile(r"^OC-MODULE-LANE:\s*([a-z0-9][a-z0-9-]*)\s*$", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class ModuleLane:
    key: str
    name: str
    keywords: tuple[str, ...]
    #: Whether the lane's typical work needs code authored by a coding executor.
    typical_executor: str = "mixed"


MODULE_LANES: tuple[ModuleLane, ...] = (
    ModuleLane("brain-cognitive-integration", "Brain / Cognitive Integration",
               ("brain", "reasoning", "cognitive")),
    ModuleLane("taxonomy", "Taxonomy", ("taxonomy", "taxon", "hassler")),
    ModuleLane("atlas-geography-environment", "Atlas / geography / environment",
               ("atlas", "geograph", "habitat", "environment", "elevation")),
    ModuleLane("literature", "Literature", ("literature", "doi", "citation")),
    ModuleLane("matrix-id", "Matrix ID", ("matrix",)),
    ModuleLane("pollinator", "Pollinator", ("pollinator", "pollination")),
    ModuleLane("mycorrhiza", "Mycorrhiza", ("mycorrhiza", "mycorrhizal", "fungus", "fungi")),
    ModuleLane("interaction-knowledge-graph", "Interaction / Knowledge Graph",
               ("knowledge graph", "interaction", "graph")),
    ModuleLane("image-taxonomy", "Image & Taxonomy", ("image", "vision", "photo")),
    ModuleLane("conservation", "Conservation", ("conservation", "cites", "iucn")),
    ModuleLane("research-station", "Research Station", ("research station", "workspace")),
    ModuleLane("university-education", "University / Education",
               ("university", "education", "curriculum", "course")),
    ModuleLane("featured-genus", "Featured Genus", ("featured genus", "featured-genus")),
    ModuleLane("calyx-education-intelligence", "Calyx / Education & Experience Intelligence",
               ("calyx-intel", "calyx education", "calyx advisory")),
    ModuleLane("frontend-ux", "Frontend / UX", ("frontend", "ux", "accessibility", "ui ")),
    ModuleLane("infrastructure-federation", "Infrastructure / federation",
               ("infrastructure", "federation", "workflow", "controller", "swarm")),
)

LANES_BY_KEY: dict[str, ModuleLane] = {lane.key: lane for lane in MODULE_LANES}

REQUIRED_LANE_KEYS: tuple[str, ...] = tuple(LANES_BY_KEY)

#: ``oc-lane:<key>`` is also the label work discovery files under
#: (``scripts/oc_product_lanes.py``), so issues arrive carrying those keys. A key is
#: translated only where it names one module lane unambiguously. The rest are known
#: product-lane keys with no single module lane; they stay ``unassigned`` (never
#: guessed) but are counted by declared key so they are visible, not silently lost.
PRODUCT_LANE_ALIASES: dict[str, str] = {
    "literature": "literature",
    "matrix-id": "matrix-id",
    "research-station": "research-station",
    "university-education": "university-education",
    "atlas": "atlas-geography-environment",
    "interaction-graph": "interaction-knowledge-graph",
}
PRODUCT_LANE_UNMAPPED: frozenset[str] = frozenset(
    {"calyx", "lexicon", "vision-lab", "improvement-discovery", "platform"}
)

_DONE = frozenset({"oc-done"})
#: Only ``oc-running`` is an execution lease. The portfolio scheduler counts nothing
#: else against capacity: ``oc-validating`` never consumes a lane, and an
#: ``oc-queued`` + ``oc-repair`` issue is eligible repair work, not running work.
_RUNNING = frozenset({"oc-running"})
_VALIDATING = frozenset({"oc-validating"})
_HELD = frozenset({"oc-blocked", "oc-runtime-backoff", "oc-repair-backoff"})


def _names(issue: Mapping[str, Any]) -> set[str]:
    return {
        label if isinstance(label, str) else str(label.get("name"))
        for label in issue.get("labels") or []
    }


def _is_open(issue: Mapping[str, Any]) -> bool:
    return str(issue.get("state") or "OPEN").upper() == "OPEN"


def declared_keys(issue: Mapping[str, Any]) -> list[str]:
    """Every lane key the issue declares, by ``oc-lane:`` label or body marker."""
    declared = sorted(
        name[len(LANE_LABEL_PREFIX):] for name in _names(issue) if name.startswith(LANE_LABEL_PREFIX)
    )
    declared += [m.lower() for m in _MARKER.findall(str(issue.get("body") or ""))]
    return declared


def assign_lane(issue: Mapping[str, Any]) -> tuple[str, str]:
    """Return ``(lane_key, how)``; ``how`` is ``declared``, ``inferred`` or ``none``.

    An explicit declaration that names no registered lane fails closed to
    ``unassigned``; it is never re-inferred from the title, because the author
    said something specific and wrong, not nothing. Established product-lane keys
    are translated through ``PRODUCT_LANE_ALIASES`` where the match is unambiguous.
    """
    distinct = set(declared_keys(issue))
    if distinct:
        if len(distinct) == 1:
            key = next(iter(distinct))
            key = PRODUCT_LANE_ALIASES.get(key, key)
            if key in LANES_BY_KEY:
                return key, "declared"
        return UNASSIGNED, "none"
    title = f" {str(issue.get('title') or '').lower()} "
    hits = {
        lane.key for lane in MODULE_LANES if any(keyword in title for keyword in lane.keywords)
    }
    if len(hits) == 1:
        return next(iter(hits)), "inferred"
    return UNASSIGNED, "none"


def _gate_for(issue: Mapping[str, Any], *, dependency_blocked: bool, provider_gated: bool) -> str | None:
    names = _names(issue)
    if names & SCIENTIFIC_GATE_LABELS:
        return "scientific_gated"
    if names & OWNER_GATE_LABELS:
        return "owner_gated"
    if names & _HELD:
        return "held"
    if dependency_blocked:
        return "dependency_blocked"
    if provider_gated:
        return "provider_blocked"
    return None


def lane_report(
    issues: Iterable[Mapping[str, Any]],
    *,
    dependency_blocked: Iterable[int] = (),
    provider_gated: Iterable[int] = (),
    capability_gap: Iterable[int] = (),
    lane_refusals: Iterable[Mapping[str, Any]] = (),
    coding_dispatch: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Per-lane state computed from that lane's own issues only.

    Lane state, in order: ``executing`` (work is running), ``replenishable`` (an
    ungated queued mission exists), ``gated`` (unfinished work exists but every
    item carries a named gate), ``capability_gap`` (only unstaffed work remains),
    ``validating`` (only work in ``oc-validating`` remains, which holds no execution
    lane), ``empty`` (nothing unfinished: discovery should replenish). ``empty`` is
    never reported healthy here; whether idle is healthy is the controller's
    homeostasis verdict, which also needs discovery evidence.

    Optional refusal and coding-dispatch records preserve planner reasons.
    Dispatch records describe admission gates, never execution or certification.
    A queued dispatch record cannot override an existing refusal or human gate.
    """
    dep = {int(n) for n in dependency_blocked}
    prov = {int(n) for n in provider_gated}
    gap = {int(n) for n in capability_gap}
    reasons = {int(r["issue_number"]): r["reason"] for r in lane_refusals}
    coding_gates = {}
    for record in coding_dispatch:
        state = record["state"]
        if state in {"provider_blocked", "dependency_blocked", "owner_gated", "scientific_gated"}:
            coding_gates[int(record["issue_number"])] = state
        elif state == "capability_gap":
            gap.add(int(record["issue_number"]))
        if state in {"provider_blocked", "dependency_blocked", "owner_gated",
                     "scientific_gated", "capability_gap"}:
            reasons[int(record["issue_number"])] = record["gate"]
    buckets: dict[str, list[dict[str, Any]]] = {key: [] for key in LANES_BY_KEY}
    buckets[UNASSIGNED] = []
    for issue in issues:
        if not _is_open(issue):
            continue
        names = _names(issue)
        if names & _DONE:
            continue
        lane, how = assign_lane(issue)
        number = int(issue.get("number") or 0)
        row = {"number": number, "how": how, "gate": None, "running": bool(names & _RUNNING),
               "validating": bool(names & _VALIDATING) and not names & _RUNNING,
               "queued": "oc-queued" in names, "gap": number in gap,
               "declared": declared_keys(issue)}
        row["gate"] = _gate_for(issue, dependency_blocked=number in dep, provider_gated=number in prov)
        if row["gate"] is None:
            row["gate"] = coding_gates.get(number)
        buckets[lane].append(row)

    lanes: dict[str, dict[str, Any]] = {}
    for key, rows in buckets.items():
        running = [r["number"] for r in rows if r["running"]]
        replenishable = [r["number"] for r in rows if r["queued"] and not r["gate"] and not r["gap"]
                         and not r["running"]]
        gated: dict[str, list[int]] = {}
        for r in rows:
            if r["gate"]:
                gated.setdefault(r["gate"], []).append(r["number"])
        gaps = [r["number"] for r in rows if r["gap"] and not r["gate"]]
        validating = [r["number"] for r in rows if r["validating"]]
        if running:
            state = "executing"
        elif replenishable:
            state = "replenishable"
        elif gated:
            state = "gated"
        elif gaps:
            state = "capability_gap"
        elif validating:
            state = "validating"
        else:
            state = "empty"
        lanes[key] = {
            "state": state,
            "running": sorted(running),
            "next_mission": min(replenishable) if replenishable else None,
            "replenishable": sorted(replenishable),
            "gates": {gate: sorted(nums) for gate, nums in sorted(gated.items())},
            "capability_gap": sorted(gaps),
            "validating": sorted(validating),
            "refusal_reasons": [
                {"issue": r["number"], "reason": reasons[r["number"]]}
                for r in sorted(rows, key=lambda r: r["number"])
                if r["number"] in reasons and (r["gate"] or r["gap"])
            ],
            "unfinished": len(rows),
        }
    return {
        "schema": SCHEMA,
        "lanes": lanes,
        "summary": {
            state: sorted(k for k, v in lanes.items() if k != UNASSIGNED and v["state"] == state)
            for state in (
                "executing", "replenishable", "gated", "capability_gap", "validating", "empty"
            )
        },
        "unassigned_unfinished": lanes[UNASSIGNED]["unfinished"],
        "unassigned_by_declared_key": _declared_counts(buckets[UNASSIGNED]),
    }


def _declared_counts(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Unassigned work grouped by the lane key it declared, so it stays visible."""
    counts: dict[str, int] = {}
    for row in rows:
        for key in sorted(set(row["declared"])):
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def report_from_plan(snapshot: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    """Observe canonical admission output without re-routing or authorizing it.

    Selection is planning evidence only. Running state still comes from issue
    labels in the supplied snapshot, not workers, matrices or coding receipts.
    """
    gates = plan["homeostasis"]["gates"]
    report = lane_report(
        snapshot.get("issues") or [],
        dependency_blocked=[row["issue"] for row in gates.get("dependency_blocked", [])],
        provider_gated=gates.get("provider_parked", []),
        capability_gap=gates.get("lane_refused", []),
        lane_refusals=[
            {"issue_number": row["issue"], "reason": row["reason"]}
            for row in gates.get("lane_refusal_reasons", [])
        ],
        coding_dispatch=plan.get("coding_dispatch", []),
    )
    selected = set(plan["selected_numbers"])
    for lane in report["lanes"].values():
        lane["planned"] = []
    for issue in snapshot.get("issues") or []:
        number = int(issue["number"])
        if number in selected:
            key, _ = assign_lane(issue)
            report["lanes"][key]["planned"].append(number)
    for lane in report["lanes"].values():
        lane["planned"].sort()
    report["evidence_category"] = "planning_and_issue_labels"
    return report
