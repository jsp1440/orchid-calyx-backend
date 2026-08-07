"""Read-only Calyx Core certification and pipeline readiness report."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.graph_pipeline_readiness import build_graph_pipeline_readiness

CONTRACT = "calyx-core-certification-v2"


def _present(name: str) -> str:
    return "present" if os.getenv(name, "").strip() else "absent"


def _probe(module_path: str) -> str:
    try:
        __import__(module_path)
        return "importable"
    except Exception as exc:  # noqa: BLE001 - readiness probe must fail closed
        return f"import_error:{type(exc).__name__}: {exc}"


def _route_checks() -> dict[str, str]:
    modules = (
        "app.routers.taxonomy_releases",
        "app.routers.graph_pipeline_readiness",
        "runtime.occurrence_staging",
        "runtime.image_staging",
        "runtime.literature_staging",
        "app.reasoning_ledger.routes",
        "app.knowledge_publication",
    )
    return {module: _probe(module) for module in modules}


def _operational_domains(taxonomy_root: Path, literature_root: Path) -> dict[str, dict[str, Any]]:
    readiness = build_graph_pipeline_readiness(
        taxonomy_root=taxonomy_root,
        literature_root=literature_root,
    )
    return {item["domain"]: item for item in readiness["domains"]}


def _pipeline_readiness(taxonomy_root: Path, literature_root: Path) -> dict[str, Any]:
    taxonomy_reports = list(taxonomy_root.glob("*/report.json")) if taxonomy_root.exists() else []
    literature_papers = list(literature_root.glob("*/paper.json")) if literature_root.exists() else []
    operational = _operational_domains(taxonomy_root, literature_root)

    def operational_state(domain: str) -> dict[str, Any]:
        report = operational.get(domain, {})
        return {
            "operational_status": report.get("status", "unknown"),
            "operational_blockers": list(report.get("blockers", [])),
            "operational_capabilities": dict(report.get("capabilities", {})),
            "exact_next_executable_job": report.get("exact_next_executable_job"),
        }

    return {
        "taxonomy": {
            "state": "inspected_releases_present" if taxonomy_reports else "no_releases" if taxonomy_root.exists() else "intake_directory_absent",
            "release_count": len(taxonomy_reports),
            "source": str(taxonomy_root),
            "production_promotion": "blocked_pending_owner_approval",
            **operational_state("taxonomy"),
        },
        "literature": {
            "state": "staging_module_available",
            "paper_state": "papers_present" if literature_papers else "no_papers" if literature_root.exists() else "extraction_directory_absent",
            "paper_count": len(literature_papers),
            "source": str(literature_root),
            "staging_module": "runtime.literature_staging",
            **operational_state("literature"),
        },
        "occurrences": {
            "state": "staging_pipeline_ready",
            "module": "runtime.occurrence_staging",
            "supported_sources": ["gbif", "inaturalist"],
            "idempotency": "checksum-deduplicated",
            "canonical_taxon_reconciliation": "adapter_available_not_durable_crosswalk",
            "unresolved_records": "explicit_review_queue",
            **operational_state("occurrences"),
        },
        "licensed_images": {
            "state": "staging_module_available",
            "module": "runtime.image_staging",
            "supported_sources": ["gbif", "inaturalist"],
            "license_enforcement": "allowlist_active",
            "idempotency": "checksum-deduplicated",
            "unresolved_records": "explicit_review_queue",
            **operational_state("licensed_images"),
        },
    }


def build_calyx_core_certification(
    *,
    taxonomy_root: Path | None = None,
    literature_root: Path | None = None,
    deployed_commit: str | None = None,
) -> dict[str, Any]:
    tax_root = taxonomy_root or Path(os.getenv("CALYX_TAXONOMY_INTAKE_DIR", "/tmp/calyx/taxonomy-releases"))
    lit_root = literature_root or Path(os.getenv("LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction"))
    route_checks = _route_checks()
    import_errors = [module for module, state in route_checks.items() if state.startswith("import_error")]
    pipeline_domains = _pipeline_readiness(tax_root, lit_root)
    operational_blockers = {
        domain: details["operational_blockers"]
        for domain, details in pipeline_domains.items()
        if details.get("operational_blockers")
    }
    return {
        "contract": CONTRACT,
        "generated_at": datetime.now(UTC).isoformat(),
        "deployed_commit": deployed_commit or os.getenv("CALYX_DEPLOYED_COMMIT", "unknown"),
        "overall_status": (
            "import_errors_present"
            if import_errors
            else "partial_operational_readiness"
            if operational_blockers
            else "ready_for_validation"
        ),
        "route_module_checks": route_checks,
        "configuration_presence": {
            name: _present(name)
            for name in (
                "DATABASE_URL",
                "CALYX_TAXONOMY_INTAKE_DIR",
                "LITERATURE_EXTRACTION_ROOT",
                "CALYX_API_KEY",
                "CALYX_OWNER_ACCESS_CODE",
                "CALYX_OWNER_SESSION_SECRET",
                "CALYX_TAXONOMY_STORAGE_PERSISTENT",
            )
        },
        "pipeline_domains": pipeline_domains,
        "operational_blockers": operational_blockers,
        "reasoning_ledger": {
            "gate_module_importable": _probe("app.reasoning_ledger.gate") == "importable",
            "publication_eligibility": "false_until_explicit_human_approval",
            "automatic_publication": False,
            "human_review_mandatory": True,
        },
        "publication_safeguards": {
            "publication_module_importable": _probe("app.knowledge_publication") == "importable",
            "automatic_publication": False,
            "production_mutation_without_owner_confirmation": False,
            "audit_trail": "required",
        },
        "no_production_mutation": True,
    }


def create_certification_router(require_owner: Callable[..., Any] | None = None) -> Any:
    from fastapi import APIRouter, Depends

    from app.security import verify_owner_or_api_key

    auth = require_owner or verify_owner_or_api_key
    router = APIRouter(tags=["calyx-certification"])

    @router.get("/mission-control/calyx-core/certification")
    def certification(_: Any = Depends(auth)) -> dict[str, Any]:  # noqa: B008
        return build_calyx_core_certification()

    return router
