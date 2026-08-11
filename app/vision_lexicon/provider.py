"""Abstract provider interface for Calyx Vision inference.

Implementations must be:
- Idempotent: repeated requests with the same image + version produce a new
  versioned analysis record rather than overwriting prior evidence.
- Provider-independent: no vendor-specific types leak through this interface.
- Honest about unavailability: return PROVIDER_UNAVAILABLE status rather than
  fabricating observations when credentials/config are absent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from .models import AnalysisStatus, VisionAnalysis


class VisionProviderUnavailable(Exception):
    """Raised when no provider is configured or credentials are absent."""

    def __init__(self, message: str = "VISION_PROVIDER_NOT_CONFIGURED") -> None:
        super().__init__(message)
        self.code = message


class VisionProvider(ABC):
    """Abstract interface for image analysis providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def provider_version(self) -> str: ...

    @abstractmethod
    def analyse_image(
        self,
        *,
        image_id: str,
        image_bytes: bytes | None = None,
        image_url: str | None = None,
        taxon_context: str | None = None,
        reference_set_id: UUID | None = None,
        analysis_version: int = 1,
    ) -> dict[str, Any]:
        """Run analysis and return a raw provider-specific result dict.

        The result will be normalised by VisionLexiconService into canonical
        VisionAnalysis + structured observations.

        Must never fabricate scientific observations.
        Must return a result indicating PROVIDER_UNAVAILABLE if the underlying
        model is not configured.
        """
        ...


class StubVisionProvider(VisionProvider):
    """Stub provider used when no real provider is configured.

    Returns PROVIDER_UNAVAILABLE status.  Never produces scientific observations.
    """

    provider_name = "STUB_UNAVAILABLE"
    provider_version = "0.0.0"

    def analyse_image(self, *, image_id: str, **_kwargs: Any) -> dict[str, Any]:
        return {
            "status": AnalysisStatus.PROVIDER_UNAVAILABLE,
            "provider": self.provider_name,
            "provider_version": self.provider_version,
            "image_id": image_id,
            "limitations": [
                "No vision provider is configured.  "
                "Set CALYX_VISION_PROVIDER and required credentials to enable "
                "live analysis.  This stub never fabricates observations."
            ],
            "regions": [],
            "observations": [],
            "morphometrics": [],
        }


def get_configured_provider() -> VisionProvider:
    """Return the configured provider, or StubVisionProvider if none is set.

    Extend this function to wire real providers as credentials become available.
    """
    import os

    provider_name = os.getenv("CALYX_VISION_PROVIDER", "").strip().upper()
    if not provider_name:
        return StubVisionProvider()

    # Future providers can be registered here, e.g.:
    # if provider_name == "ANTHROPIC_CLAUDE":
    #     from .providers.anthropic import AnthropicVisionProvider
    #     return AnthropicVisionProvider(api_key=os.environ["ANTHROPIC_API_KEY"])

    raise VisionProviderUnavailable(
        f"CALYX_VISION_PROVIDER={provider_name!r} is set but no matching "
        "provider implementation is registered.  Configure a supported "
        "provider or leave CALYX_VISION_PROVIDER unset to use the stub."
    )
