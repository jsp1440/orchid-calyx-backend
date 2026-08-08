from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import matrix_operational as api
from app.security import verify_owner_or_api_key
from runtime.matrix_identification import Candidate
from runtime.matrix_identification_registry import (
    RegistryCharacter,
    create_registry_version,
)
from runtime.matrix_operational import (
    create_identification_session,
    get_candidate_explanation,
    resolve_candidate_name,
)


def _registry(root: Path) -> dict:
    return create_registry_version(
        registry_id="cattleya-close-pair",
        version="2026-08",
        title="Cattleya close-candidate fixture",
        scope={"family": "Orchidaceae", "purpose": "review-only fixture"},
        characters=[
            RegistryCharacter("lip_color", "Lip color", weight=2.0),
            RegistryCharacter("flower_count", "Flowers per inflorescence", value_type="numeric_range", weight=1.5),
            RegistryCharacter("pseudobulb_shape", "Pseudobulb shape", weight=1.0),
            RegistryCharacter("fragrance", "Fragrance", weight=0.5),
        ],
        candidates=[
            Candidate(
                taxon_id="taxon:cattleya-labiata",
                scientific_name="Cattleya labiata",
                states={
                    "lip_color": "purple",
                    "flower_count": {"min": 2, "max": 5},
                    "pseudobulb_shape": "club-shaped",
                },
                provenance={
                    "source": "fixture:reviewed-literature",
                    "synonyms": ["Cattleya labiata Lindl."],
                },
            ),
            Candidate(
                taxon_id="taxon:cattleya-warneri",
                scientific_name="Cattleya warneri",
                states={
                    "lip_color": "magenta",
                    "flower_count": {"min": 2, "max": 4},
                    "pseudobulb_shape": "fusiform",
                    "fragrance": "present",
                },
                provenance={"source": "fixture:reviewed-literature"},
            ),
        ],
        provenance={
            "evidence_contract": "reviewed-literature-fixture",
            "artifact_registry": "BUILD-BRAIN-111A",
        },
        actor="test-reviewer",
        root=root,
    )["record"]


def _observations() -> list[dict]:
    return [
        {"character": "lip_color", "value": "purple", "certainty": "certain", "weight": 1.0},
        {"character": "flower_count", "value": 4, "certainty": "probable", "weight": 1.0},
        {"character": "pseudobulb_shape", "value": "club-shaped", "certainty": "certain", "weight": 1.0},
        {"character": "fragrance", "value": None, "certainty": "unknown", "weight": 1.0},
    ]


def test_close_candidate_ranking_is_deterministic_and_explainable(tmp_path: Path):
    registry_root = tmp_path / "registry"
    _registry(registry_root)
    session_root = tmp_path / "sessions"
    first = create_identification_session(
        registry_id="cattleya-close-pair",
        version="2026-08",
        observations=_observations(),
        registry_root=registry_root,
        root=session_root,
    )
    replay = create_identification_session(
        registry_id="cattleya-close-pair",
        version="2026-08",
        observations=_observations(),
        registry_root=registry_root,
        root=session_root,
    )

    assert first["created"] is True
    assert replay["created"] is False
    assert first["session"]["session_id"] == replay["session"]["session_id"]
    candidates = first["session"]["candidates"]
    assert candidates[0]["taxon_id"] == "taxon:cattleya-labiata"
    assert candidates[0]["score"] > candidates[1]["score"]
    assert candidates[0]["support_count"] >= 3
    assert candidates[1]["contradiction_count"] >= 2
    assert candidates[0]["unknown_count"] == 1
    assert candidates[0]["missing_data_count"] == 0
    assert 0 <= candidates[0]["confidence_lower"] <= candidates[0]["confidence_upper"] <= 1
    assert first["session"]["definitive_identification"] is False
    assert first["session"]["human_review_required"] is True


def test_missing_candidate_data_is_distinct_from_contradiction(tmp_path: Path):
    registry_root = tmp_path / "registry"
    _registry(registry_root)
    session = create_identification_session(
        registry_id="cattleya-close-pair",
        version="2026-08",
        observations=[
            {"character": "fragrance", "value": "present", "certainty": "certain"},
        ],
        registry_root=registry_root,
        root=tmp_path / "sessions",
    )["session"]
    by_id = {item["taxon_id"]: item for item in session["candidates"]}
    labiata = by_id["taxon:cattleya-labiata"]
    warneri = by_id["taxon:cattleya-warneri"]
    assert labiata["missing_data_count"] == 1
    assert labiata["contradiction_count"] == 0
    assert warneri["support_count"] == 1


def test_synonym_resolution_returns_canonical_identity(tmp_path: Path):
    registry_root = tmp_path / "registry"
    record = _registry(registry_root)
    candidates = [Candidate(**item) for item in record["candidates"]]
    resolved = resolve_candidate_name(candidates, "Cattleya labiata Lindl.")
    assert resolved == {
        "state": "matched",
        "canonical_taxon_id": "taxon:cattleya-labiata",
        "scientific_name": "Cattleya labiata",
    }
    unmatched = resolve_candidate_name(candidates, "Unknown orchid")
    assert unmatched["state"] == "unmatched"


def test_character_explanation_is_retrievable_read_only(tmp_path: Path):
    registry_root = tmp_path / "registry"
    _registry(registry_root)
    session_root = tmp_path / "sessions"
    session = create_identification_session(
        registry_id="cattleya-close-pair",
        version="2026-08",
        observations=_observations(),
        registry_root=registry_root,
        root=session_root,
    )["session"]
    explanation = get_candidate_explanation(
        session["session_id"], "taxon:cattleya-labiata", root=session_root
    )
    assert explanation["candidate"]["explanations"]
    assert {item["status"] for item in explanation["candidate"]["explanations"]} >= {
        "matched",
        "ignored_unknown_observation",
    }
    assert explanation["definitive_identification"] is False


def test_unknown_character_and_duplicate_observation_fail_closed(tmp_path: Path):
    registry_root = tmp_path / "registry"
    _registry(registry_root)
    for observations, expected in (
        ([{"character": "not_registered", "value": "x"}], "unknown matrix character"),
        (
            [
                {"character": "lip_color", "value": "purple"},
                {"character": "lip_color", "value": "purple"},
            ],
            "duplicate observation",
        ),
    ):
        try:
            create_identification_session(
                registry_id="cattleya-close-pair",
                version="2026-08",
                observations=observations,
                registry_root=registry_root,
                root=tmp_path / "sessions",
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("invalid Matrix session input must fail closed")


def test_protected_api_persists_then_reads_ranking_and_explanation(tmp_path: Path, monkeypatch):
    registry_root = tmp_path / "registry"
    _registry(registry_root)
    session_root = tmp_path / "sessions"
    monkeypatch.setenv("CALYX_MATRIX_REGISTRY_DIR", str(registry_root))
    monkeypatch.setenv("CALYX_MATRIX_SESSION_DIR", str(session_root))

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "test-owner"}
    client = TestClient(app)

    created = client.post(
        "/brain/mission-control/matrix/sessions",
        json={
            "registry_id": "cattleya-close-pair",
            "version": "2026-08",
            "observations": _observations(),
            "limit": 10,
        },
    )
    assert created.status_code == 200
    session_id = created.json()["session"]["session_id"]

    read = client.get(f"/brain/mission-control/matrix/sessions/{session_id}")
    assert read.status_code == 200
    assert read.json()["candidates"][0]["taxon_id"] == "taxon:cattleya-labiata"

    explanation = client.get(
        f"/brain/mission-control/matrix/sessions/{session_id}/candidates/taxon:cattleya-labiata"
    )
    assert explanation.status_code == 200
    assert explanation.json()["human_review_required"] is True

    synonym = client.get(
        "/brain/mission-control/matrix/registries/cattleya-close-pair/2026-08/resolve/Cattleya%20labiata%20Lindl."
    )
    assert synonym.status_code == 200
    assert synonym.json()["canonical_taxon_id"] == "taxon:cattleya-labiata"
