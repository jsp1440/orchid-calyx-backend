"""Provider-free bridge from admitted sources to deduplicated queue candidates.

The bridge is deliberately pure: it prepares bounded child-task payloads but never
creates issues, fetches source data, or mutates scientific records.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .inventory import CandidateDisposition, FederationCandidate

_PARENT_ISSUE = 1086


@dataclass(frozen=True, slots=True)
class SourceChildTask:
    """A deterministic, reviewable implementation-task candidate."""

    task_key: str
    capability_key: str
    title: str
    priority: str
    body: str
    source_fingerprint: str


@dataclass(frozen=True, slots=True)
class BridgeSuppression:
    """Why a source candidate did not produce another child task."""

    source_fingerprint: str
    task_key: str
    reason: str
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceQueueBridgeResult:
    create: tuple[SourceChildTask, ...]
    suppressed: tuple[BridgeSuppression, ...]


def source_task_key(candidate: FederationCandidate) -> str:
    """Return the canonical identity shared by issues and implementation PRs."""
    return f"source-federation:add:{candidate.fingerprint}"


def _priority(candidate: FederationCandidate) -> str:
    """Rank admitted work conservatively from its inspectable implementation cost."""
    cost = candidate.implementation_cost.strip().casefold()
    return "P2" if cost == "low" else "P3"


def _task_body(candidate: FederationCandidate, task_key: str) -> str:
    controls = ", ".join(candidate.locality_controls) or "none"
    identifiers = ", ".join(candidate.identifiers)
    domains = ", ".join(candidate.domains)
    return f"""Parent: #{_PARENT_ISSUE}

Implement a bounded, read-only adapter evaluation for {candidate.source_name}.
This task does not authorize harvesting, scientific publication, or canonical
taxonomy/data mutation.

OC-QUEUE-CAPABILITY: {task_key}
OC-SOURCE-FINGERPRINT: {candidate.fingerprint}
OC-SOURCE-OWNER: {candidate.source_owner}
OC-SOURCE-IDENTITY: {candidate.identity}
OC-SOURCE-IDENTIFIERS: {identifiers}
OC-SOURCE-ACCESS: {candidate.access.value}
OC-SOURCE-RIGHTS: {candidate.rights.value}
OC-SOURCE-LICENSE: {candidate.license_identifier}
OC-SOURCE-DOMAINS: {domains}
OC-SOURCE-OVERLAP: {candidate.overlap}
OC-SOURCE-INCREMENTAL-VALUE: {candidate.incremental_value}
OC-TAXONOMY-RECONCILIATION: {candidate.taxonomy_reconciliation}
OC-PROVENANCE-CONTRACT: {candidate.provenance_contract}
OC-LOCALITY-RISK: {candidate.locality_risk}
OC-LOCALITY-CONTROLS: {controls}
OC-IMPLEMENTATION-COST: {candidate.implementation_cost}
OC-SWARM-READS: taxonomy
OC-SWARM-WRITES: source-federation
"""


def bridge_source_candidates(
    candidates: Iterable[FederationCandidate],
    *,
    existing_task_keys: Iterable[str] = (),
) -> SourceQueueBridgeResult:
    """Prepare one child task per admitted source identity.

    Existing task keys represent active or completed issue/PR lineage. Matching is
    normalized and suppresses duplication regardless of which queue candidate
    rediscovered the capability.
    """
    existing = {key.strip().casefold() for key in existing_task_keys}
    seen_fingerprints: set[str] = set()
    create: list[SourceChildTask] = []
    suppressed: list[BridgeSuppression] = []

    for candidate in candidates:
        task_key = source_task_key(candidate)
        normalized_key = task_key.casefold()

        if candidate.fingerprint in seen_fingerprints:
            suppressed.append(
                BridgeSuppression(
                    candidate.fingerprint,
                    task_key,
                    "duplicate-candidate",
                )
            )
            continue
        seen_fingerprints.add(candidate.fingerprint)

        if candidate.disposition is not CandidateDisposition.ADD:
            suppressed.append(
                BridgeSuppression(
                    candidate.fingerprint,
                    task_key,
                    "not-admitted",
                    candidate.admission_blockers,
                )
            )
            continue

        if normalized_key in existing:
            suppressed.append(
                BridgeSuppression(
                    candidate.fingerprint,
                    task_key,
                    "existing-delivery-lineage",
                )
            )
            continue

        create.append(
            SourceChildTask(
                task_key=task_key,
                capability_key=task_key,
                title=(
                    f"{_priority(candidate)} SOURCE-FEDERATION — "
                    f"{candidate.source_name}"
                ),
                priority=_priority(candidate),
                body=_task_body(candidate, task_key),
                source_fingerprint=candidate.fingerprint,
            )
        )

    return SourceQueueBridgeResult(tuple(create), tuple(suppressed))
