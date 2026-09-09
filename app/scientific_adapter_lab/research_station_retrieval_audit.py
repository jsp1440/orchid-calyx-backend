"""Research Station retrieval audit — Approved Task Priority 18.

Inspects arbitrary-taxon literature/evidence retrieval: query planning,
source attribution, snippets, and failure states.

Status vocabulary:
  READY        — implemented, tested, and integrated
  GAP          — described in acceptance criteria but not yet closed
  BLOCKED      — requires external dependency (NO-API mode, unprovisioned infra)
  OWNER_GATED  — requires explicit owner authorization before proceeding

No live-model spending. No production KG mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "research-station-retrieval-audit/v1"
AUDIT_DATE = "2026-09-09"


class RetrievalAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class RetrievalAuditCriterion:
    """One measurable criterion in the research station retrieval audit."""

    criterion_id: str
    area: str        # query | planning | attribution | snippets | failure | literature | security
    title: str
    status: str      # RetrievalAuditStatus constant
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
# Canonical retrieval criteria
# ---------------------------------------------------------------------------

RETRIEVAL_AUDIT_CRITERIA: tuple[RetrievalAuditCriterion, ...] = (

    # ------------------------------------------------------------------ QUERY
    RetrievalAuditCriterion(
        criterion_id="query_retrieval_query_model",
        area="query",
        title="RetrievalQuery model — structured query with mode, collections, filters",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.evidence_retrieval.models.RetrievalQuery",
        evidence=(
            "RetrievalQuery: text, mode=HYBRID, collections, object_types, document_classes, "
            "authors, language, verification_state, review_state, temporal_status, "
            "intended_consumers, active_only, historical, limit (1-100), "
            "per_source_limit (1-20), offset (0-10000), parent_expansion, filters"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RetrievalAuditCriterion(
        criterion_id="query_limit_bounds_validation",
        area="query",
        title="Query limit bounds validation — ValueError on out-of-range limit/offset",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.evidence_retrieval.models.RetrievalQuery.__post_init__",
        evidence=(
            "RetrievalQuery.__post_init__(): raises ValueError('INVALID_RETRIEVAL_LIMIT') "
            "if not 1<=limit<=100 or not 1<=per_source_limit<=20 or not 0<=offset<=10000; "
            "bounded retrieval prevents runaway fetches"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RetrievalAuditCriterion(
        criterion_id="query_hybrid_mode",
        area="query",
        title="Hybrid retrieval mode — semantic vector + keyword fusion",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.evidence_retrieval.engine.RetrievalEngine.search",
        evidence=(
            "RetrievalEngine.search(): mode=HYBRID performs both semantic vector search "
            "and keyword match; cosine() similarity computed per candidate document; "
            "fused ranking combines semantic and lexical scores"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RetrievalAuditCriterion(
        criterion_id="query_semantic_index_availability",
        area="query",
        title="Semantic index availability check — SEMANTIC_INDEX_UNAVAILABLE on missing index",
        status=RetrievalAuditStatus.BLOCKED,
        authoritative_module="app.evidence_retrieval.engine.RetrievalEngine.search",
        evidence=(
            "search(): raises RuntimeError('SEMANTIC_INDEX_UNAVAILABLE') if semantic "
            "index is not initialized; _safe_retrieval() in speak_routes catches and "
            "returns empty result rather than crashing mobile shell"
        ),
        gap_description=None,
        blocker_reason=(
            "Semantic vector index not provisioned in this execution environment; "
            "semantic retrieval degraded_mode=True; keyword fallback still functions"
        ),
        next_action="Provision semantic index in deployment environment for hybrid retrieval",
    ),

    # ------------------------------------------------------------------ PLANNING
    RetrievalAuditCriterion(
        criterion_id="planning_parent_expansion",
        area="planning",
        title="Query planning — parent_expansion AUTO policy for document hierarchy",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.evidence_retrieval.engine.RetrievalEngine._expand",
        evidence=(
            "_expand(): parent_expansion=AUTO evaluates whether to fetch parent document "
            "for context enrichment; policy decisions per document type; "
            "bounded expansion: does not recurse indefinitely"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RetrievalAuditCriterion(
        criterion_id="planning_deep_research_limit",
        area="planning",
        title="Deep research retrieval planning — DEEP_RESEARCH_RETRIEVAL_LIMIT=20",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes._effective_retrieval_limit",
        evidence=(
            "_effective_retrieval_limit(): raises limit to DEEP_RESEARCH_RETRIEVAL_LIMIT=20 "
            "when deep research mode detected; _deep_research_requested() keyword detection; "
            "research_mode param: auto | always | never"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RetrievalAuditCriterion(
        criterion_id="planning_arbitrary_taxon_query",
        area="planning",
        title="Arbitrary taxon retrieval — no taxon_id restriction in RetrievalQuery",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.evidence_retrieval.models.RetrievalQuery",
        evidence=(
            "RetrievalQuery.text accepts any taxon name string; collections filter "
            "allows per-source scoping; no hardcoded taxon_id constraint; "
            "arbitrary orchid taxa retrievable by common or scientific name"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ ATTRIBUTION
    RetrievalAuditCriterion(
        criterion_id="attribution_source_locator",
        area="attribution",
        title="Source locator attribution — exact locator or EXACT_LOCATOR_UNAVAILABLE",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.evidence_retrieval.engine.RetrievalEngine._assemble",
        evidence=(
            "_assemble(): anchor_locator included in result document; "
            "fallback: 'locator': 'EXACT_LOCATOR_UNAVAILABLE' when anchor not computable; "
            "no fabricated locators: UNAVAILABLE string is the honest signal"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RetrievalAuditCriterion(
        criterion_id="attribution_ranking_explanation",
        area="attribution",
        title="Ranking explanation — ranking_explanation list in retrieval result",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.evidence_retrieval.engine.RetrievalEngine._assemble",
        evidence=(
            "_assemble(): 'ranking_explanation' list included in result; "
            "explains score components for each ranked document; "
            "mobile shell can surface ranking rationale to owner"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RetrievalAuditCriterion(
        criterion_id="attribution_reliability_score",
        area="attribution",
        title="Source reliability scoring — _reliability() per result document",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.evidence_retrieval.engine.RetrievalEngine._reliability",
        evidence=(
            "_reliability(): computes reliability score from document metadata; "
            "verification_state and review_state used in reliability computation; "
            "scores included in assembled result for downstream citation quality"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RetrievalAuditCriterion(
        criterion_id="attribution_temporal_status",
        area="attribution",
        title="Temporal status attribution — _temporal() freshness signal per result",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.evidence_retrieval.engine.RetrievalEngine._temporal",
        evidence=(
            "_temporal(): computes temporal freshness signal from document date metadata; "
            "temporal_status filter in RetrievalQuery; "
            "stale evidence can be filtered or flagged without suppression"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SNIPPETS
    RetrievalAuditCriterion(
        criterion_id="snippets_external_citations",
        area="snippets",
        title="External citation snippets — doi/pmid/pmcid/authors/title/journal extraction",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes._external_citations",
        evidence=(
            "_external_citations(): extracts doi, pmid, pmcid, authors, title, journal "
            "from retrieval external_literature results; "
            "citation snippets passed to mobile turn response for owner display"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RetrievalAuditCriterion(
        criterion_id="snippets_query_model_disclosure",
        area="snippets",
        title="Query model disclosure — query_model metadata in retrieval response",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.evidence_retrieval.engine.RetrievalEngine.search",
        evidence=(
            "search() result: 'query_model': self.provider.metadata if query_vector is not None "
            "else None; 'normalized_query': q.text; enables transparency about which embedding "
            "model generated the query vector"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ FAILURE
    RetrievalAuditCriterion(
        criterion_id="failure_safe_retrieval_fallback",
        area="failure",
        title="Safe retrieval fallback — _safe_retrieval() returns empty on exception",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes._safe_retrieval",
        evidence=(
            "_safe_retrieval(): catches all exceptions from RetrievalEngine.search(); "
            "returns empty dict rather than propagating crash to mobile shell; "
            "semantic_retrieval_degraded_mode=True surfaced in speak_status()"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RetrievalAuditCriterion(
        criterion_id="failure_unavailable_evidence_state",
        area="failure",
        title="Unavailable evidence state — UNAVAILABLE for all unreachable domains",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.calyx_conversation.teaching_synthesis.build_teaching_synthesis",
        evidence=(
            "build_teaching_synthesis(): evidence_state='unavailable' for each domain "
            "without a live provider; knowledge_gaps list enumerates all unavailable domains; "
            "synthesis still produced with explicit uncertainty disclosure"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RetrievalAuditCriterion(
        criterion_id="failure_live_europe_pmc",
        area="failure",
        title="Live Europe PMC retrieval — blocked by NO-API in current environment",
        status=RetrievalAuditStatus.BLOCKED,
        authoritative_module="app.calyx_orchestrator.research_executor.GovervedResearchExecutor",
        evidence=(
            "GovervedResearchExecutor: literature executor path requires live Europe PMC network; "
            "calyx_research_executor_audit: literature_executor_live_network is BLOCKED; "
            "_AUTHORITY all-False: no live network calls permitted in NO-API mode"
        ),
        gap_description=None,
        blocker_reason=(
            "Live Europe PMC network access not provisioned; "
            "NO-API mode blocks all external literature retrieval APIs"
        ),
        next_action="Activate live literature retrieval when network access and provider are provisioned",
    ),

    # ------------------------------------------------------------------ LITERATURE
    RetrievalAuditCriterion(
        criterion_id="literature_extraction_pipeline",
        area="literature",
        title="Literature extraction pipeline — literature_extraction module",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.literature_extraction",
        evidence=(
            "literature_extraction module: PDF metadata extraction, evidence spans, "
            "methods/results/conclusions parsing; citation extraction without fabrication; "
            "static pipeline operates without live model API calls"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    RetrievalAuditCriterion(
        criterion_id="literature_review_required_state",
        area="literature",
        title="Review required state — REVIEW_REQUIRED on external literature citations",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.calyx_conversation.speak_routes._external_citations",
        evidence=(
            "External citation items carry review_state='REVIEW_REQUIRED'; "
            "no autonomous literature promotion; owner must review before canonical use; "
            "automatic_publication=False enforced at speak_routes level"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SECURITY
    RetrievalAuditCriterion(
        criterion_id="security_no_autonomous_publication",
        area="security",
        title="No autonomous retrieval publication — review_required on all external results",
        status=RetrievalAuditStatus.OWNER_GATED,
        authoritative_module="app.calyx_conversation.speak_routes.speak_status",
        evidence=(
            "automatic_publication=False in speak_status; "
            "knowledge_graph_mutation=False in turn response; "
            "CLAUDE.md: never publish governed scientific knowledge without owner authorization"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action="Await explicit owner authorization before promoting any retrieval result to canonical KG",
    ),
    RetrievalAuditCriterion(
        criterion_id="security_internal_access_boundary",
        area="security",
        title="Internal access boundary — internal_access=False by default in RetrievalQuery",
        status=RetrievalAuditStatus.READY,
        authoritative_module="app.evidence_retrieval.models.RetrievalQuery",
        evidence=(
            "RetrievalQuery.internal_access=False by default; "
            "requires explicit True to access internal-only documents; "
            "owner-scoped sessions prevent cross-owner document access"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
)


# ---------------------------------------------------------------------------
# Audit builders
# ---------------------------------------------------------------------------

@dataclass
class ResearchStationRetrievalAudit:
    """Machine-readable research station retrieval audit result."""

    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[RetrievalAuditCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[RetrievalAuditCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[RetrievalAuditCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(RetrievalAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(RetrievalAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(RetrievalAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(RetrievalAuditStatus.OWNER_GATED))

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


def get_research_station_retrieval_audit() -> ResearchStationRetrievalAudit:
    """Return the current retrieval audit. Pure function — no external calls."""
    return ResearchStationRetrievalAudit(criteria=list(RETRIEVAL_AUDIT_CRITERIA))


def get_criteria_by_status(status: str) -> list[RetrievalAuditCriterion]:
    return [c for c in RETRIEVAL_AUDIT_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[RetrievalAuditCriterion]:
    return [c for c in RETRIEVAL_AUDIT_CRITERIA if c.area == area]


def get_gaps() -> list[RetrievalAuditCriterion]:
    return get_criteria_by_status(RetrievalAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in RETRIEVAL_AUDIT_CRITERIA
        if c.next_action
    ]
