from __future__ import annotations

import hashlib
import json

import pytest

from app.calyx_flywheel.models import SimulationCase
from app.calyx_flywheel.simulations import (
    ExecutionMode,
    ExpectedInvariant,
    FixtureSimulationRunner,
    GovernedToolFixture,
    InvariantClass,
    InvariantOperator,
    LiveCanaryPolicy,
    RegressionCase,
    SimulationArchive,
    SimulationObservation,
    SimulationSnapshot,
    SimulationTurn,
    seed_regression_cases,
)
from app.calyx_flywheel.locality import SensitiveLocalityError


def _snapshot() -> SimulationSnapshot:
    return SimulationSnapshot(
        code_sha="a" * 40,
        model_id="fixture-model",
        model_version="fixture-v1",
        prompt_version="prompt-v7",
        knowledge_version="kg-snapshot-2026-08-23",
        taxonomy_version="world-plants-2.1.2026",
    )


def _case(
    *invariants: ExpectedInvariant,
    turns: int = 1,
) -> RegressionCase:
    return RegressionCase(
        base=SimulationCase(
            case_id="case-1",
            procedure_id="procedure-1",
            procedure_version=1,
            inputs={"subject": "Phalaenopsis"},
        ),
        version=2,
        title="Deterministic case",
        turns=tuple(
            SimulationTurn(role="operator", content=f"Turn {index}")
            for index in range(turns)
        ),
        invariants=invariants
        or (
            ExpectedInvariant(
                invariant_id="answer-status",
                classification=InvariantClass.SCIENTIFIC,
                selector="final.status",
                operator=InvariantOperator.EQUALS,
                expected="SUPPORTED",
            ),
        ),
    )


def _response_hash(response: dict[str, object]) -> str:
    encoded = json.dumps(
        response,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_snapshot_requires_exact_reproducibility_identities() -> None:
    snapshot = _snapshot()
    assert len(snapshot.snapshot_hash) == 64
    assert snapshot.taxonomy_version == "world-plants-2.1.2026"

    with pytest.raises(ValueError, match="SIMULATION_CODE_SHA_REQUIRED"):
        SimulationSnapshot(
            code_sha="main",
            model_id="fixture-model",
            model_version="v1",
            prompt_version="p1",
            knowledge_version="k1",
            taxonomy_version="t1",
        )


def test_governed_tool_fixture_pins_response_hash() -> None:
    response = {"records": ["source-1"], "availability": "available"}
    fixture = GovernedToolFixture(
        fixture_id="literature-1",
        tool_name="literature_search",
        request={"query": "Phalaenopsis"},
        response=response,
        response_hash=_response_hash(response),
    )
    assert fixture.response["availability"] == "available"

    with pytest.raises(ValueError, match="SIMULATION_FIXTURE_HASH_MISMATCH"):
        GovernedToolFixture(
            fixture_id="literature-1",
            tool_name="literature_search",
            request={"query": "Phalaenopsis"},
            response=response,
            response_hash="0" * 64,
        )


def test_sensitive_locality_cannot_enter_fixture_or_observation() -> None:
    response = {"availability": "available"}
    with pytest.raises(SensitiveLocalityError):
        GovernedToolFixture(
            fixture_id="unsafe",
            tool_name="occurrence",
            request={"latitude": -12.4},
            response=response,
            response_hash=_response_hash(response),
        )

    with pytest.raises(SensitiveLocalityError):
        SimulationObservation(
            turn_index=0,
            facts={"locality": "protected place"},
        )


def test_generated_variant_requires_an_explicit_parent() -> None:
    with pytest.raises(ValueError, match="GENERATED_VARIANT_REQUIRES_PARENT"):
        RegressionCase(
            base=SimulationCase(
                case_id="variant-1",
                procedure_id="procedure-1",
                procedure_version=1,
            ),
            version=1,
            title="Variant",
            turns=(SimulationTurn(role="operator", content="Question"),),
            invariants=(
                ExpectedInvariant(
                    "status",
                    InvariantClass.SCIENTIFIC,
                    "final.status",
                    InvariantOperator.PRESENT,
                ),
            ),
            generated_variant=True,
        )


def test_fixture_runner_captures_trace_usage_and_allows_promotion_only_when_green() -> None:
    case = _case(
        ExpectedInvariant(
            "status",
            InvariantClass.SCIENTIFIC,
            "final.status",
            InvariantOperator.EQUALS,
            "SUPPORTED",
        ),
        ExpectedInvariant(
            "no-abstention",
            InvariantClass.GOVERNANCE,
            "summary.abstention_count",
            InvariantOperator.EQUALS,
            0,
        ),
        turns=2,
    )

    def driver(_case: RegressionCase, _snapshot: SimulationSnapshot):
        return (
            SimulationObservation(
                turn_index=0,
                facts={"status": "INTERMEDIATE"},
                retrieved_source_ids=("source-1",),
                policy_decisions=("evidence-required",),
                token_count=10,
            ),
            SimulationObservation(
                turn_index=1,
                facts={"status": "SUPPORTED"},
                retrieved_source_ids=("source-2",),
                assertion_ids=("assertion-1",),
                policy_decisions=("counterevidence-checked",),
                token_count=12,
            ),
        )

    report = FixtureSimulationRunner().run(
        run_id="run-green",
        case=case,
        snapshot=_snapshot(),
        driver=driver,
    )

    assert report.promotion_allowed is True
    assert report.failure_reasons == ()
    assert report.total_tokens == 22
    assert report.total_cost_microusd == 0
    assert all(result.passed for result in report.invariant_results)
    assert report.observations[-1].assertion_ids == ("assertion-1",)


def test_failed_scientific_invariant_blocks_promotion() -> None:
    case = _case()

    report = FixtureSimulationRunner().run(
        run_id="run-red",
        case=case,
        snapshot=_snapshot(),
        driver=lambda _case, _snapshot: (
            SimulationObservation(turn_index=0, facts={"status": "UNSUPPORTED"}),
        ),
    )

    assert report.promotion_allowed is False
    assert len(report.failure_reasons) == 1
    assert report.invariant_results[0].classification is InvariantClass.SCIENTIFIC


def test_fixture_mode_rejects_paid_cost() -> None:
    with pytest.raises(ValueError, match="FIXTURE_SIMULATION_CANNOT_RECORD_PAID_COST"):
        FixtureSimulationRunner().run(
            run_id="paid-fixture",
            case=_case(),
            snapshot=_snapshot(),
            driver=lambda _case, _snapshot: (
                SimulationObservation(
                    turn_index=0,
                    facts={"status": "SUPPORTED"},
                    cost_microusd=1,
                ),
            ),
        )


def test_live_canary_is_opt_in_and_budget_capped() -> None:
    case = _case()
    driver = lambda _case, _snapshot: (  # noqa: E731
        SimulationObservation(
            turn_index=0,
            facts={"status": "SUPPORTED"},
            token_count=50,
            cost_microusd=100,
        ),
    )

    with pytest.raises(PermissionError, match="LIVE_CANARY_NOT_OPTED_IN"):
        FixtureSimulationRunner().run(
            run_id="canary-disabled",
            case=case,
            snapshot=_snapshot(),
            driver=driver,
            mode=ExecutionMode.LIVE_CANARY,
            canary_policy=LiveCanaryPolicy(),
        )

    with pytest.raises(PermissionError, match="LIVE_CANARY_BUDGET_EXCEEDED"):
        FixtureSimulationRunner().run(
            run_id="canary-over-budget",
            case=case,
            snapshot=_snapshot(),
            driver=driver,
            mode=ExecutionMode.LIVE_CANARY,
            canary_policy=LiveCanaryPolicy(
                opt_in=True,
                max_tokens=40,
                max_cost_microusd=90,
            ),
        )

    report = FixtureSimulationRunner().run(
        run_id="canary-bounded",
        case=case,
        snapshot=_snapshot(),
        driver=driver,
        mode=ExecutionMode.LIVE_CANARY,
        canary_policy=LiveCanaryPolicy(
            opt_in=True,
            max_tokens=50,
            max_cost_microusd=100,
        ),
    )
    assert report.mode is ExecutionMode.LIVE_CANARY
    assert report.total_cost_microusd == 100


def test_runner_requires_one_ordered_observation_per_turn() -> None:
    with pytest.raises(ValueError, match="SIMULATION_OBSERVATION_COUNT_MISMATCH"):
        FixtureSimulationRunner().run(
            run_id="missing-turn",
            case=_case(turns=2),
            snapshot=_snapshot(),
            driver=lambda _case, _snapshot: (
                SimulationObservation(turn_index=0, facts={"status": "SUPPORTED"}),
            ),
        )

    with pytest.raises(ValueError, match="SIMULATION_OBSERVATION_ORDER_INVALID"):
        FixtureSimulationRunner().run(
            run_id="wrong-order",
            case=_case(turns=2),
            snapshot=_snapshot(),
            driver=lambda _case, _snapshot: (
                SimulationObservation(turn_index=1, facts={"status": "SUPPORTED"}),
                SimulationObservation(turn_index=0, facts={"status": "SUPPORTED"}),
            ),
        )


def test_archive_is_addressable_and_append_only(tmp_path) -> None:
    report = FixtureSimulationRunner().run(
        run_id="archive-1",
        case=_case(),
        snapshot=_snapshot(),
        driver=lambda _case, _snapshot: (
            SimulationObservation(turn_index=0, facts={"status": "SUPPORTED"}),
        ),
    )
    archive = SimulationArchive(tmp_path / "simulations")

    first_path = archive.store(report)
    second_path = archive.store(report)

    assert first_path == second_path
    assert archive.list_run_ids() == ("archive-1",)
    loaded = archive.load("archive-1")
    assert loaded["run_id"] == "archive-1"
    assert loaded["snapshot"]["code_sha"] == "a" * 40
    assert loaded["case_hash"] == report.case_hash

    first_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="SIMULATION_RUN_IMMUTABLE"):
        archive.store(report)


def test_seed_library_contains_every_required_regression_family() -> None:
    cases = seed_regression_cases()
    ids = {case.base.case_id for case in cases}
    assert ids == {
        "taxonomy-reconciliation",
        "phalaenopsis-temperature-traits",
        "sensitive-locality",
        "missing-project-context",
        "counterevidence",
        "evidence-insufficiency",
    }
    assert all(case.version == 1 for case in cases)
    assert all(case.case_hash for case in cases)


def test_seed_cases_define_behaviour_not_scientific_answers() -> None:
    cases = {case.base.case_id: case for case in seed_regression_cases()}
    phalaenopsis = cases["phalaenopsis-temperature-traits"]
    assert phalaenopsis.invariants[0].selector == "final.trait_evidence_status"
    assert phalaenopsis.invariants[0].expected == "SOURCE_BOUND"

    insufficiency = cases["evidence-insufficiency"]
    assert insufficiency.invariants[0].selector == "summary.abstention_count"
    assert insufficiency.invariants[0].operator is InvariantOperator.GTE

    locality = cases["sensitive-locality"]
    assert locality.invariants[0].expected == "WITHHELD"
