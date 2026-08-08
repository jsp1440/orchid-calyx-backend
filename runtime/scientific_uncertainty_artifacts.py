"""Non-live result artifact contract for the CALYX-617 mean-CI candidate."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from runtime.scientific_uncertainty import UNCERTAINTY_SCHEMA_VERSION

MEAN_CI_ARTIFACT_SCHEMA_VERSION = "calyx-mean-ci-result-artifact-candidate/v1"


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(payload: Any) -> str:
    return hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()


def build_mean_ci_result_artifact_candidate(
    *,
    project_id: str,
    plan_id: str,
    dataset_id: str,
    raw_dataset_checksum_sha256: str,
    analytical_rows_sha256: str,
    target_variable: str,
    target_unit: str,
    uncertainty: dict[str, Any],
) -> dict[str, Any]:
    """Normalize a governed Student-t interval into a non-live result artifact candidate."""
    if uncertainty.get("schema_version") != UNCERTAINTY_SCHEMA_VERSION:
        raise ValueError("MEAN_CI_ARTIFACT_UNCERTAINTY_SCHEMA_UNSUPPORTED")
    if uncertainty.get("estimand") != "population_mean":
        raise ValueError("MEAN_CI_ARTIFACT_ESTIMAND_UNSUPPORTED")
    if uncertainty.get("distribution") != "student_t":
        raise ValueError("MEAN_CI_ARTIFACT_DISTRIBUTION_UNSUPPORTED")
    if uncertainty.get("p_value_generated") is not False:
        raise ValueError("MEAN_CI_ARTIFACT_P_VALUE_FORBIDDEN")
    if uncertainty.get("scientific_interpretation_generated") is not False:
        raise ValueError("MEAN_CI_ARTIFACT_INTERPRETATION_FORBIDDEN")

    variable = str(target_variable or "").strip()
    unit = str(target_unit or "").strip()
    if not variable:
        raise ValueError("MEAN_CI_ARTIFACT_TARGET_VARIABLE_REQUIRED")
    if not unit:
        raise ValueError("MEAN_CI_ARTIFACT_TARGET_UNIT_REQUIRED")

    row = {
        "variable": variable,
        "unit": unit,
        "estimand": "population_mean",
        "n": uncertainty["sample_size"],
        "estimate": uncertainty["sample_mean"],
        "sample_sd": uncertainty["sample_sd"],
        "standard_error": uncertainty["standard_error"],
        "confidence_level": uncertainty["confidence_level"],
        "lower": uncertainty["lower"],
        "upper": uncertainty["upper"],
        "distribution": "student_t",
        "degrees_of_freedom": uncertainty["degrees_of_freedom"],
    }
    table = {
        "table_kind": "estimate_with_confidence_interval",
        "columns": [
            "variable",
            "unit",
            "estimand",
            "n",
            "estimate",
            "sample_sd",
            "standard_error",
            "confidence_level",
            "lower",
            "upper",
            "distribution",
            "degrees_of_freedom",
        ],
        "rows": [row],
    }
    interval_figure = {
        "figure_kind": "estimate_with_confidence_interval",
        "title": f"Mean estimate and confidence interval — {variable}",
        "data": [
            {
                "variable": variable,
                "estimate": uncertainty["sample_mean"],
                "lower": uncertainty["lower"],
                "upper": uncertainty["upper"],
                "unit": unit,
            }
        ],
        "estimate_field": "estimate",
        "lower_field": "lower",
        "upper_field": "upper",
        "significance_coloring_allowed": False,
        "interpretation_generated": False,
    }
    core = {
        "schema_version": MEAN_CI_ARTIFACT_SCHEMA_VERSION,
        "candidate_method": "mean_ci.v1",
        "method_registered": False,
        "project_id": str(project_id),
        "plan_id": str(plan_id),
        "dataset_id": str(dataset_id),
        "raw_dataset_checksum_sha256": str(raw_dataset_checksum_sha256),
        "analytical_rows_sha256": str(analytical_rows_sha256),
        "target_variable": variable,
        "target_unit": unit,
        "result_table": table,
        "figure_specs": [interval_figure],
        "uncertainty_artifact": uncertainty,
        "figure_specs_are_rendering_instructions_not_interpretation": True,
        "significance_coloring_allowed": False,
        "p_value_generated": False,
        "scientific_interpretation_generated": False,
        "human_review_required_for_scientific_conclusion": True,
        "scientific_publication_authorized": False,
        "knowledge_graph_mutation_authorized": False,
    }
    artifact_sha256 = _sha(core)
    return {
        **core,
        "artifact_sha256": artifact_sha256,
        "artifact_id": f"mean-ci-candidate-artifact-{artifact_sha256[:24]}",
    }
