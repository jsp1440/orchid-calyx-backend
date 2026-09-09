from scripts.oc_model_router import choose_route


def test_cheap_is_the_default():
    route = choose_route(title="Update issue receipt", body="Tight bounded status change")
    assert route.tier == "cheap"
    assert route.model == "claude-haiku-4-5"
    assert route.max_turns == 24
    assert route.escalated is False


def test_normal_implementation_promotes_to_standard():
    route = choose_route(title="Implement dossier endpoint", body="Integrate the existing service and tests")
    assert route.tier == "standard"
    assert route.model == "claude-sonnet-5"
    assert route.escalated is True


def test_deep_concurrency_problem_routes_to_deep():
    route = choose_route(title="Repair atomic lease race condition", body="Cross-repo concurrency failure")
    assert route.tier == "deep"
    assert route.model == "claude-opus-5"
    assert route.max_turns == 75


def test_repair_retry_escalates_one_tier_only():
    route = choose_route(title="Update issue receipt", body="retry", labels="oc-repair")
    assert route.tier == "standard"
    assert "repair-escalation=cheap->standard" in route.reason


def test_standard_repair_escalates_to_deep():
    route = choose_route(title="Implement workflow repair", body="retry", labels="oc-repair")
    assert route.tier == "deep"
    assert "repair-escalation=standard->deep" in route.reason


def test_deep_repair_stays_capped():
    route = choose_route(title="Atomic concurrency architecture", body="retry", labels="oc-repair")
    assert route.tier == "deep"
    assert "repair-escalation=capped" in route.reason


def test_maximum_tier_can_disable_expensive_deep_model():
    route = choose_route(
        title="Atomic concurrency architecture",
        body="very difficult",
        maximum_tier="standard",
    )
    assert route.tier == "standard"
    assert route.model == "claude-sonnet-5"


def test_explicit_model_label_overrides_heuristics_but_respects_cap():
    cheap = choose_route(
        title="Architecture and concurrency",
        body="deep words are present",
        labels="oc-model-cheap",
    )
    assert cheap.tier == "cheap"

    capped = choose_route(
        title="simple task",
        body="",
        labels="oc-model-deep",
        maximum_tier="standard",
    )
    assert capped.tier == "standard"


def test_models_and_turn_budgets_are_configurable():
    route = choose_route(
        title="Implement integration",
        body="",
        models={"standard": "custom-sonnet"},
        max_turns={"standard": 11},
    )
    assert route.model == "custom-sonnet"
    assert route.max_turns == 11
