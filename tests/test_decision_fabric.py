from __future__ import annotations

import pytest

from app.decision_fabric import (
    DecisionAnswer,
    DecisionEngine,
    DecisionResult,
    StaticDecisionAdapter,
    autonomy_gate_spec,
    literature_triage_spec,
)
from app.decision_fabric.engine import DecisionContractError


def lit_result(conf=0.91):
    return DecisionResult(
        spec_id="oc.literature-triage",
        spec_version="1.0.0",
        # A provider the policy names, so escalation has somewhere to go.
        provider="fast-classifier",
        provider_model="offline",
        answers=(
            DecisionAnswer(
                "orchid_relevance",
                "direct",
                conf,
                {"direct": conf},
                ("title", "abstract"),
            ),
            DecisionAnswer("primary_data", "yes", conf, {"yes": conf}, ("abstract",)),
            DecisionAnswer(
                "topic",
                "pollination",
                conf,
                {"pollination": conf},
                ("title", "abstract"),
            ),
            DecisionAnswer(
                "full_text_warranted", True, conf, {"true": conf}, ("abstract",)
            ),
        ),
        latency_ms=1.0,
        input_tokens=0,
        cost_usd=0.0,
    )


def test_literature_decision_routes_without_provider_dependency():
    spec = literature_triage_spec()
    state = {
        "title": "Pollination of an orchid",
        "abstract": "We observed pollinator visits and seed set.",
        "keywords": ["Orchidaceae"],
    }
    adapter = StaticDecisionAdapter(lit_result())
    result, route = DecisionEngine().run(spec, state, adapter)
    assert route.state == "accepted"
    assert result.cost_usd == 0
    assert adapter.calls == 1


def test_threshold_change_reroutes_stored_result_without_new_call():
    state = {"title": "x", "abstract": "y", "keywords": []}
    adapter = StaticDecisionAdapter(lit_result(0.78))
    spec = literature_triage_spec()
    result, first = DecisionEngine().run(spec, state, adapter)
    assert first.state == "escalate"
    changed = spec.with_thresholds(accept=0.75, escalate=0.50)
    second = DecisionEngine.route(changed, result)
    assert second.state == "accepted"
    assert adapter.calls == 1


def test_forbidden_source_field_fails_closed():
    spec = literature_triage_spec()
    bad = lit_result()
    answers = list(bad.answers)
    answers[0] = DecisionAnswer(
        "orchid_relevance", "direct", 0.9, {"direct": 0.9}, ("private_note",)
    )
    bad = DecisionResult(
        bad.spec_id,
        bad.spec_version,
        bad.provider,
        bad.provider_model,
        tuple(answers),
        1,
        0,
        0,
    )
    with pytest.raises(DecisionContractError, match="forbidden source field"):
        DecisionEngine.validate_result(
            spec,
            bad,
            {"title": "x", "abstract": "y", "keywords": [], "private_note": "secret"},
        )


def test_unknown_is_an_allowed_scientific_answer():
    spec = literature_triage_spec()
    r = lit_result()
    answers = list(r.answers)
    answers[0] = DecisionAnswer(
        "orchid_relevance", "unknown", 0.4, {"unknown": 0.4}, ("title",)
    )
    r = DecisionResult(
        r.spec_id, r.spec_version, r.provider, r.provider_model, tuple(answers), 1, 0, 0
    )
    DecisionEngine.validate_result(
        spec, r, {"title": "x", "abstract": "y", "keywords": []}
    )
    assert DecisionEngine.route(spec, r).state == "review"


def test_same_engine_governs_autonomy_decisions():
    spec = autonomy_gate_spec()
    state = {
        "ci_status": "success",
        "mergeability": "mergeable",
        "changed_files": ["tests/x.py"],
        "task_metadata": {"safe": True},
        "lease_state": "held",
        "acceptance_receipts": ["tests pass"],
    }
    result = DecisionResult(
        spec_id=spec.id,
        spec_version=spec.version,
        provider="fixture",
        provider_model="offline",
        answers=(
            DecisionAnswer(
                "blocker_type",
                "none",
                0.99,
                {"none": 0.99},
                ("ci_status", "mergeability"),
            ),
            DecisionAnswer(
                "safe_to_merge",
                True,
                0.99,
                {"true": 0.99},
                ("ci_status", "mergeability", "changed_files", "task_metadata"),
            ),
            DecisionAnswer(
                "acceptance_met",
                True,
                0.99,
                {"true": 0.99},
                ("ci_status", "acceptance_receipts", "task_metadata"),
            ),
        ),
        latency_ms=0,
        input_tokens=0,
        cost_usd=0,
    )
    _, route = DecisionEngine().run(spec, state, StaticDecisionAdapter(result))
    assert route.state == "accepted"
