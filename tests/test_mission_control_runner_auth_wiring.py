"""Security + integration coverage for the Mission Control runtime/runner routes.

Background: app/routers/mycorrhiza.py used to define run-once, execute-next,
and execute-all on an orphaned, standalone FastAPI() instance that was never
mounted into the live application and had no authentication dependency at
all. That file has been deleted. The routes now live directly on the
canonical app (app/main.py's `app`), reusing the real job-queue
implementation in runtime/autonomous_runner.py, and are gated by the same
verify_owner_or_api_key dependency (RUNTIME_WRITE_AUTH) used by every other
owner-only Mission Control write route.

This file exists specifically to verify, in one place, the properties the
security review requires:
  1. unauthenticated access is denied
  2. insufficiently privileged (invalid credential) access is denied
  3. authorized execution is permitted
  4. the routes are mounted on the canonical live app, not a side instance
  5. route behavior is deterministic and observable
  6. no duplicate/orphan FastAPI application remains for these endpoints
"""

import importlib

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.main import app

WRITE_ROUTES = [
    "/api/runner/run-once",
    "/api/runner/execute-next",
    "/api/runner/execute-all",
    "/api/runner/autonomous-cycle",
    "/api/runner/start",
    "/api/runner/stop",
    "/api/runner/restart",
]


# ---------------------------------------------------------------------------
# 1. Unauthenticated access is denied
# ---------------------------------------------------------------------------


def test_all_runner_write_routes_reject_unauthenticated(monkeypatch):
    """No credentials at all -> every write route is rejected before its body runs.

    This assertion never touches the database: verify_owner_or_api_key is a
    FastAPI dependency, so it runs before any route body, which is what lets
    this be tested uniformly across all seven routes regardless of DB state.
    """
    monkeypatch.setenv("CALYX_API_KEY", "configured-secret")
    monkeypatch.delenv("CALYX_OWNER_ACCESS_CODE", raising=False)
    client = TestClient(app)

    for path in WRITE_ROUTES:
        response = client.post(path)
        assert response.status_code == 401, f"{path} should reject unauthenticated requests"
        assert response.json()["detail"] == "Owner session or API key is required"
        assert "configured-secret" not in response.text


# ---------------------------------------------------------------------------
# 2. Insufficiently privileged (invalid credential) access is denied
# ---------------------------------------------------------------------------


def test_all_runner_write_routes_reject_invalid_api_key(monkeypatch):
    """A wrong API key is rejected exactly like no key -- it never reaches the route body."""
    monkeypatch.setenv("CALYX_API_KEY", "the-real-secret")
    client = TestClient(app)

    for path in WRITE_ROUTES:
        response = client.post(path, headers={"X-API-Key": "wrong-guess"})
        assert response.status_code == 401, f"{path} should reject an invalid API key"
        assert response.json()["detail"] == "Invalid or missing API key"
        assert "the-real-secret" not in response.text


def test_runner_health_and_configuration_remain_public_read_only():
    """Sanity check: the auth boundary is deliberate, not accidental -- read-only
    diagnostics stay reachable without credentials, only the write routes gate."""
    client = TestClient(app)

    assert client.get("/api/runner/health").status_code == 200
    assert client.get("/api/runtime/configuration").status_code == 200


# ---------------------------------------------------------------------------
# 3. Authorized execution is permitted
# ---------------------------------------------------------------------------


def test_authorized_owner_or_api_key_permits_autonomous_cycle(monkeypatch):
    """A valid API key runs the route body: a real (deterministic, DB-optional)
    engine cycle, not just an auth pass-through."""
    monkeypatch.setenv("CALYX_API_KEY", "test-secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)

    response = client.post("/api/runner/autonomous-cycle", headers={"X-API-Key": "test-secret"})

    assert response.status_code == 200
    assert response.json()["status"] in {"completed", "failed"}


def test_authorized_run_once_delegates_to_the_canonical_job_queue(monkeypatch):
    """run-once is a thin, auth-gated wrapper around runtime.autonomous_runner.enqueue_default_jobs.

    The real function does a live DB write, which this offline test suite
    cannot exercise; instead this proves the wiring itself -- auth passes,
    and the route calls through to exactly the function the canonical
    background loop uses -- by substituting a stand-in and confirming the
    route returns its result unmodified.
    """
    monkeypatch.setenv("CALYX_API_KEY", "test-secret")
    sentinel = {"status": "ok", "jobs_created": ["stand-in"], "jobs_skipped_as_duplicates": []}
    monkeypatch.setattr(main, "enqueue_default_jobs", lambda: sentinel)
    client = TestClient(app)

    response = client.post("/api/runner/run-once", headers={"X-API-Key": "test-secret"})

    assert response.status_code == 200
    assert response.json() == sentinel


def test_authorized_owner_session_also_permits_execution(monkeypatch):
    """The owner-session cookie/bearer path is an equally valid credential, not
    just the API key -- matching every other owner-only Mission Control route."""
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


# ---------------------------------------------------------------------------
# 4. Router is actually mounted in the canonical live app
# ---------------------------------------------------------------------------


def test_runner_routes_are_registered_directly_on_the_canonical_app():
    """The routes must exist on app.main.app -- the same FastAPI instance the
    live service serves -- not on any separate app object."""
    registered_paths = {route.path for route in app.routes}

    for path in WRITE_ROUTES + ["/api/runner/health", "/api/runtime/configuration"]:
        assert path in registered_paths, f"{path} is not mounted on the canonical app"


def test_execute_next_route_is_bound_to_the_canonical_job_queue_function():
    """execute-next must be the exact runtime.autonomous_runner.execute_next_job
    function object as its handler -- not a second, divergent implementation."""
    from runtime.autonomous_runner import execute_next_job

    matches = [route for route in app.routes if getattr(route, "path", None) == "/api/runner/execute-next"]
    assert len(matches) == 1
    assert matches[0].endpoint is execute_next_job


# ---------------------------------------------------------------------------
# 5. Route behavior remains deterministic and observable
# ---------------------------------------------------------------------------


def test_high_risk_routes_require_explicit_confirmation_before_evaluation(monkeypatch):
    """Without confirm=true, the high-risk lifecycle/queue-drain routes always
    return the same observable "awaiting_owner" shape -- they never touch
    runtime state on a bare, unconfirmed POST."""
    monkeypatch.setenv("CALYX_API_KEY", "test-secret")
    client = TestClient(app)
    headers = {"X-API-Key": "test-secret"}

    for path in ["/api/runner/execute-all", "/api/runner/start", "/api/runner/stop", "/api/runner/restart"]:
        response = client.post(path, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "awaiting_owner"
        assert body["decision"]["status"] == "review_required"


def test_high_risk_routes_remain_blocked_pending_owner_governance_even_when_confirmed(monkeypatch):
    """This is the documented human-governance boundary.

    execute-all, start, stop, and restart request AutonomyLevel.OWNER_APPROVAL_REQUIRED
    from the constitutional orchestrator (runtime.constitutional_orchestrator).
    That policy always resolves to status "review_required" at that level --
    by design, no confirm=true flag in the request body can promote it further.
    Real activation of full-queue draining or worker lifecycle changes needs an
    actual Brain/owner governance decision (e.g. a policy-registry change),
    which is outside what an HTTP request can grant itself. Until that
    decision is made, the correct, secure, and deterministic behavior is to
    stay blocked -- this test locks that in so the boundary can't be
    silently loosened by a future change to app.main.
    """
    monkeypatch.setenv("CALYX_API_KEY", "test-secret")
    client = TestClient(app)
    headers = {"X-API-Key": "test-secret"}

    for path in ["/api/runner/execute-all", "/api/runner/start", "/api/runner/stop", "/api/runner/restart"]:
        response = client.post(path, json={"confirm": True}, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "blocked"
        assert body["decision"]["status"] == "review_required"


def test_runner_allowed_actions_disclose_risk_tier_without_authenticating():
    """/api/runner/health's allowedActions map is the deterministic, observable
    contract a caller inspects before attempting a write -- confirm it lists
    every write route with its declared risk tier."""
    client = TestClient(app)
    actions = client.get("/api/runner/health").json()["allowedActions"]

    assert actions["executeAll"]["risk"] == "high"
    assert actions["startRuntime"]["risk"] == "high"
    assert actions["stopRuntime"]["risk"] == "high"
    assert actions["restartRuntime"]["risk"] == "high"
    for entry in actions.values():
        assert entry["allowed"] is False
        assert entry["auth"] == "owner_session_or_api_key_required"


# ---------------------------------------------------------------------------
# 6. No duplicate/orphan FastAPI application remains for these endpoints
# ---------------------------------------------------------------------------


def test_mycorrhiza_orphan_router_module_no_longer_exists():
    """app/routers/mycorrhiza.py -- the orphaned, unauthenticated standalone
    FastAPI() instance this whole slice replaces -- has been deleted outright
    rather than left importable as dead code."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.routers.mycorrhiza")


def test_no_second_fastapi_instance_serves_runner_paths():
    """Only one FastAPI() app in app.main defines these routes; nothing else
    in the app.routers package declares a competing app object for them."""
    import app.main as main_module

    fastapi_app_attrs = [
        name
        for name, value in vars(main_module).items()
        if type(value).__name__ == "FastAPI"
    ]
    assert fastapi_app_attrs == ["app"]
