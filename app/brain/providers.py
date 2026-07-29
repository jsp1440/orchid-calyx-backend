from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class AIProvider(Protocol):
    id: str
    model: str

    def complete(
        self, messages: list[dict[str, str]], *, options: dict[str, Any]
    ) -> str: ...
    def health(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ProviderDescriptor:
    id: str
    models: tuple[str, ...]
    transport: str


SUPPORTED_PROVIDER_INTERFACES = (
    ProviderDescriptor("openai", (), "remote"),
    ProviderDescriptor("anthropic", (), "remote"),
    ProviderDescriptor("gemini", (), "remote"),
    ProviderDescriptor("llama", (), "remote-or-local"),
    ProviderDescriptor("local", (), "local"),
)


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {}

    def register(self, provider: AIProvider) -> None:
        if provider.id in self._providers:
            raise ValueError("PROVIDER_ALREADY_REGISTERED")
        self._providers[provider.id] = provider

    def get(self, provider_id: str) -> AIProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise LookupError("PROVIDER_NOT_CONFIGURED") from exc
