from __future__ import annotations

import io

import pytest
from openpyxl import Workbook
from pydantic import ValidationError

from app.data_intelligence.models import (
    AnalysisOperation,
    AnalysisPlan,
    DataIntelligenceError,
)
from app.data_intelligence.repository import FileDatasetRepository
from app.data_intelligence.service import DataIntelligenceService


@pytest.fixture()
def service(tmp_path):
    return DataIntelligenceService(FileDatasetRepository(tmp_path))


def _csv_bytes() -> bytes:
    return (
        "genus,height,flowers\n"
        "Cattleya,10,3\n"
        "Cattleya,14,5\n"
        "Dendrobium,8,7\n"
        "Dendrobium,12,9\n"
    ).encode("utf-8")


def _xlsx_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["genus", "height", "flowers"])
    sheet.append(["Cattleya", 10, 3])
    sheet.append(["Cattleya", 14, 5])
    sheet.append(["Dendrobium", 8, 7])
    sheet.append(["Dendrobium", 12, 9])
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def test_csv_ingest_profile_execute_and_rerun_are_deterministic(service):
    ingested = service.ingest(
        owner="owner@example.org",
        project_id="project-1",
        logical_name="orchid-growth",
        filename="orchids.csv",
        data=_csv_bytes(),
    )
    dataset = ingested["dataset"]
    assert ingested["created"] is True
    assert ingested["profile"]["row_count"] == 4
    assert ingested["profile"]["column_count"] == 3

    duplicate = service.ingest(
        owner="owner@example.org",
        project_id="project-1",
        logical_name="orchid-growth",
        filename="orchids.csv",
        data=_csv_bytes(),
    )
    assert duplicate["created"] is False
    assert duplicate["dataset"]["version_id"] == dataset["version_id"]

    plan = service.compile_intent(
        dataset_id=dataset["dataset_id"],
        version_id=dataset["version_id"],
        intent="mean height by genus chart",
    )
    result = service.execute(
        owner="owner@example.org", project_id="project-1", plan=plan
    )
    assert result["sandbox"]["network_access"] is False
    assert result["sandbox"]["arbitrary_code_execution"] is False
    assert result["reasoning_reference"]["source_kind"] == "dataset"
    assert set(result["artifact_hashes"]) == {"table.json", "chart.svg"}

    rerun = service.rerun(
        owner="owner@example.org",
        project_id="project-1",
        dataset_id=dataset["dataset_id"],
        version_id=dataset["version_id"],
        analysis_id=result["analysis_id"],
    )
    assert rerun["equivalent_artifacts"] is True
    assert rerun["previous_artifact_hashes"] == rerun["current_artifact_hashes"]


def test_xlsx_ingest_and_profile(service):
    result = service.ingest(
        owner="owner",
        project_id="project-1",
        logical_name="orchid-growth-xlsx",
        filename="orchids.xlsx",
        data=_xlsx_bytes(),
    )
    assert result["dataset"]["format"] == "xlsx"
    assert result["profile"]["row_count"] == 4
    height = next(
        item for item in result["profile"]["columns"] if item["name"] == "height"
    )
    assert height["type"] == "integer"
    assert height["mean"] == 11.0


def test_tenant_and_project_scope_is_fail_closed(service):
    result = service.ingest(
        owner="owner-a",
        project_id="project-a",
        logical_name="scope-test",
        filename="orchids.csv",
        data=_csv_bytes(),
    )
    dataset = result["dataset"]
    with pytest.raises(DataIntelligenceError, match="DATASET_VERSION_NOT_FOUND"):
        service.repository.get(
            "owner-b", "project-a", dataset["dataset_id"], dataset["version_id"]
        )
    with pytest.raises(DataIntelligenceError, match="DATASET_VERSION_NOT_FOUND"):
        service.repository.get(
            "owner-a", "project-b", dataset["dataset_id"], dataset["version_id"]
        )


def test_unsafe_or_untyped_execution_is_rejected():
    with pytest.raises(ValidationError):
        AnalysisOperation(kind="python")


def test_unsupported_intent_is_explicit(service):
    with pytest.raises(DataIntelligenceError, match="INTENT_NOT_SUPPORTED"):
        service.compile_intent(
            dataset_id="d" * 32,
            version_id="0" * 64,
            intent="run arbitrary python from the internet",
        )


def test_wrong_version_and_resource_limits_are_structured(service):
    result = service.ingest(
        owner="owner",
        project_id="project-1",
        logical_name="limits",
        filename="orchids.csv",
        data=_csv_bytes(),
    )
    dataset = result["dataset"]
    wrong = AnalysisPlan(
        dataset={"dataset_id": dataset["dataset_id"], "version_id": "0" * 64},
        intent="sort by height",
        operations=[AnalysisOperation(kind="sort", column="height")],
    )
    with pytest.raises(DataIntelligenceError, match="DATASET_VERSION_NOT_FOUND"):
        service.execute(owner="owner", project_id="project-1", plan=wrong)

    service.limits.max_rows = 2
    valid = AnalysisPlan(
        dataset={
            "dataset_id": dataset["dataset_id"],
            "version_id": dataset["version_id"],
        },
        intent="sort by height",
        operations=[AnalysisOperation(kind="sort", column="height")],
    )
    with pytest.raises(DataIntelligenceError, match="ROW_LIMIT_EXCEEDED"):
        service.execute(owner="owner", project_id="project-1", plan=valid)


def test_numeric_sort_join_and_pivot_are_deterministic(service):
    sort_source = service.ingest(
        owner="owner",
        project_id="project-1",
        logical_name="sort-source",
        filename="sort.csv",
        data=b"height\n10\n8\n12\n",
    )["dataset"]
    sort_plan = AnalysisPlan(
        dataset={
            "dataset_id": sort_source["dataset_id"],
            "version_id": sort_source["version_id"],
        },
        intent="sort by height",
        operations=[AnalysisOperation(kind="sort", column="height")],
    )
    sorted_result = service.execute(
        owner="owner", project_id="project-1", plan=sort_plan
    )
    table = service.repository.analysis_dir(
        "owner",
        "project-1",
        sort_source["dataset_id"],
        sort_source["version_id"],
        sorted_result["analysis_id"],
    ) / "table.json"
    assert table.read_text(encoding="utf-8") == '[{"height":"8"},{"height":"10"},{"height":"12"}]'

    left = service.ingest(
        owner="owner",
        project_id="project-1",
        logical_name="left",
        filename="left.csv",
        data=b"genus,height\nCattleya,10\nDendrobium,8\n",
    )["dataset"]
    right = service.ingest(
        owner="owner",
        project_id="project-1",
        logical_name="right",
        filename="right.csv",
        data=b"genus,region\nCattleya,Andes\nDendrobium,Asia\n",
    )["dataset"]
    join_plan = AnalysisPlan(
        dataset={"dataset_id": left["dataset_id"], "version_id": left["version_id"]},
        intent="join datasets",
        operations=[
            AnalysisOperation(
                kind="join",
                other_dataset={
                    "dataset_id": right["dataset_id"],
                    "version_id": right["version_id"],
                },
                left_on="genus",
                right_on="genus",
                join_how="inner",
            )
        ],
    )
    joined = service.execute(owner="owner", project_id="project-1", plan=join_plan)
    assert joined["row_count"] == 2

    source = service.ingest(
        owner="owner",
        project_id="project-1",
        logical_name="pivot",
        filename="pivot.csv",
        data=(
            b"genus,season,flowers\n"
            b"Cattleya,spring,3\n"
            b"Cattleya,summer,5\n"
            b"Dendrobium,spring,7\n"
        ),
    )["dataset"]
    pivot_plan = AnalysisPlan(
        dataset={
            "dataset_id": source["dataset_id"],
            "version_id": source["version_id"],
        },
        intent="pivot flower counts",
        operations=[
            AnalysisOperation(
                kind="pivot",
                pivot_index="genus",
                pivot_columns="season",
                aggregate_column="flowers",
                aggregate_function="sum",
            )
        ],
    )
    first = service.execute(owner="owner", project_id="project-1", plan=pivot_plan)
    second = service.execute(owner="owner", project_id="project-1", plan=pivot_plan)
    assert first["analysis_id"] == second["analysis_id"]
    assert first["artifact_hashes"] == second["artifact_hashes"]
