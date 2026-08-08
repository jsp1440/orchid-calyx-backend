from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import conservatory_operational as api
from app.security import verify_owner_or_api_key
from runtime.conservatory_operational import ConservatoryService


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _payload(*, accession: str = "FCOS-2026-001", import_id: str = "import-1", tag: str = "Cattleya labiata") -> dict:
    return {
        "import_id": import_id,
        "collection": {
            "collection_id": "jeff-orchids",
            "title": "Private Orchid Collection",
            "description": "Fixture collection",
        },
        "accession": {
            "accession_number": accession,
            "acquired_at": "2026-08-07T12:00:00-07:00",
            "source": "fixture nursery",
        },
        "plant": {
            "display_name": "Cattleya labiata",
            "scientific_name": "Cattleya labiata",
            "identity_state": "unresolved",
            "tag_text": tag,
            "clone_name": "primary division",
        },
        "location": {
            "location_id": "greenhouse-bench-a",
            "label": "Greenhouse Bench A",
            "zone": "warm-intermediate",
            "privacy": "private",
        },
        "media": [
            {
                "media_id": f"{accession}-flower",
                "role": "flower",
                "sha256": _sha(f"{accession}-flower"),
                "source_uri": f"upload://conservatory/{accession}/flower.jpg",
                "license": "private-owner-media",
                "attribution": "Collection owner",
            },
            {
                "media_id": f"{accession}-tag",
                "role": "tag",
                "sha256": _sha(f"{accession}-tag"),
                "source_uri": f"upload://conservatory/{accession}/tag.jpg",
                "license": "private-owner-media",
                "attribution": "Collection owner",
            },
        ],
    }


def test_intake_is_owner_scoped_unresolved_and_replay_safe(tmp_path: Path):
    service = ConservatoryService(tmp_path / "conservatory")
    first = service.intake("owner-a", _payload())
    replay = service.intake("owner-a", _payload())

    assert first["created"] is True
    assert first["replayed"] is False
    assert first["identity_state"] == "unresolved"
    assert first["identity_review_required"] is True
    assert first["taxonomy_acceptance_authorized"] is False
    assert first["knowledge_graph_mutation_authorized"] is False
    assert replay["created"] is False
    assert replay["replayed"] is True
    assert replay["plant_id"] == first["plant_id"]


def test_import_replay_conflict_fails_closed(tmp_path: Path):
    service = ConservatoryService(tmp_path / "conservatory")
    service.intake("owner-a", _payload())
    changed = _payload()
    changed["plant"]["tag_text"] = "different tag"
    try:
        service.intake("owner-a", changed)
    except ValueError as exc:
        assert "CONSERVATORY_IMPORT_REPLAY_CONFLICT" in str(exc)
    else:
        raise AssertionError("changed import under same replay key must fail")


def test_qr_target_printable_label_and_scan_open_private_dossier(tmp_path: Path):
    service = ConservatoryService(tmp_path / "conservatory")
    result = service.intake("owner-a", _payload())
    label = result["label"]
    assert label["qr_target"].endswith(label["label_id"])
    assert label["qr_payload"] == label["qr_target"]
    printable = service.printable_label("owner-a", label["label_id"])
    assert printable["printable"]["secondary_text"] == "FCOS-2026-001"

    dossier = service.scan("owner-a", label["label_id"])
    assert dossier["plant"]["plant_id"] == result["plant_id"]
    assert dossier["current_location"]["privacy"] == "private"
    assert dossier["public_location_exposure"] is False
    assert dossier["events"][0]["event_type"] == "acquisition"


def test_repot_flowering_treatment_and_movement_history(tmp_path: Path):
    service = ConservatoryService(tmp_path / "conservatory")
    result = service.intake("owner-a", _payload())
    plant_id = result["plant_id"]
    service.create_location(
        "owner-a",
        {"location_id": "shade-house", "label": "Shade House", "privacy": "private"},
    )
    service.add_event(
        "owner-a",
        plant_id,
        event_type="repotting",
        occurred_at="2026-08-08T10:00:00-07:00",
        details={"medium": "bark"},
    )
    service.add_event(
        "owner-a",
        plant_id,
        event_type="flowering",
        occurred_at="2026-08-09T10:00:00-07:00",
        details={"flowers": 3},
    )
    service.add_event(
        "owner-a",
        plant_id,
        event_type="treatment",
        occurred_at="2026-08-10T10:00:00-07:00",
        details={"treatment": "fixture"},
    )
    movement = service.add_event(
        "owner-a",
        plant_id,
        event_type="movement",
        occurred_at="2026-08-11T10:00:00-07:00",
        location_id="shade-house",
    )
    assert movement["event"]["details"]["to_location_id"] == "shade-house"
    dossier = service.dossier("owner-a", plant_id)
    assert [event["event_type"] for event in dossier["events"]] == [
        "acquisition",
        "repotting",
        "flowering",
        "treatment",
        "movement",
    ]
    assert dossier["current_location"]["location_id"] == "shade-house"


def test_deterministic_duplicate_detection_flags_tag_match(tmp_path: Path):
    service = ConservatoryService(tmp_path / "conservatory")
    first = service.intake("owner-a", _payload())
    second = service.intake(
        "owner-a",
        _payload(accession="FCOS-2026-002", import_id="import-2", tag="Cattleya labiata"),
    )
    assert second["plant_id"] != first["plant_id"]
    assert second["duplicate_review_required"] is True
    assert second["duplicate_candidates"][0]["plant_id"] == first["plant_id"]
    assert "same_tag_text" in second["duplicate_candidates"][0]["reasons"]


def test_owner_isolation_prevents_cross_owner_scan(tmp_path: Path):
    service = ConservatoryService(tmp_path / "conservatory")
    result = service.intake("owner-a", _payload())
    label_id = result["label"]["label_id"]
    try:
        service.scan("owner-b", label_id)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("another owner must not resolve a private label")


def test_matched_identity_requires_canonical_taxon_id(tmp_path: Path):
    service = ConservatoryService(tmp_path / "conservatory")
    payload = _payload()
    payload["plant"]["identity_state"] = "matched"
    try:
        service.intake("owner-a", payload)
    except ValueError as exc:
        assert "CONSERVATORY_MATCHED_TAXON_ID_REQUIRED" in str(exc)
    else:
        raise AssertionError("matched identity without canonical taxon ID must fail")


def test_protected_api_and_readiness_are_owner_scoped(tmp_path: Path, monkeypatch):
    service = ConservatoryService(tmp_path / "conservatory")
    monkeypatch.setattr(api, "_service", lambda: service)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "owner-a", "auth_type": "test"}
    client = TestClient(app)

    created = client.post("/brain/mission-control/conservatory/intake", json=_payload())
    assert created.status_code == 200
    plant_id = created.json()["plant_id"]
    label_id = created.json()["label"]["label_id"]

    dossier = client.get(f"/brain/mission-control/conservatory/plants/{plant_id}")
    assert dossier.status_code == 200
    assert dossier.json()["private_collection"] is True
    scanned = client.get(f"/brain/mission-control/conservatory/scan/{label_id}")
    assert scanned.status_code == 200

    readiness = client.get("/brain/mission-control/conservatory/readiness")
    assert readiness.status_code == 200
    payload = readiness.json()
    assert payload["plants"] == 1
    assert payload["public_location_exposure"] is False
    assert payload["autonomous_taxonomic_acceptance"] is False
    assert payload["production_deployment_authorized"] is False
