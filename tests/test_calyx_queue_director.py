from runtime.calyx_queue_director import DevelopmentIntent, normalize_intents


def intent(**kw):
    base = dict(source_key="frontend-660", issue_number=660, title="Research Station to Matrix", repo="orchid-continuum-frontend", objective="Preserve canonical project identity", acceptance_criteria=("mounted journey proves exact project return",), priority=5)
    base.update(kw)
    return DevelopmentIntent(**base)


def test_safe_intent_becomes_bounded_candidate():
    result = normalize_intents([intent()])
    assert result["no_api_mode"] is True
    assert result["provider_launch_authorized"] is False
    assert result["authority"] == "queue-bridge"
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["source_ref"] == "#660"


def test_duplicate_source_is_suppressed():
    result = normalize_intents([intent(), intent()])
    assert len(result["candidates"]) == 1
    assert result["rejected"] == [{"source_key": "frontend-660", "reason": "duplicate_source_key"}]


def test_provider_work_parks_under_no_api():
    result = normalize_intents([intent(requires_provider=True)])
    assert result["candidates"] == []
    assert result["parked"][0]["reason"] == "runtime_backoff_no_api"


def test_protected_work_is_owner_gated():
    result = normalize_intents([intent(protected_boundaries=("main-merge",))])
    assert result["candidates"] == []
    assert result["parked"][0]["reason"] == "owner_gate"


def test_unbounded_or_unknown_repo_fails_closed():
    result = normalize_intents([intent(repo="unknown"), intent(source_key="empty", acceptance_criteria=())])
    assert result["candidates"] == []
    assert len(result["rejected"]) == 2


def test_fingerprint_is_stable_for_unchanged_reasoning():
    first = normalize_intents([intent()])["candidates"][0]["material_fingerprint"]
    second = normalize_intents([intent()])["candidates"][0]["material_fingerprint"]
    assert first == second
