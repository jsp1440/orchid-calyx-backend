"""Release 1 environment checklist: preflight script and owner readiness route.

Both surfaces report names, the required flag and presence only. Sentinel
values are planted in every variable and must never appear in any output, nor
their SHA-256 / MD5 digests.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import member_auth
from app.release_env import RELEASE1_ENV, RELEASE1_ENV_NAMES, config_readiness

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "preflight_release1_env.py"
ROUTE = "/api/system/config-readiness"
TEST_API_KEY = "local-test-api-key-not-a-credential"
TEST_SESSION_SECRET = "local-test-session-secret-not-a-credential"
MEMBER_UUID = "44444444-4444-4444-4444-444444444444"
REQUIRED = [v.name for v in RELEASE1_ENV if v.required]


def sentinel(name: str) -> str:
    return f"SENTINEL-{name}-7f3kq9"


def all_sentinels() -> dict[str, str]:
    return {name: sentinel(name) for name in RELEASE1_ENV_NAMES}


def assert_no_values(text: str, values: dict[str, str]) -> None:
    for value in values.values():
        assert value not in text
        assert value.lower() not in text.lower()
        assert hashlib.sha256(value.encode()).hexdigest()[:16] not in text
        assert hashlib.md5(value.encode()).hexdigest()[:16] not in text
        assert base64.b64encode(value.encode()).decode()[:16] not in text


def clean_env(**overrides: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in RELEASE1_ENV_NAMES}
    env.update(overrides)
    return env


def run_script(env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


# --- catalogue ---------------------------------------------------------------


def test_catalogue_names_are_unique_and_cover_the_release1_contract():
    assert len(RELEASE1_ENV_NAMES) == len(set(RELEASE1_ENV_NAMES))
    for name in (
        "OC_SUPABASE_URL",
        "OC_SUPABASE_ANON_KEY",
        "OCU_SUPABASE_URL",
        "OCU_SUPABASE_ANON_KEY",
        "CALYX_OWNER_ACCESS_CODE",
        "CALYX_OWNER_SESSION_SECRET",
        "CALYX_API_KEY",
        "OC_MEMBER_READS_ENABLED",
        "CALYX_EVIDENCE_FEEDBACK_ACTOR_REF_SECRET",
        "CALYX_EVIDENCE_FEEDBACK_ROOT",
        "DATABASE_URL",
        "NO_API_MODE",
        "FIRECRAWL_API_KEY",
        "FIRECRAWL_PILOT_GENUS",
        "FIRECRAWL_PILOT_ISSUE_NUMBER",
    ):
        assert name in RELEASE1_ENV_NAMES, name
    for item in RELEASE1_ENV:
        assert item.purpose and item.default and item.when_missing, item.name
        for fallback in item.fallbacks:
            assert fallback in RELEASE1_ENV_NAMES


def test_readme_documents_every_catalogue_variable():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for item in RELEASE1_ENV:
        required = "**Yes**" if item.required else "No"
        assert f"| `{item.name}` | {required}" in readme, item.name


def test_catalogue_names_match_what_the_code_reads():
    """Guard against a renamed variable leaving a stale checklist entry."""
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "app").rglob("*.py")
        if path.name != "release_env.py"
    )
    for name in RELEASE1_ENV_NAMES:
        assert f'"{name}"' in sources, name


# --- readiness function ------------------------------------------------------


def test_every_variable_is_reported_absent_on_an_empty_environment():
    report = config_readiness({})
    assert [v["name"] for v in report["variables"]] == list(RELEASE1_ENV_NAMES)
    assert all(v["present"] is False for v in report["variables"])
    assert report["ready"] is False
    assert report["missing_required"] == REQUIRED


def test_blank_values_are_absent_and_fallbacks_satisfy_required():
    env = {name: sentinel(name) for name in REQUIRED}
    env["OC_SUPABASE_URL"] = "   "
    env.pop("OC_SUPABASE_ANON_KEY")
    assert config_readiness(env)["missing_required"] == [
        "OC_SUPABASE_URL",
        "OC_SUPABASE_ANON_KEY",
    ]
    env["OCU_SUPABASE_URL"] = sentinel("OCU_SUPABASE_URL")
    env["OCU_SUPABASE_ANON_KEY"] = sentinel("OCU_SUPABASE_ANON_KEY")
    report = config_readiness(env)
    assert report["ready"] is True
    by_name = {v["name"]: v for v in report["variables"]}
    assert by_name["OC_SUPABASE_URL"] == {
        "name": "OC_SUPABASE_URL",
        "required": True,
        "present": False,
        "satisfied": True,
    }


def test_report_holds_only_names_flags_and_booleans():
    values = all_sentinels()
    report = config_readiness(values)
    assert set(report) == {"ready", "missing_required", "variables"}
    for entry in report["variables"]:
        assert set(entry) <= {"name", "required", "present", "satisfied"}
        assert all(isinstance(entry[k], bool) for k in entry if k != "name")
    assert_no_values(json.dumps(report), values)


# --- preflight script ----------------------------------------------------------


def test_script_reports_every_variable_and_never_prints_values():
    values = all_sentinels()
    text_run = run_script(clean_env(**values))
    json_run = run_script(clean_env(**values), "--json")
    assert text_run.returncode == 0, text_run.stderr
    assert json_run.returncode == 0, json_run.stderr
    lines = text_run.stdout.splitlines()
    for name in RELEASE1_ENV_NAMES:
        assert any(line.startswith(f"{name}: present [") for line in lines), name
    assert lines[-1] == "READY: every required variable is present"
    assert [v["name"] for v in json.loads(json_run.stdout)["variables"]] == list(
        RELEASE1_ENV_NAMES
    )
    for run in (text_run, json_run):
        assert_no_values(run.stdout + run.stderr, values)


def test_script_exits_non_zero_when_a_required_variable_is_missing():
    values = all_sentinels()
    values.pop("CALYX_OWNER_SESSION_SECRET")
    result = run_script(clean_env(**values))
    assert result.returncode == 1
    assert "CALYX_OWNER_SESSION_SECRET: absent [required]" in result.stdout
    assert "NOT READY: missing required: CALYX_OWNER_SESSION_SECRET" in result.stdout
    assert_no_values(result.stdout + result.stderr, values)


def test_script_only_optional_missing_is_ready():
    values = {name: sentinel(name) for name in REQUIRED}
    result = run_script(clean_env(**values))
    assert result.returncode == 0, result.stdout
    assert "NO_API_MODE: absent [optional]" in result.stdout


def test_script_makes_no_network_connection(monkeypatch, capsys):
    import importlib.util

    def refuse(*_a, **_k):
        raise AssertionError("preflight must not open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    for name in RELEASE1_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    spec = importlib.util.spec_from_file_location("preflight_release1_env", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main([]) == 1
    assert "NOT READY" in capsys.readouterr().out


# --- owner-only route ------------------------------------------------------------


@pytest.fixture
def planted(monkeypatch) -> dict[str, str]:
    values = all_sentinels()
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    # Authentication needs real (test-only) values for these three.
    monkeypatch.setenv("CALYX_API_KEY", TEST_API_KEY)
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.setenv("OC_MEMBER_READS_ENABLED", "true")
    for name in (
        "CALYX_API_KEY",
        "CALYX_OWNER_SESSION_SECRET",
        "OC_MEMBER_READS_ENABLED",
    ):
        values.pop(name)
    member_auth.clear_member_token_cache()
    yield values
    member_auth.clear_member_token_cache()


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def owner_headers() -> dict[str, str]:
    from app.security import create_owner_session_token

    return {"Authorization": f"Bearer {create_owner_session_token('owner')['token']}"}


def member_headers(monkeypatch) -> dict[str, str]:
    response = Mock(status_code=200, ok=True)
    response.json.return_value = {"id": MEMBER_UUID, "email": "member@example.org"}
    monkeypatch.setattr(
        "app.university.learner_auth.requests.get", Mock(return_value=response)
    )

    def enc(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    claims = {"sub": MEMBER_UUID, "exp": int(time.time() + 3600)}
    token = f"{enc({'alg': 'HS256', 'typ': 'JWT'})}.{enc(claims)}.sig"
    return {"Authorization": f"Bearer {token}"}


def test_owner_gets_presence_report_without_values(client, planted):
    response = client.get(ROUTE, headers=owner_headers())
    assert response.status_code == 200, response.text
    body = response.json()
    assert [v["name"] for v in body["variables"]] == list(RELEASE1_ENV_NAMES)
    assert all(v["present"] is True for v in body["variables"])
    assert body["ready"] is True
    assert_no_values(response.text, planted)
    assert TEST_SESSION_SECRET not in response.text
    assert TEST_API_KEY not in response.text


def test_member_is_forbidden(client, planted, monkeypatch):
    response = client.get(ROUTE, headers=member_headers(monkeypatch))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "OWNER_ACCESS_REQUIRED"
    assert_no_values(response.text, planted)


def test_anonymous_is_unauthorized(client, planted):
    response = client.get(ROUTE)
    assert response.status_code == 401
    assert "variables" not in response.text
    assert_no_values(response.text, planted)


def test_backend_api_key_alone_is_not_the_owner(client, planted):
    response = client.get(ROUTE, headers={"X-API-Key": TEST_API_KEY})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "OWNER_SESSION_REQUIRED"
