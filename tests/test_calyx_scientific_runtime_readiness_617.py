from __future__ import annotations

import runtime.scientific_runtime_readiness as readiness


def test_scientific_runtime_readiness_reports_validated_ci_environment():
    result = readiness.scientific_runtime_readiness()

    assert result["python_compatible"] is True
    assert result["required_python_minimum"] == "3.12"
    assert result["scientific_dependency_profile"] == "requirements-scientific.txt"
    assert result["scipy_available"] is True
    assert result["scipy_required_version"] == readiness.MEAN_CI_SCIPY_REQUIRED_VERSION
    assert result["scipy_version"] == readiness.MEAN_CI_SCIPY_REQUIRED_VERSION
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


def test_required_scipy_version_is_the_single_pin_in_the_dependency_profile():
    profile = readiness.SCIENTIFIC_DEPENDENCY_PROFILE_PATH
    assert profile.name == readiness.SCIENTIFIC_DEPENDENCY_PROFILE
    pinned = [
        line.split("==", 1)[1].strip()
        for line in profile.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("scipy==")
    ]
    assert len(pinned) == 1
    assert readiness.MEAN_CI_SCIPY_REQUIRED_VERSION == pinned[0]
    assert readiness.required_scipy_version() == pinned[0]


def test_required_scipy_version_fails_closed_without_an_exact_pin(
    tmp_path, monkeypatch
):
    assert readiness.required_scipy_version(tmp_path / "missing.txt") is None

    loose = tmp_path / "loose.txt"
    loose.write_text("-r requirements.txt\nscipy>=1.11\n", encoding="utf-8")
    assert readiness.required_scipy_version(loose) is None

    ambiguous = tmp_path / "ambiguous.txt"
    ambiguous.write_text("scipy==1.18.0\nscipy==1.18.1\n", encoding="utf-8")
    assert readiness.required_scipy_version(ambiguous) is None

    exact = tmp_path / "exact.txt"
    exact.write_text("# profile\nscipy==1.18.0  # validated\n", encoding="utf-8")
    assert readiness.required_scipy_version(exact) == "1.18.0"

    monkeypatch.setattr(readiness, "MEAN_CI_SCIPY_REQUIRED_VERSION", None)
    result = readiness.scientific_runtime_readiness()
    assert result["scipy_required_version"] is None
    assert result["scipy_compatible"] is False
    assert result["mean_ci_candidate_dependency_ready"] is False
