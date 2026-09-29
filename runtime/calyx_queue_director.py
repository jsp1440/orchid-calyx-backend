"""Governed Calyx reasoning contract for Queue Bridge work intents.

Calyx may rank and decompose already-legitimate development work, but this
adapter never grants execution authority. The deterministic Queue Bridge
remains authoritative for deduplication, protected boundaries, provider
policy, leases, and persistence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from runtime.brain_capability_registry import (
    CapabilityRegistry,
    canonical_brain_registry,
)
from scripts.oc_backlog_refiller import plan_refill

_SCHEMA = "oc.calyx-development-intent.v1"
_PROTECTED = frozenset(
    {
        "production",
        "production-db",
        "canonical-taxonomy",
        "canonical-kg",
        "scientific-publication",
        "provenance-policy",
        "sensitive-locality",
        "credentials",
        "secrets",
        "spending",
        "security-governance",
        "destructive-operation",
        "main-merge",
    }
)
_ALLOWED_REPOS = frozenset(
    {
        "orchid-calyx-backend",
        "orchid-continuum-frontend",
        "Orchid-Continuum-Brain",
    }
)


@dataclass(frozen=True, slots=True)
class DevelopmentIntent:
    source_key: str
    issue_number: int
    title: str
    repo: str
    objective: str
    acceptance_criteria: tuple[str, ...]
    required_capabilities: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    priority: int = 2
    protected_boundaries: tuple[str, ...] = ()
    requires_provider: bool = False


def _fingerprint(intent: DevelopmentIntent) -> str:
    material = {
        "schema": _SCHEMA,
        "source_key": intent.source_key,
        "issue_number": intent.issue_number,
        "title": intent.title,
        "repo": intent.repo,
        "objective": intent.objective,
        "acceptance_criteria": list(intent.acceptance_criteria),
        "required_capabilities": sorted(set(intent.required_capabilities)),
        "dependencies": list(intent.dependencies),
        "priority": intent.priority,
        "protected_boundaries": sorted(intent.protected_boundaries),
        "requires_provider": intent.requires_provider,
    }
    encoded = json.dumps(
        material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_intents(
    intents: Iterable[DevelopmentIntent],
    *,
    registry: CapabilityRegistry | None = None,
) -> dict[str, Any]:
    """Normalize Calyx reasoning into Queue Bridge candidates, fail closed."""
    candidates: list[dict[str, Any]] = []
    parked: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    capability_registry = registry or canonical_brain_registry()

    for intent in intents:
        if intent.source_key in seen:
            rejected.append(
                {"source_key": intent.source_key, "reason": "duplicate_source_key"}
            )
            continue
        seen.add(intent.source_key)
        if (
            intent.repo not in _ALLOWED_REPOS
            or intent.issue_number <= 0
            or not intent.acceptance_criteria
        ):
            rejected.append(
                {"source_key": intent.source_key, "reason": "invalid_or_unbounded_intent"}
            )
            continue
        declared_boundaries = set(intent.protected_boundaries)
        protected = sorted(declared_boundaries & _PROTECTED)
        unknown_boundaries = sorted(declared_boundaries - _PROTECTED)
        if protected or unknown_boundaries:
            parked.append(
                {
                    "source_key": intent.source_key,
                    "reason": "owner_gate",
                    "protected_boundaries": protected,
                    "unknown_boundaries": unknown_boundaries,
                }
            )
            continue
        if intent.requires_provider:
            parked.append(
                {"source_key": intent.source_key, "reason": "runtime_backoff_no_api"}
            )
            continue
        capability_results = [
            capability_registry.eligibility(capability_id)
            for capability_id in sorted(set(intent.required_capabilities))
        ]
        if any(not result["eligible"] for result in capability_results):
            parked.append(
                {
                    "source_key": intent.source_key,
                    "reason": "brain_capability_ineligible",
                    "capability_results": capability_results,
                }
            )
            continue
        candidates.append(
            {
                "source_kind": "issue",
                # Calyx is a reasoning producer under the already-authorized
                # autonomous-orchestrator lane; it is not a new authority.
                "queue_source_kind": "autonomous-orchestrator",
                "source_ref": f"#{intent.issue_number}",
                "title": intent.title,
                "material_fingerprint": _fingerprint(intent),
                "semantic_key": f"calyx-director:{intent.source_key}",
                "priority": max(0, min(5, int(intent.priority))),
                "required_capabilities": sorted(set(intent.required_capabilities)),
                "dependencies": list(intent.dependencies),
                "protected_boundaries": [],
            }
        )

    candidates.sort(key=lambda candidate: (candidate["priority"], candidate["semantic_key"]))
    return {
        "schema": _SCHEMA,
        "candidates": candidates,
        "parked": parked,
        "rejected": rejected,
        "provider_launch_authorized": False,
        "no_api_mode": True,
        "authority": "queue-bridge",
    }


def plan_calyx_refill(
    intents: Iterable[DevelopmentIntent],
    snapshot: dict[str, Any],
    *,
    reserve_depth: int = 2,
    planner_ok: bool = True,
    registry: CapabilityRegistry | None = None,
) -> dict[str, Any]:
    """Send safe Calyx intents through the canonical reserve planner."""
    normalized = normalize_intents(intents, registry=registry)
    result = plan_refill(
        snapshot,
        normalized["candidates"],
        reserve_depth=reserve_depth,
        planner_ok=planner_ok,
    )
    result.update(
        {
            "calyx_schema": _SCHEMA,
            "calyx_parked": normalized["parked"],
            "calyx_rejected": normalized["rejected"],
            "provider_launch_authorized": False,
            "no_api_mode": True,
            "authority": "queue-bridge",
        }
    )
    return result
