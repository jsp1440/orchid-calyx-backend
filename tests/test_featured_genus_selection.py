import pytest

from app.featured_genus.selection import (
    DEFAULT_ROTATION_CANDIDATES,
    ROTATION_WINDOW_SECONDS,
    canonical_genus,
    select_featured_genus,
)


def test_deterministic_rotation_matches_frontend_window_math():
    # The frontend featuredGenus.ts contract: floor(epoch / 12h) % len(candidates).
    first = select_featured_genus(0, policy={})
    assert first["genus"] == "Cattleya"
    assert first["source"] == "deterministic_rotation"
    assert first["window"]["index"] == 0

    third_window = select_featured_genus(ROTATION_WINDOW_SECONDS * 3 + 5, policy={})
    assert third_window["genus"] == "Dendrobium"
    assert third_window["window"]["seconds_remaining"] == ROTATION_WINDOW_SECONDS - 5

    wrapped = select_featured_genus(
        ROTATION_WINDOW_SECONDS * len(DEFAULT_ROTATION_CANDIDATES), policy={}
    )
    assert wrapped["genus"] == "Cattleya"


def test_selection_is_reproducible_for_the_same_epoch():
    a = select_featured_genus(1_700_000_000, policy={})
    b = select_featured_genus(1_700_000_000, policy={})
    assert a["genus"] == b["genus"]
    assert a["window"] == b["window"]


def test_canonical_genus_rejects_binomials_routes_and_oversized_values():
    for bad in ("Cattleya labiata", "cattleya", "", "Cattleya?x=1", "/atlas", "C" * 121, None):
        with pytest.raises(ValueError):
            canonical_genus(bad)
    assert canonical_genus("  Cattleya  ") == "Cattleya"


def _override(**overrides):
    base = {
        "genus": "Dracula",
        "reason": "Editorial feature for the vampire-orchid teaching week.",
        "reviewer": "science-editor",
        "expires_at": "2999-01-01",
    }
    base.update(overrides)
    return base


def test_active_editorial_override_wins_and_reports_provenance():
    result = select_featured_genus(0, policy={"override": _override()})
    assert result["genus"] == "Dracula"
    assert result["source"] == "editorial_override"
    assert result["override"]["status"] == "active"
    assert result["override"]["reviewer"] == "science-editor"
    # The deterministic identity remains visible for auditability.
    assert result["rotation"]["deterministic_genus"] == "Cattleya"


def test_expired_override_falls_back_to_rotation():
    result = select_featured_genus(1_700_000_000, policy={"override": _override(expires_at="2020-01-01")})
    assert result["source"] == "deterministic_rotation"
    assert result["override"]["status"] == "expired"


def test_non_candidate_override_requires_evidence_review():
    rejected = select_featured_genus(0, policy={"override": _override(genus="Paphiopedilum")})
    assert rejected["source"] == "deterministic_rotation"
    assert rejected["override"]["status"] == "rejected"

    accepted = select_featured_genus(
        0, policy={"override": _override(genus="Paphiopedilum", evidence_reviewed=True)}
    )
    assert accepted["genus"] == "Paphiopedilum"
    assert accepted["source"] == "editorial_override"


def test_override_missing_fields_is_rejected_loudly():
    result = select_featured_genus(0, policy={"override": {"genus": "Dracula"}})
    assert result["override"]["status"] == "rejected"
    assert set(result["override"]["missing"]) == {"reason", "reviewer", "expires_at"}


def test_malformed_policy_file_degrades_to_deterministic_with_warning(tmp_path):
    bad = tmp_path / "policy.json"
    bad.write_text("{not json", encoding="utf-8")
    result = select_featured_genus(0, policy_path=bad)
    assert result["source"] == "deterministic_rotation"
    assert "policy_load_warning" in result


def test_missing_policy_file_degrades_to_deterministic_with_warning(tmp_path):
    result = select_featured_genus(0, policy_path=tmp_path / "absent.json")
    assert result["genus"] == "Cattleya"
    assert "policy_load_warning" in result


def test_noncanonical_policy_candidates_fall_back_to_defaults():
    policy = {"rotation": {"candidates": ["Cattleya labiata", "Dracula"]}}
    result = select_featured_genus(0, policy=policy)
    assert "candidates_warning" in result
    assert result["rotation"]["candidates"] == list(DEFAULT_ROTATION_CANDIDATES)
