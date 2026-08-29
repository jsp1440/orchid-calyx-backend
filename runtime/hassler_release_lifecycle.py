"""Read-only lifecycle classification for the exact current Hassler release.

This module answers one question with explicit evidence semantics: where is
``WorldOrchids 26-08 (Aug 2 2026).csv`` in the governed intake lifecycle right
now — absent, durably uploaded/inspected, smoke-verified, partially staged,
fully staged, superseded by a newer release, or activated as canonical
taxonomy?

Three rules govern everything here:

1. Unavailable is never zero. A probe that could not be executed yields
   ``UNAVAILABLE`` evidence and an ``unavailable_evidence`` entry. It never
   collapses into ``ABSENT``, ``0``, or ``false``.
2. Upload and staging never imply activation. Activation is a separately
   protected owner-governed surface. Migration 107 has no ``activated`` release
   state at all, so activation can only ever be reported from an explicit
   canonical-taxonomy probe.
3. Nothing in this module mutates anything. It classifies supplied read-only
   evidence and emits receipts.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

CONTRACT_VERSION = "calyx-hassler-release-lifecycle/v1"

EXPECTED_FILENAME = "WorldOrchids 26-08 (Aug 2 2026).csv"
EXPECTED_SHA256 = "e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f"
EXPECTED_SIZE_BYTES = 11_529_836
EXPECTED_VERSION_LABEL = "26-08"
EXPECTED_ACQUIRED_AT = "2026-08-02"

LIFECYCLE_STATES = (
    "UNAVAILABLE",
    "ABSENT",
    "UPLOADED_INSPECTED",
    "SMOKE_VERIFIED",
    "STAGING_IN_PROGRESS",
    "STAGED_COMPLETE",
    "SUPERSEDED",
    "ACTIVATED",
)

DURABLE_RELEASE_STATES = (
    "inspected",
    "staging",
    "staged",
    "review_required",
    "reviewed",
)

UNAVAILABLE = "unavailable"

RELINK_DOMAINS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("occurrences", ("occurrences",)),
    ("media", ("images",)),
    ("traits", ("traits",)),
    ("literature", ("literature",)),
    ("interactions", ("pollinators", "mycorrhizae")),
    ("knowledge_graph", ("knowledge_graph_edges",)),
)


@dataclass(frozen=True)
class Evidence:
    """A single read-only probe outcome."""

    available: bool
    payload: Any = None
    detail: str = ""

    @classmethod
    def unavailable(cls, detail: str) -> Evidence:
        return cls(available=False, payload=None, detail=detail)

    @classmethod
    def of(cls, payload: Any, detail: str = "") -> Evidence:
        return cls(available=True, payload=payload, detail=detail)

    def as_dict(self) -> dict[str, Any]:
        return {"available": self.available, "detail": self.detail}


def _artifact_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _release_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, Mapping):
        raw = payload.get("releases")
    elif isinstance(payload, Sequence) and not isinstance(payload, str | bytes):
        raw = payload
    else:
        raw = None
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def verify_source_identity(source: Mapping[str, Any] | None) -> dict[str, Any]:
    """Compare an observed release snapshot against the exact expected release."""
    expected = {
        "filename": EXPECTED_FILENAME,
        "sha256": EXPECTED_SHA256,
        "size_bytes": EXPECTED_SIZE_BYTES,
        "version_label": EXPECTED_VERSION_LABEL,
        "acquired_at": EXPECTED_ACQUIRED_AT,
    }
    if source is None:
        return {
            "verified": None,
            "reason": UNAVAILABLE,
            "expected": expected,
            "observed": None,
            "mismatches": [],
        }

    observed_map = _mapping(source)
    snapshot = _mapping(observed_map.get("snapshot")) or observed_map
    observed = {
        "filename": snapshot.get("filename"),
        "sha256": snapshot.get("sha256") or observed_map.get("release_id"),
        "size_bytes": snapshot.get("size_bytes"),
        "version_label": snapshot.get("version_label"),
        "acquired_at": snapshot.get("acquired_at"),
    }
    mismatches: list[dict[str, Any]] = []
    for field, expected_value in expected.items():
        actual = observed.get(field)
        if actual is None:
            mismatches.append(
                {"field": field, "expected": expected_value, "observed": UNAVAILABLE}
            )
            continue
        if field == "size_bytes":
            try:
                actual = int(actual)
            except (TypeError, ValueError):
                mismatches.append(
                    {
                        "field": field,
                        "expected": expected_value,
                        "observed": str(actual),
                    }
                )
                continue
        if actual != expected_value:
            mismatches.append(
                {"field": field, "expected": expected_value, "observed": actual}
            )
    hard_mismatches = [item for item in mismatches if item["observed"] != UNAVAILABLE]
    return {
        "verified": not mismatches,
        "reason": (
            "identity_matches_exact_release"
            if not mismatches
            else (
                "identity_conflict"
                if hard_mismatches
                else "identity_evidence_incomplete"
            )
        ),
        "expected": expected,
        "observed": observed,
        "mismatches": mismatches,
    }


def _superseding_releases(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    newer: list[dict[str, Any]] = []
    for entry in entries:
        release_id = str(entry.get("release_id") or "")
        if release_id == EXPECTED_SHA256:
            continue
        snapshot = _mapping(entry.get("snapshot"))
        acquired_at = str(snapshot.get("acquired_at") or "")
        if acquired_at and acquired_at > EXPECTED_ACQUIRED_AT:
            newer.append(
                {
                    "release_id": release_id,
                    "filename": snapshot.get("filename"),
                    "version_label": snapshot.get("version_label"),
                    "acquired_at": acquired_at,
                    "state": entry.get("state"),
                }
            )
    return sorted(newer, key=lambda item: str(item["acquired_at"]))


def _staging_view(staging: Evidence, expected_rows: int | None) -> dict[str, Any]:
    if not staging.available:
        return {
            "evidence": UNAVAILABLE,
            "detail": staging.detail,
            "staged_rows": None,
            "expected_rows": expected_rows,
            "complete": None,
            "next_row_index": None,
            "open_review_items": None,
            "change_report_present": None,
        }
    payload = _mapping(staging.payload)
    checkpoint = _mapping(payload.get("checkpoint"))
    counts = _mapping(payload.get("counts"))
    change_report = payload.get("change_report")
    staged_rows = counts.get("staged")
    return {
        "evidence": "observed",
        "detail": staging.detail,
        "staged_rows": int(staged_rows) if staged_rows is not None else None,
        "expected_rows": expected_rows,
        "complete": (
            bool(checkpoint.get("completed"))
            if checkpoint.get("completed") is not None
            else None
        ),
        "next_row_index": (
            int(checkpoint["next_row_index"])
            if checkpoint.get("next_row_index") is not None
            else None
        ),
        "open_review_items": (
            int(counts["open_review"])
            if counts.get("open_review") is not None
            else None
        ),
        "change_report_present": isinstance(change_report, Mapping),
    }


def _smoke_view(readiness: Evidence) -> dict[str, Any]:
    if not readiness.available:
        return {"evidence": UNAVAILABLE, "verified": None, "detail": readiness.detail}
    payload = _mapping(readiness.payload)
    gates = payload.get("gates")
    if not isinstance(gates, Sequence):
        return {
            "evidence": UNAVAILABLE,
            "verified": None,
            "detail": "readiness payload exposed no gate list",
        }
    for gate in gates:
        if isinstance(gate, Mapping) and gate.get("name") == "smoke_fixture":
            return {
                "evidence": "observed",
                "verified": gate.get("status") == "passed",
                "detail": str(gate.get("evidence") or ""),
                "blocking_reason": gate.get("blocking_reason"),
            }
    return {
        "evidence": UNAVAILABLE,
        "verified": None,
        "detail": "readiness payload exposed no smoke_fixture gate",
    }


def _activation_view(active_taxonomy: Evidence) -> dict[str, Any]:
    if not active_taxonomy.available:
        return {
            "evidence": UNAVAILABLE,
            "active_release_id": None,
            "exact_release_is_active": None,
            "detail": active_taxonomy.detail
            or "no canonical taxonomy activation probe was supplied",
        }
    payload = _mapping(active_taxonomy.payload)
    raw_active = payload.get("active_release_id")
    active_release_id = str(raw_active) if raw_active else None
    return {
        "evidence": "observed",
        "active_release_id": active_release_id,
        "exact_release_is_active": active_release_id == EXPECTED_SHA256,
        "detail": active_taxonomy.detail,
    }


def classify_release_lifecycle(
    *,
    releases: Evidence,
    release_detail: Evidence | None = None,
    readiness: Evidence | None = None,
    staging: Evidence | None = None,
    active_taxonomy: Evidence | None = None,
) -> dict[str, Any]:
    """Classify the exact Hassler release into exactly one lifecycle state."""
    release_detail = release_detail or Evidence.unavailable("release detail not probed")
    readiness = readiness or Evidence.unavailable("readiness not probed")
    staging = staging or Evidence.unavailable("staging status not probed")
    active_taxonomy = active_taxonomy or Evidence.unavailable(
        "canonical taxonomy activation not probed"
    )

    unavailable_evidence: list[dict[str, str]] = []
    for name, evidence in (
        ("release_list", releases),
        ("release_detail", release_detail),
        ("readiness", readiness),
        ("staging", staging),
        ("canonical_activation", active_taxonomy),
    ):
        if not evidence.available:
            unavailable_evidence.append({"probe": name, "detail": evidence.detail})

    entries = _release_entries(releases.payload) if releases.available else []
    exact_entry: dict[str, Any] | None = None
    for entry in entries:
        snapshot = _mapping(entry.get("snapshot"))
        if (
            str(entry.get("release_id") or "") == EXPECTED_SHA256
            or str(snapshot.get("sha256") or "") == EXPECTED_SHA256
        ):
            exact_entry = entry
            break
    if exact_entry is None and release_detail.available:
        candidate = _mapping(release_detail.payload)
        if candidate:
            exact_entry = candidate

    identity = verify_source_identity(exact_entry)
    durable_state = str(exact_entry.get("state") or "") if exact_entry else None
    if durable_state and durable_state not in DURABLE_RELEASE_STATES:
        durable_state_known = False
    else:
        durable_state_known = bool(durable_state)

    snapshot = _mapping(exact_entry.get("snapshot")) if exact_entry else {}
    raw_rows = snapshot.get("row_count")
    expected_rows = int(raw_rows) if raw_rows is not None else None

    staging_view = _staging_view(staging, expected_rows)
    smoke_view = _smoke_view(readiness)
    activation_view = _activation_view(active_taxonomy)
    superseding = _superseding_releases(entries) if releases.available else []

    present = exact_entry is not None
    if present:
        durably_uploaded: bool | None = True
    elif releases.available:
        durably_uploaded = False
    else:
        durably_uploaded = None

    staged_rows = staging_view["staged_rows"]
    staging_complete = staging_view["complete"]
    fully_staged = bool(
        staging_complete
        and expected_rows is not None
        and staged_rows is not None
        and staged_rows == expected_rows
    )

    if activation_view["exact_release_is_active"] is True:
        state = "ACTIVATED"
        rationale = (
            "The canonical taxonomy activation probe reports the exact release as "
            "the active canonical release."
        )
    elif superseding:
        state = "SUPERSEDED"
        rationale = (
            f"{len(superseding)} durable release(s) acquired after "
            f"{EXPECTED_ACQUIRED_AT} are present; the exact release is no longer "
            "the current intake target."
        )
    elif fully_staged:
        state = "STAGED_COMPLETE"
        rationale = (
            "Durable staging reports a completed checkpoint with staged row count "
            "equal to the inspected source row count."
        )
    elif present and staged_rows is not None and staged_rows > 0:
        state = "STAGING_IN_PROGRESS"
        rationale = (
            "Durable staging has advanced past row zero but has not reported a "
            "completed checkpoint matching the inspected row count."
        )
    elif present and smoke_view["verified"] is True:
        state = "SMOKE_VERIFIED"
        rationale = (
            "The exact release is durably present and the smoke_fixture gate is "
            "passed; no bounded staging batch has been observed."
        )
    elif present:
        state = "UPLOADED_INSPECTED"
        rationale = (
            "The exact release is durably present and inspected; the smoke gate is "
            "not yet passed or not observable."
        )
    elif releases.available:
        state = "ABSENT"
        rationale = (
            "The release list probe succeeded and contains no release matching the "
            "exact SHA-256; the release has never been durably uploaded."
        )
    else:
        state = "UNAVAILABLE"
        rationale = (
            "The release list probe did not succeed. Absence cannot be asserted "
            "from an unavailable probe."
        )

    staged_release_id = (
        EXPECTED_SHA256 if state in {"STAGING_IN_PROGRESS", "STAGED_COMPLETE"} else None
    )
    active_release_id = activation_view["active_release_id"]
    if activation_view["evidence"] == UNAVAILABLE:
        active_vs_staged = UNAVAILABLE
    elif active_release_id is None:
        active_vs_staged = "no_active_canonical_release"
    elif active_release_id == EXPECTED_SHA256:
        active_vs_staged = "exact_release_is_active"
    else:
        active_vs_staged = "active_release_differs_from_exact_release"

    return {
        "contract": CONTRACT_VERSION,
        "read_only": True,
        "expected_release": {
            "filename": EXPECTED_FILENAME,
            "sha256": EXPECTED_SHA256,
            "size_bytes": EXPECTED_SIZE_BYTES,
            "version_label": EXPECTED_VERSION_LABEL,
            "acquired_at": EXPECTED_ACQUIRED_AT,
        },
        "lifecycle_state": state,
        "lifecycle_rationale": rationale,
        "lifecycle_states": list(LIFECYCLE_STATES),
        "identity": identity,
        "durably_uploaded": durably_uploaded,
        "durable_release_state": durable_state if durable_state_known else None,
        "durable_release_state_recognized": durable_state_known
        if durable_state
        else None,
        "smoke": smoke_view,
        "staging": staging_view,
        "superseded_by": superseding,
        "superseded": bool(superseding),
        "activation": activation_view,
        "active_vs_staged": {
            "state": active_vs_staged,
            "active_release_id": active_release_id,
            "staged_release_id": staged_release_id,
        },
        "unavailable_evidence": unavailable_evidence,
        "evidence_complete": not unavailable_evidence,
        "activation_authorized": False,
        "activation_invoked": False,
        "activation_implied_by_upload_or_staging": False,
        "automatic_promotion": False,
        "production_taxonomy_mutation_authorized": False,
        "knowledge_graph_mutation_authorized": False,
        "scientific_publication_authorized": False,
    }


def enumerate_downstream_relink_impact(
    *,
    change_report: Evidence,
    domain_counts: Evidence | None = None,
) -> dict[str, Any]:
    """Enumerate downstream relink/backfill work from read-only evidence."""
    domain_counts = domain_counts or Evidence.unavailable(
        "no read-only downstream count probe was supplied"
    )
    counts_payload = _mapping(domain_counts.payload) if domain_counts.available else {}

    if change_report.available:
        report = _mapping(change_report.payload)
        summary = _mapping(report.get("summary"))
        drivers = {
            "accepted_name_change_candidates": summary.get(
                "accepted_name_change_candidates"
            ),
            "removed_taxa": summary.get("removed_taxa"),
            "added_taxa": summary.get("added_taxa"),
            "synonym_changes": summary.get("synonym_changes"),
            "status_changes": summary.get("status_changes"),
            "malformed_rows": summary.get("malformed_rows"),
            "duplicate_identities": summary.get("duplicate_identities"),
        }
        drivers_evidence = "observed"
    else:
        drivers = dict.fromkeys(
            (
                "accepted_name_change_candidates",
                "removed_taxa",
                "added_taxa",
                "synonym_changes",
                "status_changes",
                "malformed_rows",
                "duplicate_identities",
            ),
            None,
        )
        drivers_evidence = UNAVAILABLE

    domains: list[dict[str, Any]] = []
    for surface, impact_domains in RELINK_DOMAINS:
        if domain_counts.available:
            observed = [counts_payload.get(name) for name in impact_domains]
            if all(value is not None for value in observed):
                affected: int | None = sum(int(value) for value in observed)
                count_evidence = "observed"
            else:
                affected = None
                count_evidence = UNAVAILABLE
        else:
            affected = None
            count_evidence = UNAVAILABLE
        domains.append(
            {
                "surface": surface,
                "impact_domains": list(impact_domains),
                "affected_records": affected,
                "count_evidence": count_evidence,
                "relink_required_when": [
                    "accepted_name_change_candidates",
                    "removed_taxa",
                ],
                "backfill_required_when": ["added_taxa"],
                "review_required_when": [
                    "synonym_changes",
                    "status_changes",
                    "duplicate_identities",
                ],
            }
        )

    unresolved_blockers: list[str] = []
    for key in ("malformed_rows", "duplicate_identities"):
        value = drivers.get(key)
        if value is None:
            unresolved_blockers.append(f"{key}_unavailable")
        elif int(value) > 0:
            unresolved_blockers.append(f"{key}_present")

    return {
        "contract": CONTRACT_VERSION,
        "read_only": True,
        "release_id": EXPECTED_SHA256,
        "drivers": drivers,
        "drivers_evidence": drivers_evidence,
        "domains": domains,
        "surfaces_enumerated": [surface for surface, _ in RELINK_DOMAINS],
        "counts_complete": all(
            item["count_evidence"] == "observed" for item in domains
        ),
        "unresolved_blockers": unresolved_blockers,
        "relink_execution_authorized": False,
        "backfill_execution_authorized": False,
        "knowledge_graph_mutation_authorized": False,
        "note": (
            "Downstream relink and backfill are enumerated for owner review only. "
            "No downstream surface is rewritten by intake, staging, or this audit."
        ),
    }


def build_owner_exception_receipt(
    *,
    lifecycle: Mapping[str, Any],
    blocking_reason: str,
    next_executable_action: str,
    responsible_party: str,
    prepared_action: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Record that a bounded action was prepared and validated but not executed."""
    receipt: dict[str, Any] = {
        "contract": CONTRACT_VERSION,
        "receipt_type": "owner_exception",
        "release_id": EXPECTED_SHA256,
        "expected_filename": EXPECTED_FILENAME,
        "lifecycle_state": lifecycle.get("lifecycle_state"),
        "lifecycle_rationale": lifecycle.get("lifecycle_rationale"),
        "unavailable_evidence": list(lifecycle.get("unavailable_evidence") or []),
        "blocking_reason": blocking_reason,
        "next_executable_action": next_executable_action,
        "responsible_party": responsible_party,
        "prepared_action": dict(prepared_action or {}),
        "action_validated": bool(prepared_action),
        "action_executed": False,
        "upload_invoked": False,
        "staging_invoked": False,
        "production_mutation": False,
        "incorporation_assumed": False,
        "activation_authorized": False,
        "activation_implied_by_upload_or_staging": False,
        "knowledge_graph_mutation_authorized": False,
        "scientific_publication_authorized": False,
    }
    receipt["artifact_hash"] = _artifact_hash(receipt)
    return receipt


def build_release_status_block(
    *,
    lifecycle: Mapping[str, Any],
    downstream: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compact Mission Control / portfolio status projection of the exact release."""
    active_vs_staged = _mapping(lifecycle.get("active_vs_staged"))
    staging = _mapping(lifecycle.get("staging"))
    identity = _mapping(lifecycle.get("identity"))
    block = {
        "contract": CONTRACT_VERSION,
        "component": "hassler_release_intake",
        "release_identity": {
            "filename": EXPECTED_FILENAME,
            "sha256": EXPECTED_SHA256,
            "version_label": EXPECTED_VERSION_LABEL,
            "acquired_at": EXPECTED_ACQUIRED_AT,
            "identity_verified": identity.get("verified"),
        },
        "lifecycle_state": lifecycle.get("lifecycle_state"),
        "active_release_id": active_vs_staged.get("active_release_id"),
        "staged_release_id": active_vs_staged.get("staged_release_id"),
        "active_vs_staged": active_vs_staged.get("state"),
        "staged_rows": staging.get("staged_rows"),
        "expected_rows": staging.get("expected_rows"),
        "resumable_from_row_index": staging.get("next_row_index"),
        "open_review_items": staging.get("open_review_items"),
        "change_report_present": staging.get("change_report_present"),
        "evidence_complete": lifecycle.get("evidence_complete"),
        "unavailable_evidence": [
            item.get("probe") for item in (lifecycle.get("unavailable_evidence") or [])
        ],
        "downstream_relink_surfaces": (
            list(downstream.get("surfaces_enumerated") or [])
            if downstream is not None
            else []
        ),
        "downstream_counts_complete": (
            downstream.get("counts_complete") if downstream is not None else None
        ),
        "taxonomy_activation": "separately_protected_owner_gate",
        "activation_authorized": False,
        "activation_implied_by_upload_or_staging": False,
        "read_only": True,
    }
    block["artifact_hash"] = _artifact_hash(block)
    return block
