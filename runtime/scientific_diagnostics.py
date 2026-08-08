"""Deterministic, non-interpretive diagnostic artifacts for CALYX-617."""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from statistics import fmean
from typing import Any

from runtime.research_analysis_workflow import ResearchAnalysisWorkflowService

DIAGNOSTICS_SCHEMA_VERSION = "calyx-scientific-diagnostics/v1"


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


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise TypeError("DIAGNOSTIC_BOOLEAN_NOT_NUMERIC")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("DIAGNOSTIC_NON_FINITE_VALUE")
    return number


def _pairs(rows: list[dict[str, Any]], x_name: str, y_name: str) -> list[tuple[int, float, float]]:
    values: list[tuple[int, float, float]] = []
    for index, row in enumerate(rows):
        x = _number(row.get(x_name))
        y = _number(row.get(y_name))
        if x is not None and y is not None:
            values.append((index, x, y))
    return values


class ScientificDiagnosticsService:
    def __init__(self, workflow: ResearchAnalysisWorkflowService | None = None) -> None:
        self.workflow = workflow or ResearchAnalysisWorkflowService()

    def _artifact_root(self, owner_id: str, project_id: str) -> Path:
        return self.workflow._project_root(owner_id, project_id) / "analysis_diagnostics"

    @staticmethod
    def _describe(rows: list[dict[str, Any]], columns: list[str]) -> dict[str, Any]:
        series: dict[str, Any] = {}
        for column in columns:
            points = []
            missing = 0
            for index, row in enumerate(rows):
                value = _number(row.get(column))
                if value is None:
                    missing += 1
                else:
                    points.append({"row_index": index, "value": value})
            series[column] = {
                "plot_kind": "univariate_values",
                "complete": len(points),
                "missing": missing,
                "points": points,
            }
        return {"series": series}

    @staticmethod
    def _pearson(rows: list[dict[str, Any]], x_name: str, y_name: str) -> dict[str, Any]:
        pairs = _pairs(rows, x_name, y_name)
        return {
            "scatter": {
                "plot_kind": "scatter",
                "x": x_name,
                "y": y_name,
                "points": [
                    {"row_index": index, "x": x, "y": y}
                    for index, x, y in pairs
                ],
            },
            "complete_pairs": len(pairs),
        }

    @staticmethod
    def _ols(
        rows: list[dict[str, Any]],
        x_name: str,
        y_name: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        pairs = _pairs(rows, x_name, y_name)
        intercept = float(result["intercept"])
        slope = float(result["slope"])
        observed_fitted = []
        residuals: list[float] = []
        for index, x, observed in pairs:
            fitted = intercept + slope * x
            residual = observed - fitted
            residuals.append(residual)
            observed_fitted.append(
                {
                    "row_index": index,
                    "x": x,
                    "observed": observed,
                    "fitted": fitted,
                    "residual": residual,
                }
            )
        residual_summary = {
            "n": len(residuals),
            "mean": fmean(residuals) if residuals else None,
            "sum_squared": sum(value * value for value in residuals),
            "max_absolute": max((abs(value) for value in residuals), default=None),
        }
        return {
            "observed_fitted": {
                "plot_kind": "observed_vs_fitted",
                "x": x_name,
                "y": y_name,
                "points": observed_fitted,
            },
            "residual_vs_fitted": {
                "plot_kind": "residual_vs_fitted",
                "points": [
                    {
                        "row_index": point["row_index"],
                        "fitted": point["fitted"],
                        "residual": point["residual"],
                    }
                    for point in observed_fitted
                ],
            },
            "residual_summary": residual_summary,
        }

    def build(
        self,
        owner_id: str,
        project_id: str,
        plan_id: str,
        analysis_id: str,
        rows: list[dict[str, Any]],
        provenance: dict[str, Any],
    ) -> dict[str, Any]:
        analysis = self.workflow.analysis.get(owner_id, project_id, analysis_id)
        binding = self.workflow.validate_plan_rows(owner_id, project_id, plan_id, rows, provenance)
        validation = binding["analysis_validation"]
        if validation["input_sha256"] != analysis["input_sha256"]:
            raise ValueError("DIAGNOSTIC_ANALYSIS_INPUT_MISMATCH")
        if analysis.get("project_id") != project_id:
            raise ValueError("DIAGNOSTIC_PROJECT_MISMATCH")
        canonical = validation["canonical_input"]
        method = analysis["method"]
        parameters = analysis["parameters"]
        analytical_rows = canonical["rows"]
        if method == "describe.v1":
            payload = self._describe(analytical_rows, parameters["columns"])
        elif method == "pearson.v1":
            payload = self._pearson(analytical_rows, parameters["x"], parameters["y"])
        elif method == "ols.v1":
            payload = self._ols(
                analytical_rows,
                parameters["x"],
                parameters["y"],
                analysis["result"],
            )
        else:  # pragma: no cover - analysis registry is fail closed
            raise ValueError("DIAGNOSTIC_METHOD_UNSUPPORTED")

        core = {
            "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
            "project_id": project_id,
            "plan_id": plan_id,
            "analysis_id": analysis_id,
            "method": method,
            "method_version": analysis["method_version"],
            "input_sha256": analysis["input_sha256"],
            "result_sha256": analysis["result_sha256"],
            "raw_dataset_checksum_sha256": binding["dataset_checksum_sha256"],
            "analytical_rows_sha256": binding["analytical_rows_sha256"],
            "diagnostics": payload,
            "diagnostics_are_descriptive_not_inferential": True,
            "model_quality_judgment_generated": False,
            "scientific_interpretation_generated": False,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }
        diagnostics_sha256 = _sha(core)
        artifact = {
            **core,
            "diagnostics_sha256": diagnostics_sha256,
            "diagnostic_id": f"diagnostic-{diagnostics_sha256[:24]}",
        }
        path = self._artifact_root(owner_id, project_id) / f"{analysis_id}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != artifact:
                raise ValueError("DIAGNOSTIC_IMMUTABLE_CONFLICT")
            return {"created": False, "diagnostic": existing}
        _atomic(path, artifact)
        return {"created": True, "diagnostic": artifact}

    def get(self, owner_id: str, project_id: str, analysis_id: str) -> dict[str, Any]:
        clean = str(analysis_id or "").strip()
        if not clean or any(token in clean for token in ("/", "\\", "..")):
            raise ValueError("DIAGNOSTIC_ANALYSIS_ID_INVALID")
        path = self._artifact_root(owner_id, project_id) / f"{clean}.json"
        if not path.exists():
            raise FileNotFoundError(clean)
        return json.loads(path.read_text(encoding="utf-8"))
