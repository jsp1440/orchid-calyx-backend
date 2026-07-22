"""Plugin registry for Harvester V2."""

from __future__ import annotations

from typing import Type

from .base import BaseHarvester


class HarvesterRegistry:
    """Stores harvester classes by canonical source name."""

    def __init__(self) -> None:
        self._plugins: dict[str, Type[BaseHarvester]] = {}

    def register(self, harvester_cls: Type[BaseHarvester]) -> Type[BaseHarvester]:
        source = getattr(harvester_cls, "source", "").strip().lower()
        if not source:
            raise ValueError("harvester class must define a non-empty source")
        if source in self._plugins:
            raise ValueError(f"harvester already registered: {source}")
        self._plugins[source] = harvester_cls
        return harvester_cls

    def get(self, source: str) -> Type[BaseHarvester]:
        key = source.strip().lower()
        try:
            return self._plugins[key]
        except KeyError as exc:
            raise KeyError(f"unknown harvester source: {source}") from exc

    def sources(self) -> tuple[str, ...]:
        return tuple(sorted(self._plugins))


registry = HarvesterRegistry()
