"""The backend's Decision Fabric is the Brain's contract, not a restatement of it.

Orchid-Continuum-Brain ``contracts/decision_fabric_v1.json`` is vendored
verbatim and pinned by sha256; the reference specs are built from it. Routing
follows the contract's words: ``escalate`` only when a stronger configured
provider is available after the one that produced the result.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.decision_fabric import (
    BRAIN_CONTRACT_SHA256,
    CONTRACT_PATH,
    DecisionAnswer,
    DecisionEngine,
    DecisionResult,
    autonomy_gate_spec,
    literature_triage_spec,
    load_contract,
    load_reference_specs,
)
from app.decision_fabric.engine import DecisionContractError


def result_for(spec, provider: str, conf: float) -> DecisionResult:
    answers = []
    for question in spec.questions:
        answer = question.options[0] if question.type == "choice" else True
        answers.append(
            DecisionAnswer(
                question.id,
                answer,
                conf,
                {str(answer): conf},
                question.allowed_source_fields[:1],
            )
        )
    return DecisionResult(
        spec.id, spec.version, provider, "offline", tuple(answers), 1.0, 0, 0.0
    )


# -- the vendored contract is pinned ----------------------------------------------


def test_vendored_contract_matches_its_pin():
    assert (
        hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() == BRAIN_CONTRACT_SHA256
    )


def test_a_drifted_contract_is_refused_not_loaded(tmp_path: Path):
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["reference_specs"]["literature_triage"]["accept_confidence"] = 0.5
    drifted = tmp_path / "decision_fabric_v1.json"
    drifted.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(DecisionContractError, match="drifted from its pin"):
        load_contract(drifted)
    assert load_contract(drifted, verify=False)["schema"] == "oc.decision-fabric.v1"


def test_a_wrong_schema_is_refused(tmp_path: Path):
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"schema": "oc.something-else.v1"}), encoding="utf-8")
    with pytest.raises(DecisionContractError, match="schema must be"):
        load_contract(other, verify=False)


# -- the reference specs are the contract's ---------------------------------------


def test_reference_specs_are_built_from_the_contract_verbatim():
    contract = load_contract()
    specs = load_reference_specs()
    assert (
        set(specs)
        == set(contract["reference_specs"])
        == {"literature_triage", "autonomy_gate"}
    )
    for name, declared in contract["reference_specs"].items():
        built = specs[name]
        assert built.id == declared["id"] and built.version == declared["version"]
        assert built.accept_confidence == declared["accept_confidence"]
        assert built.escalate_confidence == declared["escalate_confidence"]
        assert list(built.provider_policy) == declared["provider_policy"]
        for question, source in zip(
            built.questions, declared["questions"], strict=True
        ):
            assert question.id == source["id"]
            assert question.type == source["type"]
            assert question.instructions == source["instructions"]
            assert (
                list(question.allowed_source_fields) == source["allowed_source_fields"]
            )
            assert list(question.options) == source.get("options", [])
            assert question.unknown_allowed is True


def test_the_named_specs_keep_their_identity():
    assert literature_triage_spec().id == "oc.literature-triage"
    assert autonomy_gate_spec().id == "oc.autonomy-gate"
    assert literature_triage_spec().provider_policy == (
        "deterministic-cache",
        "fast-classifier",
        "strong-reasoner",
        "human-review",
    )


# -- escalate means a stronger configured provider remains -----------------------


def test_escalates_when_a_stronger_provider_follows_the_result_provider():
    spec = literature_triage_spec()
    route = DecisionEngine.route(spec, result_for(spec, "fast-classifier", 0.70))
    assert route.state == "escalate"
    assert "stronger configured provider available: strong-reasoner" in route.reasons


def test_reviews_when_only_a_human_remains_after_the_result_provider():
    spec = literature_triage_spec()
    route = DecisionEngine.route(spec, result_for(spec, "strong-reasoner", 0.70))
    assert route.state == "review"
    assert "no stronger configured provider after 'strong-reasoner'" in route.reasons


def test_reviews_when_the_result_provider_is_not_in_the_policy():
    spec = literature_triage_spec()
    route = DecisionEngine.route(spec, result_for(spec, "fixture", 0.70))
    assert route.state == "review"
    assert DecisionEngine.stronger_providers(spec, "fixture") == ()


def test_reviews_below_the_escalate_floor_whatever_the_provider():
    spec = literature_triage_spec()
    route = DecisionEngine.route(spec, result_for(spec, "deterministic-cache", 0.40))
    assert route.state == "review"
    assert route.reasons == ("confidence below autonomous routing floor",)


def test_accepts_at_or_above_the_accept_threshold_whatever_the_provider():
    spec = literature_triage_spec()
    assert (
        DecisionEngine.route(spec, result_for(spec, "fixture", 0.80)).state
        == "accepted"
    )


def test_autonomy_gate_escalates_from_deterministic_checks_to_the_reasoner_only():
    spec = autonomy_gate_spec()
    assert DecisionEngine.stronger_providers(spec, "deterministic-checks") == (
        "reasoning-provider",
    )
    assert DecisionEngine.stronger_providers(spec, "reasoning-provider") == ()
    assert (
        DecisionEngine.route(spec, result_for(spec, "deterministic-checks", 0.75)).state
        == "escalate"
    )
    assert (
        DecisionEngine.route(spec, result_for(spec, "reasoning-provider", 0.75)).state
        == "review"
    )
