"""Versioned, deterministic taxonomy evaluation for CALYX-EVOLVE-001.

A measurement that could not be taken is recorded as ``unavailable`` with a
reason.  It is never coerced to ``0``: a fabricated zero would make an unmeasured
cost look free and an unmeasured false-merge rate look clean.  Anything that
consumes a metric must therefore check ``state`` before reading ``value``.

The aggregate score is a transparent weighted sum computed *after* hard safety
constraints pass.  It never absorbs the false-merge count: that stays a separate,
always-visible integer, and the analyzer raises counterevidence whenever it is
non-zero regardless of how the aggregate moved.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from runtime.calyx_evolve.fixture import EXPECT_ACCEPTED, TaxonomyFixture
from runtime.calyx_evolve.reconciler import OUTCOME_ACCEPTED, ReconciliationArtifact

EVALUATOR_VERSION = "calyx-evolve-taxonomy-evaluator-1.0.0"
SCORING_VERSION = "calyx-evolve-weighted-score-1.0.0"

STATE_MEASURED = "measured"
STATE_UNAVAILABLE = "unavailable"

HIGHER_IS_BETTER = "higher_better"
LOWER_IS_BETTER = "lower_better"
NEUTRAL = "neutral"

METRIC_ACCURACY = "accepted_name_exact_match_accuracy"
METRIC_FALSE_MERGE_COUNT = "false_merge_count"
METRIC_FALSE_MERGE_RATE = "false_merge_rate"
METRIC_MISSED_COUNT = "missed_resolution_count"
METRIC_ABSTENTION_COUNT = "unresolved_abstention_count"
METRIC_PROVENANCE = "provenance_completeness"
METRIC_REPLAY = "deterministic_replay"
METRIC_RUNTIME = "runtime_seconds"
METRIC_COST = "estimated_cost_usd"


class MetricUnavailable(RuntimeError):
    """Raised when an unavailable metric is read as a number."""


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    key: str
    label: str
    unit: str
    direction: str
    weight: float = 0.0
    safety_visible: bool = False
    #: Whether a change against the baseline is a scientific result worth a
    #: success/failure finding.  Runtime and cost are operational, not
    #: correctness, so a slower run is not reported as a scientific failure.
    comparison_reportable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "unit": self.unit,
            "direction": self.direction,
            "weight": self.weight,
            "safety_visible": self.safety_visible,
            "comparison_reportable": self.comparison_reportable,
        }


METRIC_DEFINITIONS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        METRIC_ACCURACY,
        "Accepted-name exact-match accuracy",
        "ratio",
        HIGHER_IS_BETTER,
        weight=0.6,
    ),
    MetricDefinition(
        METRIC_FALSE_MERGE_COUNT,
        "False merges",
        "count",
        LOWER_IS_BETTER,
        safety_visible=True,
    ),
    MetricDefinition(
        METRIC_FALSE_MERGE_RATE,
        "False-merge rate",
        "ratio",
        LOWER_IS_BETTER,
        weight=0.3,
        safety_visible=True,
    ),
    MetricDefinition(
        METRIC_MISSED_COUNT,
        "Expected resolutions missed",
        "count",
        LOWER_IS_BETTER,
    ),
    MetricDefinition(
        METRIC_ABSTENTION_COUNT,
        "Unresolved / abstained records",
        "count",
        NEUTRAL,
        comparison_reportable=False,
    ),
    MetricDefinition(
        METRIC_PROVENANCE,
        "Provenance completeness",
        "ratio",
        HIGHER_IS_BETTER,
        weight=0.1,
    ),
    MetricDefinition(
        METRIC_REPLAY,
        "Deterministic replay",
        "boolean_ratio",
        HIGHER_IS_BETTER,
    ),
    MetricDefinition(
        METRIC_RUNTIME, "Runtime", "seconds", LOWER_IS_BETTER, comparison_reportable=False
    ),
    MetricDefinition(
        METRIC_COST,
        "Estimated provider/compute cost",
        "usd",
        LOWER_IS_BETTER,
        comparison_reportable=False,
    ),
)

DEFINITIONS_BY_KEY: dict[str, MetricDefinition] = {d.key: d for d in METRIC_DEFINITIONS}

#: Metrics that participate in the weighted aggregate score.
WEIGHTED_KEYS: tuple[str, ...] = tuple(d.key for d in METRIC_DEFINITIONS if d.weight > 0)


@dataclass(frozen=True, slots=True)
class MetricValue:
    key: str
    value: float | int | None
    state: str
    basis: str

    @classmethod
    def measured(cls, key: str, value: float, basis: str) -> MetricValue:
        return cls(key=key, value=value, state=STATE_MEASURED, basis=basis)

    @classmethod
    def unavailable(cls, key: str, reason: str) -> MetricValue:
        return cls(key=key, value=None, state=STATE_UNAVAILABLE, basis=reason)

    @property
    def is_measured(self) -> bool:
        return self.state == STATE_MEASURED

    def numeric(self) -> float:
        if not self.is_measured or self.value is None:
            raise MetricUnavailable(f"metric {self.key!r} is {self.state}: {self.basis}")
        return float(self.value)

    def to_dict(self) -> dict[str, Any]:
        definition = DEFINITIONS_BY_KEY.get(self.key)
        return {
            "key": self.key,
            "value": self.value,
            "state": self.state,
            "basis": self.basis,
            "unit": definition.unit if definition else "unknown",
            "direction": definition.direction if definition else NEUTRAL,
        }


@dataclass(frozen=True, slots=True)
class MetricVector:
    evaluator_version: str
    scoring_version: str
    fixture_hash: str
    values: tuple[MetricValue, ...]
    false_merge_records: tuple[str, ...]
    missed_records: tuple[str, ...]

    def get(self, key: str) -> MetricValue:
        for value in self.values:
            if value.key == key:
                return value
        raise KeyError(key)

    def as_mapping(self) -> dict[str, MetricValue]:
        return {value.key: value for value in self.values}

    def unavailable_keys(self) -> tuple[str, ...]:
        return tuple(v.key for v in self.values if not v.is_measured)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluator_version": self.evaluator_version,
            "scoring_version": self.scoring_version,
            "fixture_hash": self.fixture_hash,
            "metrics": [value.to_dict() for value in self.values],
            "false_merge_records": list(self.false_merge_records),
            "missed_records": list(self.missed_records),
            "unavailable_metrics": list(self.unavailable_keys()),
        }


def classify_resolutions(
    artifact: ReconciliationArtifact, fixture: TaxonomyFixture
) -> dict[str, list[str]]:
    """Bucket every fixture record into correct / false merge / missed / abstained.

    A **false merge** is any emitted accepted name that does not equal the locked
    expectation — whether the expectation was a different taxon or an abstention.
    It is the failure class that silently corrupts a taxonomy, so it is counted
    separately from a mere miss.
    """

    expectations = fixture.expected_outcomes()
    by_record = {resolution.record_id: resolution for resolution in artifact.resolutions}

    buckets: dict[str, list[str]] = {
        "correct": [],
        "false_merge": [],
        "missed": [],
        "abstained": [],
        "unevaluated": [],
    }

    for record_id, (expected_outcome, expected_name) in sorted(expectations.items()):
        resolution = by_record.get(record_id)
        if resolution is None:
            buckets["unevaluated"].append(record_id)
            continue
        if resolution.outcome == OUTCOME_ACCEPTED:
            if expected_outcome == EXPECT_ACCEPTED and resolution.accepted_name == expected_name:
                buckets["correct"].append(record_id)
            else:
                buckets["false_merge"].append(record_id)
        else:
            buckets["abstained"].append(record_id)
            if expected_outcome == EXPECT_ACCEPTED:
                buckets["missed"].append(record_id)
            else:
                buckets["correct"].append(record_id)

    return {key: sorted(value) for key, value in buckets.items()}


def evaluate(
    artifact: ReconciliationArtifact,
    fixture: TaxonomyFixture,
    *,
    runtime_seconds: float | None,
    replay_deterministic: bool | None,
    declared_cost_usd: float | None = None,
    cost_basis: str | None = None,
) -> MetricVector:
    """Score ``artifact`` against the locked expectations of ``fixture``."""

    if artifact.fixture_hash != fixture.fixture_hash:
        raise ValueError(
            "artifact was produced against a different fixture version; refusing to score"
        )

    buckets = classify_resolutions(artifact, fixture)
    total = len(fixture.records)
    correct = len(buckets["correct"])
    false_merges = len(buckets["false_merge"])
    missed = len(buckets["missed"])
    abstained = len(buckets["abstained"])
    unevaluated = len(buckets["unevaluated"])

    values: list[MetricValue] = []

    if unevaluated:
        values.append(
            MetricValue.unavailable(
                METRIC_ACCURACY,
                f"{unevaluated} fixture record(s) produced no resolution",
            )
        )
    else:
        values.append(
            MetricValue.measured(
                METRIC_ACCURACY,
                correct / total if total else 0.0,
                f"{correct}/{total} records matched the locked expectation",
            )
        )

    values.append(
        MetricValue.measured(
            METRIC_FALSE_MERGE_COUNT,
            false_merges,
            f"records: {buckets['false_merge'] or 'none'}",
        )
    )
    values.append(
        MetricValue.measured(
            METRIC_FALSE_MERGE_RATE,
            false_merges / total if total else 0.0,
            f"{false_merges}/{total} records were merged into the wrong taxon",
        )
    )
    values.append(
        MetricValue.measured(
            METRIC_MISSED_COUNT,
            missed,
            f"records: {buckets['missed'] or 'none'}",
        )
    )
    values.append(
        MetricValue.measured(
            METRIC_ABSTENTION_COUNT,
            abstained,
            f"{abstained}/{total} records were left unresolved",
        )
    )

    claims = [r for r in artifact.resolutions if r.outcome == OUTCOME_ACCEPTED]
    if not claims:
        values.append(
            MetricValue.unavailable(
                METRIC_PROVENANCE,
                "candidate made no taxonomic claim, so provenance completeness is undefined",
            )
        )
    else:
        complete = sum(1 for r in claims if r.provenance_complete())
        values.append(
            MetricValue.measured(
                METRIC_PROVENANCE,
                complete / len(claims),
                f"{complete}/{len(claims)} claims carried complete provenance",
            )
        )

    if replay_deterministic is None:
        values.append(
            MetricValue.unavailable(METRIC_REPLAY, "replay was not exercised")
        )
    else:
        values.append(
            MetricValue.measured(
                METRIC_REPLAY,
                1.0 if replay_deterministic else 0.0,
                "second in-sandbox execution produced an identical artifact digest"
                if replay_deterministic
                else "second in-sandbox execution produced a different artifact digest",
            )
        )

    if runtime_seconds is None:
        values.append(
            MetricValue.unavailable(METRIC_RUNTIME, "runtime was not measured")
        )
    else:
        values.append(
            MetricValue.measured(METRIC_RUNTIME, float(runtime_seconds), "sandbox wall clock")
        )

    if declared_cost_usd is None:
        values.append(
            MetricValue.unavailable(
                METRIC_COST,
                "no provider or compute cost was reported for this candidate",
            )
        )
    else:
        values.append(
            MetricValue.measured(
                METRIC_COST,
                float(declared_cost_usd),
                cost_basis or "declared by candidate",
            )
        )

    return MetricVector(
        evaluator_version=EVALUATOR_VERSION,
        scoring_version=SCORING_VERSION,
        fixture_hash=fixture.fixture_hash,
        values=tuple(values),
        false_merge_records=tuple(buckets["false_merge"]),
        missed_records=tuple(buckets["missed"]),
    )


@dataclass(frozen=True, slots=True)
class AggregateScore:
    scoring_version: str
    value: float | None
    state: str
    basis: str
    contributions: tuple[tuple[str, float], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "scoring_version": self.scoring_version,
            "value": self.value,
            "state": self.state,
            "basis": self.basis,
            "contributions": [
                {"metric": key, "contribution": contribution}
                for key, contribution in self.contributions
            ],
        }


def aggregate_score(vector: MetricVector) -> AggregateScore:
    """Compute the transparent weighted score, failing closed on gaps.

    The score is only a ranking convenience.  It is deliberately unavailable
    when any weighted input is unmeasured, so a missing measurement can never
    look like a good one.
    """

    mapping = vector.as_mapping()
    missing = [key for key in WEIGHTED_KEYS if not mapping.get(key, MetricValue.unavailable(key, "absent")).is_measured]
    if missing:
        return AggregateScore(
            scoring_version=vector.scoring_version,
            value=None,
            state=STATE_UNAVAILABLE,
            basis=f"weighted metrics unavailable: {sorted(missing)}",
        )

    contributions: list[tuple[str, float]] = []
    total = 0.0
    for key in WEIGHTED_KEYS:
        definition = DEFINITIONS_BY_KEY[key]
        raw = mapping[key].numeric()
        oriented = raw if definition.direction == HIGHER_IS_BETTER else (1.0 - raw)
        contribution = definition.weight * oriented
        contributions.append((key, round(contribution, 9)))
        total += contribution

    return AggregateScore(
        scoring_version=vector.scoring_version,
        value=round(total, 9),
        state=STATE_MEASURED,
        basis="weighted sum of oriented metric values",
        contributions=tuple(contributions),
    )


def metric_catalogue() -> list[dict[str, Any]]:
    return [definition.to_dict() for definition in METRIC_DEFINITIONS]


def compare(
    candidate: MetricVector, baseline: MetricVector
) -> list[dict[str, Any]]:
    """Per-metric candidate-vs-baseline comparison, preserving unavailability."""

    rows: list[dict[str, Any]] = []
    candidate_map = candidate.as_mapping()
    baseline_map = baseline.as_mapping()
    for definition in METRIC_DEFINITIONS:
        cand = candidate_map.get(definition.key)
        base = baseline_map.get(definition.key)
        delta: float | None = None
        direction_label = "unavailable"
        if cand is not None and base is not None and cand.is_measured and base.is_measured:
            delta = round(cand.numeric() - base.numeric(), 9)
            if delta == 0:
                direction_label = "unchanged"
            elif definition.direction == HIGHER_IS_BETTER:
                direction_label = "improved" if delta > 0 else "regressed"
            elif definition.direction == LOWER_IS_BETTER:
                direction_label = "improved" if delta < 0 else "regressed"
            else:
                direction_label = "changed"
        rows.append(
            {
                "metric": definition.key,
                "label": definition.label,
                "unit": definition.unit,
                "direction": definition.direction,
                "safety_visible": definition.safety_visible,
                "comparison_reportable": definition.comparison_reportable,
                "baseline": base.to_dict() if base else None,
                "candidate": cand.to_dict() if cand else None,
                "delta": delta,
                "assessment": direction_label,
            }
        )
    return rows


def measured_values(values: Iterable[MetricValue]) -> Mapping[str, float]:
    return {value.key: value.numeric() for value in values if value.is_measured}
