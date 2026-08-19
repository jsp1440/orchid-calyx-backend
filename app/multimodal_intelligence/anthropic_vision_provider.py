"""Real Anthropic-backed :class:`VisionProvider` adapter and its registration.

Registers the first non-fixture :class:`~.integration.VisionProvider`
implementation into ``DEFAULT_VISION_PROVIDER_REGISTRY``
(``app/multimodal_intelligence/vision_provider_registry.py``, which previously
had zero registrations anywhere in this backend). This module performs a
genuine external call - a real HTTP request to Anthropic's Messages API with
image content, real credential handling, real response parsing - not a mock.

Two dependencies this module deliberately does not attempt to solve, and
fails closed on rather than guesses at:

- Resolving an ``image_id`` to raw image bytes. No production image-storage
  client exists yet anywhere in this backend (see Brain's AUDIT-0002 ranked
  item 5, the ``atlas_intelligence`` data-source question, for the adjacent
  open gap). The default registration's factory supplies a loader that fails
  closed with ``VISION_IMAGE_SOURCE_NOT_CONFIGURED`` until a real one is
  wired by whichever caller needs live inference.
- The Matrix character vocabulary a concrete identification session wants
  observed. This varies per call (it is exactly ``identify_from_image``'s own
  ``dataset.definitions`` argument), so it cannot be hardcoded here without
  inventing a canonical vocabulary this module has no authority to define.
  The default factory fails closed with
  ``VISION_CHARACTER_VOCABULARY_NOT_CONFIGURED`` until one is supplied.

Both failures surface only when ``analyze()`` is actually invoked - never
during registration or the side-effect-free ``readiness_probe`` - matching
the registry's own contract that provider factories are not instantiated
during readiness checks.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .contracts import (
    CharacterDefinition,
    CharacterObservation,
    ImageAnalysisResult,
    ModelProvenance,
    PlantPartDetection,
)
from .vision_provider_registry import (
    DEFAULT_VISION_PROVIDER_REGISTRY,
    ProviderProbeResult,
    VisionProviderRegistration,
    VisionProviderRegistry,
)

_API_KEY_ENV = "ANTHROPIC_API_KEY"
_MODEL_ENV = "CALYX_VISION_ANTHROPIC_MODEL"
_DEFAULT_MODEL = "claude-sonnet-4-20250514"
_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_MAX_REPORTED_CONFIDENCE = 0.98


class AnthropicVisionProviderError(RuntimeError):
    pass


def _no_image_source_configured(image_id: str) -> bytes:
    del image_id
    raise AnthropicVisionProviderError("VISION_IMAGE_SOURCE_NOT_CONFIGURED")


def _no_vocabulary_configured() -> Mapping[str, CharacterDefinition]:
    raise AnthropicVisionProviderError("VISION_CHARACTER_VOCABULARY_NOT_CONFIGURED")


def _sniff_media_type(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise AnthropicVisionProviderError("VISION_IMAGE_FORMAT_UNSUPPORTED")


def _extract_json_object(text: str) -> dict:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise AnthropicVisionProviderError("VISION_PROVIDER_INVALID_JSON") from exc
    if not isinstance(parsed, dict):
        raise AnthropicVisionProviderError("VISION_PROVIDER_OBJECT_REQUIRED")
    return parsed


def _anthropic_error_code(exc: HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return f"VISION_PROVIDER_HTTP_{exc.code}"
    error = payload.get("error") if isinstance(payload, dict) else None
    error_type = str(error.get("type", "")).strip() if isinstance(error, dict) else ""
    message = str(error.get("message", "")).strip() if isinstance(error, dict) else ""
    safe_message = " ".join(message.split())[:500]
    parts = [f"VISION_PROVIDER_HTTP_{exc.code}"]
    if error_type:
        parts.append(error_type.upper())
    if safe_message:
        parts.append(safe_message)
    return ":".join(parts)


@dataclass(frozen=True, slots=True)
class AnthropicVisionProvider:
    """Governed :class:`VisionProvider` adapter calling Anthropic's Messages API.

    ``image_bytes_loader`` and ``character_vocabulary`` are required, explicit
    dependencies rather than a hardcoded storage backend or vocabulary - see
    module docstring for why. Both may raise (fail closed) rather than
    silently return an empty/synthetic result.
    """

    api_key: str
    image_bytes_loader: Callable[[str], bytes]
    character_vocabulary: Callable[[], Mapping[str, CharacterDefinition]]
    license_code: str
    attribution: str
    model: str = _DEFAULT_MODEL
    provider_name: str = "anthropic"

    def analyze(self, *, image_id: str, content_hash: str) -> ImageAnalysisResult:
        image_bytes = self.image_bytes_loader(image_id)
        actual_hash = sha256(image_bytes).hexdigest()
        if actual_hash != content_hash:
            raise AnthropicVisionProviderError("VISION_IMAGE_CONTENT_HASH_MISMATCH")

        vocabulary = self.character_vocabulary()
        for definition in vocabulary.values():
            definition.validate()

        text, inference_id = self._call_model(image_bytes, vocabulary)
        payload = _extract_json_object(text)
        return self._build_result(
            image_id=image_id,
            content_hash=content_hash,
            inference_id=inference_id,
            payload=payload,
            vocabulary=vocabulary,
        )

    def _call_model(
        self, image_bytes: bytes, vocabulary: Mapping[str, CharacterDefinition]
    ) -> tuple[str, str]:
        media_type = _sniff_media_type(image_bytes)
        character_spec = [
            {"character_id": key, "label": definition.label, "allowed_states": list(definition.allowed_states)}
            for key, definition in sorted(vocabulary.items())
        ]
        system = (
            "You are a governed botanical vision analysis provider for the Orchid Continuum. "
            "Examine the supplied orchid image and return exactly one JSON object with keys "
            "'detected_parts' (array of {part, confidence}), 'character_observations' "
            "(array of {character_id, state, confidence}), and 'warnings' (array of strings). "
            "Only use character_id values from the supplied vocabulary, and only use a state "
            "value listed in that character's own allowed_states, or null if it cannot be "
            "determined from the image. confidence must be a number between 0 and "
            f"{_MAX_REPORTED_CONFIDENCE} inclusive - never claim certainty. Do not invent "
            "character_id values outside the supplied vocabulary. Return only the JSON "
            "object, no other text."
        )
        encoded = base64.b64encode(image_bytes).decode("ascii")
        body = {
            "model": self.model,
            "max_tokens": 2048,
            "temperature": 0,
            "system": system,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": encoded},
                        },
                        {"type": "text", "text": json.dumps({"character_vocabulary": character_spec})},
                    ],
                }
            ],
        }
        request = Request(
            _ANTHROPIC_MESSAGES_URL,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "anthropic-version": "2023-06-01",
                "x-api-key": self.api_key,
                "User-Agent": "calyx-governed-vision-provider",
            },
        )
        try:
            with urlopen(request, timeout=60) as response:
                result = json.loads(response.read())
        except HTTPError as exc:
            raise AnthropicVisionProviderError(_anthropic_error_code(exc)) from exc
        except (URLError, TimeoutError) as exc:
            raise AnthropicVisionProviderError("VISION_PROVIDER_UNREACHABLE") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AnthropicVisionProviderError("VISION_PROVIDER_INVALID_RESPONSE") from exc

        blocks = result.get("content")
        if not isinstance(blocks, list):
            raise AnthropicVisionProviderError("VISION_PROVIDER_CONTENT_REQUIRED")
        text = "\n".join(
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        if not text:
            raise AnthropicVisionProviderError("VISION_PROVIDER_TEXT_REQUIRED")
        inference_id = str(result.get("id") or "").strip() or "unknown"
        return text, inference_id

    def _build_result(
        self,
        *,
        image_id: str,
        content_hash: str,
        inference_id: str,
        payload: dict,
        vocabulary: Mapping[str, CharacterDefinition],
    ) -> ImageAnalysisResult:
        warnings: list[str] = [str(item) for item in (payload.get("warnings") or [])]

        detected_parts: list[PlantPartDetection] = []
        for item in payload.get("detected_parts") or []:
            try:
                part = str(item["part"]).strip()
                confidence = min(max(float(item["confidence"]), 0.0), _MAX_REPORTED_CONFIDENCE)
                if not part:
                    raise ValueError("empty part")
            except (KeyError, TypeError, ValueError):
                warnings.append("DETECTED_PART_MALFORMED_DROPPED")
                continue
            detected_parts.append(PlantPartDetection(part=part, confidence=confidence))

        character_observations: list[CharacterObservation] = []
        for item in payload.get("character_observations") or []:
            try:
                character_id = str(item["character_id"]).strip()
                raw_state = item.get("state")
                state = str(raw_state).strip() if raw_state is not None else None
                confidence = min(max(float(item["confidence"]), 0.0), _MAX_REPORTED_CONFIDENCE)
            except (KeyError, TypeError, ValueError):
                warnings.append("CHARACTER_OBSERVATION_MALFORMED_DROPPED")
                continue
            definition = vocabulary.get(character_id)
            if definition is None or (state is not None and state not in definition.allowed_states):
                warnings.append(f"CHARACTER_OBSERVATION_OUT_OF_VOCABULARY:{character_id}")
                continue
            character_observations.append(
                CharacterObservation(
                    character_id=character_id,
                    state=state,
                    confidence=confidence,
                    provenance=(f"anthropic_vision:{self.model}",),
                )
            )

        if not detected_parts:
            raise AnthropicVisionProviderError("VISION_PROVIDER_NO_PLANT_PARTS_DETECTED")

        result = ImageAnalysisResult(
            image_id=image_id,
            content_hash=content_hash,
            license_code=self.license_code,
            attribution=self.attribution,
            model=ModelProvenance(
                provider="anthropic",
                model_name=self.model,
                model_version=self.model,
                inference_id=inference_id,
            ),
            detected_parts=tuple(detected_parts),
            character_observations=tuple(character_observations),
            warnings=tuple(warnings),
        )
        result.validate()
        return result


def _readiness_probe() -> ProviderProbeResult:
    """Side-effect-free: checks only that a credential is present locally."""
    if (os.environ.get(_API_KEY_ENV) or "").strip():
        return ProviderProbeResult(ready=True)
    return ProviderProbeResult(ready=False, code="PROVIDER_CREDENTIALS_NOT_CONFIGURED")


def _default_factory() -> AnthropicVisionProvider:
    api_key = (os.environ.get(_API_KEY_ENV) or "").strip()
    if not api_key:
        raise AnthropicVisionProviderError("VISION_PROVIDER_CREDENTIALS_NOT_CONFIGURED")
    model = (os.environ.get(_MODEL_ENV) or "").strip() or _DEFAULT_MODEL
    return AnthropicVisionProvider(
        api_key=api_key,
        image_bytes_loader=_no_image_source_configured,
        character_vocabulary=_no_vocabulary_configured,
        license_code="ORCHID_CONTINUUM_GOVERNED_ANALYSIS",
        attribution="Orchid Continuum Vision Provider (Anthropic)",
        model=model,
    )


def register_default_anthropic_vision_provider(
    registry: VisionProviderRegistry = DEFAULT_VISION_PROVIDER_REGISTRY,
) -> None:
    """Register the "anthropic" adapter, idempotently.

    Safe to call more than once (e.g. multiple import paths reaching this
    module during test collection): a second call is a silent no-op rather
    than raising ``VISION_PROVIDER_ALREADY_REGISTERED``, since re-registering
    the same static adapter definition is not a real conflict.
    """
    if registry.get("anthropic") is not None:
        return
    registry.register(
        VisionProviderRegistration(
            name="anthropic",
            provider_factory=_default_factory,
            readiness_probe=_readiness_probe,
            production_capable=True,
            model_family="claude-vision",
            adapter_version="anthropic-vision-v1",
        )
    )
