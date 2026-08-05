"""Read-only production-readiness contract for the four core graph domains.

The report intentionally separates executable code readiness from live-data
claims.  It performs local, read-only observations only; database counts remain
unknown unless a caller supplies an explicit read-only count observer.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from runtime.knowledge_graph.adapters import adapters_by_domain
from runtime.knowledge_graph.source_registry import registry_by_domain

CONTRACT = "calyx-graph-pipeline-core-readiness-v1"
STATUSES = frozenset({"operational", "partial", "blocked", "absent"})
CountObserver = Callable[[str], dict[str, Any] | None]


def _unknown_count(reason: str) -> dict[str, Any]:
    return {"value": None, "observed_at": None, "source": None, "reason": reason}


def _local_taxonomy_observation(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if not root.exists():
        return _unknown_count("No local World Plants intake directory exists."), {
            "state": "not_observed", "source": str(root), "updated_at": None
        }
    reports: list[tuple[str, dict[str, Any]]] = []
    for report_path in root.glob("*/report.json"):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        acquired = str(report.get("snapshot", {}).get("acquired_at") or "")
        reports.append((acquired, report))
    if not reports:
        return _unknown_count("No readable local World Plants inspection report exists."), {
            "state": "not_observed", "source": str(root), "updated_at": None
        }
    acquired, latest = max(reports, key=lambda item: item[0])
    row_count = latest.get("snapshot", {}).get("row_count")
    count = (
        {"value": row_count, "observed_at": acquired or None,
         "source": "latest local World Plants inspection report", "reason": None}
        if isinstance(row_count, int) and row_count >= 0
        else _unknown_count("Latest World Plants report has no validated row_count.")
    )
    return count, {
        "state": str(latest.get("state") or "unknown"),
        "source": str(root),
        "checkpoint": latest.get("release_id"),
        "updated_at": acquired or None,
    }


def _local_literature_observation(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if not root.exists():
        return _unknown_count("No local literature extraction directory exists."), {
            "state": "not_observed", "source": str(root), "updated_at": None
        }
    papers = list(root.glob("*/paper.json"))
    latest = max((p.stat().st_mtime for p in papers), default=None)
    observed_at = (
        datetime.fromtimestamp(latest, tz=timezone.utc).isoformat() if latest else None
    )
    return {
        "value": len(papers), "observed_at": observed_at,
        "source": "local literature extraction paper.json files", "reason": None,
    }, {
        "state": "observed", "source": str(root), "updated_at": observed_at,
        "checkpoint": None,
    }


def _projection(domain: str) -> dict[str, Any]:
    registry_domain = "media" if domain == "licensed_images" else domain
    source = registry_by_domain().get(registry_domain)
    adapter = adapters_by_domain().get(registry_domain)
    return {
        "state": "registered" if source and source.enabled and source.sql and adapter else "blocked",
        "staging_only": True,
        "production_graph_mutation": False,
        "source_query": source.query_id if source else None,
        "adapter": adapter.domain if adapter else None,
        "taxon_mapping": source.taxon_mapping if source else None,
    }


DOMAIN_DEFINITIONS: dict[str, dict[str, Any]] = {
    "taxonomy": {
        "status": "partial",
        "components": [
            "runtime.world_plants_ingest.parse_world_orchids_release",
            "runtime.world_plants_release_store.WorldPlantsReleaseStore",
            "runtime.world_plants_delta.compare_and_crosswalk",
            "runtime.world_plants_synonyms.parse_synonym_assertions",
            "runtime.knowledge_graph.canonical_taxonomy.build_canonical_registry",
            "app.routers.taxonomy_releases.create_taxonomy_release_router",
        ],
        "capabilities": {
            "source_ingestion": "implemented", "raw_persistence": "local_file_store",
            "normalization": "implemented", "taxonomic_reconciliation": "implemented_review_gated",
            "provenance": "implemented", "staging_graph_projection": "missing",
            "publication_readiness": "blocked", "freshness_or_checkpoint_monitoring": "partial",
            "mission_control_visibility": "implemented",
        },
        "blockers": [
            "No executable job projects an inspected World Plants release into the staging graph.",
            "No executable promotion job binds the reviewed release to the canonical graph backbone.",
        ],
        "next_job": "python scripts/smoke_world_plants_activation.py",
    },
    "occurrences": {
        "status": "partial",
        "components": [
            "app.harvest.plugins.gbif.plugin.GBIFHarvester",
            "app.harvest.plugins.inaturalist.plugin.INaturalistHarvester",
            "app.harvest.manager.HarvestManager",
            "runtime.knowledge_graph.source_registry._OCCURRENCES",
            "runtime.knowledge_graph.adapters.OCCURRENCES_ADAPTER",
            "runtime.knowledge_graph.orchestrator.BuildOrchestrator",
        ],
        "capabilities": {
            "source_ingestion": "implemented_bounded", "raw_persistence": "in_memory_only",
            "normalization": "implemented", "taxonomic_reconciliation": "missing_canonical_crosswalk",
            "provenance": "partial", "staging_graph_projection": "registered",
            "publication_readiness": "blocked", "freshness_or_checkpoint_monitoring": "in_memory_only",
            "mission_control_visibility": "telemetry_only",
        },
        "blockers": [
            "Harvester V2 has no durable production HarvestPersistence implementation.",
            "GBIF taxonKey and iNaturalist taxon ids are not reconciled to canonical taxon_id before oc_atlas.occurrences projection.",
            "Harvester V2 has no durable production CheckpointStore implementation.",
        ],
        "next_job": "python scripts/run_bounded_resumable_graph_dry_run.py",
    },
    "licensed_images": {
        "status": "partial",
        "components": [
            "app.harvest.plugins.gbif.plugin.GBIFHarvester.extract_images",
            "app.harvest.plugins.inaturalist.plugin.INaturalistHarvester.extract_images",
            "runtime.taxonomy_image_population.build_taxonomy_image_candidates",
            "runtime.knowledge_graph.source_registry._MEDIA",
            "runtime.knowledge_graph.adapters.IMAGES_ADAPTER",
            "runtime.knowledge_graph.orchestrator.BuildOrchestrator",
        ],
        "capabilities": {
            "source_ingestion": "implemented_bounded", "raw_persistence": "in_memory_only",
            "normalization": "implemented", "taxonomic_reconciliation": "candidate_builder_only",
            "provenance": "implemented_in_candidates", "staging_graph_projection": "registered",
            "publication_readiness": "blocked", "freshness_or_checkpoint_monitoring": "in_memory_only",
            "mission_control_visibility": "telemetry_only",
        },
        "blockers": [
            "No durable executable persists normalized licensed images into oc_core media relations.",
            "No executable bridges harvested image records through verified canonical record-media links into the registered gallery projection.",
        ],
        "next_job": "python scripts/run_bounded_resumable_graph_dry_run.py",
    },
    "literature": {
        "status": "partial",
        "components": [
            "app.literature_extraction.cli.run_cli",
            "app.literature_extraction.repository.LiteratureResultRepository",
            "app.literature_extraction.normalization.normalize_and_reconcile",
            "app.literature_extraction.candidate_handoff.LiteratureCandidateHandoffService",
            "runtime.knowledge_graph.source_registry._LITERATURE",
            "runtime.knowledge_graph.adapters.LITERATURE_ADAPTER",
        ],
        "capabilities": {
            "source_ingestion": "text_file_only", "raw_persistence": "local_file_store",
            "normalization": "implemented", "taxonomic_reconciliation": "name_join_only",
            "provenance": "implemented", "staging_graph_projection": "registered",
            "publication_readiness": "blocked", "freshness_or_checkpoint_monitoring": "missing",
            "mission_control_visibility": "paper_lookup_only",
        },
        "blockers": [
            "No DOI or URL fetcher is wired into the executable literature extraction CLI/API.",
            "Literature graph source rows lack canonical taxon ids and rely on an exact name join.",
            "No freshness or resumable ingestion checkpoint is implemented for literature evidence.",
        ],
        "next_job": "python -m app.literature_extraction tests/fixtures/literature/calyx_brain_001_orchid_study.txt --output /tmp/calyx-literature-bounded",
    },
}


def build_graph_pipeline_readiness(
    *,
    taxonomy_root: str | Path | None = None,
    literature_root: str | Path | None = None,
    count_observer: CountObserver | None = None,
) -> dict[str, Any]:
    """Build the machine-readable contract without writing external state."""
    taxonomy_path = Path(taxonomy_root or os.getenv(
        "CALYX_TAXONOMY_INTAKE_DIR", "/tmp/calyx/taxonomy-releases"
    ))
    literature_path = Path(literature_root or os.getenv(
        "LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction"
    ))
    tax_count, tax_checkpoint = _local_taxonomy_observation(taxonomy_path)
    lit_count, lit_checkpoint = _local_literature_observation(literature_path)
    local = {
        "taxonomy": (tax_count, tax_checkpoint),
        "literature": (lit_count, lit_checkpoint),
    }

    domains: list[dict[str, Any]] = []
    for name, definition in DOMAIN_DEFINITIONS.items():
        count = None
        if count_observer is not None:
            count = count_observer(name)
        if count is None:
            count = local.get(name, (_unknown_count(
                "No read-only live count observer is configured for this domain."
            ), {}))[0]
        checkpoint = local.get(name, (None, {
            "state": "not_observed", "source": None, "updated_at": None,
            "checkpoint": None,
        }))[1]
        domains.append({
            "domain": name,
            "status": definition["status"],
            "executable_components": list(definition["components"]),
            "capabilities": dict(definition["capabilities"]),
            "source_checkpoint": checkpoint,
            "record_count": count,
            "graph_projection": (
                {"state": "missing", "staging_only": True,
                 "production_graph_mutation": False, "source_query": None,
                 "adapter": None, "taxon_mapping": "canonical_release"}
                if name == "taxonomy" else _projection(name)
            ),
            "blockers": list(definition["blockers"]),
            "exact_next_executable_job": definition["next_job"],
        })

    return {
        "contract": CONTRACT,
        "read_only": True,
        "production_graph_mutation": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "statuses": sorted(STATUSES),
        "domains": domains,
        "summary": {status: sum(d["status"] == status for d in domains) for status in sorted(STATUSES)},
        "priority_order": ["taxonomy", "occurrences", "licensed_images", "literature"],
        "first_safe_bounded_job_after_merge": "python scripts/smoke_world_plants_activation.py",
    }
