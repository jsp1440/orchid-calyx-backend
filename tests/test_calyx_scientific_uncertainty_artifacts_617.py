from __future__ import annotations

import copy

import pytest

from runtime.scientific_uncertainty import mean_confidence_interval
from runtime.scientific_uncertainty_artifacts import (
    build_mean_ci_result_artifact_candidate,
)


def _artifact():
    uncertainty = mean_confidence_interval([1.0, 2.0, 3.0, 4.0], 0.95)
    return build_mean_ci_result_artifact_candidate(
        project_id="project-1",
        plan_id="plan-1",
        dataset_id="dataset-1",
        raw_dataset_checksum_sha256="a" * 64,
        analytical_rows_sha256="b" * 64,
        target_variable="petal_length_cm",
        target_unit="cm",
        uncertainty=uncertainty,
    )


def test_mean_ci_candidate_artifact_preserves_estimate_interval_and_identity():
    artifact = _artifact()

    assert artifact["candidate_method"] == "mean_ci.v1"
    assert artifact["method_registered"] is False
    assert artifact["raw_dataset_checksum_sha256"] == "a" * 64
    assert artifact["analytical_rows_sha256"] == "b" * 64
    table = artifact["result_table"]
    assert table["table_kind"] == "estimate_with_confidence_interval"
    row = table["rows"][0]
    assert row["variable"] == "petal_length_cm"
    assert row["unit"] == "cm"
    assert row["estimate"] == 2.5
    assert row["lower"] < row["estimate"] < row["upper"]
    assert row["distribution"] == "student_t"


def test_mean_ci_candidate_artifact_figure_has_no_significance_semantics():
    artifact = _artifact()

    assert artifact["significance_coloring_allowed"] is False
    assert artifact["p_value_generated"] is False
    assert artifact["scientific_interpretation_generated"] is False
    assert artifact["human_review_required_for_scientific_conclusion"] is True
    figure = artifact["figure_specs"][0]
    assert figure["figure_kind"] == "estimate_with_confidence_interval"
    assert figure["significance_coloring_allowed"] is False
    assert figure["interpretation_generated"] is False


def test_mean_ci_candidate_artifact_is_content_addressed_and_deterministic():
    first = _artifact()
    second = _artifact()

    assert first == second
    assert first["artifact_id"].endswith(first["artifact_sha256"][:24])


def test_mean_ci_candidate_artifact_rejects_non_governed_uncertainty():
    uncertainty = mean_confidence_interval([1.0, 2.0, 3.0, 4.0], 0.95)

    wrong_distribution = copy.deepcopy(uncertainty)
    wrong_distribution["distribution"] = "normal"
    with pytest.raises(ValueError, match="MEAN_CI_ARTIFACT_DISTRIBUTION_UNSUPPORTED"):
        build_mean_ci_result_artifact_candidate(
            project_id="project-1",
            plan_id="plan-1",
            dataset_id="dataset-1",
            raw_dataset_checksum_sha256="a" * 64,
            analytical_rows_sha256="b" * 64,
            target_variable="petal_length_cm",
            target_unit="cm",
            uncertainty=wrong_distribution,
        )

    p_value_payload = copy.deepcopy(uncertainty)
    p_value_payload["p_value_generated"] = True
    with pytest.raises(ValueError, match="MEAN_CI_ARTIFACT_P_VALUE_FORBIDDEN"):
        build_mean_ci_result_artifact_candidate(
            project_id="project-1",
            plan_id="plan-1",
            dataset_id="dataset-1",
            raw_dataset_checksum_sha256="a" * 64,
            analytical_rows_sha256="b" * 64,
            target_variable="petal_length_cm",
            target_unit="cm",
            uncertainty=p_value_payload,
        )


def test_mean_ci_candidate_artifact_requires_target_unit():
    uncertainty = mean_confidence_interval([1.0, 2.0, 3.0, 4.0], 0.95)
    with pytest.raises(ValueError, match="MEAN_CI_ARTIFACT_TARGET_UNIT_REQUIRED"):
        build_mean_ci_result_artifact_candidate(
            project_id="project-1",
            plan_id="plan-1",
            dataset_id="dataset-1",
            raw_dataset_checksum_sha256="a" * 64,
            analytical_rows_sha256="b" * 64,
            target_variable="petal_length_cm",
            target_unit="",
            uncertainty=uncertainty,
        )
