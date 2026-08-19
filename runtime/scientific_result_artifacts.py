"""Immutable result-table and figure-spec artifacts for CALYX-617."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from runtime.scientific_analysis import ScientificAnalysisService
from runtime.scientific_diagnostics import ScientificDiagnosticsService

RESULT_ARTIFACT_SCHEMA_VERSION = "calyx-scientific-result-artifact/v1"


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


def _table(analysis: dict[str, Any]) -> dict[str, Any]:
    method = analysis["method"]
    result = analysis["result"]
    if method == "describe.v1":
        columns = ["variable", "n", "missing", "mean", "median", "sample_sd", "min", "max"]
        rows = [
            {
                "variable": variable,
                "n": values["n"],
                "missing": values["missing"],
                "mean": values["mean"],
                "median": values["median"],
                "sample_sd": values["sample_sd"],
                "min": values["min"],
                "max": values["max"],
            }
            for variable, values in sorted(result["columns"].items())
        ]
    elif method == "pearson.v1":
        columns = ["n", "r", "r_squared"]
        rows = [{key: result[key] for key in columns}]
    elif method == "ols.v1":
        columns = ["n", "intercept", "slope", "r_squared", "residual_standard_error"]
        rows = [{key: result[key] for key in columns}]
    else:  # pragma: no cover
        raise ValueError("RESULT_ARTIFACT_METHOD_UNSUPPORTED")
    return {
        "table_kind": "analysis_result",
        "columns": columns,
        "rows": rows,
    }


def _figure_specs(method: str, diagnostic: dict[str, Any] | None) -> list[dict[str, Any]]:
    if diagnostic is None:
        return []
    diagnostic_id = diagnostic["diagnostic_id"]
    if method == "describe.v1":
        return [
            {
                "figure_kind": "univariate_values",
                "title": f"Values — {variable}",
                "diagnostic_id": diagnostic_id,
                "data_path": ["diagnostics", "series", variable, "points"],
                "x_field": "row_index",
                "y_field": "value",
                "interpretation_generated": False,
            }
            for variable in sorted(diagnostic["diagnostics"]["series"])
        ]
    if method == "pearson.v1":
        scatter = diagnostic["diagnostics"]["scatter"]
        return [
            {
                "figure_kind": "scatter",
                "title": f"{scatter['y']} vs {scatter['x']}",
                "diagnostic_id": diagnostic_id,
                "data_path": ["diagnostics", "scatter", "points"],
                "x_field": "x",
                "y_field": "y",
                "interpretation_generated": False,
            }
        ]
    if method == "ols.v1":
        return [
            {
                "figure_kind": "observed_vs_fitted",
                "title": "Observed and fitted response",
                "diagnostic_id": diagnostic_id,
                "data_path": ["diagnostics", "observed_fitted", "points"],
                "x_field": "x",
                "y_fields": ["observed", "fitted"],
                "interpretation_generated": False,
            },
            {
                "figure_kind": "residual_vs_fitted",
                "title": "Residuals vs fitted values",
                "diagnostic_id": diagnostic_id,
                "data_path": ["diagnostics", "residual_vs_fitted", "points"],
                "x_field": "fitted",
                "y_field": "residual",
                "interpretation_generated": False,
            },
        ]
    return []


class ScientificResultArtifactService:
    def __init__(
        self,
        analysis: ScientificAnalysisService | None = None,
        diagnostics: ScientificDiagnosticsService | None = None,
    ) -> None:
        self.analysis = analysis or ScientificAnalysisService()
        self.diagnostics = diagnostics

    def _root(self, owner_id: str, project_id: str) -> Path:
        return self.analysis._project_root(owner_id, project_id) / "analysis_result_artifacts"

    def build(self, owner_id: str, project_id: str, analysis_id: str) -> dict[str, Any]:
        analysis = self.analysis.get(owner_id, project_id, analysis_id)
        diagnostic: dict[str, Any] | None = None
        if self.diagnostics is not None:
            try:
                diagnostic = self.diagnostics.get(owner_id, project_id, analysis_id)
            except FileNotFoundError:
                diagnostic = None
        table = _table(analysis)
        figures = _figure_specs(analysis["method"], diagnostic)
        core = {
            "schema_version": RESULT_ARTIFACT_SCHEMA_VERSION,
            "project_id": project_id,
            "analysis_id": analysis_id,
            "method": analysis["method"],
            "method_version": analysis["method_version"],
            "input_sha256": analysis["input_sha256"],
            "result_sha256": analysis["result_sha256"],
            "diagnostic_id": diagnostic.get("diagnostic_id") if diagnostic else None,
            "diagnostics_sha256": diagnostic.get("diagnostics_sha256") if diagnostic else None,
            "result_table": table,
            "figure_specs": figures,
            "figure_specs_are_rendering_instructions_not_interpretation": True,
            "scientific_interpretation_generated": False,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }
        artifact_sha256 = _sha(core)
        artifact = {
            **core,
            "artifact_sha256": artifact_sha256,
            "artifact_id": f"analysis-artifact-{artifact_sha256[:24]}",
        }
        path = self._root(owner_id, project_id) / f"{analysis_id}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != artifact:
                raise ValueError("RESULT_ARTIFACT_IMMUTABLE_CONFLICT")
            return {"created": False, "artifact": existing}
        _atomic(path, artifact)
        return {"created": True, "artifact": artifact}

    def get(self, owner_id: str, project_id: str, analysis_id: str) -> dict[str, Any]:
        clean = str(analysis_id or "").strip()
        if not clean or any(token in clean for token in ("/", "\\", "..")):
            raise ValueError("RESULT_ARTIFACT_ANALYSIS_ID_INVALID")
        path = self._root(owner_id, project_id) / f"{clean}.json"
        if not path.exists():
            raise FileNotFoundError(clean)
        return json.loads(path.read_text(encoding="utf-8"))
