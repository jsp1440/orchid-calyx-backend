"""Calyx access economics on the Speak path (Release-1 journeys 3 and 16).

Proves that a generative (paid) provider turn is spent only under an explicit,
fail-closed entitlement policy, that denial degrades to the deterministic
governed composer rather than failing the turn, that per-subject metering and
the program ceiling hold, and that a provider outage returns the reserved turn
and still answers (journey 16: an unavailable provider does not break Calyx).

Everything runs in-process: the conversation store and the access ledger are
in-memory, and the "generative" provider is a fake that records whether it was
called, so no test can reach a paid provider.
"""

from __future__ import annotations

import pytest

from app.calyx_conversation import speak_routes
from app.calyx_conversation.access_economics import (
    CEILING_ENV,
    MEMBER_QUOTA_ENV,
    MODE_ENV,
    POLICY_VERSION,
    CalyxAccessPolicy,
)
from app.calyx_conversation.provider import (
    DeterministicGovernedReplyProvider,
    GeneratedReply,
)
from app.calyx_conversation.store import ConversationStore
from runtime.research_station_store import MemoryProjectRecordStore

PRIVILEGED = {"actor": "backend_api_key", "auth_type": "api_key"}
OWNER = {"actor": "owner", "auth_type": "owner_session"}
MEMBER_A = {"subject": "member-a"}
MEMBER_B = {"subject": "member-b"}

QUESTION = "Which pollinators are reported for Ophrys apifera and how strong is that evidence?"


class FakeGenerativeProvider:
    """Stands in for a paid provider. Counts calls; can be told to fail."""

    provider_name = "fake-generative"
    model_name = "fake-model"

    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def generate(self, *, messages, governed_context) -> GeneratedReply:
        self.calls += 1
        if self.fail:
            raise RuntimeError("PROVIDER_UNAVAILABLE_503")
        return GeneratedReply(
            text="generative answer", provider=self.provider_name, model=self.model_name, request_hash="h" * 64
        )


class BrokenStore(MemoryProjectRecordStore):
    def get(self, **kwargs):
        raise RuntimeError("relation does not exist")

    def put(self, **kwargs):
        raise RuntimeError("relation does not exist")


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch):
    """Same isolation the other Speak tests use: in-memory conversation store and
    no semantic index, external literature or climate provider calls."""
    store = ConversationStore(dsn="")
    monkeypatch.setattr(speak_routes, "STORE", store)
    monkeypatch.setattr(
        speak_routes,
        "_retrieval",
        lambda message, mode, limit, internal_access: {
            "results": [],
            "total_eligible_results": 0,
            "retrieval_mode": mode,
        },
    )
    monkeypatch.setattr(
        speak_routes,
        "augment_retrieval_with_external_literature",
        lambda retrieval, message, limit: retrieval,
    )
    monkeypatch.setattr(
        speak_routes,
        "build_seasonal_climate_context",
        lambda message: {
            "requested": False,
            "status": "not_relevant",
            "products": [],
            "external": True,
            "time_sensitive": True,
        },
    )
    return store


@pytest.fixture()
def fake_provider(monkeypatch):
    provider = FakeGenerativeProvider()
    monkeypatch.setattr(speak_routes, "configured_reply_provider", lambda: provider)
    return provider


def install_policy(monkeypatch, env: dict[str, str] | None = None, store=None) -> CalyxAccessPolicy:
    policy = CalyxAccessPolicy(env=env or {}, store=store if store is not None else MemoryProjectRecordStore())
    monkeypatch.setattr(speak_routes, "ACCESS_POLICY", policy)
    return policy


def conversation_for(auth: dict) -> str:
    return speak_routes.create_conversation(
        speak_routes.ConversationCreateRequest(project_id="pollination"), auth
    )["conversation_id"]


def turn(auth: dict, conversation_id: str, **overrides) -> dict:
    request = speak_routes.ConversationTurnRequest(message=QUESTION, research_mode="never", **overrides)
    return speak_routes.append_turn(conversation_id, request, auth)


# ---------------------------------------------------------------------------
# Default policy: owner_only
# ---------------------------------------------------------------------------


def test_default_mode_is_owner_only_and_privileged_tier_gets_generative(monkeypatch, fake_provider):
    install_policy(monkeypatch)
    result = turn(PRIVILEGED, conversation_for(PRIVILEGED))
    access = result["access_policy"]
    assert access["policy_version"] == POLICY_VERSION
    assert access["mode"] == "owner_only" and access["mode_source"] == "default"
    assert access["tier"] == "privileged"
    assert access["generative_allowed"] is True
    assert access["decision_reason"] == "allowed_privileged"
    assert access["provider_outcome"] == "generative"
    assert access["public_budget_isolation"] is True
    assert access["development_budget_governor_charged"] is False
    assert result["provider"]["name"] == "fake-generative"
    assert result["provider"]["generative"] is True
    assert fake_provider.calls == 1


def test_owner_session_is_privileged(monkeypatch, fake_provider):
    install_policy(monkeypatch)
    result = turn(OWNER, conversation_for(OWNER))
    assert result["access_policy"]["tier"] == "privileged"
    assert result["access_policy"]["generative_allowed"] is True


def test_member_is_not_entitled_by_default_and_never_reaches_the_provider(monkeypatch, fake_provider):
    install_policy(monkeypatch)
    result = turn(MEMBER_A, conversation_for(MEMBER_A))
    access = result["access_policy"]
    assert access["tier"] == "member"
    assert access["generative_allowed"] is False
    assert access["decision_reason"] == "tier_not_entitled"
    assert access["provider_class"] == "deterministic"
    assert result["provider"]["name"] == DeterministicGovernedReplyProvider.provider_name
    assert result["provider"]["generative"] is False
    assert result["provider"]["fallback_error"] is None
    assert result["answer"]
    assert fake_provider.calls == 0


# ---------------------------------------------------------------------------
# Modes, quotas, ceilings
# ---------------------------------------------------------------------------


def test_disabled_mode_denies_everyone_including_privileged(monkeypatch, fake_provider):
    install_policy(monkeypatch, {MODE_ENV: "disabled"})
    result = turn(PRIVILEGED, conversation_for(PRIVILEGED))
    assert result["access_policy"]["decision_reason"] == "mode_disabled"
    assert result["provider"]["generative"] is False
    assert fake_provider.calls == 0


def test_unrecognised_mode_fails_closed(monkeypatch, fake_provider):
    install_policy(monkeypatch, {MODE_ENV: "everyone-free"})
    result = turn(PRIVILEGED, conversation_for(PRIVILEGED))
    assert result["access_policy"]["mode"] == "disabled"
    assert result["access_policy"]["mode_source"].startswith("unrecognised_value_fail_closed")
    assert fake_provider.calls == 0


def test_metered_mode_meters_members_per_subject_per_day(monkeypatch, fake_provider):
    install_policy(monkeypatch, {MODE_ENV: "metered", MEMBER_QUOTA_ENV: "2"})
    conv_a = conversation_for(MEMBER_A)
    first = turn(MEMBER_A, conv_a)["access_policy"]
    assert first["decision_reason"] == "allowed_metered"
    assert first["quota"] == {"member_daily_turns": 2, "used_today": 1, "remaining_today": 1}
    second = turn(MEMBER_A, conv_a)["access_policy"]
    assert second["quota"]["used_today"] == 2 and second["quota"]["remaining_today"] == 0
    third = turn(MEMBER_A, conv_a)
    assert third["access_policy"]["decision_reason"] == "member_quota_exhausted"
    assert third["provider"]["generative"] is False
    assert third["answer"]  # still answered, deterministically
    assert fake_provider.calls == 2
    # Another member has their own allowance.
    other = turn(MEMBER_B, conversation_for(MEMBER_B))["access_policy"]
    assert other["decision_reason"] == "allowed_metered"
    assert other["quota"]["used_today"] == 1


def test_metered_mode_with_zero_quota_gives_members_nothing(monkeypatch, fake_provider):
    install_policy(monkeypatch, {MODE_ENV: "metered"})
    result = turn(MEMBER_A, conversation_for(MEMBER_A))
    assert result["access_policy"]["decision_reason"] == "member_quota_exhausted"
    assert result["access_policy"]["quota"]["member_daily_turns"] == 0
    assert fake_provider.calls == 0


def test_program_ceiling_applies_to_privileged_tier_too(monkeypatch, fake_provider):
    install_policy(monkeypatch, {CEILING_ENV: "1"})
    conv = conversation_for(PRIVILEGED)
    first = turn(PRIVILEGED, conv)["access_policy"]
    assert first["generative_allowed"] is True
    assert first["ceiling"] == {"daily_turns": 1, "used_today": 1, "remaining_today": 0}
    second = turn(PRIVILEGED, conv)
    assert second["access_policy"]["decision_reason"] == "program_ceiling_reached"
    assert second["provider"]["generative"] is False
    assert fake_provider.calls == 1


def test_generative_mode_never_uses_the_deterministic_path_without_spending(monkeypatch, fake_provider):
    install_policy(monkeypatch, {CEILING_ENV: "5"})
    result = turn(PRIVILEGED, conversation_for(PRIVILEGED), generative_mode="never")
    access = result["access_policy"]
    assert access["generative_requested"] is False
    assert access["decision_reason"] == "generative_not_requested"
    assert access["reserved"] == []
    assert access["ceiling"]["used_today"] is None  # ledger never consulted
    assert fake_provider.calls == 0


def test_no_generative_provider_configured_is_stated_not_guessed(monkeypatch):
    install_policy(monkeypatch)
    monkeypatch.setattr(speak_routes, "configured_reply_provider", lambda: DeterministicGovernedReplyProvider())
    result = turn(PRIVILEGED, conversation_for(PRIVILEGED))
    access = result["access_policy"]
    assert access["generative_provider_configured"] is False
    assert access["decision_reason"] == "no_generative_provider_configured"
    assert result["provider"]["generative"] is False


# ---------------------------------------------------------------------------
# Failure modes (journey 16)
# ---------------------------------------------------------------------------


def test_provider_outage_falls_back_deterministically_and_returns_the_reserved_turn(monkeypatch):
    failing = FakeGenerativeProvider(fail=True)
    monkeypatch.setattr(speak_routes, "configured_reply_provider", lambda: failing)
    policy = install_policy(monkeypatch, {MODE_ENV: "metered", MEMBER_QUOTA_ENV: "1", CEILING_ENV: "3"})
    result = turn(MEMBER_A, conversation_for(MEMBER_A))
    access = result["access_policy"]
    assert access["generative_allowed"] is True  # the decision was to try
    assert access["provider_outcome"] == "deterministic_fallback_after_provider_error"
    assert result["provider"]["name"] == DeterministicGovernedReplyProvider.provider_name
    assert result["provider"]["generative"] is False
    assert "PROVIDER_UNAVAILABLE_503" in result["provider"]["fallback_error"]
    assert result["answer"]
    assert failing.calls == 1
    # The failed turn was given back: the member can try again, and the
    # program ceiling was not consumed.
    preview = policy.preview(auth=MEMBER_A, subject="member-a", candidate=failing).as_dict()
    assert preview["quota"]["used_today"] == 0
    assert preview["ceiling"]["used_today"] == 0


def test_ledger_outage_fails_closed_when_a_count_is_needed(monkeypatch, fake_provider):
    install_policy(monkeypatch, {MODE_ENV: "metered", MEMBER_QUOTA_ENV: "5"}, store=BrokenStore())
    result = turn(MEMBER_A, conversation_for(MEMBER_A))
    access = result["access_policy"]
    assert access["decision_reason"] == "ledger_unavailable"
    assert access["ledger"]["status"] == "unavailable"
    assert result["provider"]["generative"] is False
    assert result["answer"]
    assert fake_provider.calls == 0


def test_ledger_outage_does_not_deny_unmetered_privileged_turns_but_is_reported(monkeypatch, fake_provider):
    install_policy(monkeypatch, store=BrokenStore())
    result = turn(PRIVILEGED, conversation_for(PRIVILEGED))
    access = result["access_policy"]
    assert access["generative_allowed"] is True
    assert access["ledger"]["status"] == "unavailable"
    assert fake_provider.calls == 1


# ---------------------------------------------------------------------------
# Visibility: status, entitlement preview, persisted metadata
# ---------------------------------------------------------------------------


def test_status_describes_the_policy(monkeypatch, fake_provider):
    install_policy(monkeypatch, {MODE_ENV: "metered", MEMBER_QUOTA_ENV: "3", CEILING_ENV: "10"})
    status = speak_routes.speak_status(PRIVILEGED)
    policy = status["access_policy"]
    assert policy["mode"] == "metered"
    assert policy["member_daily_turns"] == 3
    assert policy["daily_ceiling_turns"] == 10
    assert policy["ledger_mode"] == "in_process_memory"
    assert policy["public_budget_isolation"] is True
    assert policy["deterministic_path_always_available"] is True


def test_entitlement_preview_does_not_spend_a_turn(monkeypatch, fake_provider):
    install_policy(monkeypatch, {MODE_ENV: "metered", MEMBER_QUOTA_ENV: "1"})
    first = speak_routes.speak_entitlement(MEMBER_A)
    second = speak_routes.speak_entitlement(MEMBER_A)
    assert first["decision"]["generative_allowed"] is True
    assert second["decision"]["quota"]["used_today"] == 0
    assert second["decision"]["reserved"] == []
    assert fake_provider.calls == 0
    # The real turn then spends the single allowance.
    result = turn(MEMBER_A, conversation_for(MEMBER_A))
    assert result["access_policy"]["quota"]["used_today"] == 1
    assert speak_routes.speak_entitlement(MEMBER_A)["decision"]["decision_reason"] == "member_quota_exhausted"


def test_access_decision_is_persisted_with_the_calyx_message(monkeypatch, fake_provider, isolated_store):
    install_policy(monkeypatch)
    conv = conversation_for(MEMBER_A)
    result = turn(MEMBER_A, conv)
    stored = isolated_store.get(conv, owner="member-a")
    calyx_messages = [m for m in stored["messages"] if m["role"] == "calyx"]
    assert calyx_messages
    metadata = calyx_messages[-1]["metadata"]
    assert metadata["access_policy"]["decision_reason"] == "tier_not_entitled"
    assert metadata["access_policy"]["provider_outcome"] == "deterministic"
    assert result["calyx_message"]["message_id"] == calyx_messages[-1]["message_id"]
