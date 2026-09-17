"""Governed Calyx reasoning contract for Queue Bridge work intents.

Calyx may rank and decompose already-legitimate development work, but this
adapter never grants execution authority.  The deterministic Queue Bridge
remains authoritative for deduplication, protected boundaries, provider
policy, leases, and persistence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

_SCHEMA = "oc.calyx-development-intent.v1"
_PROTECTED = frozenset({
    "production", "production-db", "canonical-taxonomy", "canonical-kg",
    "scientific-publication", "provenance-policy", "sensitive-locality",
    "credentials", "secrets", "spending", "security-governance",
    "destructive-operation", "main-merge",
})
_ALLOWED_REPOS = frozenset({
    "orchid-calyx-backend", "orchid-continuum-frontend", "Orchid-Continuum-Brain"
})


@dataclass(frozen=True, slots=True)
class DevelopmentIntent:
    source_key: str
    issue_number: int
    title: str
    repo: str
    objective: str
    acceptance_criteria: tuple[str, ...]
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
        "dependencies": list(intent.dependencies),
        "priority": intent.priority,
        "protected_boundaries": sorted(intent.protected_boundaries),
        "requires_provider": intent.requires_provider,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def normalize_intents(intents: Iterable[DevelopmentIntent]) -> dict[str, Any]:
    """Normalize Calyx reasoning into Queue Bridge candidates, fail closed.

    No provider is launched here.  In NO-API mode provider-requiring intents
    are parked, and protected/invalid intents are owner-gated or rejected.
    """
    candidates: list[dict[str, Any]] = []
    parked: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for intent in intents:
        if intent.source_key in seen:
            rejected.append({"source_key": intent.source_key, "reason": "duplicate_source_key"})
            continue
        seen.add(intent.source_key)
        if intent.repo not in _ALLOWED_REPOS or intent.issue_number <= 0 or not intent.acceptance_criteria:
            rejected.append({"source_key": intent.source_key, "reason": "invalid_or_unbounded_intent"})
            continue
        protected = sorted(set(intent.protected_boundaries) & _PROTECTED)
        if protected:
            parked.append({"source_key": intent.source_key, "reason": "owner_gate", "protected_boundaries": protected})
            continue
        if intent.requires_provider:
            parked.append({"source_key": intent.source_key, "reason": "runtime_backoff_no_api"})
            continue
        candidates.append({
            "source_kind": "issue",
            "queue_source_kind": "calyx-development-director",
            "source_ref": f"#{intent.issue_number}",
            "title": intent.title,
            "material_fingerprint": _fingerprint(intent),
            "semantic_key": f"calyx-director:{intent.source_key}",
            "priority": max(0, min(5, int(intent.priority))),
            "dependencies": list(intent.dependencies),
            "protected_boundaries": [],
            "reasoning_context": {
                "objective": intent.objective,
                "acceptance_criteria": list(intent.acceptance_criteria),
                "repo": intent.repo,
            },
        })

    candidates.sort(key=lambda c: (c["priority"], c["semantic_key"]))
    return {
        "schema": _SCHEMA,
        "candidates": candidates,
        "parked": parked,
        "rejected": rejected,
        "provider_launch_authorized": False,
        "no_api_mode": True,
        "authority": "queue-bridge",
    }
