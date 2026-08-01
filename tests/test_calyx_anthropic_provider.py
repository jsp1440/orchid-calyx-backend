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
        repository_files={"tests/example.py": "def test_example():\n    assert False\n"},
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
    with pytest.raises(AnthropicPatchProviderError, match="ANTHROPIC_API_KEY_NOT_CONFIGURED"):
        generate_file_changes(_request())


def test_generate_file_changes_rejects_non_json(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setattr(
        anthropic_provider,
        "urlopen",
        lambda request, timeout: _Response({"content": [{"type": "text", "text": "not json"}]}),
    )
    with pytest.raises(AnthropicPatchProviderError, match="ANTHROPIC_PROVIDER_INVALID_JSON"):
        generate_file_changes(_request())
