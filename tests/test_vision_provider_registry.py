from app.multimodal_intelligence.vision_provider_registry import (
    ProviderProbeResult,
    VisionProviderRegistration,
    VisionProviderRegistry,
    provider_readiness,
)


class _NeverInstantiatedProvider:
    provider_name = "dummy"

    def analyze(self, *, image_id: str, content_hash: str):
        raise AssertionError(f"provider execution is outside readiness scope: {image_id}:{content_hash}")


def _registration(*, name="dummy", production_capable=True, probe=None):
    return VisionProviderRegistration(
        name=name,
        provider_factory=_NeverInstantiatedProvider,
        readiness_probe=probe or (lambda: ProviderProbeResult(ready=True)),
        production_capable=production_capable,
        model_family="test-model-family",
        adapter_version="test-v1",
    )


def test_no_provider_selected_fails_closed_without_probe_or_factory():
    registry = VisionProviderRegistry()

    result = provider_readiness(registry=registry, environ={})

    assert result["provider_status"] == "PROVIDER_NOT_CONFIGURED"
    assert result["provider_ready"] is False
    assert result["live_inference_enabled"] is False
    assert result["registered_providers"] == ()


def test_selected_unregistered_adapter_cannot_become_ready_from_environment():
    result = provider_readiness(
        registry=VisionProviderRegistry(),
        environ={
            "CALYX_VISION_PROVIDER": "imaginary-provider",
            "CALYX_VISION_LIVE_INFERENCE_ENABLED": "true",
        },
    )

    assert result["provider_status"] == "PROVIDER_ADAPTER_NOT_REGISTERED"
    assert result["selected_provider"] == "imaginary-provider"
    assert result["adapter_registered"] is False
    assert result["provider_ready"] is False
    assert result["live_inference_requested"] is True
    assert result["live_inference_enabled"] is False


def test_nonproduction_adapter_is_visible_but_cannot_enable_live_inference():
    registry = VisionProviderRegistry()
    registry.register(_registration(name="fixture", production_capable=False))

    result = provider_readiness(
        registry=registry,
        environ={
            "CALYX_VISION_PROVIDER": "fixture",
            "CALYX_VISION_LIVE_INFERENCE_ENABLED": "true",
        },
    )

    assert result["provider_status"] == "PROVIDER_NOT_PRODUCTION_CAPABLE"
    assert result["adapter_registered"] is True
    assert result["production_capable"] is False
    assert result["provider_ready"] is False
    assert result["live_inference_enabled"] is False


def test_registered_production_adapter_preserves_specific_readiness_blocker():
    registry = VisionProviderRegistry()
    registry.register(
        _registration(
            probe=lambda: ProviderProbeResult(
                ready=False,
                code="PROVIDER_CREDENTIALS_NOT_CONFIGURED",
            )
        )
    )

    result = provider_readiness(
        registry=registry,
        environ={"CALYX_VISION_PROVIDER": "dummy"},
    )

    assert result["provider_status"] == "PROVIDER_CREDENTIALS_NOT_CONFIGURED"
    assert result["production_capable"] is True
    assert result["provider_ready"] is False
    assert result["model_family"] == "test-model-family"
    assert result["adapter_version"] == "test-v1"


def test_probe_exception_fails_closed_without_exposing_exception_text():
    registry = VisionProviderRegistry()

    def broken_probe():
        raise RuntimeError("secret-bearing provider diagnostic")

    registry.register(_registration(probe=broken_probe))

    result = provider_readiness(
        registry=registry,
        environ={"CALYX_VISION_PROVIDER": "dummy"},
    )

    assert result["provider_status"] == "PROVIDER_READINESS_CHECK_FAILED"
    assert result["provider_ready"] is False
    assert "secret" not in str(result).lower()


def test_live_inference_requires_registered_production_ready_adapter_and_explicit_flag():
    registry = VisionProviderRegistry()
    registry.register(_registration())

    disabled = provider_readiness(
        registry=registry,
        environ={"CALYX_VISION_PROVIDER": "dummy"},
    )
    enabled = provider_readiness(
        registry=registry,
        environ={
            "CALYX_VISION_PROVIDER": "dummy",
            "CALYX_VISION_LIVE_INFERENCE_ENABLED": "true",
        },
    )

    assert disabled["provider_status"] == "READY"
    assert disabled["provider_ready"] is True
    assert disabled["live_inference_requested"] is False
    assert disabled["live_inference_enabled"] is False
    assert enabled["provider_status"] == "READY"
    assert enabled["provider_ready"] is True
    assert enabled["live_inference_requested"] is True
    assert enabled["live_inference_enabled"] is True


def test_registry_rejects_duplicate_provider_names_case_insensitively():
    registry = VisionProviderRegistry()
    registry.register(_registration(name="Provider-A"))

    try:
        registry.register(_registration(name="provider-a"))
    except ValueError as exc:
        assert str(exc) == "VISION_PROVIDER_ALREADY_REGISTERED"
    else:
        raise AssertionError("duplicate provider registration should fail closed")
