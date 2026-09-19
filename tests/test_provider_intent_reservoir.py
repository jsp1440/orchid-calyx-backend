import pytest

from app.calyx_orchestrator.provider_intent_reservoir import (
    ProviderIntent,
    ProviderRequestReservoir,
)


def intent(**kw):
    base = dict(
        objective="compare pollination mechanisms",
        capability="mechanistic-synthesis",
        deterministic_insufficiency="retrieved evidence conflicts and deterministic rules cannot discriminate",
        expected_gain="identify discriminating observation",
        affected_tasks=("COGINT-002",),
    )
    base.update(kw)
    return ProviderIntent(**base)


def test_complexity_does_not_imply_provider_authority():
    r = ProviderRequestReservoir()
    e = r.preserve(intent())
    assert e.state == "PRESERVED"
    with pytest.raises(PermissionError):
        r.authorize([e.intent.dedupe_key], authorization_envelope=False)


def test_denial_preserves_intent_and_is_non_program_blocking():
    r = ProviderRequestReservoir()
    e = r.preserve(intent(blocking=False))
    r.deny_without_blocking_program(e.intent.dedupe_key)
    record = r.records()[0]
    assert record["state"] == "DEFERRED"
    assert record["deterministic_fallback"]
    assert record["objective"]


def test_deduplicates_equivalent_requests_and_unions_tasks():
    r = ProviderRequestReservoir()
    first = r.preserve(intent())
    second = r.preserve(intent(affected_tasks=("COGINT-003",)))
    assert first is second
    assert second.state == "DEDUPLICATED"
    assert second.duplicate_count == 2
    assert second.task_refs == {"COGINT-002", "COGINT-003"}


def test_batches_by_capability_not_provider():
    r = ProviderRequestReservoir()
    r.preserve(intent(provider="anthropic"))
    r.preserve(intent(objective="interpret historical Latin diagnosis", capability="literature-translation",
                      deterministic_insufficiency="no local translation artifact", provider="anthropic"))
    assert set(r.batches()) == {"mechanistic-synthesis", "literature-translation"}


def test_cache_prevents_repeat_provider_authorization():
    r = ProviderRequestReservoir()
    e = r.preserve(intent())
    r.mark_provider_free_resolved(e.intent.dedupe_key, "kg:result:42")
    cached = r.preserve(intent())
    assert cached.state == "CACHED"
    assert cached.cached_result_ref == "kg:result:42"


def test_sensitive_locality_and_secrets_fail_closed():
    r = ProviderRequestReservoir()
    with pytest.raises(ValueError):
        r.preserve(intent(sensitive_locality=True))
    with pytest.raises(ValueError):
        r.preserve(intent(contains_secret=True))


def test_piggyback_authority_cannot_be_inferred():
    r = ProviderRequestReservoir()
    e = r.preserve(intent())
    with pytest.raises(PermissionError):
        r.authorize([e.intent.dedupe_key], authorization_envelope=False)
    admitted = r.authorize([e.intent.dedupe_key], authorization_envelope=True)
    assert admitted[0].state == "AUTHORIZED"
