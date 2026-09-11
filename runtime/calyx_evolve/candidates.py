"""DESIGN stage: typed candidate reconciliation strategies and their lineage.

A candidate is a *declarative configuration* — never executable code supplied by
a model.  That keeps the EXPERIMENT stage bounded: the sandbox interprets a
fixed set of knobs, so a candidate cannot reach outside the evaluator no matter
where the configuration came from.

Every candidate records its hypothesis, its parents, the generator that produced
it, and a novelty key.  The novelty key is derived from the *effective
configuration* only, so two differently-named candidates that describe the same
strategy deduplicate against each other — including failed ones, which stay
queryable so the loop stops rediscovering them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from runtime.calyx_evolve.provenance import content_hash
from runtime.calyx_evolve.redaction import assert_inspectable

GENERATOR_FIXTURE = "deterministic_fixture"
GENERATOR_OPERATOR = "operator"
GENERATOR_MUTATION = "deterministic_mutation"

KNOWN_GENERATORS: frozenset[str] = frozenset(
    {GENERATOR_FIXTURE, GENERATOR_OPERATOR, GENERATOR_MUTATION}
)

#: Upper bound on fuzzy edit distance the sandbox will honour.
MAX_FUZZY_DISTANCE = 3

#: Hypothesis text is a concise claim, never a reasoning trace.
HYPOTHESIS_MAX_CHARS = 400


class CandidateError(ValueError):
    """Raised when a candidate configuration is not admissible."""


@dataclass(frozen=True, slots=True)
class ReconciliationConfig:
    """The complete, typed knob set the sandbox will interpret.

    The three ``request_*``/``emit_*`` flags are not features — they exist so the
    safety screen has something real to reject.  A candidate that asks for a
    production write, a taxonomy activation, or protected-locality output is
    stopped before execution; see :mod:`runtime.calyx_evolve.safety`.
    """

    normalize_case: bool = True
    collapse_whitespace: bool = True
    strip_authorship: bool = True
    follow_synonyms: bool = True
    fuzzy_max_distance: int = 0
    ambiguity_guard: bool = True
    emit_provenance: bool = True
    request_production_write: bool = False
    request_taxonomy_activation: bool = False
    emit_protected_locality: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.fuzzy_max_distance, int) or isinstance(
            self.fuzzy_max_distance, bool
        ):
            raise CandidateError("fuzzy_max_distance must be an int")
        if self.fuzzy_max_distance < 0:
            raise CandidateError("fuzzy_max_distance must not be negative")
        if self.fuzzy_max_distance > MAX_FUZZY_DISTANCE:
            raise CandidateError(
                f"fuzzy_max_distance {self.fuzzy_max_distance} exceeds the bounded "
                f"maximum of {MAX_FUZZY_DISTANCE}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def mutate(self, **changes: Any) -> ReconciliationConfig:
        return replace(self, **changes)

    @property
    def config_hash(self) -> str:
        return content_hash(self.to_dict())


BASELINE_CONFIG = ReconciliationConfig()


@dataclass(frozen=True, slots=True)
class Candidate:
    """One designed strategy, with lineage back to the candidates it came from."""

    candidate_id: str
    campaign_id: str
    label: str
    hypothesis: str
    config: ReconciliationConfig
    generator: str = GENERATOR_FIXTURE
    parent_ids: tuple[str, ...] = ()
    is_baseline: bool = False
    declared_cost_usd: float | None = None
    cost_basis: str | None = None
    generator_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.candidate_id).strip():
            raise CandidateError("candidate_id is required")
        if not str(self.campaign_id).strip():
            raise CandidateError("campaign_id is required")
        if self.generator not in KNOWN_GENERATORS:
            raise CandidateError(
                f"generator {self.generator!r} is not one of {sorted(KNOWN_GENERATORS)}"
            )
        if not str(self.hypothesis).strip():
            raise CandidateError(f"candidate {self.candidate_id!r} has no hypothesis")
        if len(self.hypothesis) > HYPOTHESIS_MAX_CHARS:
            raise CandidateError(
                f"hypothesis for {self.candidate_id!r} exceeds {HYPOTHESIS_MAX_CHARS} "
                "characters; record a concise claim, not a reasoning trace"
            )
        if self.candidate_id in self.parent_ids:
            raise CandidateError(f"candidate {self.candidate_id!r} cannot be its own parent")
        if self.declared_cost_usd is not None:
            if isinstance(self.declared_cost_usd, bool) or not isinstance(
                self.declared_cost_usd, (int, float)
            ):
                raise CandidateError("declared_cost_usd must be a number or None")
            if self.declared_cost_usd < 0:
                raise CandidateError("declared_cost_usd must not be negative")
            if not str(self.cost_basis or "").strip():
                raise CandidateError(
                    "a declared cost requires a cost_basis naming how it was measured"
                )
        assert_inspectable(
            {
                "hypothesis": self.hypothesis,
                "label": self.label,
                "generator_metadata": dict(self.generator_metadata),
            }
        )

    @property
    def novelty_key(self) -> str:
        """Deduplication key derived from the effective configuration only."""

        return content_hash(self.config.to_dict())

    @property
    def lineage_depth(self) -> int:
        return 0 if not self.parent_ids else 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "campaign_id": self.campaign_id,
            "label": self.label,
            "hypothesis": self.hypothesis,
            "generator": self.generator,
            "parent_ids": list(self.parent_ids),
            "is_baseline": self.is_baseline,
            "config": self.config.to_dict(),
            "config_hash": self.config.config_hash,
            "novelty_key": self.novelty_key,
            "declared_cost_usd": self.declared_cost_usd,
            "cost_basis": self.cost_basis,
            "generator_metadata": dict(self.generator_metadata),
        }


def ancestry(candidate: Candidate, index: Mapping[str, Candidate]) -> tuple[str, ...]:
    """Return ``candidate``'s ancestor ids, nearest first, without cycles."""

    seen: set[str] = {candidate.candidate_id}
    ordered: list[str] = []
    frontier: list[str] = list(candidate.parent_ids)
    while frontier:
        parent_id = frontier.pop(0)
        if parent_id in seen:
            continue
        seen.add(parent_id)
        ordered.append(parent_id)
        parent = index.get(parent_id)
        if parent is not None:
            frontier.extend(parent.parent_ids)
    return tuple(ordered)


def deduplicate(candidates: Iterable[Candidate]) -> tuple[tuple[Candidate, ...], tuple[Candidate, ...]]:
    """Split ``candidates`` into ``(kept, duplicates)`` by novelty key.

    The first candidate seen for a novelty key wins; later ones are duplicates.
    Duplicates are returned rather than discarded so the campaign can record why
    a candidate was not run.
    """

    kept: list[Candidate] = []
    duplicates: list[Candidate] = []
    seen: dict[str, str] = {}
    for candidate in candidates:
        key = candidate.novelty_key
        if key in seen:
            duplicates.append(candidate)
            continue
        seen[key] = candidate.candidate_id
        kept.append(candidate)
    return tuple(kept), tuple(duplicates)
