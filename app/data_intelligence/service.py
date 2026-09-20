from __future__ import annotations

import hashlib
import html
import json
import math
import platform
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import fmean
from typing import Any

from .models import AnalysisOperation, AnalysisPlan, ChartSpec, DataIntelligenceError
from .repository import DatasetVersion, FileDatasetRepository

EXECUTOR_VERSION = "calyx-data-001.1"
PROFILE_SCHEMA_VERSION = "calyx-data-profile-001.1"


@dataclass
class DataLimits:
    max_rows: int = 50_000
    max_columns: int = 200
    max_output_rows: int = 5_000
    max_operations: int = 25


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _coerce_number(value: Any) -> float | None:
    if _missing(value) or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _infer_type(values: list[Any]) -> str:
    present = [value for value in values if not _missing(value)]
    if not present:
        return "empty"
    lowered = {str(value).strip().casefold() for value in present}
    if lowered <= {"true", "false", "yes", "no", "0", "1"}:
        return "boolean"
    if all(re.fullmatch(r"[-+]?\d+", str(value).strip()) for value in present):
        return "integer"
    if all(_coerce_number(value) is not None for value in present):
        return "number"
    return "text"


def _canonical_rows(rows: list[dict[str, Any]]) -> bytes:
    return json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _aggregate(values: list[Any], function: str) -> Any:
    if function == "count":
        return len([value for value in values if not _missing(value)])
    numeric = [
        number
        for value in values
        if (number := _coerce_number(value)) is not None
    ]
    if not numeric:
        raise DataIntelligenceError(
            "AGGREGATION_REQUIRES_NUMERIC_VALUES", {"function": function}
        )
    if function == "sum":
        return sum(numeric)
    if function == "mean":
        return fmean(numeric)
    if function == "min":
        return min(numeric)
    if function == "max":
        return max(numeric)
    raise DataIntelligenceError("UNSUPPORTED_AGGREGATION", {"function": function})


def _sort_key(value: Any) -> tuple[int, Any]:
    if _missing(value):
        return (2, "")
    numeric = _coerce_number(value)
    if numeric is not None:
        return (0, numeric)
    return (1, str(value).casefold())


class DataIntelligenceService:
    """Bounded typed-plan analysis; arbitrary user code is never executed."""

    def __init__(
        self,
        repository: FileDatasetRepository,
        limits: DataLimits | None = None,
    ) -> None:
        self.repository = repository
        self.limits = limits or DataLimits()

    def ingest(
        self,
        *,
        owner: str,
        project_id: str,
        logical_name: str,
        filename: str,
        data: bytes,
    ) -> dict[str, Any]:
        metadata, created = self.repository.ingest(
            owner=owner,
            project_id=project_id,
            logical_name=logical_name,
            filename=filename,
            data=data,
        )
        profile = self.profile(
            owner=owner,
            project_id=project_id,
            dataset=metadata,
        )
        return {
            "created": created,
            "dataset": metadata.to_dict(),
            "profile": profile,
        }

    def profile(
        self,
        *,
        owner: str,
        project_id: str,
        dataset: DatasetVersion,
    ) -> dict[str, Any]:
        cached = self.repository.get_profile(
            owner,
            project_id,
            dataset.dataset_id,
            dataset.version_id,
        )
        if cached is not None and cached.get("schema_version") == PROFILE_SCHEMA_VERSION:
            return cached

        columns, rows = self.repository.read_rows(
            owner,
            project_id,
            dataset.dataset_id,
            dataset.version_id,
        )
        self._enforce_input_limits(columns, rows)
        duplicate_count = len(rows) - len(
            {
                tuple(str(row.get(column, "")) for column in columns)
                for row in rows
            }
        )
        column_profiles: list[dict[str, Any]] = []
        warnings: list[str] = []
        for column in columns:
            values = [row.get(column) for row in rows]
            missing_count = sum(1 for value in values if _missing(value))
            inferred = _infer_type(values)
            present = [value for value in values if not _missing(value)]
            column_profile: dict[str, Any] = {
                "name": column,
                "type": inferred,
                "missing_count": missing_count,
                "missing_fraction": (
                    (missing_count / len(rows)) if rows else 0.0
                ),
                "unique_count": len({str(value) for value in present}),
            }
            numeric = [
                number
                for value in present
                if (number := _coerce_number(value)) is not None
            ]
            if inferred in {"integer", "number"} and numeric:
                column_profile["min"] = min(numeric)
                column_profile["max"] = max(numeric)
                column_profile["mean"] = fmean(numeric)
            if rows and missing_count / len(rows) > 0.5:
                warnings.append(f"HIGH_MISSINGNESS:{column}")
            if present and len({str(value) for value in present}) == 1:
                warnings.append(f"CONSTANT_COLUMN:{column}")
            column_profiles.append(column_profile)

        stable: dict[str, Any] = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "dataset_id": dataset.dataset_id,
            "version_id": dataset.version_id,
            "content_hash": dataset.content_hash,
            "row_count": len(rows),
            "column_count": len(columns),
            "duplicate_row_count": duplicate_count,
            "columns": column_profiles,
            "anomalies": sorted(set(warnings)),
        }
        stable["profile_fingerprint"] = hashlib.sha256(
            json.dumps(
                stable,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        self.repository.save_profile(
            owner,
            project_id,
            dataset.dataset_id,
            dataset.version_id,
            stable,
        )
        return stable

    def compile_intent(
        self,
        *,
        dataset_id: str,
        version_id: str,
        intent: str,
    ) -> AnalysisPlan:
        raw = intent.strip()
        lowered = raw.casefold()
        operations: list[AnalysisOperation] = []
        chart: ChartSpec | None = None

        grouped = re.search(
            r"\b(?:average|mean|sum|max|min)\s+"
            r"([A-Za-z0-9_.-]+)\s+by\s+([A-Za-z0-9_.-]+)",
            lowered,
        )
        if grouped:
            first_word = grouped.group(0).split()[0]
            function = "mean" if first_word == "average" else first_word
            value_column, group_column = grouped.group(1), grouped.group(2)
            operations.append(
                AnalysisOperation(
                    kind="group_aggregate",
                    group_by=[group_column],
                    aggregate_column=value_column,
                    aggregate_function=function,
                )
            )
            if any(token in lowered for token in ("chart", "plot", "graph")):
                chart = ChartSpec(
                    x=group_column,
                    y=f"{function}_{value_column}",
                    title=raw,
                )
        else:
            count = re.search(r"\bcount\s+by\s+([A-Za-z0-9_.-]+)", lowered)
            sort = re.search(
                r"\bsort\s+by\s+([A-Za-z0-9_.-]+)"
                r"(?:\s+(desc|descending))?",
                lowered,
            )
            select = re.search(r"\bselect\s+(.+)$", lowered)
            if count:
                group_column = count.group(1)
                operations.append(
                    AnalysisOperation(
                        kind="group_aggregate",
                        group_by=[group_column],
                        aggregate_function="count",
                    )
                )
                if any(token in lowered for token in ("chart", "plot", "graph")):
                    chart = ChartSpec(
                        x=group_column,
                        y="count",
                        title=raw,
                    )
            elif sort:
                operations.append(
                    AnalysisOperation(
                        kind="sort",
                        column=sort.group(1),
                        descending=bool(sort.group(2)),
                    )
                )
            elif select:
                columns = [
                    part.strip()
                    for part in re.split(r"[, ]+", select.group(1))
                    if part.strip()
                ]
                operations.append(
                    AnalysisOperation(kind="select", columns=columns)
                )
            else:
                raise DataIntelligenceError(
                    "INTENT_NOT_SUPPORTED",
                    {
                        "supported_examples": [
                            "mean height by genus",
                            "count by genus",
                            "sort by height desc",
                            "select genus,height",
                        ]
                    },
                )

        return AnalysisPlan(
            dataset={"dataset_id": dataset_id, "version_id": version_id},
            intent=raw,
            operations=operations,
            chart=chart,
            seed=0,
        )

    def execute(
        self,
        *,
        owner: str,
        project_id: str,
        plan: AnalysisPlan,
    ) -> dict[str, Any]:
        if len(plan.operations) > self.limits.max_operations:
            raise DataIntelligenceError("OPERATION_LIMIT_EXCEEDED")

        dataset = self.repository.get(
            owner,
            project_id,
            plan.dataset.dataset_id,
            plan.dataset.version_id,
        )
        columns, rows = self.repository.read_rows(
            owner,
            project_id,
            dataset.dataset_id,
            dataset.version_id,
        )
        self._enforce_input_limits(columns, rows)
        current = [dict(row) for row in rows]
        for operation in plan.operations:
            current = self._apply(owner, project_id, current, operation)
            if len(current) > self.limits.max_output_rows:
                raise DataIntelligenceError(
                    "OUTPUT_ROW_LIMIT_EXCEEDED",
                    {"limit": self.limits.max_output_rows},
                )

        table_bytes = _canonical_rows(current)
        chart_bytes = self._chart(current, plan.chart) if plan.chart else None
        identity_payload = (
            f"{owner}\x1f{project_id}\x1f{EXECUTOR_VERSION}\x1f"
            f"{plan.fingerprint}"
        ).encode("utf-8")
        analysis_id = hashlib.sha256(identity_payload).hexdigest()[:40]
        stable_manifest: dict[str, Any] = {
            "schema_version": EXECUTOR_VERSION,
            "analysis_id": analysis_id,
            "dataset": dataset.to_dict(),
            "plan": plan.canonical_payload(),
            "plan_fingerprint": plan.fingerprint,
            "sandbox": {
                "executor": "calyx-typed-interpreter",
                "executor_version": EXECUTOR_VERSION,
                "arbitrary_code_execution": False,
                "network_access": False,
                "restricted_to_dataset_scope": True,
                "max_rows": self.limits.max_rows,
                "max_columns": self.limits.max_columns,
                "max_output_rows": self.limits.max_output_rows,
                "max_operations": self.limits.max_operations,
                "python_version": platform.python_version(),
            },
            "assumptions": [
                "Typed-plan execution only; unrestricted Python and SQL are rejected."
            ],
            "warnings": [],
            "review_state": "unreviewed",
            "reasoning_reference": {
                "source_kind": "dataset",
                "source_id": dataset.version_id,
                "dataset_id": dataset.dataset_id,
                "execution_id": analysis_id,
                "content_hash": dataset.content_hash,
                "extra": {
                    "project_id": project_id,
                    "plan_fingerprint": plan.fingerprint,
                    "executor_version": EXECUTOR_VERSION,
                },
            },
        }
        stable_manifest["manifest_fingerprint"] = hashlib.sha256(
            json.dumps(
                stable_manifest,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        manifest = {
            **stable_manifest,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }
        artifacts = self.repository.save_analysis(
            owner=owner,
            project_id=project_id,
            dataset_id=dataset.dataset_id,
            version_id=dataset.version_id,
            analysis_id=analysis_id,
            manifest=manifest,
            table_bytes=table_bytes,
            chart_bytes=chart_bytes,
        )
        return {
            **manifest,
            "artifact_hashes": artifacts,
            "row_count": len(current),
        }

    def rerun(
        self,
        *,
        owner: str,
        project_id: str,
        dataset_id: str,
        version_id: str,
        analysis_id: str,
    ) -> dict[str, Any]:
        previous = self.repository.get_analysis(
            owner,
            project_id,
            dataset_id,
            version_id,
            analysis_id,
        )
        plan = AnalysisPlan.model_validate(previous["plan"])
        current = self.execute(owner=owner, project_id=project_id, plan=plan)
        if current["analysis_id"] != analysis_id:
            raise DataIntelligenceError("ANALYSIS_ID_DRIFT")
        old_hashes = previous.get("artifact_hashes", {})
        new_hashes = current.get("artifact_hashes", {})
        return {
            "analysis_id": analysis_id,
            "equivalent_artifacts": old_hashes == new_hashes,
            "previous_artifact_hashes": old_hashes,
            "current_artifact_hashes": new_hashes,
            "manifest_fingerprint": current["manifest_fingerprint"],
        }

    def _enforce_input_limits(
        self,
        columns: list[str],
        rows: list[dict[str, Any]],
    ) -> None:
        if len(columns) > self.limits.max_columns:
            raise DataIntelligenceError(
                "COLUMN_LIMIT_EXCEEDED", {"limit": self.limits.max_columns}
            )
        if len(rows) > self.limits.max_rows:
            raise DataIntelligenceError(
                "ROW_LIMIT_EXCEEDED", {"limit": self.limits.max_rows}
            )

    @staticmethod
    def _require_columns(
        rows: list[dict[str, Any]],
        columns: list[str],
    ) -> None:
        available = set(rows[0]) if rows else set(columns)
        missing = [column for column in columns if column not in available]
        if missing:
            raise DataIntelligenceError("COLUMN_NOT_FOUND", {"columns": missing})

    def _apply(
        self,
        owner: str,
        project_id: str,
        rows: list[dict[str, Any]],
        operation: AnalysisOperation,
    ) -> list[dict[str, Any]]:
        if operation.kind == "select":
            self._require_columns(rows, operation.columns)
            return [
                {column: row.get(column) for column in operation.columns}
                for row in rows
            ]

        if operation.kind == "filter_equals":
            column = operation.column or ""
            self._require_columns(rows, [column])
            target = str(operation.value)
            return [row for row in rows if str(row.get(column)) == target]

        if operation.kind == "sort":
            column = operation.column or ""
            self._require_columns(rows, [column])
            return sorted(
                rows,
                key=lambda row: _sort_key(row.get(column)),
                reverse=operation.descending,
            )

        if operation.kind == "limit":
            return rows[: operation.limit]

        if operation.kind == "aggregate":
            column = operation.aggregate_column
            values = [row.get(column) for row in rows] if column else [1] * len(rows)
            label = (
                "count"
                if operation.aggregate_function == "count" and not column
                else f"{operation.aggregate_function}_{column}"
            )
            return [
                {
                    label: _aggregate(
                        values,
                        operation.aggregate_function or "count",
                    )
                }
            ]

        if operation.kind == "group_aggregate":
            required = [
                *operation.group_by,
                *(
                    [operation.aggregate_column]
                    if operation.aggregate_column
                    else []
                ),
            ]
            self._require_columns(rows, required)
            groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                key = tuple(str(row.get(column, "")) for column in operation.group_by)
                groups[key].append(row)
            label = (
                "count"
                if operation.aggregate_function == "count"
                and not operation.aggregate_column
                else f"{operation.aggregate_function}_{operation.aggregate_column}"
            )
            output: list[dict[str, Any]] = []
            for key in sorted(groups):
                group_rows = groups[key]
                values = (
                    [row.get(operation.aggregate_column) for row in group_rows]
                    if operation.aggregate_column
                    else [1] * len(group_rows)
                )
                output.append(
                    {
                        **dict(zip(operation.group_by, key, strict=True)),
                        label: _aggregate(
                            values,
                            operation.aggregate_function or "count",
                        ),
                    }
                )
            return output

        if operation.kind == "pivot":
            index = operation.pivot_index or ""
            pivot_column = operation.pivot_columns or ""
            required = [index, pivot_column]
            if operation.aggregate_column:
                required.append(operation.aggregate_column)
            self._require_columns(rows, required)
            buckets: dict[tuple[str, str], list[Any]] = defaultdict(list)
            pivot_values: set[str] = set()
            for row in rows:
                left = str(row.get(index, ""))
                top = str(row.get(pivot_column, ""))
                pivot_values.add(top)
                value = (
                    row.get(operation.aggregate_column)
                    if operation.aggregate_column
                    else 1
                )
                buckets[(left, top)].append(value)
            output: list[dict[str, Any]] = []
            for left in sorted({key[0] for key in buckets}):
                result_row: dict[str, Any] = {index: left}
                for top in sorted(pivot_values):
                    values = buckets.get((left, top), [])
                    result_row[top] = (
                        _aggregate(
                            values,
                            operation.aggregate_function or "count",
                        )
                        if values
                        else 0
                    )
                output.append(result_row)
            return output

        if operation.kind == "join":
            other = operation.other_dataset
            if other is None:
                raise DataIntelligenceError("JOIN_DATASET_REQUIRED")
            right_columns, right_rows = self.repository.read_rows(
                owner,
                project_id,
                other.dataset_id,
                other.version_id,
            )
            self._enforce_input_limits(right_columns, right_rows)
            left_on = operation.left_on or ""
            right_on = operation.right_on or ""
            self._require_columns(rows, [left_on])
            self._require_columns(right_rows, [right_on])
            index: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in right_rows:
                index[str(row.get(right_on))].append(row)
            output: list[dict[str, Any]] = []
            for left in rows:
                matches = index.get(str(left.get(left_on)), [])
                if not matches and operation.join_how == "left":
                    output.append(dict(left))
                for right in matches:
                    merged = dict(left)
                    for key, value in right.items():
                        target = key if key not in merged else f"right.{key}"
                        merged[target] = value
                    output.append(merged)
                    if len(output) > self.limits.max_output_rows:
                        raise DataIntelligenceError(
                            "OUTPUT_ROW_LIMIT_EXCEEDED",
                            {"limit": self.limits.max_output_rows},
                        )
            return output

        raise DataIntelligenceError(
            "UNSUPPORTED_OPERATION", {"kind": operation.kind}
        )

    @staticmethod
    def _chart(rows: list[dict[str, Any]], chart: ChartSpec) -> bytes:
        if not rows:
            raise DataIntelligenceError("CHART_REQUIRES_ROWS")
        if chart.x not in rows[0] or chart.y not in rows[0]:
            raise DataIntelligenceError("CHART_COLUMN_NOT_FOUND")

        points: list[tuple[str, float]] = []
        for row in rows[:20]:
            number = _coerce_number(row.get(chart.y))
            if number is None or not math.isfinite(number):
                raise DataIntelligenceError("CHART_Y_MUST_BE_NUMERIC")
            points.append((str(row.get(chart.x, "")), number))

        max_value = max((abs(value) for _, value in points), default=1.0) or 1.0
        width = 800
        height = 420
        margin = 50
        usable = width - margin * 2
        bar_width = max(8, usable // max(1, len(points)))
        bars: list[str] = []
        for index, (label, value) in enumerate(points):
            x = margin + index * bar_width
            bar_height = int((abs(value) / max_value) * 280)
            y = 340 - bar_height
            bars.append(
                f'<rect x="{x}" y="{y}" width="{max(4, bar_width - 4)}" '
                f'height="{bar_height}" />'
            )
            escaped = html.escape(label)
            bars.append(
                f'<text x="{x}" y="365" font-size="10" '
                f'transform="rotate(35 {x} 365)">{escaped}</text>'
            )

        title = html.escape(chart.title or f"{chart.y} by {chart.x}")
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">'
            f'<text x="{margin}" y="28" font-size="18">{title}</text>'
            f'<line x1="{margin}" y1="340" x2="{width - margin}" y2="340" '
            'stroke="currentColor" />'
            + "".join(bars)
            + "</svg>"
        )
        return svg.encode("utf-8")
