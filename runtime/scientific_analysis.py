"""Governed Scientific Computing & Analysis Engine for CALYX issue #617.

This first slice intentionally exposes a small, deterministic method registry instead of
arbitrary code execution. Every result is content-addressed and preserves dataset,
method, parameter, missingness, diagnostic, and output provenance.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from statistics import fmean, median, stdev
from typing import Any

from runtime.research_station import ResearchStationService

ANALYSIS_SCHEMA_VERSION = "calyx-scientific-analysis/v1"
MAX_ROWS = 10_000
MAX_COLUMNS = 100
MISSING_POLICIES = {"complete_case"}

METHOD_REGISTRY: dict[str, dict[str, Any]] = {
    "describe.v1": {
        "name": "Descriptive statistics",
        "family": "descriptive",
        "version": "1.0.0",
        "parameters": {"columns": "non-empty list[str]"},
        "outputs": ["n", "missing", "mean", "median", "sample_sd", "min", "max"],
        "assumptions": ["Selected columns are numeric after missing-value removal."],
        "inferential": False,
    },
    "pearson.v1": {
        "name": "Pearson product-moment correlation",
        "family": "correlation",
        "version": "1.0.0",
        "parameters": {"x": "column name", "y": "column name"},
        "outputs": ["n", "r", "r_squared"],
        "assumptions": [
            "Relationship is approximately linear for inferential interpretation.",
            "Observations are appropriately independent for the intended interpretation.",
            "Extreme outliers can materially affect the coefficient.",
        ],
        "inferential": False,
    },
    "ols.v1": {
        "name": "Simple ordinary least-squares regression",
        "family": "regression",
        "version": "1.0.0",
        "parameters": {"x": "predictor column name", "y": "response column name"},
        "outputs": ["n", "intercept", "slope", "r_squared", "residual_standard_error"],
        "assumptions": [
            "Mean relationship between predictor and response is approximately linear.",
            "Observations are appropriately independent for the intended interpretation.",
            "Residual variance is approximately constant for classical inference.",
            "Residual normality is relevant only to inferential procedures not implemented here.",
        ],
        "inferential": False,
    },
}


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(payload: Any) -> str:
    material = payload if isinstance(payload, str) else _stable(payload)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _finite_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise TypeError("ANALYSIS_BOOLEAN_NOT_NUMERIC")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("ANALYSIS_NON_NUMERIC_VALUE") from exc
    if not math.isfinite(number):
        raise ValueError("ANALYSIS_NON_FINITE_VALUE")
    return number


class ScientificAnalysisService:
    def __init__(self, research: ResearchStationService | None = None) -> None:
        self.research = research or ResearchStationService()

    @staticmethod
    def capabilities() -> dict[str, Any]:
        return {
            "schema_version": ANALYSIS_SCHEMA_VERSION,
            "engine": "orchid-continuum-scientific-computing",
            "execution_mode": "governed_deterministic_methods_only",
            "max_rows": MAX_ROWS,
            "max_columns": MAX_COLUMNS,
            "missing_policies": sorted(MISSING_POLICIES),
            "methods": METHOD_REGISTRY,
            "arbitrary_code_execution": False,
            "autonomous_model_selection": False,
            "autonomous_scientific_publication": False,
            "knowledge_graph_mutation_authorized": False,
        }

    def _project_root(self, owner_id: str, project_id: str) -> Path:
        root, _project = self.research._project(owner_id, project_id)
        return root

    @staticmethod
    def _validate_rows(rows: Any) -> tuple[list[dict[str, Any]], list[str]]:
        if not isinstance(rows, list) or not rows:
            raise ValueError("ANALYSIS_ROWS_REQUIRED")
        if len(rows) > MAX_ROWS:
            raise ValueError("ANALYSIS_ROW_LIMIT_EXCEEDED")
        if not all(isinstance(row, dict) for row in rows):
            raise ValueError("ANALYSIS_ROWS_MUST_BE_OBJECTS")
        columns = sorted({str(key) for row in rows for key in row})
        if not columns or len(columns) > MAX_COLUMNS:
            raise ValueError("ANALYSIS_COLUMN_LIMIT_INVALID")
        normalized = [{str(key): value for key, value in row.items()} for row in rows]
        return normalized, columns

    @staticmethod
    def _validate_method(method: str, parameters: Any) -> tuple[str, dict[str, Any]]:
        method = str(method or "").strip()
        if method not in METHOD_REGISTRY:
            raise ValueError("ANALYSIS_METHOD_UNSUPPORTED")
        if not isinstance(parameters, dict):
            raise TypeError("ANALYSIS_PARAMETERS_INVALID")
        params = dict(parameters)
        if method == "describe.v1":
            columns = params.get("columns")
            if not isinstance(columns, list) or not columns or not all(str(c).strip() for c in columns):
                raise ValueError("ANALYSIS_DESCRIBE_COLUMNS_REQUIRED")
            params = {"columns": [str(c).strip() for c in columns]}
        else:
            x = str(params.get("x") or "").strip()
            y = str(params.get("y") or "").strip()
            if not x or not y or x == y:
                raise ValueError("ANALYSIS_X_Y_REQUIRED")
            params = {"x": x, "y": y}
        return method, params

    def validate(self, owner_id: str, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._project_root(owner_id, project_id)
        method, parameters = self._validate_method(payload.get("method"), payload.get("parameters"))
        rows, available_columns = self._validate_rows(payload.get("rows"))
        missing_policy = str(payload.get("missing_policy") or "complete_case").strip().casefold()
        if missing_policy not in MISSING_POLICIES:
            raise ValueError("ANALYSIS_MISSING_POLICY_UNSUPPORTED")
        requested = parameters["columns"] if method == "describe.v1" else [parameters["x"], parameters["y"]]
        missing_columns = [column for column in requested if column not in available_columns]
        if missing_columns:
            raise ValueError(f"ANALYSIS_COLUMNS_NOT_FOUND:{','.join(missing_columns)}")
        provenance = payload.get("provenance")
        if not isinstance(provenance, dict) or not provenance:
            raise ValueError("ANALYSIS_PROVENANCE_REQUIRED")
        dataset_ref = payload.get("dataset_ref")
        if dataset_ref is not None and not isinstance(dataset_ref, dict):
            raise ValueError("ANALYSIS_DATASET_REF_INVALID")
        canonical_input = {
            "project_id": project_id,
            "method": method,
            "method_version": METHOD_REGISTRY[method]["version"],
            "parameters": parameters,
            "missing_policy": missing_policy,
            "rows": rows,
            "provenance": provenance,
            "dataset_ref": dataset_ref or None,
        }
        return {
            "valid": True,
            "method": method,
            "method_spec": METHOD_REGISTRY[method],
            "parameters": parameters,
            "available_columns": available_columns,
            "row_count": len(rows),
            "missing_policy": missing_policy,
            "input_sha256": _sha(canonical_input),
            "canonical_input": canonical_input,
        }

    @staticmethod
    def _column(rows: list[dict[str, Any]], name: str) -> tuple[list[float], int]:
        values: list[float] = []
        missing = 0
        for row in rows:
            value = _finite_number(row.get(name))
            if value is None:
                missing += 1
            else:
                values.append(value)
        return values, missing

    @staticmethod
    def _pairs(rows: list[dict[str, Any]], x_name: str, y_name: str) -> tuple[list[tuple[float, float]], int]:
        pairs: list[tuple[float, float]] = []
        dropped = 0
        for row in rows:
            x = _finite_number(row.get(x_name))
            y = _finite_number(row.get(y_name))
            if x is None or y is None:
                dropped += 1
                continue
            pairs.append((x, y))
        return pairs, dropped

    @staticmethod
    def _describe(rows: list[dict[str, Any]], columns: list[str]) -> tuple[dict[str, Any], list[str], int]:
        output: dict[str, Any] = {}
        warnings: list[str] = []
        total_missing = 0
        for column in columns:
            values, missing = ScientificAnalysisService._column(rows, column)
            total_missing += missing
            if not values:
                raise ValueError(f"ANALYSIS_NO_COMPLETE_VALUES:{column}")
            output[column] = {
                "n": len(values),
                "missing": missing,
                "mean": fmean(values),
                "median": median(values),
                "sample_sd": stdev(values) if len(values) >= 2 else None,
                "min": min(values),
                "max": max(values),
            }
            if len(values) < 3:
                warnings.append(f"{column}: fewer than 3 complete observations")
        return {"columns": output}, warnings, total_missing

    @staticmethod
    def _pearson(pairs: list[tuple[float, float]]) -> tuple[dict[str, Any], list[str]]:
        if len(pairs) < 2:
            raise ValueError("ANALYSIS_PEARSON_REQUIRES_TWO_COMPLETE_PAIRS")
        xs = [pair[0] for pair in pairs]
        ys = [pair[1] for pair in pairs]
        mx, my = fmean(xs), fmean(ys)
        sx = sum((x - mx) ** 2 for x in xs)
        sy = sum((y - my) ** 2 for y in ys)
        if sx == 0 or sy == 0:
            raise ValueError("ANALYSIS_PEARSON_ZERO_VARIANCE")
        cross = sum((x - mx) * (y - my) for x, y in pairs)
        r = cross / math.sqrt(sx * sy)
        r = max(-1.0, min(1.0, r))
        warnings = ["Fewer than 3 complete pairs; correlation is extremely unstable."] if len(pairs) < 3 else []
        return {"n": len(pairs), "r": r, "r_squared": r * r}, warnings

    @staticmethod
    def _ols(pairs: list[tuple[float, float]]) -> tuple[dict[str, Any], list[str]]:
        if len(pairs) < 2:
            raise ValueError("ANALYSIS_OLS_REQUIRES_TWO_COMPLETE_PAIRS")
        xs = [pair[0] for pair in pairs]
        ys = [pair[1] for pair in pairs]
        mx, my = fmean(xs), fmean(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx == 0:
            raise ValueError("ANALYSIS_OLS_ZERO_PREDICTOR_VARIANCE")
        sxy = sum((x - mx) * (y - my) for x, y in pairs)
        slope = sxy / sxx
        intercept = my - slope * mx
        fitted = [intercept + slope * x for x in xs]
        residuals = [y - yhat for y, yhat in zip(ys, fitted)]
        sse = sum(value * value for value in residuals)
        sst = sum((y - my) ** 2 for y in ys)
        r_squared = None if sst == 0 else 1.0 - (sse / sst)
        residual_se = math.sqrt(sse / (len(pairs) - 2)) if len(pairs) > 2 else None
        warnings: list[str] = []
        if len(pairs) < 3:
            warnings.append("Fewer than 3 complete pairs; residual variance cannot be estimated.")
        return {
            "n": len(pairs),
            "intercept": intercept,
            "slope": slope,
            "r_squared": r_squared,
            "residual_standard_error": residual_se,
        }, warnings

    def execute(self, owner_id: str, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        validation = self.validate(owner_id, project_id, payload)
        canonical = validation["canonical_input"]
        method = validation["method"]
        rows = canonical["rows"]
        parameters = validation["parameters"]
        dropped = 0
        if method == "describe.v1":
            result, warnings, dropped = self._describe(rows, parameters["columns"])
        elif method == "pearson.v1":
            pairs, dropped = self._pairs(rows, parameters["x"], parameters["y"])
            result, warnings = self._pearson(pairs)
        elif method == "ols.v1":
            pairs, dropped = self._pairs(rows, parameters["x"], parameters["y"])
            result, warnings = self._ols(pairs)
        else:  # pragma: no cover - registry validation is fail-closed
            raise ValueError("ANALYSIS_METHOD_UNSUPPORTED")

        result_sha = _sha(result)
        identity_material = {
            "input_sha256": validation["input_sha256"],
            "result_sha256": result_sha,
            "schema_version": ANALYSIS_SCHEMA_VERSION,
        }
        analysis_id = f"analysis-{_sha(identity_material)[:24]}"
        record = {
            "schema_version": ANALYSIS_SCHEMA_VERSION,
            "analysis_id": analysis_id,
            "project_id": project_id,
            "method": method,
            "method_name": METHOD_REGISTRY[method]["name"],
            "method_version": METHOD_REGISTRY[method]["version"],
            "parameters": parameters,
            "missing_policy": validation["missing_policy"],
            "rows_received": validation["row_count"],
            "rows_or_values_dropped_for_missingness": dropped,
            "input_sha256": validation["input_sha256"],
            "result_sha256": result_sha,
            "dataset_ref": canonical["dataset_ref"],
            "provenance": canonical["provenance"],
            "assumptions": list(METHOD_REGISTRY[method]["assumptions"]),
            "warnings": warnings,
            "result": result,
            "computed_output": True,
            "interpretation_generated": False,
            "human_review_required_for_scientific_conclusion": True,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "arbitrary_code_execution": False,
            "reproducibility": {
                "engine_schema_version": ANALYSIS_SCHEMA_VERSION,
                "method": method,
                "method_version": METHOD_REGISTRY[method]["version"],
                "input_sha256": validation["input_sha256"],
                "result_sha256": result_sha,
                "deterministic_replay": True,
            },
        }
        root = self._project_root(owner_id, project_id)
        path = root / "analyses" / f"{analysis_id}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != record:
                raise ValueError("ANALYSIS_IMMUTABLE_CONFLICT")
            return {"created": False, "analysis": existing}
        _atomic(path, record)
        return {"created": True, "analysis": record}

    def get(self, owner_id: str, project_id: str, analysis_id: str) -> dict[str, Any]:
        root = self._project_root(owner_id, project_id)
        clean = str(analysis_id or "").strip()
        if not clean or any(token in clean for token in ("/", "\\", "..")):
            raise ValueError("ANALYSIS_ID_INVALID")
        path = root / "analyses" / f"{clean}.json"
        if not path.exists():
            raise FileNotFoundError(clean)
        return json.loads(path.read_text(encoding="utf-8"))

    def readiness(self, owner_id: str, project_id: str) -> dict[str, Any]:
        root = self._project_root(owner_id, project_id)
        analyses_dir = root / "analyses"
        count = len(list(analyses_dir.glob("analysis-*.json"))) if analyses_dir.exists() else 0
        return {
            "schema_version": ANALYSIS_SCHEMA_VERSION,
            "project_id": project_id,
            "method_count": len(METHOD_REGISTRY),
            "analysis_count": count,
            "ready_for_bounded_private_analysis": True,
            "ready_for_arbitrary_code_execution": False,
            "ready_for_autonomous_scientific_publication": False,
            "ready_for_knowledge_graph_mutation": False,
        }
