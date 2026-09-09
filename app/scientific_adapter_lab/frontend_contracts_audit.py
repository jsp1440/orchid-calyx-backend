"""Frontend/backend contracts audit — Approved Task Priority 36.

Inspect route parsing, schema compatibility, degraded states, auth boundaries,
and stale endpoint assumptions.

No live-model spending. No production mutation. Read-only static audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "frontend-contracts-audit/v1"
AUDIT_DATE = "2026-09-09"


class FrontendContractsAuditStatus:
    READY = "READY"
    GAP = "GAP"
    BLOCKED = "BLOCKED"
    OWNER_GATED = "OWNER_GATED"


@dataclass(frozen=True)
class FrontendContractsCriterion:
    criterion_id: str
    area: str
    title: str
    status: str
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


FRONTEND_CONTRACTS_CRITERIA: tuple[FrontendContractsCriterion, ...] = (

    # ------------------------------------------------------------------ ROUTE_SCHEMA
    FrontendContractsCriterion(
        criterion_id="route_schema_prefix_stable",
        area="route_schema",
        title="Route prefix stable — /api/vision-lexicon prefix is the canonical frontend contract",
        status=FrontendContractsAuditStatus.READY,
        authoritative_module="app.vision_lexicon.routes",
        evidence=(
            "router = APIRouter(prefix='/api/vision-lexicon', tags=['vision-lexicon']); "
            "routes: GET /status, POST /reference-sets, GET /reference-sets/{id}, "
            "GET /lexicon/concepts/{id}/reference-sets, POST /analyses, GET /analyses/{id}, "
            "GET /analyses/{id}/observations, GET /analyses/{id}/morphometrics, "
            "POST /figure-specifications, GET /figure-specifications/{id}, "
            "POST /validation-runs, GET /validation-runs/{id}, "
            "GET /reference-sets/{id}/aggregate-summary, "
            "GET /lexicon/concepts/{id}/vision-evidence, POST /reviews; "
            "prefix is the stable contract surface"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FrontendContractsCriterion(
        criterion_id="route_schema_runner_prefix",
        area="route_schema",
        title="Runtime runner prefix stable — /api/runner endpoints are the execution contract",
        status=FrontendContractsAuditStatus.READY,
        authoritative_module="runtime.executor_router",
        evidence=(
            "router = APIRouter(prefix='/api/runner', tags=['Calyx Runtime Executor']); "
            "POST /execute (queue), POST /execute/{module_id}, GET /executions, "
            "GET /executions/{id}, GET /history, GET /events (limit 1-500), "
            "POST /retry/{execution_id}, POST /cancel/{execution_id}; "
            "runner prefix is the stable runtime execution contract surface"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FrontendContractsCriterion(
        criterion_id="route_schema_version_field",
        area="route_schema",
        title="Schema version field — vision activation preflight exposes schema_version in response",
        status=FrontendContractsAuditStatus.READY,
        authoritative_module="app.vision_lexicon.preflight",
        evidence=(
            "preflight.py: 'schema_version': 'vision-activation-preflight/v2'; "
            "schema_ready: connectivity and schema_problem is None; "
            "schema_problem field surfaces schema validation failures to frontend; "
            "schema_version field allows frontend to detect preflight response format changes"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ DEGRADED_STATES
    FrontendContractsCriterion(
        criterion_id="degraded_fail_closed_no_db",
        area="degraded_states",
        title="Fail-closed on DB absence — vision routes fail closed when DATABASE_URL is not configured",
        status=FrontendContractsAuditStatus.READY,
        authoritative_module="app.vision_lexicon.routes",
        evidence=(
            "routes.py docstring: 'These routes are fail-closed unless the governed durable "
            "PostgreSQL path is enabled and its schema is available. Local/unit-test use may "
            "retain process-local memory'; "
            "preflight.py: persistence_activation_ready = database_url_configured and connectivity and schema_ready; "
            "DATABASE_URL absence → degraded/blocked, not silent success"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FrontendContractsCriterion(
        criterion_id="degraded_brain_integration",
        area="degraded_states",
        title="Brain integration degraded state — DATABASE_URL absence returns degraded-but-successful result",
        status=FrontendContractsAuditStatus.READY,
        authoritative_module="runtime.brain_integration",
        evidence=(
            "brain_integration.py docstring: 'When DATABASE_URL is unavailable the workers "
            "return a degraded-but-successful result'; "
            "self._degraded(): returns a marked degraded payload — not an exception; "
            "kernel_registry.py: KernelHealth = Literal['healthy', 'attention', 'degraded', 'critical', 'unknown']; "
            "degraded state is a first-class health value, not silently collapsed"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FrontendContractsCriterion(
        criterion_id="degraded_kernel_health_surface",
        area="degraded_states",
        title="Kernel health surfaced — degraded/critical kernels are listed and reported to frontend",
        status=FrontendContractsAuditStatus.READY,
        authoritative_module="runtime.kernel_registry",
        evidence=(
            "KernelStatus: active | planned | degraded | blocked | retired; "
            "KernelHealth: healthy | attention | degraded | critical | unknown; "
            "summarize_registry(): degraded = [id for health in {degraded, critical}]; "
            "summary: health='degraded' when any kernel degraded but none critical; "
            "degraded kernel list is returned to caller for frontend display"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ AUTH_BOUNDARIES
    FrontendContractsCriterion(
        criterion_id="auth_write_endpoints_api_key",
        area="auth_boundaries",
        title="Write endpoints require API key — POST/retry/cancel require X-API-Key header",
        status=FrontendContractsAuditStatus.READY,
        authoritative_module="runtime.executor_router",
        evidence=(
            "WRITE_AUTH = [Depends(verify_api_key)]; "
            "executor_router: POST /execute, POST /execute/{id}, POST /retry/{id}, POST /cancel/{id} "
            "all carry WRITE_AUTH = [Depends(verify_api_key)]; "
            "read endpoints (GET) do not require API key; "
            "mutation endpoints are uniformly write-auth gated"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FrontendContractsCriterion(
        criterion_id="auth_api_key_constant_time_compare",
        area="auth_boundaries",
        title="API key constant-time comparison — hmac.compare_digest prevents timing attacks",
        status=FrontendContractsAuditStatus.READY,
        authoritative_module="app.security.verify_api_key",
        evidence=(
            "verify_api_key(): hmac.compare_digest(api_key, expected_key); "
            "not expected_key → 401 'API key authentication is not configured'; "
            "not api_key or digest mismatch → 401 'Invalid or missing API key'; "
            "constant-time comparison prevents timing-based key extraction"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FrontendContractsCriterion(
        criterion_id="auth_owner_session_signed",
        area="auth_boundaries",
        title="Owner session token is HMAC-signed — session token is signed with CALYX_OWNER_SESSION_SECRET",
        status=FrontendContractsAuditStatus.READY,
        authoritative_module="app.security.create_owner_session_token",
        evidence=(
            "create_owner_session_token(): HMAC(key=secret.encode(), msg=payload.encode(), sha256); "
            "token = base64(payload).signature; "
            "not secret → 503 'Owner session signing is not configured'; "
            "verify_owner_access_code(): hmac.compare_digest(access_code, expected) — constant time; "
            "owner session is signed and token-TTL bounded"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FrontendContractsCriterion(
        criterion_id="auth_read_list_unauthenticated",
        area="auth_boundaries",
        title="Read/list endpoints are unauthenticated — GET executions/events/history require no key",
        status=FrontendContractsAuditStatus.READY,
        authoritative_module="runtime.executor_router",
        evidence=(
            "executor_router: GET /executions, GET /executions/{id}, GET /history, GET /events "
            "have no WRITE_AUTH dependency; "
            "read access does not require authentication — only write/mutation operations require API key; "
            "this is the explicit auth boundary design: read-public, write-authenticated"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ SCIENTIFIC_CONTRACT
    FrontendContractsCriterion(
        criterion_id="scientific_cannot_determine_preserved",
        area="scientific_contract",
        title="CANNOT_DETERMINE is a first-class outcome — never silently collapsed into PASS or FAIL",
        status=FrontendContractsAuditStatus.READY,
        authoritative_module="app.vision_lexicon.contracts.CharacterConformanceResult",
        evidence=(
            "CharacterConformanceResult: PASS | PARTIAL | FAIL | CANNOT_DETERMINE; "
            "contracts.py docstring: 'CANNOT_DETERMINE is preserved as a first-class outcome "
            "and must never be silently collapsed into PASS or FAIL'; "
            "CharacterConformanceCheck docstring: 'CANNOT_DETERMINE is a first-class result'; "
            "FrontendEvidenceSummary carries conformance results — frontend must handle all four states"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FrontendContractsCriterion(
        criterion_id="scientific_machine_generated_entry_state",
        area="scientific_contract",
        title="MACHINE_GENERATED is entry state — no auto-promotion from vision outputs",
        status=FrontendContractsAuditStatus.READY,
        authoritative_module="app.vision_lexicon.contracts.VisionReviewState",
        evidence=(
            "VisionReviewState: MACHINE_GENERATED | COMMUNITY_REVIEWED | EXPERT_REVIEWED | "
            "REVISION_REQUIRED | APPROVED | REJECTED | SCIENTIFIC_APPROVAL_PENDING; "
            "contracts.py docstring: 'MACHINE_GENERATED is the entry state for all Vision outputs. "
            "No automatic promotion to APPROVED without human review'; "
            "VisionReviewRecord.auto_promotion_blocked: bool; "
            "COMMUNITY tier review → auto_promotion_blocked must be True"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FrontendContractsCriterion(
        criterion_id="scientific_absolute_unit_calibration",
        area="scientific_contract",
        title="Absolute units require calibration — CharacterObservation and MorphometricObservation enforce this",
        status=FrontendContractsAuditStatus.READY,
        authoritative_module="app.vision_lexicon.contracts.CharacterObservation",
        evidence=(
            "CharacterObservation.validate(): unit not in _RELATIVE_UNITS and basis != CALIBRATED_SCALE "
            "→ ABSOLUTE_UNIT_REQUIRES_CALIBRATION; "
            "MorphometricObservation.validate(): metric_type.requires_calibration() and "
            "not calibration_state.is_calibrated() → ABSOLUTE_DIMENSION_REQUIRES_CALIBRATION; "
            "MetricType.requires_calibration(): True for ABSOLUTE_LENGTH/AREA/VOLUME"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FrontendContractsCriterion(
        criterion_id="scientific_color_evidence_bounded",
        area="scientific_contract",
        title="Color evidence bounded by phenotype class — vision alone cannot assert chemically verified pigment",
        status=FrontendContractsAuditStatus.READY,
        authoritative_module="app.vision_lexicon.contracts.ColorPhenotypeObservation",
        evidence=(
            "ColorPhenotypeClass: IMAGE_DERIVED | INFERRED_PIGMENT_CLASS | CHEMICALLY_VERIFIED; "
            "ColorPhenotypeObservation.validate(): phenotype_class != IMAGE_DERIVED and "
            "not pigment_evidence_source → PIGMENT_EVIDENCE_SOURCE_REQUIRED; "
            "Vision MUST NOT elevate image colour into CHEMICALLY_VERIFIED without independent evidence"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),

    # ------------------------------------------------------------------ FRONTEND_EVIDENCE_CONTRACT
    FrontendContractsCriterion(
        criterion_id="frontend_evidence_summary_flat",
        area="frontend_evidence_contract",
        title="FrontendEvidenceSummary is a flat contract — frontend does not reconstruct from raw DB tables",
        status=FrontendContractsAuditStatus.READY,
        authoritative_module="app.vision_lexicon.contracts.FrontendEvidenceSummary",
        evidence=(
            "FrontendEvidenceSummary (frozen dataclass): concept_id, concept_label, "
            "reference_sets, reference_images, vision_observations, morphometrics, "
            "aggregate_summary, figure_specifications, visual_assets, validation_runs, "
            "review_state, provenance, limitations; "
            "contracts.py: 'All scientific logic lives in the backend. The frontend must not "
            "need to reconstruct scientific assertions from raw database tables'"
        ),
        gap_description=None,
        blocker_reason=None,
        next_action=None,
    ),
    FrontendContractsCriterion(
        criterion_id="frontend_contract_stale_endpoint_risk",
        area="frontend_evidence_contract",
        title="Stale endpoint risk — live endpoint-to-schema validation requires DB access",
        status=FrontendContractsAuditStatus.BLOCKED,
        authoritative_module="app.vision_lexicon.routes",
        evidence=(
            "Route structure is statically auditable from source code; "
            "stale endpoint detection (mismatched frontend assumptions about field names, "
            "missing fields in live responses, schema drift from DB migrations) "
            "requires live integration testing against a running backend with DATABASE_URL"
        ),
        gap_description=None,
        blocker_reason="Live endpoint-to-schema compatibility testing requires DATABASE_URL and running backend — not available in this static audit context",
        next_action="Run integration tests against a live backend to detect stale endpoint assumptions and schema drift",
    ),
)


@dataclass
class FrontendContractsAudit:
    schema_version: str = SCHEMA_VERSION
    audit_date: str = AUDIT_DATE
    no_auto_publication: bool = True
    no_production_mutation: bool = True
    criteria: list[FrontendContractsCriterion] = field(default_factory=list)

    def by_status(self, status: str) -> list[FrontendContractsCriterion]:
        return [c for c in self.criteria if c.status == status]

    def by_area(self, area: str) -> list[FrontendContractsCriterion]:
        return [c for c in self.criteria if c.area == area]

    def ready_count(self) -> int:
        return len(self.by_status(FrontendContractsAuditStatus.READY))

    def gap_count(self) -> int:
        return len(self.by_status(FrontendContractsAuditStatus.GAP))

    def blocked_count(self) -> int:
        return len(self.by_status(FrontendContractsAuditStatus.BLOCKED))

    def owner_gated_count(self) -> int:
        return len(self.by_status(FrontendContractsAuditStatus.OWNER_GATED))

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


def get_frontend_contracts_audit() -> FrontendContractsAudit:
    return FrontendContractsAudit(criteria=list(FRONTEND_CONTRACTS_CRITERIA))


def get_criteria_by_status(status: str) -> list[FrontendContractsCriterion]:
    return [c for c in FRONTEND_CONTRACTS_CRITERIA if c.status == status]


def get_criteria_by_area(area: str) -> list[FrontendContractsCriterion]:
    return [c for c in FRONTEND_CONTRACTS_CRITERIA if c.area == area]


def get_gaps() -> list[FrontendContractsCriterion]:
    return get_criteria_by_status(FrontendContractsAuditStatus.GAP)


def get_next_actions() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": c.criterion_id,
            "area": c.area,
            "title": c.title,
            "status": c.status,
            "next_action": c.next_action,
        }
        for c in FRONTEND_CONTRACTS_CRITERIA
        if c.next_action
    ]
