"""Release-1 journey 16 — an unavailable AI provider (and no database) does not break deterministic OC.

Runs the real application (``app.main``) with every generative-provider and
database variable removed, and pins, by execution:

* the public deterministic surfaces still answer, each with its honest status
  (200 with an empty list, 401 behind a gate, 503 with a stated reason), never
  a 5xx crash page;
* the Calyx query path answers from the Continuum and states that no generative
  claim is made without evidence;
* a Speak turn degrades to the deterministic governed composer and *says* that
  no generative provider is configured, instead of guessing;
* a provider that fails mid-turn still yields an answer with the outcome named.

Nothing here reaches a network provider: there is no key to reach one with, and
the two external enrichments the Speak path may consult are pinned to their
"not relevant" shapes exactly as the existing Speak suite does.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.calyx_conversation import routes as conversation_routes
from app.calyx_conversation import speak_routes
from app.calyx_conversation.provider import GeneratedReply
from app.calyx_conversation.store import ConversationStore, ConversationStoreUnavailable
from app.main import app
from app.security import verify_owner_or_api_key
from app.semantic_index import repository_runtime

PROVIDER_AND_DB_ENV = [
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "ANTHROPIC_API_KEY",
    "CALYX_AGENT_PROVIDER",
    "CALYX_AGENT_MODEL",
    "CALYX_CHAT_MODEL",
    "CALYX_GENERATIVE_ENTITLEMENT_MODE",
    "DATABASE_URL",
    "CALYX_API_KEY",
]
PRIVILEGED = {"actor": "backend_api_key", "auth_type": "api_key"}
QUESTION = "Which pollinators are reported for Ophrys apifera and how strong is that evidence?"
CRASH_MARKERS = ("Traceback", "Internal Server Error", "Exception")


class FailingGenerativeProvider:
    provider_name = "fake-generative"
    model_name = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, messages, governed_context) -> GeneratedReply:
        self.calls += 1
        raise RuntimeError("PROVIDER_UNAVAILABLE_503")


@pytest.fixture()
def dark(monkeypatch):
    """No provider, no database, in-memory Speak store, no external enrichment calls."""
    for name in PROVIDER_AND_DB_ENV:
        monkeypatch.delenv(name, raising=False)
    # The test session's conftest pins a placeholder DATABASE_URL at import time, so the
    # module-level singletons were built believing a database exists. Rebuild them the way
    # a process booted without DATABASE_URL would.
    memory_store = ConversationStore(dsn="")
    monkeypatch.setattr(speak_routes, "STORE", memory_store)
    monkeypatch.setattr(conversation_routes, "STORE", memory_store)
    monkeypatch.setattr(conversation_routes, "_ENGINE", None)
    monkeypatch.setattr(
        repository_runtime, "RUNTIME", repository_runtime.SemanticIndexRepositoryRuntime(database_url="")
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
    yield
    app.dependency_overrides.pop(verify_owner_or_api_key, None)


@pytest.fixture()
def anonymous(dark) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def privileged(dark) -> TestClient:
    app.dependency_overrides[verify_owner_or_api_key] = lambda: dict(PRIVILEGED)
    return TestClient(app, raise_server_exceptions=False)


def assert_not_a_crash(response) -> None:
    assert response.status_code < 500 or response.status_code == 503, response.text[:300]
    for marker in CRASH_MARKERS:
        assert marker not in response.text, response.text[:300]


# -- deterministic surfaces ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "expected_status", "expected_fragment"),
    [
        ("GET", "/health", 200, '"status":"ok"'),
        ("GET", "/api/mission-control/health", 200, '"status"'),
        ("GET", "/api/community/observations", 200, '"total":0'),
        ("GET", "/api/constituent/newsletter/archive", 200, '"total":0'),
        ("GET", "/api/field-observations", 401, "Owner session or API key is required"),
        ("GET", "/api/calyx/speak/conversations", 401, "Owner session or API key is required"),
        ("GET", "/api/platform/species/1/dossier", 503, "database is not configured"),
        ("GET", "/api/platform/species/1/atlas", 503, "database is not configured"),
        ("GET", "/api/platform/federation/resolve-species?name=Dracula%20vampira", 503, "database is not configured"),
    ],
)
def test_public_surfaces_answer_honestly_with_no_provider_and_no_database(
    anonymous, method, path, expected_status, expected_fragment
):
    response = anonymous.request(method, path)
    assert_not_a_crash(response)
    assert response.status_code == expected_status, response.text[:300]
    assert expected_fragment in response.text


def test_a_gated_query_without_credentials_is_refused_not_answered_by_a_fallback(anonymous):
    response = anonymous.post("/api/calyx/query", json={"message": QUESTION})
    assert response.status_code == 401
    assert "Owner session or API key is required" in response.text


# -- Calyx query path ---------------------------------------------------------------------


def test_calyx_query_answers_from_the_continuum_and_declares_its_epistemic_policy(privileged):
    response = privileged.post("/api/calyx/query", json={"message": QUESTION})
    assert_not_a_crash(response)
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert isinstance(body["answer"], str) and body["answer"].strip()
    assert "searched the Orchid Continuum" in body["answer"]
    assert body["epistemic_policy"] == {
        "continuum_first": True,
        "generative_claims_without_evidence": False,
        "conversation_does_not_publish_knowledge": True,
        "knowledge_graph_mutation": False,
    }
    assert body["persistence_mode"] == "memory"
    assert isinstance(body["retrieval"], dict)


# -- Speak path ---------------------------------------------------------------------------


def start_conversation(client: TestClient) -> str:
    created = client.post("/api/calyx/speak/conversations", json={"project_id": "pollination"})
    assert created.status_code == 201, created.text[:300]
    return created.json()["conversation_id"]


def test_speak_turn_degrades_to_the_governed_composer_and_states_no_provider_is_configured(privileged):
    conversation_id = start_conversation(privileged)
    turn = privileged.post(
        f"/api/calyx/speak/conversations/{conversation_id}/turns",
        json={"message": QUESTION, "research_mode": "never"},
    )
    assert_not_a_crash(turn)
    assert turn.status_code == 200, turn.text[:300]
    body = turn.json()

    provider = body["provider"]
    assert provider["name"] == "deterministic-governed"
    assert provider["fallback_error"] is None
    assert provider["configuration"]["generative_ready"] is False
    assert provider["configuration"]["openai_key_present"] is False
    assert provider["configuration"]["calyx_agent_provider"] is None

    policy = body["access_policy"]
    assert policy["generative_provider_configured"] is False
    assert policy["generative_allowed"] is False
    assert policy["decision_reason"] == "no_generative_provider_configured"
    assert policy["provider_class"] == "deterministic"
    assert body["persistence_mode"] == "memory"
    assert isinstance(body["answer"], str) and body["answer"].strip()


def test_a_provider_that_fails_mid_turn_still_yields_a_governed_answer_and_names_the_outcome(
    privileged, monkeypatch
):
    failing = FailingGenerativeProvider()
    monkeypatch.setattr(speak_routes, "configured_reply_provider", lambda: failing)
    conversation_id = start_conversation(privileged)
    turn = privileged.post(
        f"/api/calyx/speak/conversations/{conversation_id}/turns",
        json={"message": QUESTION, "research_mode": "never"},
    )
    assert_not_a_crash(turn)
    assert turn.status_code == 200, turn.text[:300]
    body = turn.json()
    assert failing.calls == 1
    assert body["access_policy"]["generative_allowed"] is True  # the decision was to try the provider
    assert body["access_policy"]["provider_outcome"] == "deterministic_fallback_after_provider_error"
    assert body["provider"]["name"] == "deterministic-governed"
    assert body["provider"]["generative"] is False
    assert "PROVIDER_UNAVAILABLE_503" in body["provider"]["fallback_error"]  # named in metadata...
    assert isinstance(body["answer"], str) and body["answer"].strip()
    assert "PROVIDER_UNAVAILABLE_503" not in body["answer"]  # ...never passed off as an answer


# -- configured but unreachable database ---------------------------------------------------

UNREACHABLE_DSN = "postgresql://calyx:calyx@127.0.0.1:1/calyx"  # port 1 refuses immediately


def test_store_names_an_unreachable_database_instead_of_leaking_a_driver_error():
    store = ConversationStore(dsn=UNREACHABLE_DSN)
    assert store.persistence_mode == "postgres"
    with pytest.raises(ConversationStoreUnavailable) as raised:
        store.create_or_touch(None, title="t", context={})
    assert raised.value.code == "CONVERSATION_STORE_UNAVAILABLE"
    with pytest.raises(ConversationStoreUnavailable):
        store.recent(limit=1)


@pytest.fixture()
def unreachable_database(dark, monkeypatch) -> TestClient:
    broken = ConversationStore(dsn=UNREACHABLE_DSN)
    monkeypatch.setattr(speak_routes, "STORE", broken)
    monkeypatch.setattr(conversation_routes, "STORE", broken)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: dict(PRIVILEGED)
    return TestClient(app, raise_server_exceptions=False)


def test_calyx_query_with_an_unreachable_conversation_database_is_a_stated_503_not_a_crash(unreachable_database):
    response = unreachable_database.post("/api/calyx/query", json={"message": QUESTION})
    assert response.status_code == 503, response.text[:300]
    detail = response.json()["detail"]
    assert detail["code"] == "CONVERSATION_STORE_UNAVAILABLE"
    assert detail["persistence_mode"] == "postgres"
    assert "no answer was invented" in detail["message"]
    for marker in CRASH_MARKERS:
        assert marker not in response.text


def test_speak_with_an_unreachable_conversation_database_is_a_stated_503_not_a_crash(unreachable_database):
    created = unreachable_database.post("/api/calyx/speak/conversations", json={"project_id": "pollination"})
    assert created.status_code == 503, created.text[:300]
    assert created.json()["detail"]["code"] == "CONVERSATION_STORE_UNAVAILABLE"
    listed = unreachable_database.get("/api/calyx/speak/conversations")
    assert listed.status_code == 503, listed.text[:300]
    assert listed.json()["detail"]["code"] == "CONVERSATION_STORE_UNAVAILABLE"
