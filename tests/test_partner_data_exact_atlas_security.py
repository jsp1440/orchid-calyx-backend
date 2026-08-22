import pytest

import oc_orchid_atlas


def test_exact_atlas_generation_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OC_ALLOW_EXACT_ORCHID_ATLAS", raising=False)
    with pytest.raises(PermissionError):
        oc_orchid_atlas.require_exact_atlas_generation()


def test_exact_atlas_generation_rejects_near_match(monkeypatch):
    monkeypatch.setenv("OC_ALLOW_EXACT_ORCHID_ATLAS", "yes")
    with pytest.raises(PermissionError):
        oc_orchid_atlas.require_exact_atlas_generation()


def test_exact_atlas_generation_requires_high_friction_acknowledgement(monkeypatch):
    monkeypatch.setenv(
        "OC_ALLOW_EXACT_ORCHID_ATLAS",
        "YES_I_UNDERSTAND_THIS_EXPORTS_EXACT_ORCHID_LOCATIONS",
    )
    assert oc_orchid_atlas.require_exact_atlas_generation() is None
