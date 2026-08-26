"""ANALYZE stage: structured findings that survive an improving score.

The analyzer is rule-based and deterministic.  It is deliberately *not* an LLM
judgment: a taxonomy false merge must remain individually visible and citable to
the exact fixture records that produced it, which an opaque verdict cannot do.

Five finding types are produced, and they are not interchangeable:

``success``          a metric moved in its good direction against the baseline;
``failure``          a metric regressed against the baseline;
``counterevidence``  evidence against promotion that an improved aggregate would
                     otherwise conceal — above all, false merges;
``uncertainty``      the candidate declined to decide, or decided narrowly;
``missing_evidence`` a measurement was not taken at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from runtime.calyx_evolve.metrics import (
    DEFINITIONS_BY_KEY,
    METRIC_ABSTENTION_COUNT,
    METRIC_ACCURACY,
    METRIC_COST,
    METRIC_FALSE_MERGE_COUNT,
    METRIC_MISSED_COUNT,
    METRIC_PROVENANCE,
    METRIC_REPLAY,
    STATE_MEASURED,
    AggregateScore,
    MetricVector,
    compare,
)
from runtime.calyx_evolve.provenance import content_hash
from runtime.calyx_evolve.redaction import assert_inspectable
from runtime.calyx_evolve.safety import SafetyViolation

FINDING_SUCCESS = "success"
FINDING_FAILURE = "failure"
FINDING_COUNTEREVIDENCE = "counterevidence"
FINDING_UNCERTAINTY = "uncertainty"
FINDING_MISSING_EVIDENCE = "missing_evidence"

FINDING_TYPES: frozenset[str] = frozenset(
    {
        FINDING_SUCCESS,
        FINDING_FAILURE,
        FINDING_COUNTEREVIDENCE,
        FINDING_UNCERTAINTY,
        FINDING_MISSING_EVIDENCE,
    }
)

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_BLOCKING = "blocking"

ANALYZER_VERSION = "calyx-evolve-analyzer-1.0.0"

#: Analysis summaries are concise by contract, never a reasoning trace.
SUMMARY_MAX_CHARS = 400


class FindingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Finding:
    run_id: str
    finding_type: str
    code: str
    summary: str
    severity: str = SEVERITY_INFO
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.finding_type not in FINDING_TYPES:
            raise FindingError(f"unknown finding type {self.finding_type!r}")
        if len(self.summary) > SUMMARY_MAX_CHARS:
            raise FindingError(
                f"finding {self.code!r} summary exceeds {SUMMARY_MAX_CHARS} characters; "
                "record a concise conclusion, not a reasoning trace"
            )
        assert_inspectable({"summary": self.summary, "evidence": dict(self.evidence)})

    @property
    def finding_id(self) -> str:
        return content_hash(
            {
                "run_id": self.run_id,
                "finding_type": self.finding_type,
                "code": self.code,
                "evidence": dict(self.evidence),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "run_id": self.run_id,
            "finding_type": self.finding_type,
            "code": self.code,
            "summary": self.summary,
            "severity": self.severity,
            "evidence": dict(self.evidence),
            "analyzer_version": ANALYZER_VERSION,
        }


def analyze(
    *,
    run_id: str,
    candidate_metrics: MetricVector,
    baseline_metrics: MetricVector | None,
    candidate_score: AggregateScore,
    baseline_score: AggregateScore | None,
    violations: tuple[SafetyViolation, ...] = (),
) -> tuple[Finding, ...]:
    """Produce the full finding set for one analysed run."""

    findings: list[Finding] = []
    mapping = candidate_metrics.as_mapping()

    # --- counterevidence: false merges are never absorbed by the score -------
    false_merge = mapping.get(METRIC_FALSE_MERGE_COUNT)
    if false_merge is not None and false_merge.is_measured and false_merge.numeric() > 0:
        aggregate_moved = (
            candidate_score.state == STATE_MEASURED
            and baseline_score is not None
            and baseline_score.state == STATE_MEASURED
            and candidate_score.value is not None
            and baseline_score.value is not None
            and candidate_score.value > baseline_score.value
        )
        summary = (
            f"{int(false_merge.numeric())} record(s) were merged into the wrong taxon"
        )
        if aggregate_moved:
            summary += " even though the aggregate score improved over the baseline"
        findings.append(
            Finding(
                run_id=run_id,
                finding_type=FINDING_COUNTEREVIDENCE,
                code="FALSE_MERGE_PRESENT",
                summary=summary + "; promotion is blocked.",
                severity=SEVERITY_BLOCKING,
                evidence={
                    "false_merge_records": list(candidate_metrics.false_merge_records),
                    "aggregate_improved": bool(aggregate_moved),
                    "candidate_score": candidate_score.value,
                    "baseline_score": baseline_score.value if baseline_score else None,
                },
            )
        )

    for violation in violations:
        findings.append(
            Finding(
                run_id=run_id,
                finding_type=FINDING_COUNTEREVIDENCE,
                code=violation.code,
                summary=violation.detail,
                severity=SEVERITY_BLOCKING,
                evidence=violation.to_dict(),
            )
        )

    # --- success / failure against the locked baseline -----------------------
    if baseline_metrics is not None:
        for row in compare(candidate_metrics, baseline_metrics):
            if not row["comparison_reportable"]:
                continue
            if row["assessment"] == "improved":
                findings.append(
                    Finding(
                        run_id=run_id,
                        finding_type=FINDING_SUCCESS,
                        code=f"IMPROVED_{row['metric'].upper()}",
                        summary=f"{row['label']} improved by {row['delta']} against the locked baseline.",
                        evidence={
                            "metric": row["metric"],
                            "delta": row["delta"],
                            "baseline": row["baseline"],
                            "candidate": row["candidate"],
                        },
                    )
                )
            elif row["assessment"] == "regressed":
                findings.append(
                    Finding(
                        run_id=run_id,
                        finding_type=FINDING_FAILURE,
                        code=f"REGRESSED_{row['metric'].upper()}",
                        summary=f"{row['label']} regressed by {row['delta']} against the locked baseline.",
                        severity=SEVERITY_WARNING,
                        evidence={
                            "metric": row["metric"],
                            "delta": row["delta"],
                            "baseline": row["baseline"],
                            "candidate": row["candidate"],
                        },
                    )
                )

    # --- failure: measured but below an absolute requirement ----------------
    provenance = mapping.get(METRIC_PROVENANCE)
    if provenance is not None and provenance.is_measured and provenance.numeric() < 1.0:
        findings.append(
            Finding(
                run_id=run_id,
                finding_type=FINDING_FAILURE,
                code="INCOMPLETE_PROVENANCE",
                summary=(
                    f"Provenance completeness is {provenance.numeric():.4f}; "
                    "every taxonomic claim must carry complete provenance."
                ),
                severity=SEVERITY_BLOCKING,
                evidence={"metric": METRIC_PROVENANCE, "value": provenance.value},
            )
        )

    replay = mapping.get(METRIC_REPLAY)
    if replay is not None and replay.is_measured and replay.numeric() < 1.0:
        findings.append(
            Finding(
                run_id=run_id,
                finding_type=FINDING_FAILURE,
                code="NONDETERMINISTIC_REPLAY",
                summary="Re-executing the candidate produced a different artifact digest.",
                severity=SEVERITY_BLOCKING,
                evidence={"metric": METRIC_REPLAY, "value": replay.value},
            )
        )

    # --- uncertainty ---------------------------------------------------------
    abstentions = mapping.get(METRIC_ABSTENTION_COUNT)
    if abstentions is not None and abstentions.is_measured and abstentions.numeric() > 0:
        findings.append(
            Finding(
                run_id=run_id,
                finding_type=FINDING_UNCERTAINTY,
                code="RECORDS_LEFT_UNRESOLVED",
                summary=(
                    f"{int(abstentions.numeric())} record(s) were left unresolved; "
                    "abstention is preferred to a speculative merge but leaves the "
                    "reconciliation incomplete."
                ),
                severity=SEVERITY_INFO,
                evidence={"metric": METRIC_ABSTENTION_COUNT, "value": abstentions.value},
            )
        )

    missed = mapping.get(METRIC_MISSED_COUNT)
    if missed is not None and missed.is_measured and missed.numeric() > 0:
        findings.append(
            Finding(
                run_id=run_id,
                finding_type=FINDING_UNCERTAINTY,
                code="EXPECTED_RESOLUTIONS_MISSED",
                summary=(
                    f"{int(missed.numeric())} record(s) with a locked expected accepted "
                    "name were abstained on rather than resolved."
                ),
                severity=SEVERITY_WARNING,
                evidence={
                    "metric": METRIC_MISSED_COUNT,
                    "records": list(candidate_metrics.missed_records),
                },
            )
        )

    # --- missing evidence ----------------------------------------------------
    for key in candidate_metrics.unavailable_keys():
        definition = DEFINITIONS_BY_KEY.get(key)
        value = mapping[key]
        findings.append(
            Finding(
                run_id=run_id,
                finding_type=FINDING_MISSING_EVIDENCE,
                code=f"UNAVAILABLE_{key.upper()}",
                summary=(
                    f"{definition.label if definition else key} was not measured: {value.basis}. "
                    "It is recorded as unavailable, not as zero."
                ),
                severity=SEVERITY_BLOCKING if key in (METRIC_ACCURACY, METRIC_PROVENANCE) else SEVERITY_WARNING,
                evidence={"metric": key, "state": value.state, "basis": value.basis},
            )
        )

    if candidate_score.state != STATE_MEASURED:
        findings.append(
            Finding(
                run_id=run_id,
                finding_type=FINDING_MISSING_EVIDENCE,
                code="UNAVAILABLE_AGGREGATE_SCORE",
                summary=f"Aggregate score is unavailable: {candidate_score.basis}",
                severity=SEVERITY_BLOCKING,
                evidence={"basis": candidate_score.basis},
            )
        )

    return tuple(findings)


def blocking_findings(findings: tuple[Finding, ...]) -> tuple[Finding, ...]:
    return tuple(f for f in findings if f.severity == SEVERITY_BLOCKING)


def summarise(findings: tuple[Finding, ...]) -> dict[str, int]:
    counts = {finding_type: 0 for finding_type in sorted(FINDING_TYPES)}
    for finding in findings:
        counts[finding.finding_type] += 1
    return counts


#: Metrics referenced above but re-exported for operator surfaces.
__all__ = [
    "ANALYZER_VERSION",
    "FINDING_COUNTEREVIDENCE",
    "FINDING_FAILURE",
    "FINDING_MISSING_EVIDENCE",
    "FINDING_SUCCESS",
    "FINDING_TYPES",
    "FINDING_UNCERTAINTY",
    "METRIC_COST",
    "SEVERITY_BLOCKING",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "Finding",
    "analyze",
    "blocking_findings",
    "summarise",
]
