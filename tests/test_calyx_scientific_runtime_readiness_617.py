from __future__ import annotations

import runtime.scientific_runtime_readiness as readiness


def test_scientific_runtime_readiness_reports_validated_ci_environment():
    result = readiness.scientific_runtime_readiness()

    assert result["python_compatible"] is True
    assert result["required_python_minimum"] == "3.12"
    assert result["scientific_dependency_profile"] == "requirements-scientific.txt"
    assert result["scipy_available"] is True
    assert result["scipy_required_version"] == "1.18.0"
    assert result["scipy_version"] == "1.18.0"
    assert result["scipy_compatible"] is True
    assert result["mean_ci_candidate_dependency_ready"] is True
    assert result["mean_ci_live_method_registered"] is False
    assert result["readiness_is_dependency_state_not_publication_authority"] is True


def test_scientific_runtime_readiness_fails_closed_when_scipy_is_absent(monkeypatch):
    monkeypatch.setattr(readiness, "find_spec", lambda package: None)

    result = readiness.scientific_runtime_readiness()

    assert result["scipy_available"] is False
    assert result["scipy_version"] is None
    assert result["scipy_compatible"] is False
    assert result["mean_ci_candidate_dependency_ready"] is False
    assert result["mean_ci_live_method_registered"] is False
