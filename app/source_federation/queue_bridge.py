"""Provider-free bridge from admitted sources to deduplicated queue candidates.

The bridge prepares bounded child-task payloads and can persist them through the
canonical Calyx task queue. It never fetches source data or mutates scientific
records.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from .inventory import CandidateDisposition, FederationCandidate

_PARENT_ISSUE = 1086
_PRIORITY_VALUE = {"P2": 20, "P3": 10}


class IdempotentSourceTaskQueue(Protocol):
    """Narrow canonical queue contract required by the federation bridge."""

    def create_task_once(
        self,
        *,
        task_key: str,
        task_type: str,
        title: str,
        payload: dict[str, Any],
        priority: int = 0,
    ) -> dict[str, Any]: ...


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
    evidence = ", ".join(candidate.metadata_evidence)
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
OC-SOURCE-URL: {candidate.source_url}
OC-SOURCE-IDENTIFIERS: {identifiers}
OC-SOURCE-ACCESS: {candidate.access.value}
OC-SOURCE-RIGHTS: {candidate.rights.value}
OC-SOURCE-LICENSE: {candidate.license_identifier}
OC-SOURCE-UPDATE-CADENCE: {candidate.update_cadence}
OC-SOURCE-METADATA-EVIDENCE: {evidence}
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


def persist_source_candidates(
    candidates: Iterable[FederationCandidate],
    queue: IdempotentSourceTaskQueue,
    *,
    existing_task_keys: Iterable[str] = (),
    limit: int = 10,
) -> dict[str, Any]:
    """Persist admitted candidates through the canonical durable task queue.

    Candidate admission and existing GitHub lineage are evaluated before any
    write. The queue's unique task-key constraint provides replay safety across
    processes; the bridge's stable fingerprint provides semantic identity.
    """

    candidate_list = tuple(candidates)
    plan = bridge_source_candidates(
        candidate_list,
        existing_task_keys=existing_task_keys,
    )
    safe_limit = max(0, min(50, int(limit)))
    selected = plan.create[:safe_limit]
    created: list[str] = []
    duplicates: list[str] = []

    for task in selected:
        result = queue.create_task_once(
            task_key=task.task_key,
            task_type="source_federation_adapter_evaluation",
            title=task.title,
            payload={
                "schema": "oc.source-federation-task.v1",
                "capability_key": task.capability_key,
                "source_fingerprint": task.source_fingerprint,
                "priority": task.priority,
                "body": task.body,
                "execution_mode": "draft_only",
                "network_fetch_authorized": False,
                "scientific_publication_authorized": False,
                "knowledge_graph_mutation_authorized": False,
                "taxonomy_mutation_authorized": False,
                "automatic_merge": False,
                "automatic_deploy": False,
            },
            priority=_PRIORITY_VALUE[task.priority],
        )
        if result.get("status") == "created":
            created.append(task.task_key)
        else:
            duplicates.append(task.task_key)

    if created:
        status = "refill_planned"
    elif selected:
        status = "reserve_satisfied"
    else:
        status = "queue_empty_healthy"

    return {
        "schema": "oc.source-federation-queue.v1",
        "status": status,
        "candidate_count": len(candidate_list),
        "eligible_count": len(plan.create),
        "selected_count": len(selected),
        "created_task_keys": created,
        "duplicate_task_keys": duplicates,
        "suppressed": [
            {
                "task_key": item.task_key,
                "reason": item.reason,
                "blockers": list(item.blockers),
            }
            for item in plan.suppressed
        ],
        "truncated_count": max(0, len(plan.create) - len(selected)),
    }
