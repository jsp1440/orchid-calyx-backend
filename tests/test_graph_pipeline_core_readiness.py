import json
import importlib

from app.routers.graph_pipeline_readiness import graph_pipeline_readiness, router
from runtime.graph_pipeline_readiness import (
    CONTRACT,
    STATUSES,
    build_graph_pipeline_readiness,
)


def _by_domain(report):
    return {item["domain"]: item for item in report["domains"]}


def _resolve_component(component):
    parts = component.split(".")
    for split_at in range(len(parts) - 1, 0, -1):
        try:
            value = importlib.import_module(".".join(parts[:split_at]))
        except ModuleNotFoundError:
            continue
        for attribute in parts[split_at:]:
            value = getattr(value, attribute)
        return value
    raise AssertionError(f"cannot import executable component: {component}")


def test_contract_has_exact_domains_and_required_fields(tmp_path):
    report = build_graph_pipeline_readiness(
        taxonomy_root=tmp_path / "taxonomy",
        literature_root=tmp_path / "literature",
    )
    domains = _by_domain(report)
    assert report["contract"] == CONTRACT
    assert report["read_only"] is True
    assert report["production_graph_mutation"] is False
    assert set(domains) == {"taxonomy", "occurrences", "licensed_images", "literature"}
    assert all(item["status"] in STATUSES for item in domains.values())
    assert all(item["executable_components"] for item in domains.values())
    assert all(item["blockers"] for item in domains.values())
    assert all(item["exact_next_executable_job"] for item in domains.values())
    for item in domains.values():
        for component in item["executable_components"]:
            assert _resolve_component(component) is not None
    assert all(set(item["capabilities"]) == {
        "source_ingestion", "raw_persistence", "normalization",
        "taxonomic_reconciliation", "provenance", "staging_graph_projection",
        "publication_readiness", "freshness_or_checkpoint_monitoring",
        "mission_control_visibility",
    } for item in domains.values())


def test_counts_are_null_without_observed_evidence(tmp_path):
    report = build_graph_pipeline_readiness(
        taxonomy_root=tmp_path / "missing-taxonomy",
        literature_root=tmp_path / "missing-literature",
    )
    for item in report["domains"]:
        assert item["record_count"]["value"] is None
        assert item["record_count"]["reason"]


def test_safe_local_counts_are_reported_with_provenance(tmp_path):
    taxonomy = tmp_path / "taxonomy" / "release-1"
    taxonomy.mkdir(parents=True)
    (taxonomy / "report.json").write_text(json.dumps({
        "release_id": "release-1", "state": "inspected",
        "snapshot": {"row_count": 7, "acquired_at": "2026-08-01T00:00:00Z"},
    }), encoding="utf-8")
    literature = tmp_path / "literature" / "paper-1"
    literature.mkdir(parents=True)
    (literature / "paper.json").write_text("{}", encoding="utf-8")

    report = build_graph_pipeline_readiness(
        taxonomy_root=tmp_path / "taxonomy",
        literature_root=tmp_path / "literature",
    )
    domains = _by_domain(report)
    assert domains["taxonomy"]["record_count"]["value"] == 7
    assert domains["taxonomy"]["source_checkpoint"]["checkpoint"] == "release-1"
    assert domains["literature"]["record_count"]["value"] == 1
    assert domains["literature"]["record_count"]["source"]


def test_injected_read_only_count_observer_is_used(tmp_path):
    report = build_graph_pipeline_readiness(
        taxonomy_root=tmp_path / "taxonomy",
        literature_root=tmp_path / "literature",
        count_observer=lambda domain: {
            "value": 3, "observed_at": "2026-08-05T00:00:00Z",
            "source": f"test-probe:{domain}", "reason": None,
        },
    )
    assert all(item["record_count"]["value"] == 3 for item in report["domains"])


def test_endpoint_is_get_only_owner_gated_and_returns_contract():
    route = next(
        item for item in router.routes
        if item.path == "/api/mission-control/graph-pipeline/readiness"
    )
    assert route.methods == {"GET"}
    assert route.dependant.dependencies
    assert route.dependant.dependencies[0].call.__name__ == "verify_owner_or_api_key"
    assert graph_pipeline_readiness({"role": "owner"})["contract"] == CONTRACT
