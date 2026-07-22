from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .models import LifecycleState
from .service import DesignPlanningService


ACTOR = "build-090c-planning-demonstration"
PROVENANCE = {
    "source_type": "OWNER_APPROVED_BUILD_SPECIFICATION",
    "source_id": "BUILD-090C",
    "version": "1",
    "content_hash": "c69a90c00000000000000000000000000000000000000000000000000000000",
}

GOALS = (
    "personal orchid collection",
    "QR code identification",
    "plant passport",
    "photographs",
    "tag history",
    "taxonomy",
    "parentage",
    "blooming history",
    "repotting history",
    "culture history",
    "environmental sensor integration",
    "greenhouse locations",
    "inventory",
    "reminders",
    "awards",
    "provenance",
    "exports",
    "future Knowledge Graph integration",
)

REASONING_AREAS = (
    (
        "navigation",
        "Use task-oriented primary navigation with collection, activity, reports, and settings.",
        ("feature-first navigation", "single long page"),
    ),
    (
        "collection workflow",
        "Make the collection inventory the stable home for filtering, bulk review, and plant access.",
        ("dashboard-only access", "location-only hierarchy"),
    ),
    (
        "search",
        "Use one collection search with explicit filters and scientific-name-aware results.",
        ("separate search per data type", "free-text results without filters"),
    ),
    (
        "QR workflow",
        "Resolve a scanned identifier to a plant passport, with explicit unknown and duplicate states.",
        ("open edit immediately", "encode mutable plant data in QR"),
    ),
    (
        "plant detail pages",
        "Use a provenance-visible passport with observation, history, media, and care sections.",
        ("one dense form", "separate disconnected records"),
    ),
    (
        "editing workflow",
        "Use task-specific append flows for repotting, bloom, culture, tag, and media history.",
        ("overwrite current values", "one universal event form"),
    ),
    (
        "environmental integration",
        "Show sensor readings with location, time range, units, gaps, and device provenance.",
        ("unqualified current number", "automatic culture conclusions"),
    ),
    (
        "reminders",
        "Connect reminders to plants, tasks, due windows, completion history, and accessibility-safe alerts.",
        ("global unlinked reminders", "notification-only history"),
    ),
    (
        "accessibility",
        "Require semantic structure, keyboard operation, visible focus, reduced motion, and text alternatives.",
        ("visual-only controls", "post-implementation accessibility review"),
    ),
    (
        "scientific presentation",
        "Preserve accepted names, synonyms, parentage, uncertainty, sources, and observation-versus-interpretation distinctions.",
        ("single simplified display name", "hide uncertain taxonomy"),
    ),
)

CONFLICTS = (
    (
        "simplicity-science",
        "REQUIREMENT_VS_SCIENTIFIC_INTEGRITY",
        ("simple plant card", "complete scientific context"),
        (4, 2),
        "SCIENTIFIC",
    ),
    (
        "mobile-desktop",
        "REQUIREMENT_VS_TECHNICAL_CONSTRAINT",
        ("rapid mobile field work", "dense desktop management"),
        (4, 5),
        "UX",
    ),
    (
        "rapid-validation",
        "PERFORMANCE_VS_USABILITY",
        ("rapid plant entry", "validated scientific and provenance fields"),
        (4, 2),
        "PRODUCT_OWNER",
    ),
    (
        "privacy-sharing",
        "REQUIREMENT_VS_PRIVACY",
        ("collection sharing", "private locality and ownership data"),
        (4, 1),
        "PRIVACY_SECURITY",
    ),
    (
        "novice-expert",
        "REQUIREMENT_VS_DESIGN_GUIDANCE",
        ("plain novice workflow", "expert taxonomic detail"),
        (4, 7),
        "UX",
    ),
)

SCREEN_NAMES = (
    "Dashboard",
    "My Plants",
    "Plant Detail",
    "QR Scanner",
    "Add Plant",
    "Repot Plant",
    "Bloom History",
    "Environmental History",
    "Media Gallery",
    "Search",
    "Reports",
    "Settings",
)


@dataclass(frozen=True)
class DemonstrationResult:
    product_request_id: str
    context_snapshot_id: str
    evidence_package_id: str
    reasoning_record_ids: tuple[str, ...]
    conflict_record_ids: tuple[str, ...]
    draft_plan_id: str
    review_plan_id: str
    audit_event_count: int


class MyConservatoryPlanningDemonstration:
    """Deterministically exercises BUILD-090 without producing interface code."""

    VERSION = "090c-my-conservatory-1"

    def __init__(self, service: DesignPlanningService) -> None:
        self.service = service

    def execute(self) -> DemonstrationResult:
        request = self.service.create_product_request(self._product_request(), ACTOR)
        context = self.service.create_context(
            request.request_id, self._context(), ACTOR
        )
        evidence = self.service.build_evidence(
            request.request_id, context.snapshot_id, self._evidence_request(), ACTOR
        )
        reasoning = tuple(
            self.service.create_reasoning(
                self._reasoning_payload(
                    request, context, evidence, area, recommendation, alternatives
                ),
                ACTOR,
            )
            for area, recommendation, alternatives in REASONING_AREAS
        )
        conflicts = tuple(
            self.service.create_conflict(
                self._conflict_payload(request, context, evidence, *definition), ACTOR
            )
            for definition in CONFLICTS
        )
        draft = self.service.create_plan(
            self._plan_payload(request, context, evidence, reasoning, conflicts), ACTOR
        )
        review = self.service.transition_plan(
            draft.interface_plan_id, LifecycleState.REVIEW_REQUIRED, ACTOR
        )
        return DemonstrationResult(
            product_request_id=request.request_id,
            context_snapshot_id=context.snapshot_id,
            evidence_package_id=evidence.evidence_package_id,
            reasoning_record_ids=tuple(item.reasoning_record_id for item in reasoning),
            conflict_record_ids=tuple(item.conflict_id for item in conflicts),
            draft_plan_id=draft.interface_plan_id,
            review_plan_id=review.interface_plan_id,
            audit_event_count=len(self.service.repository.audits()),
        )

    @staticmethod
    def _product_request() -> dict[str, Any]:
        requirements = []
        for index, goal in enumerate(GOALS, 1):
            requirements.append(
                {
                    "requirement_id": f"mc-req-{index:02d}",
                    "category": "SCIENTIFIC"
                    if goal
                    in {
                        "taxonomy",
                        "parentage",
                        "provenance",
                        "future Knowledge Graph integration",
                    }
                    else "PRODUCT",
                    "statement": f"My Conservatory must support {goal}.",
                    "status": "CONFIRMED",
                    "source": "BUILD-090C owner-approved specification",
                    "rationale": "Explicit demonstration requirement.",
                    "priority": "HIGH" if index <= 8 else "NORMAL",
                    "hard_constraint": goal in {"taxonomy", "provenance"},
                    "provenance": [PROVENANCE],
                }
            )
        return {
            "logical_key": "my-conservatory",
            "product_name": "My Conservatory",
            "product_family": "Orchid Continuum",
            "business_objective": "Provide an owner-controlled personal orchid collection system.",
            "scientific_objective": "Preserve taxonomic, parentage, observation, and provenance context.",
            "educational_objective": "Help growers understand plant history and culture without false certainty.",
            "intended_users": ["orchid growers", "collection managers", "researchers"],
            "user_roles": [
                "collection owner",
                "authorized collaborator",
                "read-only guest",
            ],
            "primary_tasks": list(GOALS[:14]),
            "secondary_tasks": list(GOALS[14:]),
            "required_data": [
                "plant identity",
                "taxonomy",
                "events",
                "media",
                "sensors",
                "locations",
                "provenance",
            ],
            "required_workflows": [
                "identify",
                "add",
                "edit",
                "record event",
                "search",
                "report",
                "export",
            ],
            "platform_targets": ["responsive web"],
            "device_targets": ["mobile", "tablet", "desktop"],
            "accessibility_requirements": [
                "keyboard",
                "screen reader",
                "visible focus",
                "reduced motion",
                "chart alternatives",
            ],
            "privacy_requirements": [
                "private by default",
                "protected locality",
                "owner-controlled sharing",
            ],
            "security_requirements": [
                "authenticated writes",
                "role-aware access",
                "immutable audit",
            ],
            "rights_and_licensing_constraints": [
                "respect media licenses",
                "internal design corpus is not redistributable",
            ],
            "integration_dependencies": [
                "taxonomy services",
                "QR identifiers",
                "environmental sensors",
                "future graph read adapter",
            ],
            "performance_expectations": [
                "bounded collection search",
                "responsive scan resolution",
                "paginated histories",
            ],
            "branding_constraints": ["Orchid Continuum conventions"],
            "known_design_decisions": [
                "append history rather than overwrite",
                "provenance visible where decisions are made",
            ],
            "unresolved_questions": [
                "sharing policy granularity",
                "supported sensor protocols",
                "offline scan requirements",
            ],
            "excluded_scope": [
                "frontend implementation",
                "Knowledge Graph publication",
                "implementation authorization",
            ],
            "priority": "HIGH",
            "requested_delivery_phase": "INTERFACE_PLANNING",
            "requirements": requirements,
        }

    @staticmethod
    def _context() -> dict[str, Any]:
        definitions = (
            (
                "BUILD_089_CORPUS",
                "corpus/design_intelligence/build-089c",
                7,
                "USER_SUPPLIED_INTERNAL_RESEARCH_ONLY",
            ),
            (
                "BUILD_090_ARCHITECTURE",
                "docs/BUILD-090A-DESIGN-REASONING-INTERFACE-PLANNING-ARCHITECTURE.md",
                5,
                "INTERNAL_APPROVED",
            ),
            (
                "ORCHID_CONTINUUM_CONVENTIONS",
                "owner:orchid-continuum",
                4,
                "OWNER_APPROVED",
            ),
            ("SCIENTIFIC_REQUIREMENTS", "BUILD-087", 2, "INTERNAL_APPROVED"),
            (
                "ACCESSIBILITY_REQUIREMENTS",
                "WCAG-aligned-owner-policy",
                3,
                "OWNER_APPROVED",
            ),
            ("EDUCATIONAL_GOALS", "BUILD-090C", 4, "OWNER_APPROVED"),
            ("COLLECTION_MANAGEMENT", "BUILD-090C", 4, "OWNER_APPROVED"),
            ("PRIVACY_REQUIREMENTS", "owner:privacy-policy", 1, "RESTRICTED"),
            ("PROVENANCE_RULES", "BUILD-082-through-090", 2, "INTERNAL_APPROVED"),
        )
        return {
            "logical_key": "my-conservatory-context",
            "items": [
                {
                    "item_id": f"mc-context-{index:02d}",
                    "item_type": kind,
                    "source_reference": source,
                    "authority_level": authority,
                    "content_hash": f"{index:064x}",
                    "provenance": (PROVENANCE,),
                    "rights_classification": rights,
                    "effective_version": "1",
                    "status": "ACTIVE",
                    "hard_constraint": kind
                    in {
                        "SCIENTIFIC_REQUIREMENTS",
                        "ACCESSIBILITY_REQUIREMENTS",
                        "PRIVACY_REQUIREMENTS",
                        "PROVENANCE_RULES",
                    },
                }
                for index, (kind, source, authority, rights) in enumerate(
                    definitions, 1
                )
            ],
            "freshness_deadline": datetime(2099, 1, 1, tzinfo=timezone.utc),
            "inaccessible_sources": [],
        }

    @staticmethod
    def _evidence_request() -> dict[str, Any]:
        return {
            "logical_key": "my-conservatory-evidence",
            "queries": [
                "accessible collection dashboard navigation and search",
                "mobile data entry progressive disclosure and validation",
                "motion reduced motion feedback recommendations",
                "scientific information visualization uncertainty provenance",
                "educational guidance cognitive load orchid collection",
            ],
            "domains": [
                "UX",
                "ACCESSIBILITY",
                "MOTION_DESIGN",
                "DASHBOARD_DESIGN",
                "SCIENTIFIC_VISUALIZATION",
                "EDUCATIONAL_PSYCHOLOGY",
                "COMPONENT_LIBRARIES",
                "BRANDING",
            ],
            "knowledge_types": [
                "GUIDELINE",
                "DESIGN_PRINCIPLE",
                "ACCESSIBILITY_REQUIREMENT",
            ],
            "requirement_ids": [
                f"mc-req-{index:02d}" for index in range(1, len(GOALS) + 1)
            ],
            "corpus_version": "BUILD-089C",
        }

    @staticmethod
    def _reasoning_payload(
        request, context, evidence, area, recommendation, alternatives
    ):
        refs = tuple(item.semantic_unit_id for item in evidence.ranked_results[:5])
        return {
            "logical_key": f"my-conservatory:{area}",
            "product_request_id": request.request_id,
            "context_snapshot_id": context.snapshot_id,
            "evidence_package_ids": [evidence.evidence_package_id],
            "affected_product_area": area,
            "affected_user_roles": request.user_roles,
            "affected_requirements": tuple(
                r.requirement_id for r in request.requirements
            ),
            "recommendation": recommendation,
            "considered_alternatives": alternatives,
            "selected_approach": recommendation,
            "rejected_alternatives": alternatives,
            "concise_decision_rationale": "The selected approach preserves confirmed requirements, explicit constraints, retrieved evidence, and known corpus gaps.",
            "supporting_evidence_references": refs,
            "conflicting_evidence_references": (),
            "assumptions": ("responsive authenticated web application",),
            "unresolved_questions": request.unresolved_questions,
            "risks": (
                "corpus coverage may be partial",
                "product validation remains future work",
            ),
            "effects": {
                "accessibility": (
                    "requires keyboard and screen-reader acceptance criteria",
                ),
                "scientific": ("preserves uncertainty and provenance",),
                "educational": ("uses staged disclosure",),
            },
            "implementation_implications": (
                "implementation requires a separately authorized future build",
            ),
            "confidence_factors": evidence.confidence_factors,
        }

    @staticmethod
    def _conflict_payload(
        request, context, evidence, key, conflict_type, refs, levels, owner
    ):
        return {
            "logical_key": f"my-conservatory:{key}",
            "product_request_id": request.request_id,
            "context_snapshot_id": context.snapshot_id,
            "evidence_package_ids": [evidence.evidence_package_id],
            "conflict_type": conflict_type,
            "conflicting_references": refs,
            "authority_levels": levels,
            "severity": "HIGH" if 1 in levels or 2 in levels else "MEDIUM",
            "affected_users": request.intended_users,
            "affected_workflows": request.required_workflows,
            "hard_constraint": 1 in levels or 2 in levels,
            "alternatives": refs,
            "recommended_resolution": "Route to the designated human decision owner without silently overriding either concern.",
            "evidence": tuple(
                item.semantic_unit_id for item in evidence.ranked_results[:3]
            ),
            "required_decision_owner_role": owner,
            "rationale": "Both concerns materially affect acceptance criteria and require an explicit reviewed disposition.",
        }

    @staticmethod
    def _screen(name: str, evidence_id: str) -> dict[str, Any]:
        slug = name.casefold().replace(" ", "-")
        return {
            "screen_id": f"mc-{slug}",
            "name": name,
            "purpose": f"Support the {name.casefold()} portion of the collection workflow.",
            "users": ["collection owner", "authorized collaborator"],
            "workflows": [name.casefold(), "return to plant passport"],
            "required_data": [
                "plant identifier",
                "authorized collection data",
                "provenance",
            ],
            "interactions": [
                "navigate",
                "filter or select",
                "confirm consequential actions",
            ],
            "accessibility": [
                "semantic heading",
                "keyboard operation",
                "visible focus",
                "announced status",
            ],
            "scientific_presentation": [
                "preserve scientific name and uncertainty",
                "show source and observation context",
            ],
            "error_handling": [
                "specific recoverable error",
                "preserve entered data",
                "no silent overwrite",
            ],
            "loading_states": ["named progress status", "retain navigation"],
            "empty_states": ["explain absence", "offer authorized next action"],
            "acceptance_criteria": [
                f"{name} is keyboard operable",
                f"{name} exposes relevant provenance",
            ],
            "evidence_references": [evidence_id],
        }

    def _plan_payload(self, request, context, evidence, reasoning, conflicts):
        screens = tuple(
            self._screen(name, evidence.evidence_package_id) for name in SCREEN_NAMES
        )
        criteria = tuple(
            {
                "criterion": item,
                "requirement_ids": [f"mc-req-{index:02d}"],
                "evidence_ids": [evidence.evidence_package_id],
            }
            for index, item in enumerate(
                (
                    "All primary workflows are reachable by keyboard.",
                    "Scientific names, uncertainty, and provenance remain visible.",
                    "QR failures and unknown identifiers are recoverable.",
                    "History events append without overwriting prior evidence.",
                    "Private locality and ownership data are protected by default.",
                ),
                1,
            )
        )
        return {
            "logical_key": "my-conservatory-interface-plan",
            "product_request_id": request.request_id,
            "context_snapshot_id": context.snapshot_id,
            "evidence_package_ids": [evidence.evidence_package_id],
            "reasoning_record_ids": [item.reasoning_record_id for item in reasoning],
            "conflict_record_ids": [item.conflict_id for item in conflicts],
            "sections": {
                "product_scope": list(GOALS),
                "user_journeys": [
                    "identify a plant by QR",
                    "add and document a plant",
                    "review care and environment history",
                    "search and export the collection",
                ],
                "information_architecture": {
                    "Dashboard": ["My Plants", "Reminders", "Recent Activity"],
                    "My Plants": ["Plant Detail", "Add Plant", "QR Scanner"],
                    "Plant Detail": [
                        "Bloom History",
                        "Repot Plant",
                        "Environmental History",
                        "Media Gallery",
                    ],
                    "Utilities": ["Search", "Reports", "Settings"],
                },
                "navigation_structure": [
                    "Dashboard",
                    "My Plants",
                    "Scan",
                    "Search",
                    "Reports",
                    "Settings",
                ],
                "view_inventory": screens,
                "primary_workflows": request.required_workflows,
                "states": {
                    "empty": "contextual guidance",
                    "loading": "announced bounded progress",
                    "failure": "recoverable error with preserved input",
                    "offline": "read-only cached identity where authorized",
                },
                "responsive_behavior": [
                    "mobile task focus",
                    "tablet adaptive panes",
                    "desktop collection workspace",
                ],
                "interaction_patterns": [
                    "progressive disclosure",
                    "append history event",
                    "confirm destructive intent",
                    "filter and sort",
                ],
                "component_requirements": [
                    "plant card",
                    "scientific name block",
                    "provenance disclosure",
                    "history timeline",
                    "accessible data table and chart alternative",
                ],
                "accessibility": {
                    "semantic_structure": True,
                    "keyboard": True,
                    "visible_focus": True,
                    "screen_reader": True,
                    "text_scaling": True,
                    "contrast": True,
                    "non_color_meaning": True,
                    "reduced_motion": True,
                    "chart_alternatives": True,
                },
                "scientific_interface": {
                    "scientific_names": True,
                    "authorship": True,
                    "accepted_names_and_synonyms": True,
                    "taxonomic_uncertainty": True,
                    "observation_vs_interpretation": True,
                    "geographic_and_temporal_scope": True,
                    "units_and_measurement_context": True,
                    "conservation_sensitivity": True,
                    "citations_and_provenance": True,
                },
                "educational_interactions": [
                    "plain-language explanation with expert detail available",
                    "do not attribute absent educational guidance to corpus",
                ],
                "content_strategy": [
                    "owner terminology plus scientific labels",
                    "confidence and gaps stated explicitly",
                ],
                "privacy_security": [
                    "private by default",
                    "role-aware sharing",
                    "protected locality",
                    "authenticated writes",
                ],
                "rights_and_attribution": list(evidence.rights_restrictions),
                "analytics_observability": [
                    "workflow failures",
                    "scan resolution latency",
                    "accessibility errors without sensitive content",
                ],
                "integration_dependencies": request.integration_dependencies,
            },
            "acceptance_criteria": criteria,
            "unresolved_questions": request.unresolved_questions,
            "corpus_gaps": evidence.known_corpus_gaps,
            "required_review_roles": [
                "PRODUCT_OWNER",
                "UX",
                "ACCESSIBILITY",
                "SCIENTIFIC",
                "PRIVACY_SECURITY",
                "TECHNICAL_FEASIBILITY",
            ],
        }
