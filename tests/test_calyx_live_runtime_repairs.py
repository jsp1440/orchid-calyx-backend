from __future__ import annotations

import inspect

import pytest
from sqlalchemy import create_engine
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.orm import Session

from app.calyx_conversation.provider_runtime import OpenAIRuntimeResponsesProvider
from app.calyx_conversation.store import ConversationStore
from app.calyx_orchestrator.schema import ensure_orchestrator_schema


class _FakeResponse:
    def __init__(self, status_code: int, body: dict, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.text = str(body)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        return self._body


def test_conversation_store_returns_latest_memory_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = ConversationStore()
    cid = store.create_or_touch(None, title=None, context={}, owner="owner")
    for index in range(12):
        store.append(cid, "operator", f"message-{index}", owner="owner")

    conversation = store.get(cid, owner="owner", message_limit=4)

    assert conversation is not None
    assert [item["content"] for item in conversation["messages"]] == [
        "message-8",
        "message-9",
        "message-10",
        "message-11",
    ]


def test_postgres_store_query_limits_newest_rows_before_reordering() -> None:
    source = inspect.getsource(ConversationStore.get)
    assert "ORDER BY created_at DESC, message_id DESC" in source
    assert "reversed(rows)" in source


def test_openai_responses_provider_returns_generative_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_post(url: str, **kwargs):
        calls.append(url)
        return _FakeResponse(
            200,
            {
                "id": "resp_123",
                "status": "completed",
                "output": [
                    {
                        "content": [
                            {"type": "output_text", "text": "A conversational Calyx answer."}
                        ]
                    }
                ],
            },
        )

    monkeypatch.setattr("app.calyx_conversation.provider_runtime.requests.post", fake_post)
    provider = OpenAIRuntimeResponsesProvider(model="gpt-5-mini", api_key="test-key")

    reply = provider.generate(
        messages=[{"role": "user", "content": "Tell me about Laelia anceps."}],
        governed_context={"retrieval": {}, "mission": None},
    )

    assert reply.provider == "openai"
    assert reply.model == "gpt-5-mini"
    assert reply.text == "A conversational Calyx answer."
    assert calls == ["https://api.openai.com/v1/responses"]


def test_openai_provider_falls_back_to_chat_for_request_shape_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_post(url: str, **kwargs):
        calls.append(url)
        if url.endswith("/responses"):
            return _FakeResponse(
                400,
                {"error": {"message": "unsupported request shape"}},
                {"x-request-id": "req_primary"},
            )
        return _FakeResponse(
            200,
            {
                "id": "chatcmpl_123",
                "choices": [
                    {"message": {"role": "assistant", "content": "Recovered generative reply."}}
                ],
            },
        )

    monkeypatch.setattr("app.calyx_conversation.provider_runtime.requests.post", fake_post)
    provider = OpenAIRuntimeResponsesProvider(model="gpt-5-mini", api_key="test-key")

    reply = provider.generate(
        messages=[{"role": "user", "content": "Tell me about Dendrobium winter rest."}],
        governed_context={"retrieval": {}, "mission": None},
    )

    assert reply.provider == "openai-chat-fallback"
    assert reply.text == "Recovered generative reply."
    assert calls == [
        "https://api.openai.com/v1/responses",
        "https://api.openai.com/v1/chat/completions",
    ]


def test_openai_provider_does_not_retry_authentication_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_post(url: str, **kwargs):
        calls.append(url)
        return _FakeResponse(
            401,
            {"error": {"message": "invalid api key"}},
            {"x-request-id": "req_auth"},
        )

    monkeypatch.setattr("app.calyx_conversation.provider_runtime.requests.post", fake_post)
    provider = OpenAIRuntimeResponsesProvider(model="gpt-5-mini", api_key="secret-value")

    with pytest.raises(RuntimeError) as exc_info:
        provider.generate(messages=[], governed_context={})

    assert "OPENAI_RESPONSES_HTTP_401" in str(exc_info.value)
    assert "secret-value" not in str(exc_info.value)
    assert calls == ["https://api.openai.com/v1/responses"]


def test_orchestrator_schema_bootstrap_creates_owned_tables() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with Session(engine) as db:
        ensure_orchestrator_schema(db)

    tables = set(sqlalchemy_inspect(engine).get_table_names())
    assert {
        "calyx_orchestrator_jobs",
        "calyx_orchestrator_findings",
        "calyx_engineering_programs",
        "calyx_engineering_program_jobs",
        "calyx_engineering_program_dependencies",
    }.issubset(tables)
