"""Exact-release lifecycle status for the Hassler / World Plants taxonomy release.

The frontend consumer (`src/lib/hasslerReleaseLifecycle.ts`) was written against
this producer, but the producer was never implemented, so the Mission Control
taxonomy panel had nothing to read. This module supplies it.

What this reports
-----------------
One question, about one release: where is ``WorldOrchids 26-08 (Aug 2 2026).csv``
in the lifecycle that `AGENTS.md` defines?

    upload -> checksum/release record -> schema validation -> normalization
    -> comparison -> reviewed change report -> bounded staging projection
    -> idempotency proof -> owner-approved activation -> species API verification

Reporting rules
---------------
*It never promotes anything.* This is a read-only observation surface. The
payload states ``read_only`` and ``automatic_promotion: false`` as facts the
panel renders, and nothing here can upload, stage, activate, or publish.

*It distinguishes "not there" from "could not look".* ``ABSENT`` is a finding:
the inventory was read and the release is not in it. ``UNAVAILABLE`` means the
evidence could not be read at all. Collapsing the second into the first would
assert the release is missing when we simply do not know, which is the kind of
fabricated production state the governance rules forbid.

*It reports the highest state it can actually establish, and says what it could
not read.* When a later-stage evidence source is unreachable, the state is not
silently promoted or demoted: the established state stands, ``unavailable_evidence``
names every source that failed, and ``evidence_complete`` goes false.

*It never invents a count.* A downstream relink count appears only when it was
observed. Anything else is withheld, because a confident ``0`` would read as
"no downstream work" when the truth is "nobody counted".
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

SCHEMA = "oc.hassler-release-lifecycle.v1"

# The ladder, lowest to highest. Mirrored by HASSLER_LIFECYCLE_STATES in the
# frontend consumer; the payload echoes it so the panel renders the same order.
LIFECYCLE_STATES: tuple[str, ...] = (
    "UNAVAILABLE",
    "ABSENT",
    "UPLOADED_INSPECTED",
    "SMOKE_VERIFIED",
    "STAGING_IN_PROGRESS",
    "STAGED_COMPLETE",
    "SUPERSEDED",
    "ACTIVATED",
)

# The real acceptance target named in AGENTS.md. Not a fixture.
EXPECTED_FILENAME = "WorldOrchids 26-08 (Aug 2 2026).csv"
EXPECTED_VERSION_LABEL = "WorldOrchids 26-08"

# Surfaces that a taxonomy relink would touch. Declaring them is a statement
# about scope, not about how much work each one implies; the counts are
# reported separately and only when observed.
RELINK_SURFACES: tuple[str, ...] = (
    "species_api",
    "knowledge_graph",
    "matrix_identification",
    "atlas_occurrences",
    "lexicon_concepts",
)

_INSPECTED_STATES = frozenset({"inspected", "uploaded", "stored"})


@dataclass(frozen=True, slots=True)
class ReleaseObservation:
    """Everything the pipeline could read, and everything it could not.

    A ``None`` collection means "could not read", which is deliberately
    different from an empty collection meaning "read it, found nothing".
    """

    releases: tuple[dict[str, Any], ...] | None = None
    inventory_error: str | None = None
    staging: dict[str, Any] | None = None
    staging_error: str | None = None
    active_release_id: str | None = None
    active_error: str | None = None
    relink_counts: dict[str, int] | None = None
    relink_error: str | None = None
    storage_backend: str | None = None

    @property
    def unavailable_evidence(self) -> list[str]:
        missing: list[str] = []
        if self.inventory_error:
            missing.append(f"release_inventory:{self.inventory_error}")
        if self.staging_error:
            missing.append(f"staging_projection:{self.staging_error}")
        if self.active_error:
            missing.append(f"active_release_pointer:{self.active_error}")
        if self.relink_error:
            missing.append(f"downstream_relink_counts:{self.relink_error}")
        return missing


# ---------------------------------------------------------------------------
# Matching the one exact release
# ---------------------------------------------------------------------------


def _snapshot_of(report: dict[str, Any]) -> dict[str, Any]:
    snapshot = report.get("snapshot")
    return snapshot if isinstance(snapshot, dict) else {}


def _normalize(value: Any) -> str:
    return str(value or "").strip().casefold()


def matches_expected_release(report: dict[str, Any]) -> bool:
    """Is this report the exact acceptance-target release?

    Matches on filename or version label. A release uploaded under a tidied-up
    filename but the right version label is still the same release, and
    refusing to recognize it would report ABSENT for something that is present.
    """
    snapshot = _snapshot_of(report)
    filename = _normalize(snapshot.get("filename") or report.get("filename"))
    version = _normalize(snapshot.get("version_label") or report.get("version_label"))
    if filename and filename == _normalize(EXPECTED_FILENAME):
        return True
    return bool(version) and version == _normalize(EXPECTED_VERSION_LABEL)


def find_expected_release(
    releases: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> dict[str, Any] | None:
    for report in releases:
        if isinstance(report, dict) and matches_expected_release(report):
            return report
    return None


# ---------------------------------------------------------------------------
# Classification (pure)
# ---------------------------------------------------------------------------


def _staging_state(staging: dict[str, Any] | None) -> str | None:
    """Reduce a staging checkpoint to a lifecycle state, or None if unreadable."""
    if not isinstance(staging, dict):
        return None
    if staging.get("complete") is True:
        return "STAGED_COMPLETE"
    counts = staging.get("counts")
    if isinstance(counts, dict):
        staged = counts.get("staged")
        total = counts.get("total")
        if isinstance(staged, int) and isinstance(total, int) and total > 0:
            return "STAGED_COMPLETE" if staged >= total else "STAGING_IN_PROGRESS"
        if isinstance(staged, int) and staged > 0:
            return "STAGING_IN_PROGRESS"
    processed = staging.get("rows_staged") or staging.get("processed")
    if isinstance(processed, int) and processed > 0:
        return "STAGING_IN_PROGRESS"
    return None


def classify_lifecycle(observation: ReleaseObservation) -> dict[str, Any]:
    """Classify the exact release. Pure, so the fail-closed rules are testable."""
    unavailable = observation.unavailable_evidence
    expected_release = {
        "filename": EXPECTED_FILENAME,
        "version_label": EXPECTED_VERSION_LABEL,
    }

    # Could not read the inventory at all: we know nothing about this release.
    if observation.releases is None:
        return {
            "lifecycle_state": "UNAVAILABLE",
            "lifecycle_states": list(LIFECYCLE_STATES),
            "lifecycle_rationale": (
                "The release inventory could not be read, so the pipeline cannot "
                "establish whether the exact release is present. This is not the "
                "same as the release being absent."
            ),
            "expected_release": expected_release,
            "active_vs_staged": {
                "state": "unknown",
                "active_release_id": None,
                "staged_release_id": None,
            },
            "superseded": False,
            "superseded_by": None,
            "unavailable_evidence": unavailable,
            "evidence_complete": False,
        }

    report = find_expected_release(observation.releases)

    if report is None:
        return {
            "lifecycle_state": "ABSENT",
            "lifecycle_states": list(LIFECYCLE_STATES),
            "lifecycle_rationale": (
                f"The release inventory was read ({len(observation.releases)} "
                f"release(s) present) and does not contain {EXPECTED_FILENAME}."
            ),
            "expected_release": expected_release,
            "active_vs_staged": {
                "state": "no_release",
                "active_release_id": observation.active_release_id,
                "staged_release_id": None,
            },
            "superseded": False,
            "superseded_by": None,
            "unavailable_evidence": unavailable,
            "evidence_complete": not unavailable,
        }

    release_id = str(report.get("release_id") or "") or None
    report_state = _normalize(report.get("state"))

    # Activation is the top of the ladder and is owner-gated; we only report it
    # when the canonical active pointer actually names this release.
    activated = bool(
        release_id
        and observation.active_release_id
        and observation.active_release_id == release_id
    )

    # Superseded: a different release holds the active pointer.
    superseded_by = None
    if (
        not activated
        and observation.active_release_id
        and release_id
        and observation.active_release_id != release_id
    ):
        superseded_by = observation.active_release_id

    staged_state = _staging_state(observation.staging)

    if activated:
        state = "ACTIVATED"
        rationale = f"The canonical active taxonomy pointer names this release ({release_id})."
    elif superseded_by:
        state = "SUPERSEDED"
        rationale = (
            f"This release is present but the canonical active pointer names a "
            f"different release ({superseded_by})."
        )
    elif staged_state:
        state = staged_state
        rationale = (
            "Staging projection evidence was read for this release."
            if staged_state == "STAGED_COMPLETE"
            else "A bounded staging projection has begun but is not complete."
        )
    elif report.get("smoke_verified") is True:
        state = "SMOKE_VERIFIED"
        rationale = "The release passed smoke verification; staging has not begun."
    elif report_state in _INSPECTED_STATES or report.get("inspection"):
        state = "UPLOADED_INSPECTED"
        rationale = (
            "The release is uploaded with a checksum record and inspection report; "
            "no staging projection evidence was established."
        )
    else:
        # Present in the inventory but carrying no state we recognize. Saying
        # UPLOADED_INSPECTED here would assert an inspection we did not see.
        state = "UNAVAILABLE"
        rationale = (
            "The release is present in the inventory but carries no recognized "
            "lifecycle state, so its position cannot be established."
        )
        unavailable = [*unavailable, f"release_state:unrecognized:{report.get('state')!r}"]

    return {
        "lifecycle_state": state,
        "lifecycle_states": list(LIFECYCLE_STATES),
        "lifecycle_rationale": rationale,
        "expected_release": expected_release,
        "release_id": release_id,
        "active_vs_staged": {
            "state": (
                "active"
                if activated
                else "staged"
                if staged_state
                else "inspected_only"
            ),
            "active_release_id": observation.active_release_id,
            "staged_release_id": release_id if staged_state else None,
        },
        "superseded": bool(superseded_by),
        "superseded_by": superseded_by,
        "unavailable_evidence": unavailable,
        "evidence_complete": not unavailable,
    }


def build_downstream_relink_impact(observation: ReleaseObservation) -> dict[str, Any]:
    """Describe what a relink would touch, counting only what was observed."""
    counts = observation.relink_counts
    domains: list[dict[str, Any]] = []
    blockers: list[str] = []

    for surface in RELINK_SURFACES:
        if isinstance(counts, dict) and isinstance(counts.get(surface), int):
            domains.append(
                {
                    "surface": surface,
                    "count": counts[surface],
                    "count_evidence": "observed",
                }
            )
        else:
            # Withheld, not zero. A zero here would read as "no downstream work".
            domains.append(
                {
                    "surface": surface,
                    "count": None,
                    "count_evidence": "unavailable",
                }
            )

    if observation.relink_error:
        blockers.append(f"relink_counter_unavailable:{observation.relink_error}")
    elif counts is None:
        blockers.append(
            "relink_counter_not_wired:no observed downstream relink counter is "
            "connected to this surface yet"
        )

    return {
        "domains": domains,
        "counts_complete": all(d["count_evidence"] == "observed" for d in domains),
        "unresolved_blockers": blockers,
    }


def build_hassler_release_status(observation: ReleaseObservation) -> dict[str, Any]:
    """Compose the full payload the frontend consumer interprets."""
    return {
        "schema": SCHEMA,
        # Stated as facts because the panel renders them as governance claims.
        "read_only": True,
        "automatic_promotion": False,
        "storage_backend": observation.storage_backend,
        "lifecycle": classify_lifecycle(observation),
        "downstream_relink_impact": build_downstream_relink_impact(observation),
    }


# ---------------------------------------------------------------------------
# Evidence gathering (does IO; every source fails soft into "unavailable")
# ---------------------------------------------------------------------------


@dataclass
class _Probe:
    """Collects one evidence source, converting any fault into a reason string."""

    errors: dict[str, str] = field(default_factory=dict)

    def read(self, name: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - any fault is "could not read"
            self.errors[name] = f"{type(exc).__name__}"
            return None


def observe_release_state(
    *,
    list_releases: Callable[[], Any],
    read_staging: Callable[[str], Any] | None = None,
    read_active_release_id: Callable[[], Any] | None = None,
    read_relink_counts: Callable[[], Any] | None = None,
    storage_backend: str | None = None,
) -> ReleaseObservation:
    """Gather lifecycle evidence, degrading to "unavailable" rather than raising.

    An observation surface that throws because a database is unreachable must
    still produce a truthful report saying so. It must never take down the
    Mission Control panel, and it must never guess.
    """
    probe = _Probe()

    raw_releases = probe.read("inventory", list_releases)
    releases: tuple[dict[str, Any], ...] | None
    if raw_releases is None:
        releases = None
    elif isinstance(raw_releases, dict):
        inner = raw_releases.get("releases")
        releases = tuple(r for r in inner if isinstance(r, dict)) if isinstance(inner, list) else ()
    elif isinstance(raw_releases, list):
        releases = tuple(r for r in raw_releases if isinstance(r, dict))
    else:
        releases = ()

    active_id = None
    if read_active_release_id is not None:
        raw_active = probe.read("active", read_active_release_id)
        active_id = str(raw_active) if isinstance(raw_active, str) and raw_active else None

    staging = None
    if read_staging is not None and releases:
        found = find_expected_release(releases)
        release_id = str(found.get("release_id") or "") if found else ""
        if release_id:
            raw_staging = probe.read("staging", lambda: read_staging(release_id))
            staging = raw_staging if isinstance(raw_staging, dict) else None

    relink_counts = None
    if read_relink_counts is not None:
        raw_counts = probe.read("relink", read_relink_counts)
        if isinstance(raw_counts, dict):
            relink_counts = {
                str(k): v for k, v in raw_counts.items() if isinstance(v, int)
            }

    return ReleaseObservation(
        releases=releases,
        inventory_error=probe.errors.get("inventory"),
        staging=staging,
        staging_error=probe.errors.get("staging"),
        active_release_id=active_id,
        active_error=probe.errors.get("active"),
        relink_counts=relink_counts,
        relink_error=probe.errors.get("relink"),
        storage_backend=storage_backend,
    )


def active_release_id_from_env() -> str | None:
    """Read the canonical active taxonomy release pointer.

    Activation is owner-governed and recorded outside this surface. Reading the
    pointer from configuration keeps this module incapable of setting it.
    """
    value = os.getenv("CALYX_ACTIVE_TAXONOMY_RELEASE_ID", "").strip()
    return value or None
