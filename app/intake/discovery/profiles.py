"""Configurable discovery profiles and execution budgets.

Profiles live in ``config/intelligence_discovery_profiles.json`` so operators
can widen coverage without code changes; the defaults below apply when the
file is absent.  Every profile is bounded: a capped look-back, a capped
window, and a capped page size.  There is no unrestricted crawl.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .providers import PROVIDERS

PROFILE_CONFIG_PATH = (
    Path(__file__).resolve().parents[3]
    / "config"
    / "intelligence_discovery_profiles.json"
)
MAX_HISTORICAL_DAYS = 366


class DiscoveryProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    description: str
    domain_hint: Literal[
        "research", "taxonomy", "conservation", "technology", "funding", "partnerships"
    ]
    providers: tuple[str, ...]
    queries: dict[str, str]
    lookback_days: int = Field(default=7, ge=1, le=31)
    max_window_days: int = Field(default=31, ge=1, le=MAX_HISTORICAL_DAYS)
    rows_per_request: int = Field(default=50, ge=1, le=100)
    new_window_days: int = Field(default=60, ge=1, le=365)
    enabled: bool = True

    @field_validator("providers")
    @classmethod
    def _known_providers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(set(value) - set(PROVIDERS))
        if unknown:
            raise ValueError(f"UNKNOWN_DISCOVERY_PROVIDER:{','.join(unknown)}")
        if not value:
            raise ValueError("DISCOVERY_PROFILE_HAS_NO_PROVIDER")
        return value

    def query_for(self, provider: str) -> str:
        return self.queries.get(provider) or self.queries["default"]


class DiscoveryBudget(BaseModel):
    """Per-cycle ceilings; reaching one stops the cycle as PARTIAL, never silently."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_requests: int = Field(default=12, ge=0, le=200)
    max_records: int = Field(default=300, ge=0, le=5000)
    max_verifications: int = Field(default=10, ge=0, le=200)
    min_interval_seconds: float = Field(default=1.0, ge=0.0, le=60.0)


DEFAULT_PROFILES: tuple[DiscoveryProfile, ...] = (
    DiscoveryProfile(
        key="orchid-literature",
        description="Newly indexed orchid literature and preprints across free scholarly registries.",
        domain_hint="research",
        providers=("crossref", "openalex", "europepmc"),
        queries={
            "default": "orchid Orchidaceae",
            "openalex": "orchid|orchidaceae",
            "europepmc": "orchid* Orchidaceae",
        },
    ),
    DiscoveryProfile(
        key="orchid-taxonomic-novelties",
        description="Protologues, new combinations and revisions in Orchidaceae.",
        domain_hint="taxonomy",
        providers=("crossref",),
        queries={"default": "Orchidaceae new species sp. nov. taxonomy"},
    ),
)


def load_profiles(path: Path | None = None) -> tuple[DiscoveryProfile, ...]:
    path = path or PROFILE_CONFIG_PATH
    if not path.exists():
        return DEFAULT_PROFILES
    raw = json.loads(path.read_text(encoding="utf-8"))
    profiles = tuple(
        DiscoveryProfile.model_validate(item) for item in raw.get("profiles", [])
    )
    keys = [profile.key for profile in profiles]
    if len(keys) != len(set(keys)):
        raise ValueError("DUPLICATE_DISCOVERY_PROFILE_KEY")
    return profiles
