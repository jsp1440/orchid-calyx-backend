from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import app.main as main
import app.security as security
from app.main import app


def test_api_key_missing_with_header_reports_configuration_blocker(monkeypatch):
    monkeypatch.delenv("CALYX_API_KEY", raising=False)
    client = TestClient(app)

    response = client.post("/api/runner/autonomous-cycle", headers={"X-API-Key": "supplied-but-unconfigured"})

    assert response.status_code == 401
    assert response.json()["detail"] == "API key authentication is not configured"
    assert "supplied-but-unconfigured" not in response.text


def test_api_key_valid_uses_constant_time_comparison(monkeypatch):
    calls: list[tuple[str, str]] = []

    def compare_digest(left: str, right: str) -> bool:
        calls.append((left, right))
        return left == right

    monkeypatch.setenv("CALYX_API_KEY", "test-secret")
    monkeypatch.setattr(security.hmac, "compare_digest", compare_digest)

    protected = FastAPI()

    @protected.post("/protected", dependencies=[Depends(security.verify_api_key)])
    def protected_route():
        return {"status": "ok"}

    response = TestClient(protected).post("/protected", headers={"X-API-Key": "test-secret"})

    assert response.status_code == 200
    assert calls == [("test-secret", "test-secret")]


def test_owner_session_authorizes_runtime_control_without_api_key(monkeypatch):
    monkeypatch.delenv("CALYX_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CALYX_OWNER_ACCESS_CODE", "owner-code")
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "owner-session-secret-for-tests")
    client = TestClient(app)

    session = client.post("/api/mission-control/owner/session", json={"access_code": "owner-code"})
    assert session.status_code == 200
    token = session.json()["token"]

    response = client.post("/api/runner/autonomous-cycle", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["status"] in {"completed", "failed"}
    assert "owner-session-secret-for-tests" not in response.text


def test_unauthorized_runtime_control_still_rejected(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", "test-secret")
    client = TestClient(app)

    response = client.post("/api/runner/autonomous-cycle")

    assert response.status_code == 401
    assert response.json()["detail"] == "Owner session or API key is required"
    assert "test-secret" not in response.text


def test_runtime_configuration_diagnostic_is_secret_safe(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", "runtime-secret")
    monkeypatch.setenv("CALYX_OWNER_ACCESS_CODE", "owner-code")
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@example/db")
    monkeypatch.setenv("CALYX_AUTOLOOP_ENABLED", "true")
    monkeypatch.setenv("CALYX_RUNTIME_INTERVAL_SECONDS", "45")
    client = TestClient(app)

    response = client.get("/api/runtime/configuration")

    assert response.status_code == 200
    payload = response.json()
    assert payload["api_key_configured"] is True
    assert payload["owner_access_code_configured"] is True
    assert payload["owner_session_secret_configured"] is True
    assert payload["database_configured"] is True
    assert payload["runtime_enabled"] is True
    assert payload["interval_seconds"] == 45
    for secret in ["runtime-secret", "owner-code", "session-secret", "user:pass"]:
        assert secret not in response.text


def test_runtime_enable_and_interval_canonical_env(monkeypatch):
    for key in main.RUNTIME_ENABLE_FLAGS + main.RUNTIME_DISABLE_FLAGS + main.RUNTIME_INTERVAL_FLAGS:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("CALYX_AUTOLOOP_ENABLED", "true")
    monkeypatch.setenv("CALYX_RUNTIME_INTERVAL_SECONDS", "9")

    assert main.autonomous_runtime_enabled_by_config() is True
    assert main.runtime_interval_seconds_from_env() == 9


def test_execute_next_uses_skip_locked_for_duplicate_job_prevention():
    source = main.execute_next.__code__.co_consts
    sql_fragments = "\n".join(str(item) for item in source if isinstance(item, str))

    assert "FOR UPDATE SKIP LOCKED" in sql_fragments
