"""Tests for the real Anthropic-backed VisionProvider adapter.

No test in this module makes a real network call - urlopen is monkeypatched
throughout. That is the intended boundary: everything up to the actual
network request (credential handling, request construction, response
parsing, vocabulary filtering, fail-closed behavior) is exercised for real.
"""

from __future__ import annotations

import json
from hashlib import sha256
from io import BytesIO
from typing import Self
from urllib.error import HTTPError

import pytest

from app.multimodal_intelligence.anthropic_vision_provider import (
    AnthropicVisionProvider,
    AnthropicVisionProviderError,
    _default_factory,
    _no_image_source_configured,
    _no_vocabulary_configured,
    _readiness_probe,
    _sniff_media_type,
    register_default_anthropic_vision_provider,
)
from app.multimodal_intelligence.contracts import CharacterDefinition
from app.multimodal_intelligence.vision_provider_registry import (
    DEFAULT_VISION_PROVIDER_REGISTRY,
    VisionProviderRegistry,
)

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-body"
_JPEG_BYTES = b"\xff\xd8\xff" + b"fake-jpeg-body"


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info) -> None:
        return None


def _model_text_response(payload: dict, *, inference_id: str = "msg_abc123") -> dict:
    return {
        "id": inference_id,
        "content": [{"type": "text", "text": json.dumps(payload)}],
    }


_VOCAB = {
    "flower_color": CharacterDefinition(
        character_id="flower_color", label="Flower color", allowed_states=("red", "white", "yellow")
    ),
}


def _provider(*, urlopen_fn, api_key="real-looking-key", vocabulary=None) -> AnthropicVisionProvider:
    return AnthropicVisionProvider(
        api_key=api_key,
        image_bytes_loader=lambda image_id: _PNG_BYTES,
        character_vocabulary=lambda: (vocabulary if vocabulary is not None else _VOCAB),
        license_code="TEST_LICENSE",
        attribution="Test Attribution",
        model="claude-test-vision",
    ), urlopen_fn


# ---- media type sniffing ----

def test_sniff_media_type_png_and_jpeg():
    assert _sniff_media_type(_PNG_BYTES) == "image/png"
    assert _sniff_media_type(_JPEG_BYTES) == "image/jpeg"


def test_sniff_media_type_unsupported_fails_closed():
    with pytest.raises(AnthropicVisionProviderError, match="VISION_IMAGE_FORMAT_UNSUPPORTED"):
        _sniff_media_type(b"not-an-image")


# ---- readiness / factory fail-closed behavior ----

def test_readiness_probe_fails_closed_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = _readiness_probe()
    assert result.ready is False
    assert result.code == "PROVIDER_CREDENTIALS_NOT_CONFIGURED"


def test_readiness_probe_ready_with_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-real-looking-key")
    result = _readiness_probe()
    assert result.ready is True
    assert result.code is None


def test_default_factory_fails_closed_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(AnthropicVisionProviderError, match="VISION_PROVIDER_CREDENTIALS_NOT_CONFIGURED"):
        _default_factory()


def test_default_factory_image_source_fails_closed_when_invoked():
    with pytest.raises(AnthropicVisionProviderError, match="VISION_IMAGE_SOURCE_NOT_CONFIGURED"):
        _no_image_source_configured("some-image-id")


def test_default_factory_vocabulary_fails_closed_when_invoked():
    with pytest.raises(AnthropicVisionProviderError, match="VISION_CHARACTER_VOCABULARY_NOT_CONFIGURED"):
        _no_vocabulary_configured()


def test_registration_is_idempotent():
    registry = VisionProviderRegistry()
    register_default_anthropic_vision_provider(registry)
    register_default_anthropic_vision_provider(registry)  # must not raise
    assert registry.provider_names() == ("anthropic",)


def test_default_registry_has_anthropic_registered():
    assert DEFAULT_VISION_PROVIDER_REGISTRY.get("anthropic") is not None


# ---- analyze(): content-hash integrity ----

def test_analyze_rejects_content_hash_mismatch():
    provider = AnthropicVisionProvider(
        api_key="k",
        image_bytes_loader=lambda image_id: _PNG_BYTES,
        character_vocabulary=lambda: _VOCAB,
        license_code="L",
        attribution="A",
    )
    with pytest.raises(AnthropicVisionProviderError, match="VISION_IMAGE_CONTENT_HASH_MISMATCH"):
        provider.analyze(image_id="img1", content_hash="0" * 64)


# ---- analyze(): full happy path with a faked HTTP layer ----

def test_analyze_builds_valid_result_from_model_response(monkeypatch):
    real_hash = sha256(_PNG_BYTES).hexdigest()
    response_payload = {
        "detected_parts": [{"part": "flower", "confidence": 0.9}],
        "character_observations": [
            {"character_id": "flower_color", "state": "red", "confidence": 0.95},
        ],
        "warnings": [],
    }

    def fake_urlopen(request, timeout=None):
        del timeout
        assert request.full_url == "https://api.anthropic.com/v1/messages"
        assert request.get_header("X-api-key") == "real-looking-key"
        body = json.loads(request.data)
        assert body["model"] == "claude-test-vision"
        return _FakeHTTPResponse(_model_text_response(response_payload))

    monkeypatch.setattr(
        "app.multimodal_intelligence.anthropic_vision_provider.urlopen", fake_urlopen
    )

    provider = AnthropicVisionProvider(
        api_key="real-looking-key",
        image_bytes_loader=lambda image_id: _PNG_BYTES,
        character_vocabulary=lambda: _VOCAB,
        license_code="TEST_LICENSE",
        attribution="Test Attribution",
        model="claude-test-vision",
    )
    result = provider.analyze(image_id="img1", content_hash=real_hash)

    assert result.image_id == "img1"
    assert result.content_hash == real_hash
    assert result.model.provider == "anthropic"
    assert result.model.inference_id == "msg_abc123"
    assert len(result.detected_parts) == 1
    assert result.detected_parts[0].part == "flower"
    assert len(result.character_observations) == 1
    observation = result.character_observations[0]
    assert observation.character_id == "flower_color"
    assert observation.state == "red"
    assert observation.provenance == ("anthropic_vision:claude-test-vision",)


def test_analyze_clamps_overconfident_model_output(monkeypatch):
    real_hash = sha256(_PNG_BYTES).hexdigest()
    response_payload = {
        "detected_parts": [{"part": "flower", "confidence": 1.0}],
        "character_observations": [],
    }

    monkeypatch.setattr(
        "app.multimodal_intelligence.anthropic_vision_provider.urlopen",
        lambda request, timeout=None: _FakeHTTPResponse(_model_text_response(response_payload)),
    )
    provider = AnthropicVisionProvider(
        api_key="k",
        image_bytes_loader=lambda image_id: _PNG_BYTES,
        character_vocabulary=lambda: _VOCAB,
        license_code="L",
        attribution="A",
    )
    result = provider.analyze(image_id="img1", content_hash=real_hash)
    assert result.detected_parts[0].confidence <= 0.98


def test_analyze_drops_out_of_vocabulary_character_observation(monkeypatch):
    real_hash = sha256(_PNG_BYTES).hexdigest()
    response_payload = {
        "detected_parts": [{"part": "flower", "confidence": 0.8}],
        "character_observations": [
            {"character_id": "not_a_real_character", "state": "whatever", "confidence": 0.9},
            {"character_id": "flower_color", "state": "not_an_allowed_state", "confidence": 0.9},
        ],
    }

    monkeypatch.setattr(
        "app.multimodal_intelligence.anthropic_vision_provider.urlopen",
        lambda request, timeout=None: _FakeHTTPResponse(_model_text_response(response_payload)),
    )
    provider = AnthropicVisionProvider(
        api_key="k",
        image_bytes_loader=lambda image_id: _PNG_BYTES,
        character_vocabulary=lambda: _VOCAB,
        license_code="L",
        attribution="A",
    )
    result = provider.analyze(image_id="img1", content_hash=real_hash)
    assert result.character_observations == ()
    assert any("OUT_OF_VOCABULARY" in warning for warning in result.warnings)


def test_analyze_raises_when_no_plant_parts_detected(monkeypatch):
    real_hash = sha256(_PNG_BYTES).hexdigest()
    monkeypatch.setattr(
        "app.multimodal_intelligence.anthropic_vision_provider.urlopen",
        lambda request, timeout=None: _FakeHTTPResponse(_model_text_response({"detected_parts": []})),
    )
    provider = AnthropicVisionProvider(
        api_key="k",
        image_bytes_loader=lambda image_id: _PNG_BYTES,
        character_vocabulary=lambda: _VOCAB,
        license_code="L",
        attribution="A",
    )
    with pytest.raises(AnthropicVisionProviderError, match="VISION_PROVIDER_NO_PLANT_PARTS_DETECTED"):
        provider.analyze(image_id="img1", content_hash=real_hash)


def test_analyze_http_error_is_translated_to_typed_error(monkeypatch):
    real_hash = sha256(_PNG_BYTES).hexdigest()

    def raise_http_error(request, timeout=None):
        del request, timeout
        raise HTTPError(
            "https://api.anthropic.com/v1/messages",
            401,
            "unauthorized",
            hdrs=None,
            fp=BytesIO(json.dumps({"error": {"type": "authentication_error", "message": "bad key"}}).encode()),
        )

    monkeypatch.setattr(
        "app.multimodal_intelligence.anthropic_vision_provider.urlopen", raise_http_error
    )
    provider = AnthropicVisionProvider(
        api_key="k",
        image_bytes_loader=lambda image_id: _PNG_BYTES,
        character_vocabulary=lambda: _VOCAB,
        license_code="L",
        attribution="A",
    )
    with pytest.raises(AnthropicVisionProviderError, match="VISION_PROVIDER_HTTP_401:AUTHENTICATION_ERROR"):
        provider.analyze(image_id="img1", content_hash=real_hash)


def test_analyze_malformed_json_response_fails_closed(monkeypatch):
    real_hash = sha256(_PNG_BYTES).hexdigest()
    not_json = {"id": "msg_1", "content": [{"type": "text", "text": "not valid json"}]}
    monkeypatch.setattr(
        "app.multimodal_intelligence.anthropic_vision_provider.urlopen",
        lambda request, timeout=None: _FakeHTTPResponse(not_json),
    )
    provider = AnthropicVisionProvider(
        api_key="k",
        image_bytes_loader=lambda image_id: _PNG_BYTES,
        character_vocabulary=lambda: _VOCAB,
        license_code="L",
        attribution="A",
    )
    with pytest.raises(AnthropicVisionProviderError, match="VISION_PROVIDER_INVALID_JSON"):
        provider.analyze(image_id="img1", content_hash=real_hash)
