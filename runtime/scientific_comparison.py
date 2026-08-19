"""Governed descriptive comparison of immutable CALYX-617 analysis runs."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from runtime.scientific_analysis import ScientificAnalysisService

COMPARISON_SCHEMA_VERSION = "calyx-scientific-comparison/v1"


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


def _dataset_identity(analysis: dict[str, Any]) -> dict[str, Any]:
    ref = analysis.get("dataset_ref") or {}
    return {
        "dataset_id": ref.get("dataset_id"),
        "raw_checksum_sha256": ref.get("raw_checksum_sha256") or ref.get("checksum_sha256"),
        "analytical_rows_sha256": ref.get("analytical_rows_sha256"),
        "analysis_plan_id": ref.get("analysis_plan_id"),
    }


def _scalar_numeric_result(result: dict[str, Any]) -> dict[str, float]:
    values: dict[str, float] = {}
    for key, value in result.items():
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            values[str(key)] = float(value)
    return values


class ScientificComparisonService:
    def __init__(self, analysis: ScientificAnalysisService | None = None) -> None:
        self.analysis = analysis or ScientificAnalysisService()

    def _root(self, owner_id: str, project_id: str) -> Path:
        return self.analysis._project_root(owner_id, project_id) / "analysis_comparisons"

    def compare(
        self,
        owner_id: str,
        project_id: str,
        analysis_a_id: str,
        analysis_b_id: str,
    ) -> dict[str, Any]:
        a = self.analysis.get(owner_id, project_id, analysis_a_id)
        b = self.analysis.get(owner_id, project_id, analysis_b_id)
        dataset_a = _dataset_identity(a)
        dataset_b = _dataset_identity(b)
        same_method = a["method"] == b["method"]
        same_method_version = a["method_version"] == b["method_version"]
        same_raw_dataset = bool(
            dataset_a["raw_checksum_sha256"]
            and dataset_a["raw_checksum_sha256"] == dataset_b["raw_checksum_sha256"]
        )
        same_analytical_rows = bool(
            dataset_a["analytical_rows_sha256"]
            and dataset_a["analytical_rows_sha256"] == dataset_b["analytical_rows_sha256"]
        )
        same_parameters = a["parameters"] == b["parameters"]
        identical_input = a["input_sha256"] == b["input_sha256"]
        identical_result = a["result_sha256"] == b["result_sha256"]

        if identical_input and identical_result:
            compatibility = "identical_run"
        elif same_method and same_method_version and same_raw_dataset:
            compatibility = "same_method_same_raw_dataset"
        elif same_method and same_method_version:
            compatibility = "same_method_different_or_unbound_dataset"
        else:
            compatibility = "different_method_or_version"

        numeric_a = _scalar_numeric_result(a["result"])
        numeric_b = _scalar_numeric_result(b["result"])
        shared = sorted(set(numeric_a) & set(numeric_b)) if same_method and same_method_version else []
        deltas = {
            key: {
                "a": numeric_a[key],
                "b": numeric_b[key],
                "delta_b_minus_a": numeric_b[key] - numeric_a[key],
            }
            for key in shared
        }
        core = {
            "schema_version": COMPARISON_SCHEMA_VERSION,
            "project_id": project_id,
            "analysis_a": {
                "analysis_id": a["analysis_id"],
                "method": a["method"],
                "method_version": a["method_version"],
                "parameters": a["parameters"],
                "input_sha256": a["input_sha256"],
                "result_sha256": a["result_sha256"],
                "dataset": dataset_a,
            },
            "analysis_b": {
                "analysis_id": b["analysis_id"],
                "method": b["method"],
                "method_version": b["method_version"],
                "parameters": b["parameters"],
                "input_sha256": b["input_sha256"],
                "result_sha256": b["result_sha256"],
                "dataset": dataset_b,
            },
            "compatibility": compatibility,
            "same_method": same_method,
            "same_method_version": same_method_version,
            "same_raw_dataset": same_raw_dataset,
            "same_analytical_rows": same_analytical_rows,
            "same_parameters": same_parameters,
            "identical_input": identical_input,
            "identical_result": identical_result,
            "numeric_result_deltas": deltas,
            "comparison_is_descriptive_not_model_selection": True,
            "preferred_analysis": None,
            "scientific_superiority_determined": False,
            "scientific_interpretation_generated": False,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
        }
        comparison_sha256 = _sha(core)
        artifact = {
            **core,
            "comparison_sha256": comparison_sha256,
            "comparison_id": f"comparison-{comparison_sha256[:24]}",
        }
        path = self._root(owner_id, project_id) / f"{artifact['comparison_id']}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != artifact:
                raise ValueError("ANALYSIS_COMPARISON_IMMUTABLE_CONFLICT")
            return {"created": False, "comparison": existing}
        _atomic(path, artifact)
        return {"created": True, "comparison": artifact}

    def get(self, owner_id: str, project_id: str, comparison_id: str) -> dict[str, Any]:
        clean = str(comparison_id or "").strip()
        if not clean or any(token in clean for token in ("/", "\\", "..")):
            raise ValueError("ANALYSIS_COMPARISON_ID_INVALID")
        path = self._root(owner_id, project_id) / f"{clean}.json"
        if not path.exists():
            raise FileNotFoundError(clean)
        return json.loads(path.read_text(encoding="utf-8"))
