"""Regression guards for the deployed owner-session smoke test's credential transport.

The backend moved the owner session to an ``HttpOnly`` cookie and returns the
literal string ``"cookie"`` in the response body's ``token`` field. The smoke
script previously treated that literal as a bearer token, which produced two
false passes followed by a genuine ``401`` on ``/owner/permissions``. These tests
pin the corrected behaviour so the same drift cannot recur silently.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "smoke_owner_backend.py"

spec = importlib.util.spec_from_file_location("smoke_owner_backend", SCRIPT_PATH)
smoke = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = smoke
spec.loader.exec_module(smoke)


def test_cookie_sentinel_is_not_treated_as_a_bearer_token():
    assert smoke.bearer_from({"token": "cookie"}) == ""


def test_real_bearer_token_is_still_honoured():
    assert smoke.bearer_from({"token": "abc.def"}) == "abc.def"
    assert smoke.bearer_from({"access_token": "xyz.123"}) == "xyz.123"


def test_missing_token_field_yields_no_bearer():
    assert smoke.bearer_from({}) == ""


def _run_with(monkeypatch, responses, *, cookie_present):
    """Drive ``main()`` against a scripted ``(path, method) -> (status, body)`` map."""
    calls = []

    def fake_request(path, *, method="GET", payload=None, token=""):
        calls.append((path, method, token))
        return responses[(path, method)]

    monkeypatch.setattr(smoke, "request", fake_request)
    monkeypatch.setattr(smoke, "session_cookie_present", lambda: cookie_present)
    monkeypatch.setattr(smoke, "ACCESS_CODE", "test-code")
    return smoke.main(), calls


BASE_OK = {
    ("/health", "GET"): (200, {}),
    ("/api/mission-control/owner/session", "POST"): (
        200,
        {"authenticated": True, "token": "cookie"},
    ),
    ("/api/mission-control/owner/session", "GET"): (200, {"authenticated": True}),
    ("/api/mission-control/owner/permissions", "GET"): (
        200,
        {"allowedActions": {"runtime": {"allowed": True}}},
    ),
    ("/brain/mission-control/chat/status", "GET"): (200, {}),
    ("/brain/mission-control/runtime/status", "GET"): (200, {}),
}


def test_cookie_transport_passes_end_to_end(monkeypatch):
    exit_code, calls = _run_with(monkeypatch, dict(BASE_OK), cookie_present=True)
    assert exit_code == 0
    # Under the cookie transport no Authorization header is ever sent.
    assert all(token == "" for _, _, token in calls)


def test_unauthenticated_validate_is_not_a_pass(monkeypatch):
    """A ``200`` carrying ``authenticated: false`` must fail, not pass.

    This is the exact false pass the previous script produced: the unauthenticated
    ``GET /owner/session`` answers ``200 {"authenticated": false}``.
    """
    responses = dict(BASE_OK)
    responses[("/api/mission-control/owner/session", "GET")] = (
        200,
        {"authenticated": False},
    )
    exit_code, _ = _run_with(monkeypatch, responses, cookie_present=True)
    assert exit_code == 1


def test_session_without_any_credential_fails(monkeypatch):
    responses = dict(BASE_OK)
    responses[("/api/mission-control/owner/session", "POST")] = (
        200,
        {"authenticated": True, "token": "cookie"},
    )
    exit_code, _ = _run_with(monkeypatch, responses, cookie_present=False)
    assert exit_code == 1


def test_permissions_401_is_reported_as_a_failed_check_not_an_abort(monkeypatch):
    """A 401 must be recorded as a failing named check, leaving later checks runnable."""
    responses = dict(BASE_OK)
    responses[("/api/mission-control/owner/permissions", "GET")] = (
        401,
        {"detail": "Invalid owner session"},
    )
    exit_code, calls = _run_with(monkeypatch, responses, cookie_present=True)
    assert exit_code == 1
    # The two trailing status checks still ran rather than being skipped by an abort.
    paths = [path for path, _, _ in calls]
    assert "/brain/mission-control/chat/status" in paths
    assert "/brain/mission-control/runtime/status" in paths
