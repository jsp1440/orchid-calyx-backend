from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "swarm_anthropic_direct.py"

spec = importlib.util.spec_from_file_location("swarm_anthropic_direct", SCRIPT)
assert spec and spec.loader
direct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(direct)


def test_direct_executor_blocks_workflow_writes() -> None:
    path = direct._safe_path(".github/workflows/orchid-completion-lane.yml")
    assert direct._writable(path) is False


def test_direct_executor_blocks_paths_outside_repository() -> None:
    with pytest.raises(ValueError):
        direct._safe_path("../../etc/passwd")


def test_direct_executor_allows_normal_source_write(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(direct, "REPO_ROOT", tmp_path)
    path = direct._safe_path("app/example.py")
    assert direct._writable(path) is True
    result = direct._tool_write_file({"path": "app/example.py", "content": "x = 1\n"})
    assert "WROTE app/example.py" in result
    assert path.read_text() == "x = 1\n"


def test_direct_executor_rejects_arbitrary_validation_command() -> None:
    result = direct._tool_run_check({"name": "curl", "target": "example.com"})
    assert result == "ERROR: unsupported check: curl"


def test_direct_executor_builds_anthropic_messages_request() -> None:
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                }
            ).encode()

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode())
        captured["timeout"] = timeout
        return Response()

    with patch.object(direct.urlrequest, "urlopen", fake_urlopen):
        response = direct._anthropic_message(
            api_key="test-key",
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=100,
            timeout=30,
        )

    assert captured["url"] == direct.ANTHROPIC_URL
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["tools"]
    assert response["usage"]["input_tokens"] == 10


def test_direct_executor_toolset_has_no_arbitrary_shell() -> None:
    names = {tool["name"] for tool in direct.TOOLS}
    assert names == {"read_file", "list_files", "search_text", "write_file", "run_check"}
