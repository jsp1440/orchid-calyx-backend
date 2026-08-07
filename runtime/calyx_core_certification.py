"""Read-only Calyx Core certification and production observability report."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.graph_pipeline_readiness import build_graph_pipeline_readiness

CONTRACT = "calyx-core-certification-v2"
PRODUCTION_OBSERVABILITY_CONTRACT = "calyx-production-certification-v1"
REASONING_RELATIONS = (
    "reasoning_ledger.ledger_heads",
    "reasoning_ledger.ledger_revisions",
    "reasoning_publication.publication_artifacts",
    "reasoning_publication.publication_attempts",
)


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


def _operational_domains(
    taxonomy_root: Path, literature_root: Path
) -> dict[str, dict[str, Any]]:
    readiness = build_graph_pipeline_readiness(
        taxonomy_root=taxonomy_root,
        literature_root=literature_root,
    )
    return {item["domain"]: item for item in readiness["domains"]}


def _latest_mtime(root: Path, pattern: str) -> str | None:
    if not root.exists():
        return None
    candidates = [path for path in root.glob(pattern) if path.is_file()]
    if not candidates:
        return None
    latest = max(path.stat().st_mtime for path in candidates)
    return datetime.fromtimestamp(latest, tz=UTC).isoformat()


def _pipeline_readiness(taxonomy_root: Path, literature_root: Path) -> dict[str, Any]:
    taxonomy_reports = (
        list(taxonomy_root.glob("*/report.json")) if taxonomy_root.exists() else []
    )
    literature_papers = (
        list(literature_root.glob("*/paper.json")) if literature_root.exists() else []
    )
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
            "state": (
                "inspected_releases_present"
                if taxonomy_reports
                else "no_releases"
                if taxonomy_root.exists()
                else "intake_directory_absent"
            ),
            "release_count": len(taxonomy_reports),
            "source": str(taxonomy_root),
            "latest_local_evidence_at": _latest_mtime(taxonomy_root, "*/report.json"),
            "production_promotion": "blocked_pending_owner_approval",
            **operational_state("taxonomy"),
        },
        "literature": {
            "state": "staging_module_available",
            "paper_state": (
                "papers_present"
                if literature_papers
                else "no_papers"
                if literature_root.exists()
                else "extraction_directory_absent"
            ),
            "paper_count": len(literature_papers),
            "source": str(literature_root),
            "latest_local_evidence_at": _latest_mtime(literature_root, "*/paper.json"),
            "staging_module": "runtime.literature_staging",
            **operational_state("literature"),
        },
        "occurrences": {
            "state": "staging_module_available",
            "module": "runtime.occurrence_staging",
            "supported_sources": ["gbif", "inaturalist"],
            "idempotency": "checksum-deduplicated",
            "canonical_taxon_reconciliation": "adapter_available_not_durable_crosswalk",
            "unresolved_records": "explicit_review_queue",
            "latest_local_evidence_at": None,
            **operational_state("occurrences"),
        },
        "licensed_images": {
            "state": "staging_module_available",
            "module": "runtime.image_staging",
            "supported_sources": ["gbif", "inaturalist"],
            "license_enforcement": "allowlist_active",
            "idempotency": "checksum-deduplicated",
            "unresolved_records": "explicit_review_queue",
            "latest_local_evidence_at": None,
            **operational_state("licensed_images"),
        },
    }


def _configuration_presence() -> dict[str, str]:
    return {
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
    }


def _safe_group_counts(connection: Any, statement: str) -> dict[str, int] | None:
    from sqlalchemy import text

    try:
        rows = connection.execute(text(statement)).fetchall()
    except Exception:  # noqa: BLE001 - absent operational tables are reported, not fatal
        return None
    return {str(row[0]): int(row[1]) for row in rows}


def _production_observability(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Collect bounded live state without returning secret values or mutating data."""

    from sqlalchemy import text

    from app.calyx_orchestrator.autonomy_policy import program_autonomy_status
    from app.database import get_engine

    environment = dict(os.environ if env is None else env)
    deployed_commit = (
        environment.get("RENDER_GIT_COMMIT")
        or environment.get("CALYX_DEPLOYED_COMMIT")
        or environment.get("GIT_COMMIT")
        or environment.get("SOURCE_VERSION")
    )
    expected_main = environment.get("CALYX_EXPECTED_MAIN_COMMIT")
    commit_match = (
        deployed_commit == expected_main
        if deployed_commit and expected_main
        else None
    )

    remediations: list[dict[str, str]] = []
    if not deployed_commit:
        remediations.append(
            {
                "code": "DEPLOYED_COMMIT_UNAVAILABLE",
                "action": "Expose the deployed revision through RENDER_GIT_COMMIT or CALYX_DEPLOYED_COMMIT.",
            }
        )
    if not expected_main:
        remediations.append(
            {
                "code": "EXPECTED_MAIN_COMMIT_UNAVAILABLE",
                "action": "Set CALYX_EXPECTED_MAIN_COMMIT from the release pipeline before certification.",
            }
        )
    elif commit_match is False:
        remediations.append(
            {
                "code": "DEPLOYED_COMMIT_BEHIND_MAIN",
                "action": "Deploy the reviewed current-main revision before treating production as certified.",
            }
        )

    database: dict[str, Any] = {
        "reachable": False,
        "dialect": None,
        "error_type": None,
    }
    migration_state: dict[str, str] = {name: "unknown" for name in REASONING_RELATIONS}
    queues: dict[str, Any] = {
        "engineering_job_status_counts": None,
        "blocked_or_failed_jobs": None,
    }
    review_queue: dict[str, Any] = {"ledger_revision_status_counts": None}

    try:
        engine = get_engine()
        database["dialect"] = engine.dialect.name
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            database["reachable"] = True
            if engine.dialect.name == "postgresql":
                for relation in REASONING_RELATIONS:
                    row = connection.execute(
                        text("SELECT to_regclass(:relation)"), {"relation": relation}
                    ).fetchone()
                    migration_state[relation] = "present" if row and row[0] else "absent"
                queues["engineering_job_status_counts"] = _safe_group_counts(
                    connection,
                    "SELECT status, count(*) FROM calyx_engineering_program_jobs GROUP BY status",
                )
                queues["blocked_or_failed_jobs"] = connection.execute(
                    text(
                        "SELECT count(*) FROM calyx_engineering_program_jobs "
                        "WHERE status = 'blocked' OR blocker IS NOT NULL"
                    )
                ).scalar_one_or_none()
                if migration_state["reasoning_ledger.ledger_revisions"] == "present":
                    review_queue["ledger_revision_status_counts"] = _safe_group_counts(
                        connection,
                        "SELECT status, count(*) FROM reasoning_ledger.ledger_revisions GROUP BY status",
                    )
    except Exception as exc:  # noqa: BLE001 - report only exception type, never DSN/detail
        database["error_type"] = type(exc).__name__

    if not database["reachable"]:
        remediations.append(
            {
                "code": "DATABASE_UNREACHABLE",
                "action": "Verify the production database binding and rerun the read-only certification probe.",
            }
        )
    missing_reasoning = [
        relation for relation, state in migration_state.items() if state == "absent"
    ]
    if missing_reasoning:
        remediations.append(
            {
                "code": "REASONING_SCHEMA_INCOMPLETE",
                "action": (
                    "Run the protected CALYX Reasoning Schema Production Activation preflight; "
                    "production apply still requires explicit owner go/no-go."
                ),
            }
        )
    if queues["engineering_job_status_counts"] is None:
        remediations.append(
            {
                "code": "ENGINEERING_QUEUE_METRICS_UNAVAILABLE",
                "action": "Verify calyx_engineering_program_jobs exists in the bound operational database.",
            }
        )

    configuration = {
        "database_url": "present" if environment.get("DATABASE_URL", "").strip() else "absent",
        "api_key": "present" if environment.get("CALYX_API_KEY", "").strip() else "absent",
        "owner_access_code": (
            "present" if environment.get("CALYX_OWNER_ACCESS_CODE", "").strip() else "absent"
        ),
        "owner_session_secret": (
            "present" if environment.get("CALYX_OWNER_SESSION_SECRET", "").strip() else "absent"
        ),
    }
    for key, state in configuration.items():
        if state == "absent":
            remediations.append(
                {
                    "code": f"CONFIGURATION_ABSENT:{key}",
                    "action": f"Configure the protected production setting for {key}; do not place its value in certification output.",
                }
            )

    graph_version = environment.get("CALYX_GRAPH_VERSION") or None
    if graph_version is None:
        remediations.append(
            {
                "code": "GRAPH_VERSION_UNAVAILABLE",
                "action": "Expose the deployed Knowledge Graph version through CALYX_GRAPH_VERSION or a read-only graph version probe.",
            }
        )

    blockers = sorted({item["code"] for item in remediations})
    return {
        "contract": PRODUCTION_OBSERVABILITY_CONTRACT,
        "read_only": True,
        "secret_values_returned": False,
        "deployment": {
            "deployed_commit": deployed_commit,
            "expected_main_commit": expected_main,
            "matches_expected_main": commit_match,
        },
        "authentication_configuration": configuration,
        "database": database,
        "migration_state": migration_state,
        "worker": program_autonomy_status(environment),
        "queues": queues,
        "review_queue": review_queue,
        "graph": {"version": graph_version},
        "blockers": blockers,
        "remediations": remediations,
        "automatic_deployment": False,
        "automatic_publication": False,
        "production_database_mutation": False,
        "production_knowledge_graph_mutation": False,
    }


def build_calyx_core_certification(
    *,
    taxonomy_root: Path | None = None,
    literature_root: Path | None = None,
    deployed_commit: str | None = None,
    include_live_probes: bool = False,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    environment = dict(os.environ if env is None else env)
    tax_root = taxonomy_root or Path(
        environment.get("CALYX_TAXONOMY_INTAKE_DIR", "/tmp/calyx/taxonomy-releases")
    )
    lit_root = literature_root or Path(
        environment.get("LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction")
    )
    route_checks = _route_checks()
    import_errors = [
        module for module, state in route_checks.items() if state.startswith("import_error")
    ]
    pipeline_domains = _pipeline_readiness(tax_root, lit_root)
    operational_blockers = {
        domain: details["operational_blockers"]
        for domain, details in pipeline_domains.items()
        if details.get("operational_blockers")
    }
    report: dict[str, Any] = {
        "contract": CONTRACT,
        "generated_at": datetime.now(UTC).isoformat(),
        "deployed_commit": deployed_commit
        or environment.get("CALYX_DEPLOYED_COMMIT", "unknown"),
        "overall_status": (
            "import_errors_present"
            if import_errors
            else "partial_operational_readiness"
            if operational_blockers
            else "ready_for_validation"
        ),
        "route_module_checks": route_checks,
        "configuration_presence": _configuration_presence(),
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
    if include_live_probes:
        report["production_observability"] = _production_observability(environment)
    return report


def create_certification_router(require_owner: Callable[..., Any] | None = None) -> Any:
    from fastapi import APIRouter, Depends

    from app.security import verify_owner_or_api_key

    auth = require_owner or verify_owner_or_api_key
    router = APIRouter(tags=["calyx-certification"])

    @router.get("/mission-control/calyx-core/certification")
    def certification(_: Any = Depends(auth)) -> dict[str, Any]:  # noqa: B008
        return build_calyx_core_certification(include_live_probes=True)

    return router
