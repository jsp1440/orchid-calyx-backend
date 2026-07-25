from __future__ import annotations

from collections.abc import Iterable

from .extractors.base import Extractor


class ExtractorRegistry:
    def __init__(self, extractors: Iterable[Extractor] = ()) -> None:
        self._extractors: dict[str, Extractor] = {}
        for extractor in extractors:
            self.register(extractor)

    def register(self, extractor: Extractor) -> None:
        if extractor.name in self._extractors:
            raise ValueError(f"extractor already registered: {extractor.name}")
        self._extractors[extractor.name] = extractor

    def ordered(self) -> list[Extractor]:
        return list(self._extractors.values())

    def names(self) -> list[str]:
        return list(self._extractors)


DEFAULT_REGISTRY = ExtractorRegistry()
