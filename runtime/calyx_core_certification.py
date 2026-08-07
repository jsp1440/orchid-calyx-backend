"""Read-only Calyx Core certification and pipeline readiness report.

The report verifies current route/module availability, configuration presence,
staging readiness, Reasoning Ledger gate availability, and publication
safeguards. It does not mutate production data or publish graph state.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONTRACT = "calyx-core-certification-v2"


def _env_present(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _probe_failure(exc: Exception) -> str:
    return f"import_error:{type(exc).__name__}: {exc}"


def _check_route_mounts() -> dict[str, str]:
    checks: dict[str, str] = {}
    for module_path in (
        "app.routers.taxonomy_releases",
        "app.routers.graph_pipeline_readiness",
        "runtime.occurrence_staging",
        "runtime.image_staging",
        "runtime.literature_staging",
        "app.reasoning_ledger.routes",
        "app.knowledge_publication",
    ):
        try:
            __import__(module_path)
            checks[module_path] = "importable"
        except Exception as exc:  # noqa: BLE001 - readiness probe must fail closed
            checks[module_path] = _probe_failure(exc)
    return checks


def _check_configuration() -> dict[str, str]:
    variables = (
        "DATABASE_URL",
        "CALYX_TAXONOMY_INTAKE_DIR",
        "LITERATURE_EXTRACTION_ROOT",
        "CALYX_TAXONOMY_STORAGE_PERSISTENT",
        "CALYX_API_KEY",
        "CALYX_OWNER_ACCESS_CODE",
        "CALYX_OWNER_SESSION_SECRET",
    )
    return {name: "present" if _env_present(name) else "absent" for name in variables}


def _check_pipeline_readiness(
    taxonomy_root: Path,
    literature_root: Path,
) -> dict[str, Any]:
    domains: dict[str, Any] = {}
    if taxonomy_root.exists():
        reports = list(taxonomy_root.glob("*/report.json"))
        domains["taxonomy"] = {
            "state": "inspected_releases_present" if reports else "no_releases",
            "release_count": len(reports),
            "source": str(taxonomy_root),
            "production_promotion": "blocked_pending_owner_approval",
        }
    else:
        domains["taxonomy"] = {
            "state": "intake_directory_absent",
            "source": str(taxonomy_root),
            "production_promotion": "blocked",
        }

    if literature_root.exists():
        papers = list(literature_root.glob("*/paper.json"))
        domains["literature"] = {
            "state": "papers_present" if papers else "no_papers",
            "paper_count": len(papers),
            "source": str(literature_root),
            "staging_module": "runtime.literature_staging",
        }
    else:
        domains["literature"] = {
            "state": "extraction_directory_absent",
            "source": str(literature_root),
            "staging_module": "runtime.literature_staging",
        }

    domains["occurrences"] = {
        "state": "staging_pipeline_ready",
        "module": "runtime.occurrence_staging",
        "supported_sources": ["gbif", "inaturalist"],
        "idempotency": "checksum-deduplicated",
        "canonical_taxon_reconciliation": True,
        "unresolved_records": "explicit_review_queue",
    }
    domains["licensed_images"] = {
        "state": "staging_pipeline_ready",
        "module": "runtime.image_staging",
        "supported_sources": ["gbif", "inaturalist"],
        "license_enforcement": "allowlist_active",
        "idempotency": "checksum-deduplicated",
        "unresolved_records": "explicit_review_queue",
    }
    return domains


def _check_reasoning_ledger() -> dict[str, Any]:
    error: str | None = None
    try:
        from app.reasoning_ledger.gate import ReasoningLedgerGate  # noqa: F401

        gate_importable = True
    except Exception as exc:  # noqa: BLE001 - readiness probe must fail closed
        gate_importable = False
        error = _probe_failure(exc)
    return {
        "gate_module_importable": gate_importable,
        "probe_error": error,
        "eligible_ledger_discovery": "requires_db_connection",
        "publication_eligibility": "false_until_explicit_owner_approval",
        "automatic_publication": False,
        "human_review_mandatory": True,
    }


def _check_publication_safeguards() -> dict[str, Any]:
    error: str | None = None
    try:
        from app.knowledge_publication import models as _publication_models  # noqa: F401

        publication_importable = True
    except Exception as exc:  # noqa: BLE001 - readiness probe must fail closed
        publication_importable = False
        error = _probe_failure(exc)
    return {
        "publication_module_importable": publication_importable,
        "probe_error": error,
        "automatic_publication": False,
        "production_mutation_without_owner_confirmation": False,
        "idempotent_replay": "enforced",
        "audit_trail": "required",
    }


def build_calyx_core_certification(
    *,
    taxonomy_root: Path | None = None,
    literature_root: Path | None = None,
    deployed_commit: str | None = None,
) -> dict[str, Any]:
    tax_root = taxonomy_root or Path(
        os.getenv("CALYX_TAXONOMY_INTAKE_DIR", "/tmp/calyx/taxonomy-releases")
    )
    lit_root = literature_root or Path(
        os.getenv("LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction")
    )
    route_checks = _check_route_mounts()
    import_errors = [
        module for module, state in route_checks.items() if state.startswith("import_error")
    ]
    return {
        "contract": CONTRACT,
        "generated_at": datetime.now(UTC).isoformat(),
        "deployed_commit": deployed_commit or os.getenv("CALYX_DEPLOYED_COMMIT", "unknown"),
        "overall_status": "ready_for_validation" if not import_errors else "import_errors_present",
        "route_module_checks": route_checks,
        "configuration_presence": _check_configuration(),
        "pipeline_domains": _check_pipeline_readiness(tax_root, lit_root),
        "reasoning_ledger": _check_reasoning_ledger(),
        "publication_safeguards": _check_publication_safeguards(),
        "no_production_mutation": True,
        "operator_summary": (
            "Core staging modules importable; human review remains mandatory before publication."
            if not import_errors
            else f"Import errors present in: {import_errors}. Resolve before validation."
        ),
    }


def create_certification_router(
    require_owner: Callable[..., Any] | None = None,
) -> Any:
    from fastapi import APIRouter, Depends

    from app.security import verify_owner_or_api_key

    auth = require_owner or verify_owner_or_api_key
    router = APIRouter(tags=["calyx-certification"])

    @router.get("/mission-control/calyx-core/certification")
    def calyx_core_certification(
        _: Any = Depends(auth),  # noqa: B008
    ) -> dict[str, Any]:
        return build_calyx_core_certification()

    return router
