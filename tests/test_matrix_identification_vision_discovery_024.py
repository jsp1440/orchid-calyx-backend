from types import SimpleNamespace
from uuid import UUID

import pytest

import runtime.matrix_identification_vision_discovery as discovery


class FakeVisionService:
    def __init__(self):
        self.requested_images = []

    def list_analyses_for_image(self, image_id):
        self.requested_images.append(image_id)
        return [
            SimpleNamespace(
                analysis_id=UUID("22222222-2222-2222-2222-222222222222"),
                image_id=image_id,
                reference_set_id=None,
                vision_model="governed-vision",
                vision_model_version="1",
                analysis_version=2,
                taxon_context="Angraecum",
                taxon_confidence=0.8,
                calibration_state="uncalibrated",
                image_quality="acceptable",
                analysis_status="complete",
                review_state="machine_generated",
                warnings=("bounded fixture",),
                limitations=("review required",),
            ),
            SimpleNamespace(
                analysis_id=UUID("11111111-1111-1111-1111-111111111111"),
                image_id=image_id,
                reference_set_id=UUID("33333333-3333-3333-3333-333333333333"),
                vision_model="governed-vision",
                vision_model_version="2",
                analysis_version=1,
                taxon_context=None,
                taxon_confidence=None,
                calibration_state="calibrated",
                image_quality="good",
                analysis_status="review_required",
                review_state="machine_generated",
                warnings=(),
                limitations=(),
            ),
        ]


def test_discovery_is_scoped_deterministic_and_read_only(monkeypatch):
    access_calls = []

    def fake_get_session(session_id, *, root=None, access_actor=None):
        access_calls.append((session_id, root, access_actor))
        return {"session_id": session_id, "revision": 7}

    monkeypatch.setattr(discovery, "get_session", fake_get_session)
    service = FakeVisionService()
    result = discovery.list_vision_analyses_for_image(
        "session-a",
        "image-42",
        access_actor="owner-a",
        root="bounded-root",
        vision_service=service,
    )

    assert access_calls == [("session-a", "bounded-root", "owner-a")]
    assert service.requested_images == ["image-42"]
    assert result["analysis_count"] == 2
    assert [item["analysis_id"] for item in result["analyses"]] == [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]
    assert result["provider_inference_requested"] is False
    assert result["matrix_state_mutated"] is False


def test_session_lookup_failure_prevents_vision_lookup(monkeypatch):
    service = FakeVisionService()

    def missing(*args, **kwargs):
        raise FileNotFoundError("identification session not found")

    monkeypatch.setattr(discovery, "get_session", missing)
    with pytest.raises(FileNotFoundError):
        discovery.list_vision_analyses_for_image(
            "session-a",
            "image-42",
            access_actor="other-owner",
            vision_service=service,
        )
    assert service.requested_images == []


def test_empty_image_id_stops_before_vision_lookup(monkeypatch):
    service = FakeVisionService()
    monkeypatch.setattr(
        discovery,
        "get_session",
        lambda *args, **kwargs: {"session_id": "session-a"},
    )
    with pytest.raises(ValueError, match="image_id is required"):
        discovery.list_vision_analyses_for_image(
            "session-a",
            "   ",
            vision_service=service,
        )
    assert service.requested_images == []
