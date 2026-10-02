from app.calyx_orchestrator.homeostasis import (
    HealthBand,
    InterventionKind,
    VitalSign,
    assess_homeostasis,
    escalate_external_request,
)


def test_healthy_signs_produce_no_interventions():
    assessment = assess_homeostasis([
        VitalSign("taxonomy_freshness_pct", 99.2, minimum=98.0),
        VitalSign("failed_jobs_pct", 0.5, maximum=2.0),
    ])
    assert assessment.status is HealthBand.HEALTHY
    assert assessment.interventions == ()


def test_knowledge_gap_requests_external_intelligence():
    assessment = assess_homeostasis([
        VitalSign("matrix_evidence_coverage_pct", 41.0, minimum=80.0)
    ])
    assert assessment.status is HealthBand.DEGRADED
    intent = assessment.interventions[0]
    assert intent.kind is InterventionKind.REQUEST_EXTERNAL_INTELLIGENCE
    assert intent.requires_external_provider is True
    assert intent.requires_owner_budget is False


def test_external_request_prefers_reuse_before_paid_provider():
    intent = assess_homeostasis([
        VitalSign("literature_evidence_coverage_pct", 20.0, minimum=80.0)
    ]).interventions[0]
    routed = escalate_external_request(
        intent,
        local_evidence_exhausted=False,
        cache_miss=True,
        free_source_unavailable=True,
        estimated_cost_usd=2.0,
        remaining_authorized_budget_usd=10.0,
    )
    assert routed.kind is InterventionKind.REFILL


def test_external_request_asks_owner_when_over_budget():
    intent = assess_homeostasis([
        VitalSign("literature_evidence_coverage_pct", 20.0, minimum=80.0)
    ]).interventions[0]
    routed = escalate_external_request(
        intent,
        local_evidence_exhausted=True,
        cache_miss=True,
        free_source_unavailable=True,
        estimated_cost_usd=12.0,
        remaining_authorized_budget_usd=5.0,
    )
    assert routed.kind is InterventionKind.REQUEST_OWNER_BUDGET
    assert routed.requires_owner_budget is True


def test_stale_observation_refreshes_before_other_actions():
    assessment = assess_homeostasis([
        VitalSign("taxonomy_freshness_pct", 99.0, minimum=98.0, stale=True)
    ])
    assert assessment.status is HealthBand.WATCH
    assert assessment.interventions[0].kind is InterventionKind.REFILL
