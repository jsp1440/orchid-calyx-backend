import pytest
from fastapi import HTTPException

from app.security import require_admin


def test_require_admin_denies_when_server_key_is_unconfigured(monkeypatch):
    monkeypatch.delenv("ORCHID_JUDGE_ADMIN_KEY", raising=False)
    with pytest.raises(HTTPException) as exc:
        require_admin("anything")
    assert exc.value.status_code == 503


def test_require_admin_denies_missing_or_incorrect_key(monkeypatch):
    monkeypatch.setenv("ORCHID_JUDGE_ADMIN_KEY", "expected-secret")

    with pytest.raises(HTTPException) as missing:
        require_admin(None)
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as incorrect:
        require_admin("wrong-secret")
    assert incorrect.value.status_code == 401


def test_require_admin_accepts_matching_configured_key(monkeypatch):
    monkeypatch.setenv("ORCHID_JUDGE_ADMIN_KEY", "expected-secret")
    assert require_admin("expected-secret") is None
