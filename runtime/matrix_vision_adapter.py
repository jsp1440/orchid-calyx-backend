"""Bounded, pluggable Vision AI extraction adapter for Matrix sessions (Phase 4).

Connects staged contributor photographs to the existing Vision-Lexicon bridge
and the governed Vision → Matrix review gate, without inventing observations
and without ever claiming live AI inference that did not happen:

* **Fixture mode (default, explicit).** Caller-supplied ``ImageAnalysisResult``
  fixtures are replayed through the real extraction pathway (provider contract
  → Vision-Lexicon analysis + character observations → governed review
  suggestions). Every record is labeled ``extraction_mode: fixture`` and the
  capability declaration states ``live_inference_performed: False``. Fixture
  results must match the staged image identity (the existing
  ``FixtureVisionProvider`` enforces this) and carry license + attribution.
* **Live mode (fail-closed).** Live inference runs only when the governed
  provider registry reports ``READY`` *and* live inference is explicitly
  enabled (``CALYX_VISION_PROVIDER`` + ``CALYX_VISION_LIVE_INFERENCE_ENABLED``).
  Any other readiness state aborts before any work with
  ``VISION_LIVE_INFERENCE_NOT_AUTHORIZED``. No credentials are read here and
  no paid provider is ever constructed implicitly.

Scientific boundaries inherited from the components this adapter composes:

* no observation is invented: only provider-reported character observations
  are recorded, and a provider observation with no determinable state is
  recorded as ``CANNOT_DETERMINE`` — anatomical absence is never inferred
  from an unobserved structure;
* machine confidence is capped at 0.95 (existing engine policy) and reviewer
  certainty is recorded independently at the review gate;
* absolute-unit/calibration rules are enforced by the Vision-Lexicon
  contracts; unit/value-type ambiguity degrades to ``needs_mapping`` at the
  existing review gate instead of forcing a Matrix value;
* extraction is idempotent: the Vision-Lexicon request hash makes the
  analysis record stable, and a replay never duplicates observations or
  review suggestions.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.multimodal_intelligence.contracts import (
    CharacterObservation as ProviderCharacterObservation,
    ImageAnalysisResult,
    ModelProvenance,
    PlantPartDetection,
)
from app.multimodal_intelligence.integration import (
    FixtureVisionProvider,
    VisionProvider,
)
from app.multimodal_intelligence.vision_provider_registry import (
    VisionProviderRegistry,
    provider_readiness,
)
from app.vision_lexicon.contracts import (
    CalibrationState,
    ImageQualityState,
    MeasurementBasis,
)
from app.vision_lexicon.service import VisionLexiconService
from runtime.contributor_intake_service import get_batch_manifest
from runtime.matrix_identification_session import get_session
from runtime.matrix_identification_vision import attach_vision_analysis

VISION_EXTRACTION_SCHEMA = "matrix-vision-extraction/v1"

FIXTURE_MODE = "fixture"
LIVE_MODE = "live"
_SUPPORTED_MODES = frozenset({FIXTURE_MODE, LIVE_MODE})

#: Existing multimodal-engine policy: machine confidence is capped at 0.95 so
#: a model can never claim near-certain anatomical truth.
MAX_VISION_CONFIDENCE = 0.95

FIXTURE_LIMITATION = (
    "Fixture mode: no live AI inference was performed; values replay a "
    "caller-supplied fixture through the governed extraction pathway."
)
MACHINE_LIMITATION = (
    "Machine vision output; requires explicit human review before Matrix scoring."
)

_DEFAULT_SERVICE: VisionLexiconService | None = None


def default_vision_service() -> VisionLexiconService:
    """Process-wide governed Vision-Lexicon service (memory or durable).

    Built lazily through the existing activation layer so durable mode
    (``CALYX_VISION_DURABLE_ENABLED`` + activated ``oc_vision`` schema) is
    honored without this module importing psycopg at module import time. The
    memory-mode service is cached so analyses survive across calls within the
    process, exactly like the upstream status surfaces.
    """
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        from app.vision_lexicon.activation import build_vision_lexicon_service

        _DEFAULT_SERVICE = build_vision_lexicon_service()
    return _DEFAULT_SERVICE


def image_analysis_result_from_dict(payload: Mapping[str, Any]) -> ImageAnalysisResult:
    """Rebuild a provider-contract result from a plain mapping (API boundary).

    Validation is deliberately left to the contract itself (``validate()`` is
    invoked by ``FixtureVisionProvider.analyze``), so license/attribution,
    model provenance, plant-part detection, and confidence-ceiling violations
    fail with the same codes as any other provider output.
    """
    model = payload.get("model") or {}
    return ImageAnalysisResult(
        image_id=str(payload.get("image_id") or ""),
        content_hash=str(payload.get("content_hash") or ""),
        license_code=str(payload.get("license_code") or ""),
        attribution=str(payload.get("attribution") or ""),
        model=ModelProvenance(
            provider=str(model.get("provider") or ""),
            model_name=str(model.get("model_name") or ""),
            model_version=str(model.get("model_version") or ""),
            inference_id=str(model.get("inference_id") or ""),
        ),
        detected_parts=tuple(
            PlantPartDetection(
                part=str(part.get("part") or ""),
                confidence=float(part.get("confidence")),
            )
            for part in (payload.get("detected_parts") or ())
        ),
        character_observations=tuple(
            ProviderCharacterObservation(
                character_id=str(obs.get("character_id") or ""),
                state=(None if obs.get("state") is None else str(obs.get("state"))),
                confidence=float(obs.get("confidence")),
                provenance=tuple(
                    str(item) for item in (obs.get("provenance") or ("fixture",))
                ),
            )
            for obs in (payload.get("character_observations") or ())
        ),
        warnings=tuple(str(item) for item in (payload.get("warnings") or ())),
    )


def vision_extraction_capability(
    *,
    registry: VisionProviderRegistry | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Truthful capability declaration for status surfaces and reports."""
    readiness = provider_readiness(registry=registry, environ=environ)
    live_available = (
        readiness["provider_status"] == "READY" and readiness["live_inference_enabled"]
    )
    return {
        "capability": "matrix_vision_extraction_adapter",
        "schema_version": VISION_EXTRACTION_SCHEMA,
        "modes": {
            FIXTURE_MODE: {
                "available": True,
                "live_inference": False,
                "label": "FIXTURE_MODE_NO_LIVE_INFERENCE",
            },
            LIVE_MODE: {
                "available": live_available,
                "live_inference": True,
                "provider_status": readiness["provider_status"],
                "live_inference_enabled": readiness["live_inference_enabled"],
            },
        },
        "provider_readiness": readiness,
        "confidence_policy": f"machine confidence capped at {MAX_VISION_CONFIDENCE}",
        "honesty_rule": (
            "Fixture mode performs no AI inference and every emitted record is "
            "labeled extraction_mode=fixture; live mode fails closed unless the "
            "governed provider registry reports READY with live inference enabled."
        ),
        "review_rule": (
            "Every extracted character remains a review-required suggestion; "
            "only explicit human accept/revise decisions enter Matrix scoring."
        ),
    }


def _session_staged_images(
    session: dict[str, Any], *, submission_ids: list[str] | None
) -> list[dict[str, Any]]:
    """Resolve staged contributor images linked to this identification session.

    Linked images are (a) images already attached to the session record and
    (b) the session's own staged image named by its intake metadata, read back
    from the persisted batch manifest. Batch-mate images belonging to other
    sessions are never pulled in.
    """
    attached = dict(session.get("contributor_images") or {})
    metadata = session.get("metadata") or {}
    linked_ids = set(attached)
    own_submission = metadata.get("contributor_submission_id")
    if own_submission:
        linked_ids.add(str(own_submission))

    images: dict[str, dict[str, Any]] = dict(attached)
    batch_id = metadata.get("contributor_batch_id")
    missing_from_record = linked_ids - set(attached)
    if batch_id and missing_from_record:
        try:
            manifest = get_batch_manifest(str(batch_id))
        except (FileNotFoundError, ValueError):
            manifest = None
        if manifest:
            for staged in manifest.get("staged", []):
                sid = str(staged.get("submission_id") or "")
                if sid in missing_from_record:
                    images[sid] = staged

    if submission_ids is not None:
        requested = {str(item) for item in submission_ids}
        unknown = requested - linked_ids
        if unknown:
            raise ValueError(
                "staged contributor image(s) not linked to this session: "
                f"{sorted(unknown)}"
            )
        linked_ids = requested

    resolved = [images[sid] for sid in sorted(linked_ids) if sid in images]
    unresolved = sorted(sid for sid in linked_ids if sid not in images)
    if unresolved:
        raise ValueError(
            "staged contributor image record(s) unavailable for session: "
            f"{unresolved}"
        )
    return resolved


def _resolve_provider(
    mode: str,
    image: dict[str, Any],
    *,
    fixture_analyses: Mapping[str, Any] | None,
    provider: VisionProvider | None,
    registry: VisionProviderRegistry | None,
    environ: Mapping[str, str] | None,
) -> VisionProvider:
    if mode == FIXTURE_MODE:
        if provider is not None:
            return provider
        submission_id = str(image.get("submission_id") or "")
        content_sha256 = str(image.get("content_sha256") or "")
        supplied = (fixture_analyses or {}).get(submission_id)
        if supplied is None and content_sha256:
            supplied = (fixture_analyses or {}).get(content_sha256)
        if supplied is None:
            raise ValueError(
                "VISION_FIXTURE_MISSING: no fixture analysis supplied for staged "
                f"image {submission_id}; fixture mode never invents observations"
            )
        result = (
            image_analysis_result_from_dict(supplied)
            if isinstance(supplied, Mapping)
            else supplied
        )
        return FixtureVisionProvider(result=result)
    if mode == LIVE_MODE:
        readiness = provider_readiness(registry=registry, environ=environ)
        if not (
            readiness["provider_status"] == "READY"
            and readiness["live_inference_enabled"]
        ):
            raise RuntimeError(
                "VISION_LIVE_INFERENCE_NOT_AUTHORIZED: live vision extraction "
                "fails closed (provider_status="
                f"{readiness['provider_status']}, live_inference_enabled="
                f"{readiness['live_inference_enabled']}); configure a "
                "production-capable provider and explicit enablement, or use "
                "explicit fixture mode"
            )
        if provider is not None:
            return provider
        active = registry or None
        registration = (
            active.get(str(readiness["selected_provider"])) if active else None
        )
        if registration is None:
            from app.multimodal_intelligence.vision_provider_registry import (
                DEFAULT_VISION_PROVIDER_REGISTRY,
            )

            registration = DEFAULT_VISION_PROVIDER_REGISTRY.get(
                str(readiness["selected_provider"])
            )
        if registration is None:  # pragma: no cover - defensive; readiness said READY
            raise RuntimeError("VISION_LIVE_INFERENCE_NOT_AUTHORIZED")
        return registration.provider_factory()
    raise ValueError(f"unsupported vision extraction mode: {mode}")


def run_vision_extraction(
    session_id: str,
    *,
    mode: str = FIXTURE_MODE,
    fixture_analyses: Mapping[str, Any] | None = None,
    provider: VisionProvider | None = None,
    submission_ids: list[str] | None = None,
    vision_service: VisionLexiconService | None = None,
    registry: VisionProviderRegistry | None = None,
    environ: Mapping[str, str] | None = None,
    access_actor: str | None = None,
    root=None,
    registry_root=None,
) -> dict[str, Any]:
    """Run bounded Vision extraction for one governed identification session.

    For every linked staged contributor image: analyze through the pluggable
    provider contract, record the analysis and its character observations in
    the Vision-Lexicon bridge (idempotently), then attach them to the session
    as review-required suggestions through the existing governed Vision →
    Matrix gate. No suggestion scores until a reviewer accepts or revises it.
    """
    if mode not in _SUPPORTED_MODES:
        raise ValueError(f"unsupported vision extraction mode: {mode}")
    session = get_session(session_id, root=root, access_actor=access_actor)
    images = _session_staged_images(session, submission_ids=submission_ids)
    if not images:
        raise ValueError(
            "no staged contributor images linked to this session; intake must "
            "stage at least one image before vision extraction"
        )

    service = vision_service or default_vision_service()
    readiness = provider_readiness(registry=registry, environ=environ)
    if mode == LIVE_MODE:
        # Fail closed before any per-image work (also resolves the provider).
        live_provider = _resolve_provider(
            LIVE_MODE,
            images[0],
            fixture_analyses=None,
            provider=provider,
            registry=registry,
            environ=environ,
        )
    else:
        live_provider = provider

    per_image: list[dict[str, Any]] = []
    for image in images:
        submission_id = str(image.get("submission_id") or "")
        content_sha256 = str(image.get("content_sha256") or "")
        if not submission_id or not content_sha256:
            raise ValueError(
                "staged contributor image identity (submission_id, "
                "content_sha256) is required for vision extraction"
            )
        image_id = submission_id
        image_provider = live_provider or _resolve_provider(
            FIXTURE_MODE,
            image,
            fixture_analyses=fixture_analyses,
            provider=None,
            registry=registry,
            environ=environ,
        )
        result = image_provider.analyze(
            image_id=image_id, content_hash=content_sha256
        )

        analysis = service.request_analysis(
            image_id=image_id,
            content_hash=content_sha256,
            reference_set_id=None,
            vision_model=result.model.model_name,
            vision_model_version=result.model.model_version,
            taxon_context=image.get("taxon_name"),
            taxon_confidence=None,
            calibration_state=CalibrationState.UNCALIBRATED,
            image_quality=ImageQualityState.UNKNOWN,
            warnings=list(result.warnings),
            limitations=[
                MACHINE_LIMITATION,
                *([FIXTURE_LIMITATION] if mode == FIXTURE_MODE else []),
            ],
        )

        existing = service.list_observations_for_analysis(analysis.analysis_id)
        replay = bool(existing)
        recorded = 0
        if not replay:
            for obs in result.character_observations:
                basis = (
                    MeasurementBasis.IMAGE_DERIVED
                    if obs.state is not None
                    else MeasurementBasis.CANNOT_DETERMINE
                )
                service.record_character_observation(
                    analysis_id=analysis.analysis_id,
                    region_id=None,
                    concept_id=None,
                    character_id=obs.character_id,
                    character_state_id=obs.state,
                    numeric_value=None,
                    unit=None,
                    relative_value=None,
                    measurement_basis=basis,
                    confidence=min(float(obs.confidence), MAX_VISION_CONFIDENCE),
                    method=(
                        f"vision:{result.model.provider}/"
                        f"{result.model.model_name}@{result.model.model_version}"
                    ),
                    evidence_region=None,
                    provenance={
                        "adapter": "matrix_vision_adapter",
                        "adapter_schema": VISION_EXTRACTION_SCHEMA,
                        "extraction_mode": mode,
                        "provider": result.model.provider,
                        "model_name": result.model.model_name,
                        "model_version": result.model.model_version,
                        "inference_id": result.model.inference_id,
                        "image_id": image_id,
                        "content_sha256": content_sha256,
                        "submission_id": submission_id,
                        "license_code": result.license_code,
                        "attribution": result.attribution,
                        "contributor_attribution": image.get("attribution_line"),
                        "permission_grant": image.get("permission_grant"),
                        "detected_parts": [
                            {"part": part.part, "confidence": part.confidence}
                            for part in result.detected_parts
                        ],
                        "observation_provenance": list(obs.provenance),
                    },
                    limitations=[
                        *result.warnings,
                        MACHINE_LIMITATION,
                        *([FIXTURE_LIMITATION] if mode == FIXTURE_MODE else []),
                    ],
                )
                recorded += 1

        attached = attach_vision_analysis(
            session_id,
            str(analysis.analysis_id),
            access_actor=access_actor,
            root=root,
            registry_root=registry_root,
            vision_service=service,
        )
        per_image.append(
            {
                "submission_id": submission_id,
                "image_id": image_id,
                "content_sha256": content_sha256,
                "analysis_id": str(analysis.analysis_id),
                "replay": replay,
                "observations_recorded": recorded,
                "observations_total": len(
                    service.list_observations_for_analysis(analysis.analysis_id)
                ),
                "suggestions_added": attached["added"],
                "extraction_mode": mode,
                "model": {
                    "provider": result.model.provider,
                    "model_name": result.model.model_name,
                    "model_version": result.model.model_version,
                    "inference_id": result.model.inference_id,
                },
                "warnings": list(result.warnings),
            }
        )

    return {
        "schema_version": VISION_EXTRACTION_SCHEMA,
        "session_id": session_id,
        "mode": mode,
        "live_inference_performed": mode == LIVE_MODE,
        "fixture_label": (
            "FIXTURE_MODE_NO_LIVE_INFERENCE" if mode == FIXTURE_MODE else None
        ),
        "images": per_image,
        "image_count": len(per_image),
        "observations_recorded": sum(item["observations_recorded"] for item in per_image),
        "suggestions_added": sum(item["suggestions_added"] for item in per_image),
        "provider_readiness": readiness,
        "capability": vision_extraction_capability(registry=registry, environ=environ),
        "governance": {
            "review_required_before_scoring": True,
            "machine_confidence_capped_at": MAX_VISION_CONFIDENCE,
            "cannot_determine_preserved": True,
            "no_invented_observations": True,
            "idempotent_replay": True,
        },
    }
