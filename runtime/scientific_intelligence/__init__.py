"""BUILD-062 Scientific Intelligence backend integration package.

Provides live adapters, normalization, caching, intelligence derivation,
and aggregation for the /api/scientific-intelligence endpoint and all
subsystem intelligence endpoints.

Extends BUILD-061 executive architecture without replacing or duplicating it.
"""

from __future__ import annotations

from runtime.scientific_intelligence.aggregator import build_scientific_intelligence_payload
from runtime.scientific_intelligence.cache import get_cached, set_cached, invalidate_all

__all__ = [
    "build_scientific_intelligence_payload",
    "get_cached",
    "set_cached",
    "invalidate_all",
]
