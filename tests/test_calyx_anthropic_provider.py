from __future__ import annotations

import json

import pytest

from app.calyx_engineering import anthropic_provider
from app.calyx_engineering.anthropic_provider import (
    AnthropicPatchProviderError,
    AnthropicPatchRequest,
    generate_file_changes,
)


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _request() -> AnthropicPatchRequest:
    return AnthropicPatchRequest(
        objective="Repair the deterministic certification failure.",
        attempt=1,
        constraints={
            "maximum_files": 10,
            "complete_file_replacements": True,
            "workflow_files_forbidden": True,
            "merge_forbidden": True,
            "deployment_forbidden": True,
        },
        repository_files={
            "tests/example.py": "def test_example():\n    assert False\n"
        },
        failure_logs=["AssertionError: expected failure"],
    )


def test_generate_file_changes_calls_anthropic_and_returns_structured_json(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setenv("CALYX_ENGINEERING_ANTHROPIC_MODEL", "approved-model")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "changes": [
                                    {
                                        "path": "tests/example.py",
                                        "content": "def test_example():\n    assert True\n",
                                        "message": "Repair deterministic test",
                                    }
                                ]
                            }
                        ),
                    }
                ]
            }
        )

    monkeypatch.setattr(anthropic_provider, "urlopen", fake_urlopen)
    result = generate_file_changes(_request())

    assert result["changes"][0]["path"] == "tests/example.py"
    assert captured["timeout"] == 120
    sent = json.loads(captured["request"].data)
    assert sent["model"] == "approved-model"
    assert sent["temperature"] == 0
    assert captured["request"].headers["X-api-key"] == "secret"


def test_generate_file_changes_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(
        AnthropicPatchProviderError, match="ANTHROPIC_API_KEY_NOT_CONFIGURED"
    ):
        generate_file_changes(_request())


def test_generate_file_changes_rejects_non_json(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setattr(
        anthropic_provider,
        "urlopen",
        lambda request, timeout: _Response(
            {"content": [{"type": "text", "text": "not json"}]}
        ),
    )
    with pytest.raises(
        AnthropicPatchProviderError, match="ANTHROPIC_PROVIDER_INVALID_JSON"
    ):
        generate_file_changes(_request())


def _with_attempt(attempt: int, logs: list[str], files: dict[str, str] | None = None):
    base = _request()
    return AnthropicPatchRequest(
        objective=base.objective,
        attempt=attempt,
        constraints=base.constraints,
        repository_files=files or base.repository_files,
        failure_logs=logs,
    )


def test_repair_attempts_share_a_cacheable_stable_prefix(monkeypatch):
    monkeypatch.delenv(anthropic_provider.PROMPT_CACHE_ENV, raising=False)
    first = anthropic_provider.repair_request_content(
        _with_attempt(1, ["first failure"])
    )
    second = anthropic_provider.repair_request_content(
        _with_attempt(2, ["second failure"])
    )
    assert first[0] == second[0]
    assert first[0]["cache_control"] == {"type": "ephemeral"}
    assert "repository_files" in json.loads(first[0]["text"])
    assert json.loads(second[1]["text"]) == {
        "attempt": 2,
        "failure_logs": ["second failure"],
    }
    assert "cache_control" not in second[1]


def test_changed_repository_file_changes_the_cached_prefix(monkeypatch):
    monkeypatch.delenv(anthropic_provider.PROMPT_CACHE_ENV, raising=False)
    before = anthropic_provider.repair_request_content(_with_attempt(1, []))
    after = anthropic_provider.repair_request_content(
        _with_attempt(
            2, [], {"tests/example.py": "def test_example():\n    assert True\n"}
        )
    )
    assert before[0]["text"] != after[0]["text"]


def test_repair_prompt_cache_can_be_disabled(monkeypatch):
    monkeypatch.setenv(anthropic_provider.PROMPT_CACHE_ENV, "off")
    content = anthropic_provider.repair_request_content(_with_attempt(1, []))
    assert all("cache_control" not in block for block in content)
    # Same information is sent either way.
    sent = {**json.loads(content[0]["text"]), **json.loads(content[1]["text"])}
    assert set(sent) == {
        "objective",
        "constraints",
        "repository_files",
        "required_response",
        "attempt",
        "failure_logs",
    }
