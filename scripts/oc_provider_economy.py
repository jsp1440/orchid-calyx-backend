"""OC-PROVIDER-ECONOMY-001 — role-specific provider registry for Orchid Continuum.

Evaluates additional AI providers (Kimi, Perplexity, Twin, Magai) as specialized
low-cost capacity against specific task classes without weakening canonical Claude
→ Gemini → OpenAI governed failover or adding uncontrolled external agents.

Rules:
- Provider routing may change cost/latency, NEVER authority, evidence status,
  completion percentage, or acceptance criteria.
- Missing cost metadata is UNKNOWN, not zero.
- Perplexity output is source-discovery context only, not evidence.
- Twin must pass through the Agent/MCP Security Gateway; it must not create a
  second autonomous control plane.
- Magai has no public API; recorded as NOT_AVAILABLE.
- Subscription access does not imply API quota; billing states are explicit.
- No credential value is requested, logged, copied, or committed here.
- No accounts, credits, auto-top-up, or spending-cap changes are made.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

SCHEMA_VERSION = "oc-provider-economy/v1"

_UNKNOWN = "UNKNOWN"
_NOT_AVAILABLE = "NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TaskClass(str, Enum):
    """Bounded role categories for provider routing."""
    CODING_REPOSITORY_EDIT = "coding_repository_edit"
    RESEARCH_WEB_RETRIEVAL = "research_web_retrieval"
    READ_ONLY_CLASSIFICATION = "read_only_classification"
    BROWSER_AUTOMATION = "browser_automation"
    SCIENTIFIC_REASONING = "scientific_reasoning"


class ApiAvailability(str, Enum):
    """Whether the provider exposes a usable API (separate from consumer subscription)."""
    AVAILABLE = "available"
    SEPARATE_BILLING = "separate_billing"
    NOT_AVAILABLE = "not_available"
    UNKNOWN = "unknown"


class ProviderHealth(str, Enum):
    """Runtime health of the provider (set externally; unknown at module load)."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


# Authority ceiling levels, ordered from lowest to highest.
_AUTHORITY_ORDER = [
    "none",
    "read_only",
    "bounded_workspace_mutation",
    "repository_code_execution",
    "production_change",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderProfile:
    """Static evaluation record for one provider.

    Created from public documentation only. No credential values stored.
    is_available reflects whether the provider can be routed to at all.
    cost_per_unit and health are explicit UNKNOWN when not measurable here.
    """

    provider_id: str
    display_name: str
    task_classes: frozenset
    api_availability: ApiAvailability
    subscription_vs_api_billing: str
    cost_per_unit: str
    authority_ceiling: str
    health: ProviderHealth
    notes: str
    gateway_required: bool
    evidence_status: str
    is_available: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "task_classes": sorted(tc.value for tc in self.task_classes),
            "api_availability": self.api_availability.value,
            "subscription_vs_api_billing": self.subscription_vs_api_billing,
            "cost_per_unit": self.cost_per_unit,
            "authority_ceiling": self.authority_ceiling,
            "health": self.health.value,
            "notes": self.notes,
            "gateway_required": self.gateway_required,
            "evidence_status": self.evidence_status,
            "is_available": self.is_available,
        }


@dataclass(frozen=True)
class SelectionResult:
    """Result of selecting a provider for a task class."""

    task_class: TaskClass
    selected_provider_id: str | None
    reason: str
    authority_ceiling: str
    gateway_required: bool
    evidence_status: str
    cost_per_unit: str
    health: ProviderHealth
    acceptance_gates_unchanged: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_class": self.task_class.value,
            "selected_provider_id": self.selected_provider_id,
            "reason": self.reason,
            "authority_ceiling": self.authority_ceiling,
            "gateway_required": self.gateway_required,
            "evidence_status": self.evidence_status,
            "cost_per_unit": self.cost_per_unit,
            "health": self.health.value,
            "acceptance_gates_unchanged": self.acceptance_gates_unchanged,
        }


# ---------------------------------------------------------------------------
# Canonical provider registry
# ---------------------------------------------------------------------------


PROVIDER_REGISTRY: dict[str, ProviderProfile] = {
    "kimi": ProviderProfile(
        provider_id="kimi",
        display_name="Kimi (Moonshot AI)",
        task_classes=frozenset({
            TaskClass.CODING_REPOSITORY_EDIT,
            TaskClass.READ_ONLY_CLASSIFICATION,
        }),
        api_availability=ApiAvailability.AVAILABLE,
        subscription_vs_api_billing=(
            "Kimi developer/API keys and OpenAI-compatible APIs are available. "
            "Kimi Code documents Anthropic-compatible use for coding tools. "
            "Membership-based quota and rate limits apply. "
            "Consumer subscription does not automatically include API quota; "
            "developer keys must be obtained separately."
        ),
        cost_per_unit=_UNKNOWN,
        authority_ceiling="repository_code_execution",
        health=ProviderHealth.UNKNOWN,
        notes=(
            "Strongest candidate for low-cost coding and analysis capacity. "
            "Must preserve identical repo permissions, leases, PR packaging, "
            "exact-head CI, scientific/security gates, and owner boundaries. "
            "No extra authority beyond repository_code_execution."
        ),
        gateway_required=False,
        evidence_status="not_applicable",
        is_available=True,
    ),
    "perplexity": ProviderProfile(
        provider_id="perplexity",
        display_name="Perplexity",
        task_classes=frozenset({TaskClass.RESEARCH_WEB_RETRIEVAL}),
        api_availability=ApiAvailability.SEPARATE_BILLING,
        subscription_vs_api_billing=(
            "Perplexity Search/Agent APIs exist but API billing and credits are "
            "SEPARATE from ordinary Perplexity subscriptions. "
            "Treat as needing independent API budget; not covered by consumer plan."
        ),
        cost_per_unit=_UNKNOWN,
        authority_ceiling="read_only",
        health=ProviderHealth.UNKNOWN,
        notes=(
            "Usable only for RESEARCH_WEB_RETRIEVAL tasks where web-grounded retrieval "
            "materially helps: source discovery, literature/federation reconnaissance, "
            "current external documentation. Output is SOURCE_DISCOVERY_CONTEXT_ONLY — "
            "source URLs and identities must flow into normal provenance/evidence review. "
            "Perplexity output must never be treated as canonical scientific evidence."
        ),
        gateway_required=False,
        evidence_status="source_discovery_context_only",
        is_available=True,
    ),
    "twin": ProviderProfile(
        provider_id="twin",
        display_name="Twin",
        task_classes=frozenset({TaskClass.BROWSER_AUTOMATION}),
        api_availability=ApiAvailability.AVAILABLE,
        subscription_vs_api_billing=(
            "Twin exposes a REST API for triggering Twin agents/automations. "
            "Billing details not confirmed from public documentation; treat as UNKNOWN."
        ),
        cost_per_unit=_UNKNOWN,
        authority_ceiling="bounded_workspace_mutation",
        health=ProviderHealth.UNKNOWN,
        notes=(
            "Not a drop-in raw LLM endpoint. Usable only for bounded browser/external "
            "automation tasks that cannot be done deterministically/API-first. "
            "Any Twin-triggered action MUST pass through the existing Agent/MCP Security "
            "Gateway. Must not receive broad GitHub/production/database authority. "
            "Must not create a second autonomous control plane."
        ),
        gateway_required=True,
        evidence_status="not_applicable",
        is_available=True,
    ),
    "magai": ProviderProfile(
        provider_id="magai",
        display_name="Magai",
        task_classes=frozenset(),
        api_availability=ApiAvailability.NOT_AVAILABLE,
        subscription_vs_api_billing=(
            "Magai publicly states it does not offer a public API. "
            "Consumer subscription only. No API integration is possible."
        ),
        cost_per_unit=_UNKNOWN,
        authority_ceiling="none",
        health=ProviderHealth.UNAVAILABLE,
        notes=(
            "Recorded as NOT_AVAILABLE per Magai's own documentation. "
            "No integration implemented. If 'Magi/Magai' refers to a different product, "
            "classification remains UNKNOWN pending exact product identity."
        ),
        gateway_required=False,
        evidence_status="not_applicable",
        is_available=False,
    ),
}

# Priority order for selection within each task class (lower index = higher priority).
_TASK_CLASS_PRIORITY: dict[str, list[str]] = {
    TaskClass.CODING_REPOSITORY_EDIT.value: ["kimi"],
    TaskClass.RESEARCH_WEB_RETRIEVAL.value: ["perplexity"],
    TaskClass.READ_ONLY_CLASSIFICATION.value: ["kimi"],
    TaskClass.BROWSER_AUTOMATION.value: ["twin"],
    TaskClass.SCIENTIFIC_REASONING.value: [],  # no non-Claude providers authorized
}


# ---------------------------------------------------------------------------
# Authority enforcement
# ---------------------------------------------------------------------------


def _authority_rank(ceiling: str) -> int:
    try:
        return _AUTHORITY_ORDER.index(ceiling)
    except ValueError:
        return -1


def check_authority_not_expanded(
    provider_id: str, requested_authority: str
) -> None:
    """Raise ValueError if requested authority exceeds the provider's ceiling.

    Provider routing may never expand authority beyond what is configured.
    """
    profile = PROVIDER_REGISTRY.get(provider_id)
    if profile is None:
        raise ValueError(f"Unknown provider_id: {provider_id!r}")
    ceiling_rank = _authority_rank(profile.authority_ceiling)
    requested_rank = _authority_rank(requested_authority)
    if requested_rank < 0:
        raise ValueError(f"Unknown authority level: {requested_authority!r}")
    if requested_rank > ceiling_rank:
        raise ValueError(
            f"Provider {provider_id!r} authority ceiling is "
            f"{profile.authority_ceiling!r}; requested {requested_authority!r} "
            f"is not permitted. Provider routing must never expand authority."
        )


def twin_must_use_security_gateway(provider_id: str) -> bool:
    """Return True if this provider must pass through the Agent/MCP Security Gateway."""
    profile = PROVIDER_REGISTRY.get(provider_id)
    return profile.gateway_required if profile else False


def perplexity_output_is_source_discovery_only(provider_id: str) -> bool:
    """Return True if the provider's output must remain source-discovery context."""
    profile = PROVIDER_REGISTRY.get(provider_id)
    return (
        profile is not None
        and profile.evidence_status == "source_discovery_context_only"
    )


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def select_provider_for_task(
    task_class: TaskClass | str,
    health_overrides: dict[str, ProviderHealth] | None = None,
) -> SelectionResult:
    """Deterministically select a provider for a task class.

    Selection is deterministic from task class + health + provider registry.
    Missing cost metadata → UNKNOWN (never zero).
    Fallback/tiering does not alter acceptance gates.

    Args:
        task_class: The task class to route.
        health_overrides: Optional runtime health states keyed by provider_id.

    Returns:
        SelectionResult with provider or None if no eligible provider exists.
    """
    if isinstance(task_class, str):
        try:
            task_class = TaskClass(task_class)
        except ValueError:
            return SelectionResult(
                task_class=TaskClass.READ_ONLY_CLASSIFICATION,
                selected_provider_id=None,
                reason=f"Unknown task_class: {task_class!r}",
                authority_ceiling="none",
                gateway_required=False,
                evidence_status=_NOT_AVAILABLE,
                cost_per_unit=_UNKNOWN,
                health=ProviderHealth.UNKNOWN,
                acceptance_gates_unchanged=True,
            )

    overrides = health_overrides or {}
    priority = _TASK_CLASS_PRIORITY.get(task_class.value, [])

    for provider_id in priority:
        profile = PROVIDER_REGISTRY.get(provider_id)
        if profile is None or not profile.is_available:
            continue
        effective_health = overrides.get(provider_id, profile.health)
        if effective_health == ProviderHealth.UNAVAILABLE:
            continue
        return SelectionResult(
            task_class=task_class,
            selected_provider_id=provider_id,
            reason=f"priority-order;task_class={task_class.value};health={effective_health.value}",
            authority_ceiling=profile.authority_ceiling,
            gateway_required=profile.gateway_required,
            evidence_status=profile.evidence_status,
            cost_per_unit=profile.cost_per_unit,
            health=effective_health,
            acceptance_gates_unchanged=True,
        )

    return SelectionResult(
        task_class=task_class,
        selected_provider_id=None,
        reason=f"no-eligible-provider;task_class={task_class.value}",
        authority_ceiling="none",
        gateway_required=False,
        evidence_status=_NOT_AVAILABLE,
        cost_per_unit=_UNKNOWN,
        health=ProviderHealth.UNKNOWN,
        acceptance_gates_unchanged=True,
    )


# ---------------------------------------------------------------------------
# Mission Control readiness (no secrets)
# ---------------------------------------------------------------------------


def build_provider_readiness_report(
    health_overrides: dict[str, ProviderHealth] | None = None,
) -> dict[str, Any]:
    """Build a public readiness report for Mission Control.

    No credential values, API keys, or secrets appear in this output.
    """
    overrides = health_overrides or {}
    entries = []
    for pid, profile in PROVIDER_REGISTRY.items():
        effective_health = overrides.get(pid, profile.health)
        entries.append(
            {
                "provider_id": pid,
                "display_name": profile.display_name,
                "is_available": profile.is_available,
                "api_availability": profile.api_availability.value,
                "health": effective_health.value,
                "task_classes": sorted(tc.value for tc in profile.task_classes),
                "authority_ceiling": profile.authority_ceiling,
                "gateway_required": profile.gateway_required,
                "evidence_status": profile.evidence_status,
                "cost_per_unit": profile.cost_per_unit,
                "subscription_vs_api_billing": profile.subscription_vs_api_billing,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "provider_count": len(entries),
        "providers": entries,
        "graph_mutation": False,
        "secrets_emitted": False,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="OC provider economy registry CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("report", help="Print Mission Control readiness report")

    sel = sub.add_parser("select", help="Select provider for a task class")
    sel.add_argument("task_class", help="Task class (e.g. coding_repository_edit)")

    args = parser.parse_args()

    if args.command == "report":
        print(json.dumps(build_provider_readiness_report(), indent=2, sort_keys=True))
    elif args.command == "select":
        result = select_provider_for_task(args.task_class)
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
