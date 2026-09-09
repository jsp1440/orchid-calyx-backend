"""Calyx owner finish-line audit — Approved Task Priority 1.

Measures the exact remaining gaps before the owner can ask Calyx where the
Orchid Continuum stands and hold a grounded scientific conversation on phone/iPad.

Status vocabulary (KEEP/CONVERGE/SUPERSEDE/GAP mirrors the inventory pattern):
  READY        — implemented, tested, and merged into the integration branch
  GAP          — described in the acceptance criteria but not yet wired end-to-end
  BLOCKED      — requires an external dependency that is unavailable (NO-API mode,
                 provider not connected, infrastructure not provisioned)
  OWNER_GATED  — requires explicit owner authorization before proceeding

No live-model spending. No taxonomy activation. No scientific publication.
No production KG mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "calyx-owner-finish-line/v1"
AUDIT_DATE = "2026-09-09"


class FinishLineStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class FinishLineCriterion:
    """One measurable criterion on the owner's Calyx finish line."""

    criterion_id: str
    area: str           # taxonomy | synthesis | vision | interaction | conservation
                        # | atlas | orchestrator | security | provider | kg
    title: str
    status: str         # FinishLineStatus constant
    authoritative_module: str
    evidence: str
    gap_description: str | None
    blocker_reason: str | None
    next_action: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "area": self.area,
            "title": self.title,
            "status": self.status,
            "authoritative_module": self.authoritative_module,
            "evidence": self.evidence,
            "gap_description": self.gap_description,
            "blocker_reason": self.blocker_reason,
            "next_action": self.next_action,
        }


# ---------------------------------------------------------------------------
# Canonical finish-line criteria
# ---------------------------------------------------------------------------

FINISH_LINE_CRITERIA: tuple[FinishLineCriterion, ...] = (

    # ------------------------------------------------------------------ SYNTHESIS
    FinishLineCriterion(
        criterion_id="synthesis_teaching_v1",
        area="synthesis",
        title="TeachingSynthesisV1 multi-domain composition contract",
        status=FinishLineStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis",
        evidence=(
            "build_teaching_synthesis() assembles 8-domain evidence; "
            "47 tests passing; merged via PR #1275 into oc-autonomous-integration"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FinishLineCriterion(
        criterion_id="synthesis_featured_genus",
        area="synthesis",
        title="Featured Genus 12-hour rotation pool (≥9 species, ~45-second active slot)",
        status=FinishLineStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.build_featured_genus_pool",
        evidence=(
            "build_featured_genus_pool() deterministic deduplication and stable sort; "
            "test_featured_pool_* tests cover >9 species, canonical identities, honest no-media"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FinishLineCriterion(
        criterion_id="synthesis_http_endpoint",
        area="synthesis",
        title="HTTP endpoint exposing TeachingSynthesisV1 to frontend/mobile",
        status=FinishLineStatus.GAP,
        authoritative_module="app.calyx_conversation.routes (not yet wired)",
        evidence="build_teaching_synthesis() exists but no /calyx/synthesis/{taxon} route registered",
        gap_description=(
            "No HTTP route exposes the synthesis contract. "
            "Frontend/iPad cannot retrieve a synthesized teaching payload without a bound endpoint."
        ),
        blocker_reason=None,
        next_action="Add GET /calyx/synthesis/{taxon_id} route in app/calyx_conversation/routes.py",
    ),
    FinishLineCriterion(
        criterion_id="synthesis_owner_narrative",
        area="synthesis",
        title="Owner narrative endpoint (/calyx-narrative) wired to synthesis contract",
        status=FinishLineStatus.GAP,
        authoritative_module="app.routers.owner_operations (narrative route exists, synthesis not injected)",
        evidence=(
            "GET /calyx-narrative registered in app/routers/owner_operations.py; "
            "does not call build_teaching_synthesis()"
        ),
        gap_description=(
            "The owner narrative route exists but returns a stub; "
            "TeachingSynthesisV1 needs to be injected as the response body."
        ),
        blocker_reason=None,
        next_action="Wire build_teaching_synthesis() into /calyx-narrative handler",
    ),

    # ------------------------------------------------------------------ INTERACTION
    FinishLineCriterion(
        criterion_id="interaction_globi_adapter",
        area="interaction",
        title="GloBI interaction laboratory — orchid-pollinator and mycorrhizal adapter",
        status=FinishLineStatus.READY,
        authoritative_module="app.scientific_adapter_lab.interaction_laboratory",
        evidence=(
            "normalize_interaction(), stage_interaction_for_review(), "
            "resolve_interaction_precedence(); 72 tests; PR #1307"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FinishLineCriterion(
        criterion_id="interaction_live_api",
        area="interaction",
        title="Live GloBI API connector (real data fetch)",
        status=FinishLineStatus.BLOCKED,
        authoritative_module="app.scientific_adapter_lab.interaction_laboratory.InteractionGateway",
        evidence="InteractionGateway(available=False) returns UNKNOWN sentinel; live path raises NotImplementedError",
        gap_description=None,
        blocker_reason=(
            "NO-API mode: live GloBI federation requires provider connector wiring "
            "beyond what is available in the current execution environment"
        ),
        next_action="Implement provider connector when execution environment permits outbound GloBI requests",
    ),

    # ------------------------------------------------------------------ VISION / MATRIX
    FinishLineCriterion(
        criterion_id="vision_matrix_proof",
        area="vision",
        title="Vision/Matrix/Glossary end-to-end proof path (Epidendrum fixture)",
        status=FinishLineStatus.READY,
        authoritative_module="app.scientific_adapter_lab.vision_matrix_proof",
        evidence=(
            "run_vision_matrix_proof() 5-stage fixture; 51 tests; "
            "capability inventory (316 lines); PR #1304"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FinishLineCriterion(
        criterion_id="vision_live_inference",
        area="vision",
        title="Live vision inference (owner submits orchid image from iPad)",
        status=FinishLineStatus.BLOCKED,
        authoritative_module="app.multimodal_intelligence.anthropic_vision_provider",
        evidence="AnthropicVisionProvider registered; NO-API mode prevents live calls",
        gap_description=None,
        blocker_reason=(
            "NO-API mode: live vision inference requires Anthropic Vision API access "
            "which is parked in the current execution environment"
        ),
        next_action="Activate vision provider when NO-API constraint lifts",
    ),

    # ------------------------------------------------------------------ CONSERVATION
    FinishLineCriterion(
        criterion_id="conservation_status_contract",
        area="conservation",
        title="Governed conservation status contract (IUCN/CITES/appendix)",
        status=FinishLineStatus.READY,
        authoritative_module="app.calyx_orchestrator.conservation_status",
        evidence=(
            "ConservationStatusRecord with review_required=True, graph_mutation=False; "
            "merged into oc-autonomous-integration (commit 546f3c7f)"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ ATLAS
    FinishLineCriterion(
        criterion_id="atlas_product_path",
        area="atlas",
        title="Atlas product path contract (governed deeper-route identifier)",
        status=FinishLineStatus.READY,
        authoritative_module="app.calyx_orchestrator.atlas_product_path",
        evidence=(
            "AtlasProductPath with review_required=True, graph_mutation=False; "
            "merged into oc-autonomous-integration (commit ab35281)"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ DOMAIN ADAPTERS
    FinishLineCriterion(
        criterion_id="domain_molecular_sequence",
        area="taxonomy",
        title="Molecular sequence / GenBank / ITS accession adapter",
        status=FinishLineStatus.READY,
        authoritative_module="app.scientific_adapter_lab.molecular_sequence",
        evidence="MolecularSequenceRecord frozen dataclass; validate(); 63 tests in PR #1304",
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FinishLineCriterion(
        criterion_id="domain_coverage_matrix",
        area="taxonomy",
        title="Scientific coverage matrix (domain × evidence-state accounting)",
        status=FinishLineStatus.READY,
        authoritative_module="app.scientific_adapter_lab.coverage_matrix",
        evidence="CoverageMatrix with DomainCoverage rows; 63 tests passing; PR #1304",
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ ORCHESTRATOR
    FinishLineCriterion(
        criterion_id="orchestrator_factory_bridge",
        area="orchestrator",
        title="Queue Bridge / Factory Bridge deterministic router",
        status=FinishLineStatus.READY,
        authoritative_module="app.calyx_orchestrator.factory_bridge",
        evidence=(
            "route_completion_to_factory() pure function; FactoryBridgeAction enum; "
            "PARK_PROVIDER_REQUIRED for NO-API items"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FinishLineCriterion(
        criterion_id="orchestrator_show_management",
        area="orchestrator",
        title="Show management audit (shows / volunteers / judging / auth / notifications)",
        status=FinishLineStatus.READY,
        authoritative_module="app.scientific_adapter_lab.show_management_audit",
        evidence="ShowManagementAudit; 45 tests; PR #1304; require_judge gap owner-gated",
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    FinishLineCriterion(
        criterion_id="security_agent_gateway",
        area="security",
        title="Agent Security Gateway — no-bypass, no-weaken invariant",
        status=FinishLineStatus.READY,
        authoritative_module="app.calyx_orchestrator.agent_security_gateway",
        evidence=(
            "AgentSecurityGateway.evaluate() enforces hard stops; "
            "cannot be bypassed, disabled, or made permissive by CI"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ KG / PROVIDER
    FinishLineCriterion(
        criterion_id="kg_production_mutation",
        area="kg",
        title="Production Knowledge Graph mutation (canonical taxon/relationship writes)",
        status=FinishLineStatus.OWNER_GATED,
        authoritative_module="(all KG candidate contracts: review_required=True, graph_mutation=False)",
        evidence=(
            "KGCandidateInteraction, KGCandidateRecord all enforce "
            "review_required=True, auto_promotion_blocked=True, graph_mutation=False"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Owner authorization required before any production KG write",
    ),
    FinishLineCriterion(
        criterion_id="kg_taxonomy_activation",
        area="kg",
        title="Taxonomy activation (promoting staged taxa to canonical)",
        status=FinishLineStatus.OWNER_GATED,
        authoritative_module="(taxonomy activation blocked until owner authorizes)",
        evidence="No autonomous taxonomy activation path exists; owner signature required",
        gap_description=None,
        blocker_reason=None,
        next_action="Owner authorization required for taxonomy activation",
    ),
    FinishLineCriterion(
        criterion_id="provider_economy",
        area="provider",
        title="Provider economy routing (Kimi / Perplexity / Twin low-cost autonomy)",
        status=FinishLineStatus.BLOCKED,
        authoritative_module="(issue #1137, oc-queued, NO-API blocked)",
        evidence="Issue #1137 parked; NO-API mode prevents provider API evaluation",
        gap_description=None,
        blocker_reason="NO-API mode: provider evaluation requires live billed model API access",
        next_action="Activate when NO-API constraint lifts and owner authorizes provider spend",
    ),
)


# ---------------------------------------------------------------------------
# Audit builders
# ---------------------------------------------------------------------------

@dataclass
class FinishLineAudit:
    """Machine-readable owner finish-line audit result."""

    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[FinishLineCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[FinishLineCriterion]:
        return [c for c in self.criteria if c.status == status]

    def ready_count(self) -> int:
        return len(self.by_status(FinishLineStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(FinishLineStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(FinishLineStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(FinishLineStatus.OWNER_GATED))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "audit_date": self.audit_date,
            "no_auto_publication": self.no_auto_publication,
            "no_production_mutation": self.no_production_mutation,
            "summary": {
                "total": len(self.criteria),
                "ready": self.ready_count(),
                "gap": self.gap_count(),
                "blocked": self.blocked_count(),
                "owner_gated": self.owner_gated_count(),
            },
            "criteria": [c.to_dict() for c in self.criteria],
        }

    def serialize_as_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2)


def get_finish_line_audit() -> FinishLineAudit:
    """Return the current owner finish-line audit. Pure function — no external calls."""
    return FinishLineAudit(criteria=list(FINISH_LINE_CRITERIA))


def get_criteria_by_status(status: str) -> list[FinishLineCriterion]:
    """Filter criteria by status."""
    return [c for c in FINISH_LINE_CRITERIA if c.status == status]


def get_gaps() -> list[FinishLineCriterion]:
    """Return criteria with GAP status — items blocking the owner experience."""
    return get_criteria_by_status(FinishLineStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    """Return actionable next steps — criteria with a defined next_action."""
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in FINISH_LINE_CRITERIA
        if c.next_action
    ]
