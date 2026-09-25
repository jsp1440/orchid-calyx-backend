"""Provider-free evaluation feedback using the existing queue and memory contracts.

This adapter consumes frozen outputs only. It never invokes a provider, dispatches
a task, writes GitHub, activates a strategy, or publishes scientific knowledge.
The caller owns the existing evaluation repository and project-scoped DB session.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_GOVERNANCE,
    AUTH_REPO_EXEC,
    TaskLeaf,
)
from app.scientific_memory.schemas import (
    CaptureCreate,
    MemoryItemCreate,
    SourceReference,
)

from .evaluators import EvaluatorRegistry, FrozenEvaluationOutput
from .improvement_discovery import (
    ImprovementDiscoveryEngine,
    ImprovementEligibility,
    ImprovementHypothesis,
    ImprovementSignal,
    PriorImprovementOutcome,
)
from .models import (
    EvaluationCase,
    EvaluationTaskClass,
    MeasurementState,
    MetricValue,
    StrategyDecisionState,
    StrategySpec,
    stable_fingerprint,
)
from .promotion import (
    PromotionEvidence,
    PromotionOutcome,
    PromotionPolicy,
    decide_strategy,
)
from .repository import InMemoryEvaluationRepository
from .strategy_runner import (
    BoundedStrategyExperimentRunner,
    ExperimentBudget,
    StrategyExecutionArtifact,
)


@dataclass(frozen=True)
class FrozenStrategyFixture:
    output: FrozenEvaluationOutput
    cost_usd: MetricValue = field(
        default_factory=lambda: MetricValue(MeasurementState.UNKNOWN)
    )
    latency_ms: MetricValue = field(
        default_factory=lambda: MetricValue(MeasurementState.UNKNOWN)
    )
    usage_units: MetricValue = field(
        default_factory=lambda: MetricValue(MeasurementState.UNKNOWN)
    )


def improvement_task_leaf(
    signal: ImprovementSignal,
    hypothesis: ImprovementHypothesis,
    *,
    issue_number: int,
    dependencies: Iterable[str] = (),
    prior_outcomes: Iterable[PriorImprovementOutcome] = (),
) -> TaskLeaf:
    """Prepare a leaf; DeepOrchestrate owns registration, dependency gates and leases."""
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("existing positive GitHub issue identity is required")
    engine = ImprovementDiscoveryEngine()
    packet = engine.build_queue_packet(
        signal, hypothesis, prior_outcomes=prior_outcomes
    )
    owner_gate = "oc-blocked" in packet.labels
    return TaskLeaf(
        key=packet.capability,
        title=packet.title,
        repo="orchid-calyx-backend",
        module="app/evals",
        priority=1,
        authority_class=AUTH_GOVERNANCE if owner_gate else AUTH_REPO_EXEC,
        consequence_risk=signal.risk_class,
        providers=["provider-free"],
        dependencies=list(dependencies),
        issue_number=issue_number,
        acceptance_criteria=[*hypothesis.evaluation_plan, hypothesis.expected_effect],
        evidence={
            "hypothesis_fingerprint": hypothesis.fingerprint,
            "material_fingerprint": hypothesis.candidate_material_fingerprint,
            "rollback_strategy_fingerprint": hypothesis.rollback_strategy_fingerprint,
            "requires_evaluation": True,
            "automatic_promotion": False,
        },
    )


def evaluate_frozen_improvement(
    *,
    signal: ImprovementSignal,
    hypothesis: ImprovementHypothesis,
    task_class: EvaluationTaskClass,
    baseline: StrategySpec,
    candidate: StrategySpec,
    case: EvaluationCase,
    registry: EvaluatorRegistry,
    baseline_fixture: FrozenStrategyFixture,
    candidate_fixture: FrozenStrategyFixture,
    policy: PromotionPolicy,
    repository: InMemoryEvaluationRepository,
    issue_number: int,
) -> PromotionOutcome:
    """Evaluate one frozen pair and retain only a fixture-scoped recommendation.

    Explicit admission checks close gaps in the older promotion contract before
    it is reused: all configured gates must exist, boolean gates must be strict,
    and a quality promotion must require a positive material improvement.
    """
    engine = ImprovementDiscoveryEngine()
    eligibility = engine.classify_eligibility(signal, hypothesis)
    if eligibility == ImprovementEligibility.REQUIRES_OWNER:
        raise ValueError("owner-gated hypotheses cannot enter autonomous evaluation")
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("existing GitHub issue identity is required")
    if (
        task_class.task_class_id != hypothesis.task_class_id
        or task_class.risk_class != signal.risk_class
    ):
        raise ValueError("evaluation task/risk lineage mismatch")
    if hypothesis.baseline_strategy_fingerprint != baseline.fingerprint:
        raise ValueError("baseline identity mismatch")
    if hypothesis.candidate_strategy_ref != candidate.implementation_ref:
        raise ValueError("candidate identity mismatch")
    if any(spec.provider_ref or spec.model_ref for spec in (baseline, candidate)):
        raise ValueError("only provider-free frozen strategies are admitted")
    if any(
        not math.isfinite(value) or value <= 0
        for value in (
            policy.minimum_absolute_improvement,
            policy.minimum_cost_reduction_ratio,
            policy.minimum_latency_reduction_ratio,
        )
    ):
        raise ValueError("positive material improvement thresholds are required")
    if not task_class.mandatory_gate_ids:
        raise ValueError("mandatory safety/scientific gates are required")
    specs = registry.specs()
    ids = [spec.evaluator_id for spec in specs]
    if len(ids) != len(set(ids)):
        raise ValueError("ambiguous evaluator versions")
    required = set(task_class.mandatory_gate_ids)
    mandatory = {spec.evaluator_id for spec in specs if spec.mandatory_gate}
    if not required.issubset(mandatory) or task_class.primary_metric not in ids:
        raise ValueError("required evaluator missing from frozen registry")
    for fixture in (baseline_fixture, candidate_fixture):
        if fixture.output.task_class_id != task_class.task_class_id:
            raise ValueError("frozen output task class mismatch")
        for gate in mandatory:
            if type(fixture.output.payload.get(gate)) is not bool:
                raise ValueError("mandatory gate must be an explicit boolean")
        score = fixture.output.payload.get(task_class.primary_metric)
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
        ):
            raise ValueError("primary metric must be finite and measured")
        for metric in (fixture.cost_usd, fixture.latency_ms, fixture.usage_units):
            if metric.state == MeasurementState.MEASURED and (
                isinstance(metric.value, bool)
                or not math.isfinite(metric.value)
                or metric.value < 0
            ):
                raise ValueError(
                    "operational measurement must be finite and nonnegative"
                )

    fixtures = {
        baseline.fingerprint: baseline_fixture,
        candidate.fingerprint: candidate_fixture,
    }

    def frozen_executor(spec: StrategySpec, frozen_case: EvaluationCase):
        fixture = fixtures[spec.fingerprint]
        return StrategyExecutionArtifact(
            strategy_fingerprint=spec.fingerprint,
            case_fingerprint=frozen_case.fingerprint,
            output=fixture.output,
            cost_usd=fixture.cost_usd.value,
            latency_ms=fixture.latency_ms.value,
        )

    runner = BoundedStrategyExperimentRunner(registry, frozen_executor)
    experiment = runner.run(
        task_class_id=task_class.task_class_id,
        baseline=baseline,
        candidate=candidate,
        case=case,
        budget=ExperimentBudget(max_executions=2, max_retries_per_strategy=0),
    )
    result_sets = []
    for run, fixture in (
        (experiment.baseline_run, baseline_fixture),
        (experiment.candidate_run, candidate_fixture),
    ):
        results = tuple(
            replace(
                result,
                cost_usd=fixture.cost_usd,
                latency_ms=fixture.latency_ms,
                usage_units=fixture.usage_units,
            )
            for result in registry.evaluate(
                run_identity_fingerprint=run.identity_fingerprint, output=fixture.output
            )
        )
        result_sets.append(results)
        repository.put_run(run)
        for result in results:
            repository.put_result(result)
    evidence = PromotionEvidence(
        baseline_results=result_sets[0],
        candidate_results=result_sets[1],
        evaluator_set_fingerprint=registry.fingerprint,
        case_fingerprints=(case.fingerprint,),
        issue_refs=(f"jsp1440/orchid-calyx-backend#{issue_number}",),
        commit_shas=tuple(
            str(value) for value in case.provenance.get("commit_shas", ())
        ),
    )
    outcome = decide_strategy(
        task_class=task_class,
        baseline=baseline,
        candidate=candidate,
        evidence=evidence,
        policy=policy,
        decision_id=f"discovery:{stable_fingerprint((hypothesis.fingerprint, evidence.fingerprint, policy.version))}",
        scope={
            "fixture_only": True,
            "case_fingerprint": case.fingerprint,
            "issue_number": issue_number,
            "activation_authorized": False,
            "hypothesis_fingerprint": hypothesis.fingerprint,
        },
    )
    outcome = replace(
        outcome,
        memory_summary={
            **outcome.memory_summary,
            "operational_measurements": {
                role: {
                    name: {
                        "state": getattr(fixture, name).state.value,
                        "value": getattr(fixture, name).value,
                    }
                    for name in ("cost_usd", "latency_ms", "usage_units")
                }
                for role, fixture in (
                    ("baseline", baseline_fixture),
                    ("candidate", candidate_fixture),
                )
            },
        },
    )
    repository.put_task_class(task_class)
    repository.put_strategy(baseline)
    repository.put_strategy(candidate)
    repository.put_case(case)
    repository.put_decision(outcome.decision)
    return outcome


def improvement_memory_capture(
    signal: ImprovementSignal,
    hypothesis: ImprovementHypothesis,
    outcome: PromotionOutcome,
) -> CaptureCreate:
    """Build canonical ANALYSIS/RESEARCH_CONTEXT capture for ScientificMemoryService."""
    engine = ImprovementDiscoveryEngine()
    eligibility = engine.classify_eligibility(signal, hypothesis)
    decision = outcome.decision
    if (
        decision.task_class_id != hypothesis.task_class_id
        or decision.baseline_strategy_fingerprint
        != hypothesis.baseline_strategy_fingerprint
    ):
        raise ValueError("decision does not match hypothesis lineage")
    if (
        decision.scope.get("fixture_only") is not True
        or not decision.evaluation_fingerprints
    ):
        raise ValueError("fixture evaluation evidence is required")
    if decision.scope.get("hypothesis_fingerprint") != hypothesis.fingerprint:
        raise ValueError("decision hypothesis identity mismatch")
    summary = engine.scientific_memory_summary(signal, hypothesis, eligibility)
    summary.update(
        decision_state=decision.state.value,
        decision_fingerprint=decision.fingerprint,
        baseline_strategy_fingerprint=decision.baseline_strategy_fingerprint,
        candidate_strategy_fingerprint=decision.candidate_strategy_fingerprint,
        decision_policy_version=decision.decision_policy_version,
        evaluator_set_fingerprint=decision.provenance["evaluator_set_fingerprint"],
        case_fingerprints=list(decision.provenance["case_fingerprints"]),
        evaluation_fingerprints=list(decision.evaluation_fingerprints),
        measured_outcome=outcome.memory_summary["measured_outcome"],
        baseline_primary=outcome.memory_summary["baseline_primary"],
        candidate_primary=outcome.memory_summary["candidate_primary"],
        operational_measurements=outcome.memory_summary["operational_measurements"],
        fixture_only=True,
        activation_authorized=False,
        retest_condition="Material strategy, baseline, evaluator or frozen case change",
    )
    return CaptureCreate(
        origin="CALYX",
        name=f"OC-EVALS discovery {decision.fingerprint[:12]}",
        query=f"Evaluate bounded strategy for {hypothesis.task_class_id}",
        result_count_snapshot=1,
        items=[
            MemoryItemCreate(
                item_type="ANALYSIS",
                authority="RESEARCH_CONTEXT",
                statement=(
                    f"Provider-free fixture strategy decision: {decision.state.value}; "
                    f"measured outcome: {summary['measured_outcome']}. No strategy activation authorized."
                ),
                source=SourceReference(
                    identifier=f"oc-evals:{decision.fingerprint}",
                    rights_basis="METADATA_ONLY",
                ),
                structured_payload=summary,
            )
        ],
    )


def prior_outcomes_from_memory(
    recalled: dict[str, Any],
) -> tuple[PriorImprovementOutcome, ...]:
    """Read compact active research-context records, never scientific authority."""
    outcomes = []
    for item in recalled.get("items", ()):
        summary = item.get("structured_payload", {})
        if (
            item.get("active") is not True
            or item.get("authority") != "RESEARCH_CONTEXT"
            or summary.get("schema") != "oc.improvement-discovery-memory.v1"
        ):
            continue
        outcomes.append(
            PriorImprovementOutcome(
                hypothesis_fingerprint=summary["hypothesis_fingerprint"],
                signal_material_fingerprint=summary["signal_material_fingerprint"],
                decision_state=StrategyDecisionState(summary["decision_state"]),
                candidate_material_fingerprint=summary[
                    "candidate_material_fingerprint"
                ],
            )
        )
    return tuple(outcomes)
