"""Tests for oc_no_api_guard.py — NO-API mode enforcement."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

# Allow importing the script from scripts/
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
oc_no_api_guard = importlib.import_module("oc_no_api_guard")
evaluate = oc_no_api_guard.evaluate
_DISABLE_VALUES = oc_no_api_guard._DISABLE_VALUES


# ---------------------------------------------------------------------------
# evaluate() — pure logic
# ---------------------------------------------------------------------------


class TestEvaluateBlocked:
    """Providers must be blocked under these conditions."""

    def test_absent_variable_is_blocked(self):
        # Fail-closed: missing variable blocks providers
        assert evaluate(None) is True

    def test_empty_string_is_blocked(self):
        assert evaluate("") is True

    def test_whitespace_only_is_blocked(self):
        assert evaluate("   ") is True

    def test_true_is_blocked(self):
        assert evaluate("true") is True

    def test_True_uppercase_is_blocked(self):
        assert evaluate("True") is True

    def test_1_is_blocked(self):
        assert evaluate("1") is True

    def test_yes_is_blocked(self):
        assert evaluate("yes") is True

    def test_on_is_blocked(self):
        assert evaluate("on") is True

    def test_arbitrary_string_is_blocked(self):
        assert evaluate("anything_else") is True

    def test_enabled_string_is_blocked(self):
        assert evaluate("enabled") is True


class TestEvaluateAllowed:
    """Providers are only allowed for explicit disable values."""

    @pytest.mark.parametrize("value", list(_DISABLE_VALUES))
    def test_disable_value_allows_providers(self, value: str):
        assert evaluate(value) is False

    @pytest.mark.parametrize("value", ["FALSE", "False", "DISABLED", "Disabled", "NO", "OFF", "0"])
    def test_disable_value_case_insensitive(self, value: str):
        assert evaluate(value) is False

    def test_false_with_whitespace_is_allowed(self):
        assert evaluate("  false  ") is False

    def test_disabled_with_whitespace_is_allowed(self):
        assert evaluate("  disabled  ") is False


# ---------------------------------------------------------------------------
# write_output() — GITHUB_OUTPUT writing
# ---------------------------------------------------------------------------


class TestWriteOutput:
    def test_writes_blocked_true(self, tmp_path, monkeypatch):
        out = tmp_path / "output"
        out.touch()
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        oc_no_api_guard.write_output(True)
        assert out.read_text() == "blocked=true\n"

    def test_writes_blocked_false(self, tmp_path, monkeypatch):
        out = tmp_path / "output"
        out.touch()
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        oc_no_api_guard.write_output(False)
        assert out.read_text() == "blocked=false\n"

    def test_appends_to_existing_output(self, tmp_path, monkeypatch):
        out = tmp_path / "output"
        out.write_text("prior=line\n")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        oc_no_api_guard.write_output(True)
        assert out.read_text() == "prior=line\nblocked=true\n"

    def test_falls_back_to_stdout_when_no_env(self, monkeypatch, capsys):
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
        oc_no_api_guard.write_output(True)
        captured = capsys.readouterr()
        assert "blocked=true" in captured.out


# ---------------------------------------------------------------------------
# main() integration — end-to-end env var → output
# ---------------------------------------------------------------------------


class TestMain:
    def test_absent_env_produces_blocked_true(self, tmp_path, monkeypatch):
        out = tmp_path / "output"
        out.touch()
        monkeypatch.delenv("NO_API_MODE", raising=False)
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        oc_no_api_guard.main()
        assert "blocked=true" in out.read_text()

    def test_false_env_produces_blocked_false(self, tmp_path, monkeypatch):
        out = tmp_path / "output"
        out.touch()
        monkeypatch.setenv("NO_API_MODE", "false")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        oc_no_api_guard.main()
        assert "blocked=false" in out.read_text()

    def test_true_env_produces_blocked_true(self, tmp_path, monkeypatch):
        out = tmp_path / "output"
        out.touch()
        monkeypatch.setenv("NO_API_MODE", "true")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        oc_no_api_guard.main()
        assert "blocked=true" in out.read_text()

    def test_disabled_env_produces_blocked_false(self, tmp_path, monkeypatch):
        out = tmp_path / "output"
        out.touch()
        monkeypatch.setenv("NO_API_MODE", "disabled")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        oc_no_api_guard.main()
        assert "blocked=false" in out.read_text()

    def test_main_always_exits_without_error(self, tmp_path, monkeypatch):
        """main() must not raise — provider steps must see blocked output, not a crash."""
        out = tmp_path / "output"
        out.touch()
        monkeypatch.setenv("NO_API_MODE", "true")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        # Should complete without exception
        oc_no_api_guard.main()

    def test_main_prints_blocked_message(self, tmp_path, monkeypatch, capsys):
        out = tmp_path / "output"
        out.touch()
        monkeypatch.setenv("NO_API_MODE", "true")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        oc_no_api_guard.main()
        captured = capsys.readouterr()
        assert "BLOCKED" in captured.out

    def test_main_prints_allowed_message(self, tmp_path, monkeypatch, capsys):
        out = tmp_path / "output"
        out.touch()
        monkeypatch.setenv("NO_API_MODE", "false")
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        oc_no_api_guard.main()
        captured = capsys.readouterr()
        assert "ALLOWED" in captured.out
