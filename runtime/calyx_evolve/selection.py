"""Deterministic candidate selection.

Three policies ship in this phase — ``baseline``, ``best_eligible`` and
``seeded_random``.  The interface is intentionally the smallest thing that
UCB1 or MAP-Elites could later implement: a policy sees the full set of scored,
screened candidates and returns one of them (or nothing).

Every policy is deterministic.  ``seeded_random`` explores, but the same seed
and the same candidate set always yield the same choice, so a campaign replays
identically.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

POLICY_BASELINE = "baseline"
POLICY_BEST_ELIGIBLE = "best_eligible"
POLICY_SEEDED_RANDOM = "seeded_random"

SELECTION_POLICIES: tuple[str, ...] = (
    POLICY_BASELINE,
    POLICY_BEST_ELIGIBLE,
    POLICY_SEEDED_RANDOM,
)


class SelectionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    """The minimum a selector needs to know about a completed run."""

    candidate_id: str
    run_id: str
    is_baseline: bool
    eligible: bool
    score: float | None
    ineligibility_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "run_id": self.run_id,
            "is_baseline": self.is_baseline,
            "eligible": self.eligible,
            "score": self.score,
            "ineligibility_reasons": list(self.ineligibility_reasons),
        }


class Selector(Protocol):
    policy: str

    def select(self, candidates: Sequence[ScoredCandidate]) -> ScoredCandidate | None:
        ...


def _ordered(candidates: Iterable[ScoredCandidate]) -> list[ScoredCandidate]:
    """Sort by candidate id so selection never depends on insertion order."""

    return sorted(candidates, key=lambda item: item.candidate_id)


@dataclass(frozen=True, slots=True)
class BaselineSelector:
    policy: str = POLICY_BASELINE

    def select(self, candidates: Sequence[ScoredCandidate]) -> ScoredCandidate | None:
        for candidate in _ordered(candidates):
            if candidate.is_baseline:
                return candidate
        return None


@dataclass(frozen=True, slots=True)
class BestEligibleSelector:
    policy: str = POLICY_BEST_ELIGIBLE

    def select(self, candidates: Sequence[ScoredCandidate]) -> ScoredCandidate | None:
        scored = [
            candidate
            for candidate in _ordered(candidates)
            if candidate.eligible and candidate.score is not None
        ]
        if not scored:
            return None
        # Ties break on candidate id, which ``_ordered`` already fixed.
        return max(scored, key=lambda item: (item.score, ))


@dataclass(frozen=True, slots=True)
class SeededRandomSelector:
    seed: int
    policy: str = POLICY_SEEDED_RANDOM

    def select(self, candidates: Sequence[ScoredCandidate]) -> ScoredCandidate | None:
        pool = [candidate for candidate in _ordered(candidates) if candidate.eligible]
        if not pool:
            return None
        return pool[random.Random(self.seed).randrange(len(pool))]


def build_selector(policy: str, *, seed: int | None = None) -> Selector:
    if policy == POLICY_BASELINE:
        return BaselineSelector()
    if policy == POLICY_BEST_ELIGIBLE:
        return BestEligibleSelector()
    if policy == POLICY_SEEDED_RANDOM:
        if seed is None:
            raise SelectionError("seeded_random selection requires an explicit seed")
        return SeededRandomSelector(seed=int(seed))
    raise SelectionError(f"unknown selection policy {policy!r}")
