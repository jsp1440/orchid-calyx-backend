import pytest
from fastapi import HTTPException

from api_occurrence_points import require_exact_occurrence_access


def test_exact_occurrence_api_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OC_ALLOW_EXACT_OCCURRENCE_API", raising=False)
    monkeypatch.setenv("CALYX_API_KEY", "expected")
    with pytest.raises(HTTPException) as exc:
        require_exact_occurrence_access("expected")
    assert exc.value.status_code == 503


def test_exact_occurrence_api_requires_configured_api_key(monkeypatch):
    monkeypatch.setenv(
        "OC_ALLOW_EXACT_OCCURRENCE_API",
        "YES_I_UNDERSTAND_THIS_EXPOSES_EXACT_ORCHID_LOCATIONS",
    )
    monkeypatch.delenv("CALYX_API_KEY", raising=False)
    with pytest.raises(HTTPException) as exc:
        require_exact_occurrence_access("anything")
    assert exc.value.status_code == 503


def test_exact_occurrence_api_rejects_wrong_api_key(monkeypatch):
    monkeypatch.setenv(
        "OC_ALLOW_EXACT_OCCURRENCE_API",
        "YES_I_UNDERSTAND_THIS_EXPOSES_EXACT_ORCHID_LOCATIONS",
    )
    monkeypatch.setenv("CALYX_API_KEY", "expected")
    with pytest.raises(HTTPException) as exc:
        require_exact_occurrence_access("wrong")
    assert exc.value.status_code == 401


def test_exact_occurrence_api_requires_both_explicit_enable_and_key(monkeypatch):
    monkeypatch.setenv(
        "OC_ALLOW_EXACT_OCCURRENCE_API",
        "YES_I_UNDERSTAND_THIS_EXPOSES_EXACT_ORCHID_LOCATIONS",
    )
    monkeypatch.setenv("CALYX_API_KEY", "expected")
    assert require_exact_occurrence_access("expected") is None
