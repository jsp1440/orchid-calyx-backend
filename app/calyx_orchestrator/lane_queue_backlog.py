"""Stable seed backlog for the TWO-DAY-COMPLETION-001 rolling lane queue.

This module imports the exact 34-item priority backlog from issue
``#1024`` (TWO-DAY-COMPLETION-001) into :class:`~app.calyx_orchestrator
.lane_queue.BacklogTask` records so :class:`~app.calyx_orchestrator
.lane_queue.RollingLaneQueue` has real, deduplicated, stably-keyed data
to schedule instead of a placeholder set.

Each ``task_key`` is a short stable slug (``two-day-001`` .. ``two-day-034``)
that mirrors the issue's own numbered ordering, so a task's position here
always matches its position in the issue body. ``priority`` is derived
from that same order (``1000 - position``) so P0 items outrank P1, P1
outranks P2, and so on, exactly as the issue's tiering (P0/P1/P2/P3/P4)
requires -- ties are impossible because every item has a distinct order.

``refs`` records the canonical GitHub issues/PRs the item is already
tracked against, per the issue's explicit instruction to "link existing
canonical issues/PRs rather than duplicating them." No dependency edges
are encoded here: the issue text describes tier admission ("P1 -- admit
as P0 slots free") and thematic prerequisites in prose, not a verified
directed acyclic graph, and inventing one would risk fabricating a
constraint the issue never actually asserted. Priority ordering alone
already reproduces the requested admission behavior in a
:class:`RollingLaneQueue`: higher tiers are always admitted first, and
lower tiers only fill lanes once a higher-tier item leaves ``QUEUED``
(active, owner-gated, blocked, or verified).
"""

from __future__ import annotations

from .lane_queue import BacklogTask, RollingLaneQueue

#: (task_key suffix, title, GitHub refs) in the exact order of issue #1024's
#: "Priority backlog" section. Position in this tuple is the sole source of
#: both ``created_order`` and ``priority``.
_TWO_DAY_BACKLOG_ITEMS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("audit-data-integration-convergence", "Audit/data-integration convergence", ("#1020",)),
    ("audit-followthrough", "Audit automatic follow-through", ("#1022", "#1025")),
    ("event-driven-continuation", "Event-driven continuation", ("#1023",)),
    ("literature-kg-orchestration", "Literature->KG orchestration", ("#1021", "#901", "#1026")),
    ("living-atlas-convergence", "Living Atlas convergence", ("#196",)),
    ("featured-genus-convergence", "Featured Genus / Genus of the Day convergence", ("#195",)),
    ("homepage-completion", "Homepage completion", ("#179", "#194", "#195")),
    ("calyx-workspace-completion", "Calyx workspace completion", ("#117", "#120", "#121", "#122", "#123", "#124", "#125", "#126", "#151", "#152", "#893")),
    ("research-station-vertical-demo", "Research Station vertical demo", ()),
    ("matrix-identification-completion", "Matrix Identification completion", ("#135",)),
    ("kg-materialization-readiness", "Knowledge Graph materialization readiness", ("#901",)),
    ("literature-corpus-source-correction", "Literature corpus source correction", ()),
    ("occurrence-corpus-source-correction", "Occurrence corpus source correction", ()),
    ("trait-integration", "Trait integration", ()),
    ("pollinator-integration", "Pollinator integration", ("#1029",)),
    ("mycorrhizal-integration", "Mycorrhizal integration", ("#1029",)),
    ("habitat-integration", "Habitat integration", ()),
    ("elevation-environment-integration", "Elevation/environment integration", ()),
    ("conservation-integration", "Conservation integration", ()),
    ("image-media-integration", "Image/media integration", ()),
    ("harvester-productivity-dashboard", "Harvester Productivity dashboard", ("#1008", "#197", "#1033")),
    ("harvester-canonicalization", "Harvester canonicalization", ()),
    ("literature-federation-expansion", "Literature federation expansion", ()),
    ("occurrence-federation-expansion", "Occurrence federation expansion", ()),
    ("trait-federation-expansion", "Trait federation expansion", ()),
    ("interaction-federation-expansion", "Interaction federation expansion", ()),
    ("mycorrhiza-genetics-federation-expansion", "Mycorrhiza/genetics federation expansion", ()),
    ("conservation-federation-expansion", "Conservation federation expansion", ()),
    ("image-federation-expansion", "Image federation expansion", ()),
    ("atlas-guided-tours", "Atlas guided tours", ()),
    ("mission-control-owner-dashboard", "Mission Control owner dashboard", ()),
    ("end-to-end-demo-script", "End-to-end demo script", ()),
    ("production-readiness-smoke-suite", "Production readiness smoke suite", ()),
    ("two-day-final-evidence-packet", "Two-day final evidence packet", ()),
)

TWO_DAY_BACKLOG_TASKS: tuple[BacklogTask, ...] = tuple(
    BacklogTask(
        task_key=f"two-day-{index + 1:03d}-{suffix}",
        title=title,
        priority=1000 - index,
        created_order=index,
    )
    for index, (suffix, title, _refs) in enumerate(_TWO_DAY_BACKLOG_ITEMS)
)

#: task_key -> canonical GitHub issue/PR references, kept separate from
#: BacklogTask (which RollingLaneQueue treats as opaque scheduling data)
#: so callers can render "linked to #1020" without the engine needing to
#: know anything about GitHub.
TWO_DAY_BACKLOG_REFS: dict[str, tuple[str, ...]] = {
    f"two-day-{index + 1:03d}-{suffix}": refs
    for index, (suffix, _title, refs) in enumerate(_TWO_DAY_BACKLOG_ITEMS)
}

def build_two_day_lane_queue(*, width: int = 5) -> RollingLaneQueue:
    """Construct a :class:`RollingLaneQueue` seeded with the #1024 backlog."""

    return RollingLaneQueue(list(TWO_DAY_BACKLOG_TASKS), width=width)
