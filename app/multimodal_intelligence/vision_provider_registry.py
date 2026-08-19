"""Governed registry and readiness reporting for canonical Vision providers.

This module extends the existing ``VisionProvider`` protocol. It does not
perform inference, dynamically import providers, read credentials, or mutate
runtime configuration. Providers must be registered explicitly by application
code, and readiness probes must be side-effect-free.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .integration import VisionProvider

_PROVIDER_ENV = "CALYX_VISION_PROVIDER"
_LIVE_INFERENCE_FLAG = "CALYX_VISION_LIVE_INFERENCE_ENABLED"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class ProviderProbeResult:
    ready: bool
    code: str | None = None

    def validate(self) -> None:
        if self.ready and self.code:
            raise ValueError("VISION_PROVIDER_READY_WITH_ERROR_CODE")
        if not self.ready and not (self.code or "").strip():
            raise ValueError("VISION_PROVIDER_NOT_READY_CODE_REQUIRED")


@dataclass(frozen=True, slots=True)
class VisionProviderRegistration:
    """Static registration metadata for one canonical Vision provider adapter."""

    name: str
    provider_factory: Callable[[], VisionProvider]
    readiness_probe: Callable[[], ProviderProbeResult]
    production_capable: bool
    model_family: str | None = None
    adapter_version: str | None = None

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("VISION_PROVIDER_NAME_REQUIRED")
        if self.model_family is not None and not self.model_family.strip():
            raise ValueError("VISION_PROVIDER_MODEL_FAMILY_INVALID")
        if self.adapter_version is not None and not self.adapter_version.strip():
            raise ValueError("VISION_PROVIDER_ADAPTER_VERSION_INVALID")


@dataclass(slots=True)
class VisionProviderRegistry:
    """In-process registry with no network, credential, or inference side effects."""

    registrations: dict[str, VisionProviderRegistration] = field(default_factory=dict)

    @staticmethod
    def _key(name: str) -> str:
        return name.strip().casefold()

    def register(self, registration: VisionProviderRegistration) -> None:
        registration.validate()
        key = self._key(registration.name)
        if key in self.registrations:
            raise ValueError("VISION_PROVIDER_ALREADY_REGISTERED")
        self.registrations[key] = registration

    def get(self, name: str) -> VisionProviderRegistration | None:
        return self.registrations.get(self._key(name))

    def provider_names(self) -> tuple[str, ...]:
        return tuple(sorted(item.name for item in self.registrations.values()))


DEFAULT_VISION_PROVIDER_REGISTRY = VisionProviderRegistry()


def configured_provider_name(environ: Mapping[str, str] | None = None) -> str | None:
    env = os.environ if environ is None else environ
    selected = (env.get(_PROVIDER_ENV) or "").strip()
    return selected or None


def live_inference_requested(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return _truthy(env.get(_LIVE_INFERENCE_FLAG))


def provider_readiness(
    *,
    registry: VisionProviderRegistry | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return side-effect-free provider readiness for status/preflight surfaces.

    The selected adapter is never instantiated here. A readiness probe may only
    inspect local configuration required by that adapter; it must not invoke
    remote inference or expose credential values.
    """

    active_registry = registry or DEFAULT_VISION_PROVIDER_REGISTRY
    selected = configured_provider_name(environ)
    live_requested = live_inference_requested(environ)

    if selected is None:
        return {
            "provider_status": "PROVIDER_NOT_CONFIGURED",
            "selected_provider": None,
            "adapter_registered": False,
            "production_capable": False,
            "provider_ready": False,
            "live_inference_requested": live_requested,
            "live_inference_enabled": False,
            "model_family": None,
            "adapter_version": None,
            "registered_providers": active_registry.provider_names(),
        }

    registration = active_registry.get(selected)
    if registration is None:
        return {
            "provider_status": "PROVIDER_ADAPTER_NOT_REGISTERED",
            "selected_provider": selected,
            "adapter_registered": False,
            "production_capable": False,
            "provider_ready": False,
            "live_inference_requested": live_requested,
            "live_inference_enabled": False,
            "model_family": None,
            "adapter_version": None,
            "registered_providers": active_registry.provider_names(),
        }

    registration.validate()
    if not registration.production_capable:
        return {
            "provider_status": "PROVIDER_NOT_PRODUCTION_CAPABLE",
            "selected_provider": registration.name,
            "adapter_registered": True,
            "production_capable": False,
            "provider_ready": False,
            "live_inference_requested": live_requested,
            "live_inference_enabled": False,
            "model_family": registration.model_family,
            "adapter_version": registration.adapter_version,
            "registered_providers": active_registry.provider_names(),
        }

    try:
        probe = registration.readiness_probe()
        probe.validate()
    except (RuntimeError, ValueError, OSError):
        return {
            "provider_status": "PROVIDER_READINESS_CHECK_FAILED",
            "selected_provider": registration.name,
            "adapter_registered": True,
            "production_capable": True,
            "provider_ready": False,
            "live_inference_requested": live_requested,
            "live_inference_enabled": False,
            "model_family": registration.model_family,
            "adapter_version": registration.adapter_version,
            "registered_providers": active_registry.provider_names(),
        }

    if not probe.ready:
        return {
            "provider_status": probe.code or "PROVIDER_NOT_READY",
            "selected_provider": registration.name,
            "adapter_registered": True,
            "production_capable": True,
            "provider_ready": False,
            "live_inference_requested": live_requested,
            "live_inference_enabled": False,
            "model_family": registration.model_family,
            "adapter_version": registration.adapter_version,
            "registered_providers": active_registry.provider_names(),
        }

    return {
        "provider_status": "READY",
        "selected_provider": registration.name,
        "adapter_registered": True,
        "production_capable": True,
        "provider_ready": True,
        "live_inference_requested": live_requested,
        "live_inference_enabled": live_requested,
        "model_family": registration.model_family,
        "adapter_version": registration.adapter_version,
        "registered_providers": active_registry.provider_names(),
    }
