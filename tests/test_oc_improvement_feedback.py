from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.deep_orchestrate import DeepOrchestrate, TaskState
from app.database import Base
from app.evals.evaluators import (
    EvaluatorRegistry,
    FrozenEvaluationOutput,
    boolean_field_evaluator,
    numeric_ratio_evaluator,
)
from app.evals.improvement_discovery import (
    ImprovementDiscoveryEngine,
    ImprovementHypothesis,
    ImprovementSignal,
    ImprovementSignalSource,
    PriorImprovementOutcome,
)
from app.evals.improvement_feedback import (
    FrozenStrategyFixture,
    evaluate_frozen_improvement,
    improvement_memory_capture,
    improvement_task_leaf,
    prior_outcomes_from_memory,
)
from app.evals.models import (
    EvaluationCase,
    EvaluationTaskClass,
    MeasurementState,
    MetricValue,
    StrategyDecisionState,
    StrategySpec,
)
from app.evals.promotion import PromotionPolicy
from app.evals.repository import InMemoryEvaluationRepository
from app.research_workspace.models import Project, SavedSearch
from app.scientific_memory.models import (
    ScientificMemoryCapture,
    ScientificMemoryDecision,
    ScientificMemoryItem,
)
from app.scientific_memory.service import ScientificMemoryError, ScientificMemoryService
from runtime.deep_orchestrate_queue_bridge import plan_deep_orchestrate_refill
from scripts.oc_swarm_dependency_graph import build_dependency_graph
from scripts.oc_swarm_resource_locks import infer_resources

FROZEN_BASELINE = json.loads(
    (Path(__file__).parent / "fixtures/evals/discovery-admission.json").read_text()
)
GATES = ("owner_gate_preserved", "no_external_side_effects", "rollback_retained")


def registry():
    result = EvaluatorRegistry()
    for gate in GATES:
        result.register(
            *boolean_field_evaluator(
                evaluator_id=gate,
                version="1",
                field_name=gate,
                category="safety",
                mandatory_gate=True,
            )
        )
    result.register(
        *numeric_ratio_evaluator(
            evaluator_id="packet_contract_accuracy",
            version="1",
            field_name="packet_contract_accuracy",
            category="task",
        )
    )
    return result


def strategy(name):
    return StrategySpec(name, "1", "queue-admission", f"repository-fixture:{name}:v1")


def inputs(*, material="m1", risk="low"):
    baseline, candidate = strategy("baseline-3a5b43df"), strategy("material-admission")
    sig = ImprovementSignal(
        "s",
        "1",
        ImprovementSignalSource.EVALUATION,
        "queue-admission",
        risk,
        "Repeated no-benefit queue packets",
        ("issue:#1396",),
        material,
        measured_metric="packet_contract_accuracy",
        measured_value=0.4,
    )
    hyp = ImprovementHypothesis(
        "material-admission",
        "1",
        sig.fingerprint,
        "queue-admission",
        risk,
        "Check prior outcomes during queue admission",
        "Increase admission correctness while preserving all owner gates",
        "packet_contract_accuracy",
        baseline.fingerprint,
        candidate.implementation_ref,
        baseline.fingerprint,
        (
            "Compare frozen queue scenarios",
            "Require explicit safety gates",
            "Retain rollback",
        ),
        sig.evidence_refs,
        material,
    )
    return sig, hyp, baseline, candidate


def candidate_admission_results():
    decisions = []
    for scenario in FROZEN_BASELINE["scenarios"]:
        name = scenario["name"]
        sig, hyp, _, _ = inputs(risk="high" if name == "owner-gated" else "low")
        prior = PriorImprovementOutcome(
            hyp.fingerprint,
            sig.material_fingerprint,
            StrategyDecisionState.KEEP_BASELINE,
            hyp.candidate_material_fingerprint,
        )
        if name == "material-change":
            sig, hyp, _, _ = inputs(material="m2")
        if name == "editorial-replay":
            hyp = replace(
                hyp, proposed_change="Same implementation with edited description"
            )
        history = (
            [prior]
            if name in {"no-benefit", "editorial-replay", "material-change"}
            else []
        )
        try:
            packet = ImprovementDiscoveryEngine().build_queue_packet(
                sig, hyp, prior_outcomes=history
            )
            admitted = "oc-queued" in packet.labels
        except ValueError as error:
            assert "suppressed" in str(error)
            admitted = False
        decisions.append(admitted)
    return decisions


def evaluation_args(*, candidate_score=None, unsafe=False):
    sig, hyp, baseline, candidate = inputs()
    measured = (
        sum(
            item["expected_admission"] == actual
            for item, actual in zip(
                FROZEN_BASELINE["scenarios"], candidate_admission_results(), strict=True
            )
        )
        / FROZEN_BASELINE["case_count"]
    )
    baseline_payload = {gate: True for gate in GATES}
    baseline_payload.update(
        owner_gate_preserved=False,
        packet_contract_accuracy=FROZEN_BASELINE["baseline_correct"]
        / FROZEN_BASELINE["case_count"],
    )
    candidate_payload = {gate: True for gate in GATES}
    candidate_payload.update(
        owner_gate_preserved=not unsafe,
        packet_contract_accuracy=measured
        if candidate_score is None
        else candidate_score,
    )
    unavailable_cost = MetricValue(MeasurementState.UNAVAILABLE)
    return {
        "signal": sig,
        "hypothesis": hyp,
        "baseline": baseline,
        "candidate": candidate,
        "task_class": EvaluationTaskClass(
            "queue-admission", "1", "low", "packet_contract_accuracy", GATES
        ),
        "case": EvaluationCase(
            "discovery-admission-five-scenarios",
            "1",
            "queue-admission",
            "tests/fixtures/evals/discovery-admission.json",
            provenance={"commit_shas": [FROZEN_BASELINE["baseline_commit"]]},
        ),
        "registry": registry(),
        "baseline_fixture": FrozenStrategyFixture(
            FrozenEvaluationOutput("baseline", "queue-admission", baseline_payload),
            cost_usd=unavailable_cost,
        ),
        "candidate_fixture": FrozenStrategyFixture(
            FrozenEvaluationOutput("candidate", "queue-admission", candidate_payload),
            cost_usd=unavailable_cost,
        ),
        "policy": PromotionPolicy(
            version="discovery-admission.v1",
            minimum_primary_score=0.4,
            minimum_absolute_improvement=0.1,
            minimum_cost_reduction_ratio=0.2,
            minimum_latency_reduction_ratio=0.2,
        ),
        "repository": InMemoryEvaluationRepository(),
        "issue_number": 1396,
    }


@pytest.fixture()
def memory_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        execution_options={"schema_translate_map": {"research_station": None}},
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Project.__table__,
            SavedSearch.__table__,
            ScientificMemoryCapture.__table__,
            ScientificMemoryItem.__table__,
            ScientificMemoryDecision.__table__,
        ],
    )
    with Session(engine) as db:
        project = Project(
            owner_subject="fixture-owner", title="OC-EVALS fixture workspace"
        )
        db.add(project)
        db.commit()
        yield db, project


def test_measured_discovery_to_queue_evaluation_memory_and_replay(memory_db):
    args = evaluation_args()
    sig, hyp = args["signal"], args["hypothesis"]
    orchestrator = DeepOrchestrate(configured_width=2)
    leaf = improvement_task_leaf(sig, hyp, issue_number=1396)
    assert orchestrator.register(leaf) is True
    assert (
        orchestrator.register(improvement_task_leaf(sig, hyp, issue_number=1396))
        is False
    )
    plan = plan_deep_orchestrate_refill(
        orchestrator,
        {"issues": [], "leases": [], "dispatch_fingerprints": []},
        reserve_depth=1,
    )
    assert plan["proposals"][0]["source_ref"] == "#1396"
    assert plan["provider_launch_authorized"] is False

    outcome = evaluate_frozen_improvement(**args)
    assert outcome.decision.state == StrategyDecisionState.PROMOTE
    assert outcome.memory_summary["baseline_primary"] == 0.4
    assert outcome.memory_summary["candidate_primary"] == 1.0
    assert (
        outcome.decision.rollback_strategy_fingerprint == args["baseline"].fingerprint
    )
    assert outcome.decision.scope["activation_authorized"] is False
    assert outcome.decision.scope["fixture_only"] is True
    repeated = evaluate_frozen_improvement(**args)
    assert repeated == outcome
    assert len(args["repository"].decisions) == 1
    assert len(args["repository"].runs) == 2

    db, project = memory_db
    service = ScientificMemoryService()
    payload = improvement_memory_capture(sig, hyp, outcome)
    first = service.create_capture(db, project.project_id, "fixture-owner", payload)
    replay = service.create_capture(db, project.project_id, "fixture-owner", payload)
    assert first["capture_id"] == replay["capture_id"]
    assert replay["idempotent_replay"] is True
    recalled = service.recall(db, project.project_id, "fixture-owner")
    assert recalled["calyx_context"]["source_evidence"] == []
    assert recalled["items"][0]["item_type"] == "ANALYSIS"
    summary = recalled["items"][0]["structured_payload"]
    assert summary["operational_measurements"]["candidate"]["cost_usd"] == {
        "state": "UNAVAILABLE",
        "value": None,
    }
    assert summary["operational_measurements"]["candidate"]["latency_ms"] == {
        "state": "UNKNOWN",
        "value": None,
    }
    prior = prior_outcomes_from_memory(recalled)
    with pytest.raises(ValueError, match="suppressed"):
        improvement_task_leaf(sig, hyp, issue_number=1396, prior_outcomes=prior)
    changed_sig, changed_hyp, _, _ = inputs(material="new-evaluation-case")
    next_leaf = improvement_task_leaf(
        changed_sig, changed_hyp, issue_number=1396, prior_outcomes=prior
    )
    assert next_leaf.key != leaf.key
    with pytest.raises(ScientificMemoryError):
        service.recall(db, project.project_id, "other-owner")


@pytest.mark.parametrize(
    "score,unsafe,state",
    [
        (0.4, False, StrategyDecisionState.KEEP_BASELINE),
        (1.0, True, StrategyDecisionState.REJECT_SAFETY),
    ],
)
def test_no_benefit_and_unsafe_outcomes_return_to_suppression(
    memory_db, score, unsafe, state
):
    args = evaluation_args(candidate_score=score, unsafe=unsafe)
    outcome = evaluate_frozen_improvement(**args)
    assert outcome.decision.state == state
    db, project = memory_db
    service = ScientificMemoryService()
    service.create_capture(
        db,
        project.project_id,
        "fixture-owner",
        improvement_memory_capture(args["signal"], args["hypothesis"], outcome),
    )
    history = prior_outcomes_from_memory(
        service.recall(db, project.project_id, "fixture-owner")
    )
    with pytest.raises(ValueError, match="suppressed"):
        improvement_task_leaf(
            args["signal"],
            args["hypothesis"],
            issue_number=1396,
            prior_outcomes=history,
        )


def test_canonical_dependency_resource_markers_and_owner_gates():
    sig, hyp, _, _ = inputs()
    packet = ImprovementDiscoveryEngine().build_queue_packet(
        sig, hyp, dependency_issues=(1377, 1374)
    )
    issue = {
        "number": 1396,
        "title": packet.title,
        "body": packet.body,
        "labels": packet.labels,
    }
    assert (
        re.search(r"^OC-QUEUE-CAPABILITY: ([^\s]+)$", packet.body, re.MULTILINE).group(
            1
        )
        == packet.capability
    )
    assert infer_resources(issue) == {
        "reads": ["provenance"],
        "writes": ["control-plane", "scientific-memory"],
    }
    assert build_dependency_graph([issue])["status"][1396]["ready"] is False
    graph = build_dependency_graph(
        [
            issue,
            {"number": 1374, "state": "CLOSED"},
            {"number": 1377, "state": "CLOSED"},
        ]
    )
    assert graph["status"][1396]["ready"] is True
    orchestrator = DeepOrchestrate()
    leaf = improvement_task_leaf(
        sig, hyp, issue_number=1396, dependencies=("dependency",)
    )
    orchestrator.register(leaf)
    assert orchestrator.ready_tasks() == []
    risky_sig, risky_hyp, _, _ = inputs(risk="high")
    risky = improvement_task_leaf(risky_sig, risky_hyp, issue_number=1396)
    owner_reservoir = DeepOrchestrate()
    owner_reservoir.register(risky)
    assert risky.state == TaskState.OWNER_GATED
    assert owner_reservoir.ready_tasks() == []


@pytest.mark.parametrize(
    "defect",
    [
        "missing-gate",
        "false-string",
        "zero-threshold",
        "paid-provider",
        "wrong-candidate",
        "wrong-output-class",
    ],
)
def test_feedback_fails_closed_before_recording_untrusted_evidence(defect):
    args = evaluation_args()
    if defect == "missing-gate":
        args["task_class"] = replace(
            args["task_class"], mandatory_gate_ids=(*GATES, "missing")
        )
    elif defect == "false-string":
        output = replace(
            args["candidate_fixture"].output,
            payload={
                **args["candidate_fixture"].output.payload,
                "owner_gate_preserved": "false",
            },
        )
        args["candidate_fixture"] = replace(args["candidate_fixture"], output=output)
    elif defect == "zero-threshold":
        args["policy"] = PromotionPolicy()
    elif defect == "paid-provider":
        args["candidate"] = replace(args["candidate"], provider_ref="paid")
    elif defect == "wrong-candidate":
        args["candidate"] = replace(args["candidate"], implementation_ref="other")
    else:
        args["candidate_fixture"] = replace(
            args["candidate_fixture"],
            output=replace(args["candidate_fixture"].output, task_class_id="other"),
        )
    with pytest.raises(ValueError):
        evaluate_frozen_improvement(**args)
    assert args["repository"].decisions == {}
    assert args["repository"].runs == {}


@pytest.mark.parametrize("value", ["false", None])
def test_extra_registry_mandatory_gate_is_strict_even_when_task_omits_it(value):
    args = evaluation_args()
    args["registry"].register(
        *boolean_field_evaluator(
            evaluator_id="protected_locality_safe",
            version="1",
            field_name="protected_locality_safe",
            category="scientific",
            mandatory_gate=True,
        )
    )
    for name in ("baseline_fixture", "candidate_fixture"):
        fixture = args[name]
        payload = dict(fixture.output.payload)
        if value is not None:
            payload["protected_locality_safe"] = value
        args[name] = replace(fixture, output=replace(fixture.output, payload=payload))
    with pytest.raises(ValueError, match="explicit boolean"):
        evaluate_frozen_improvement(**args)
    assert args["repository"].decisions == {}
    assert args["repository"].runs == {}


@pytest.mark.parametrize("issue_number", [True, 1.5, "1396", None, 0, -1])
def test_canonical_issue_identity_rejects_nonpositive_or_noninteger_values(
    issue_number,
):
    args = evaluation_args()
    with pytest.raises(ValueError, match="GitHub issue identity"):
        improvement_task_leaf(
            args["signal"], args["hypothesis"], issue_number=issue_number
        )
    args["issue_number"] = issue_number
    with pytest.raises(ValueError, match="GitHub issue identity"):
        evaluate_frozen_improvement(**args)
    assert args["repository"].runs == {}
