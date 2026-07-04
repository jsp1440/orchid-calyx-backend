"""BUILD-017 Brain-backed knowledge gap diagnostics.

BUILD-016 scored knowledge coverage from runtime discovery only. BUILD-017 adds a
second evidence layer from the live Brain database catalog so existing Orchid
Continuum tables can reduce false gaps and produce better implementation queues.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - deployment dependent
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]

from .knowledge_gap_discovery import DOMAIN_KEYWORDS, KnowledgeGapDiscoveryEngine


REPO_ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTIC_DIR = REPO_ROOT / "runtime" / "knowledge_gap_diagnostics"


DOMAIN_TABLE_HINTS: dict[str, list[str]] = {
    "Taxonomy": ["taxonomy", "taxon", "species", "genus", "synonym", "name"],
    "Images": ["image", "media", "photo", "vision", "asset"],
    "Occurrences": ["occurrence", "atlas", "gbif", "inat", "geo", "location"],
    "Pollination": ["pollination", "pollinator", "interaction", "globi", "ecology"],
    "Mycorrhiza": ["mycorrhiza", "fungal", "fungus"],
    "Conservation": ["conservation", "iucn", "threat", "habitat", "climate"],
    "Literature": ["literature", "citation", "reference", "paper", "doc", "claim"],
    "Traits": ["trait", "morphology", "phenology", "flower", "life", "eol"],
    "Governance": ["governance", "review", "audit", "provenance", "claim", "source"],
}


@dataclass
class DomainDiagnostic:
    domain: str
    runtime_status: str
    runtime_score: int
    brain_score: int
    adjusted_score: int
    status: str
    runtime_matches: list[str] = field(default_factory=list)
    brain_matches: list[dict[str, str]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


class KnowledgeGapDiagnosticsEngine:
    """Combine BUILD-016 runtime gaps with live Brain schema/table evidence."""

    def __init__(
        self,
        output_dir: Path | None = None,
        gap_engine: KnowledgeGapDiscoveryEngine | None = None,
        inventory: dict[str, Any] | None = None,
    ) -> None:
        self.output_dir = output_dir or DIAGNOSTIC_DIR
        self.latest_path = self.output_dir / "latest.json"
        self.gap_engine = gap_engine or KnowledgeGapDiscoveryEngine()
        self.database_url = os.environ.get("DATABASE_URL")
        self._inventory_override = inventory
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def diagnose(self, write_cache: bool = True) -> dict[str, Any]:
        base = self.gap_engine.latest()
        inventory = self._brain_inventory()
        diagnostics = self._domain_diagnostics(base.get("domain_coverage", {}), inventory)
        gaps = self._ranked_gaps(diagnostics)
        payload = {
            "build": "BUILD-017",
            "status": "brain_backed_gap_diagnostics_ready",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_build": base.get("build"),
            "source_snapshot_id": base.get("source_snapshot_id"),
            "brain": {
                "status": inventory.get("status"),
                "connection": inventory.get("connection"),
                "schema_count": inventory.get("schema_count", 0),
                "table_count": inventory.get("table_count", 0),
                "message": inventory.get("message"),
            },
            "summary": {
                "domains": len(diagnostics),
                "gaps": len(gaps),
                "covered": sum(1 for item in diagnostics if item.status == "covered"),
                "thin": sum(1 for item in diagnostics if item.status == "thin"),
                "critical": sum(1 for item in gaps if item["priority"] == "CRITICAL"),
                "high": sum(1 for item in gaps if item["priority"] == "HIGH"),
            },
            "domain_diagnostics": {item.domain: asdict(item) for item in diagnostics},
            "gaps": gaps,
            "top_actions": [item["proposed_action"] for item in gaps[:5]],
        }
        if write_cache:
            self.latest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    def latest(self) -> dict[str, Any]:
        if self.latest_path.exists():
            return json.loads(self.latest_path.read_text(encoding="utf-8"))
        return self.diagnose(write_cache=True)

    def domains(self) -> dict[str, Any]:
        payload = self.latest()
        return {"build": "BUILD-017", "count": len(payload.get("domain_diagnostics", {})), "domains": payload.get("domain_diagnostics", {})}

    def gaps(self) -> dict[str, Any]:
        payload = self.latest()
        return {"build": "BUILD-017", "count": len(payload.get("gaps", [])), "gaps": payload.get("gaps", [])}

    def queue(self, limit: int = 10) -> dict[str, Any]:
        gaps = self.latest().get("gaps", [])[:limit]
        return {
            "build": "BUILD-017",
            "queue_depth": len(gaps),
            "queue": [
                {
                    "queue_rank": index + 1,
                    "gap_id": gap["gap_id"],
                    "domain": gap["domain"],
                    "task": gap["proposed_action"],
                    "priority": gap["priority"],
                    "adjusted_score": gap["adjusted_score"],
                }
                for index, gap in enumerate(gaps)
            ],
        }

    def dashboard(self) -> dict[str, Any]:
        payload = self.latest()
        return {
            "build": "BUILD-017",
            "status": payload.get("status"),
            "brain": payload.get("brain", {}),
            "summary": payload.get("summary", {}),
            "top_gaps": payload.get("gaps", [])[:5],
            "top_actions": payload.get("top_actions", []),
        }

    def _brain_inventory(self) -> dict[str, Any]:
        if self._inventory_override is not None:
            return self._normalize_inventory(self._inventory_override, status="provided", connection="test_inventory")
        if not self.database_url:
            return {
                "status": "degraded",
                "connection": "unavailable",
                "schema_count": 0,
                "table_count": 0,
                "tables": [],
                "message": "DATABASE_URL is not configured; diagnostics use runtime discovery only.",
            }
        if psycopg is None:
            return {
                "status": "degraded",
                "connection": "unavailable",
                "schema_count": 0,
                "table_count": 0,
                "tables": [],
                "message": "psycopg is unavailable; diagnostics use runtime discovery only.",
            }
        try:
            schemas: list[str] = []
            tables: list[dict[str, str]] = []
            with psycopg.connect(self.database_url, connect_timeout=10) as conn:  # type: ignore[union-attr]
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT schema_name
                        FROM information_schema.schemata
                        WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
                        ORDER BY schema_name
                        LIMIT 200
                        """
                    )
                    schemas = [str(row[0]) for row in cur.fetchall()]
                    cur.execute(
                        """
                        SELECT table_schema, table_name
                        FROM information_schema.tables
                        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                          AND table_type = 'BASE TABLE'
                        ORDER BY table_schema, table_name
                        LIMIT 1000
                        """
                    )
                    tables = [{"schema": str(row[0]), "table": str(row[1])} for row in cur.fetchall()]
            return {
                "status": "connected",
                "connection": "connected",
                "schema_count": len(schemas),
                "table_count": len(tables),
                "schemas": schemas,
                "tables": tables,
                "message": "Live Brain database inventory available.",
            }
        except Exception as exc:
            return {
                "status": "degraded",
                "connection": "failed",
                "schema_count": 0,
                "table_count": 0,
                "tables": [],
                "message": f"Brain database inventory failed: {exc}",
            }

    def _normalize_inventory(self, inventory: dict[str, Any], status: str, connection: str) -> dict[str, Any]:
        tables = inventory.get("tables", []) or inventory.get("tables_sample", []) or []
        schemas = inventory.get("schemas", []) or []
        schema_names = [item.get("schema", item) if isinstance(item, dict) else item for item in schemas]
        return {
            "status": inventory.get("status", status),
            "connection": inventory.get("connection", connection),
            "schema_count": inventory.get("schema_count", len(schema_names)),
            "table_count": inventory.get("table_count", len(tables)),
            "schemas": [str(item) for item in schema_names],
            "tables": tables,
            "message": inventory.get("message"),
        }

    def _domain_diagnostics(self, runtime_coverage: dict[str, Any], inventory: dict[str, Any]) -> list[DomainDiagnostic]:
        tables = inventory.get("tables", [])
        diagnostics: list[DomainDiagnostic] = []
        for domain in DOMAIN_KEYWORDS:
            runtime = runtime_coverage.get(domain, {})
            runtime_matches = [str(item) for item in runtime.get("matched_items", [])]
            brain_matches = self._brain_matches(domain, tables)
            runtime_score = int(runtime.get("coverage_score", 0))
            brain_score = min(100, len(brain_matches) * 25)
            adjusted_score = max(runtime_score, brain_score)
            status = "covered" if adjusted_score >= 60 else "thin" if adjusted_score else "gap"
            diagnostics.append(
                DomainDiagnostic(
                    domain=domain,
                    runtime_status=str(runtime.get("status", "unknown")),
                    runtime_score=runtime_score,
                    brain_score=brain_score,
                    adjusted_score=adjusted_score,
                    status=status,
                    runtime_matches=runtime_matches,
                    brain_matches=brain_matches[:25],
                    evidence=[f"Runtime matched items: {len(runtime_matches)}", f"Brain matched tables: {len(brain_matches)}"],
                )
            )
        return diagnostics

    def _brain_matches(self, domain: str, tables: list[dict[str, Any]]) -> list[dict[str, str]]:
        keywords = DOMAIN_TABLE_HINTS.get(domain, DOMAIN_KEYWORDS[domain])
        matches: list[dict[str, str]] = []
        for item in tables:
            schema = str(item.get("schema", ""))
            table = str(item.get("table", ""))
            haystack = f"{schema}.{table}".lower()
            if any(keyword in haystack for keyword in keywords):
                matches.append({"schema": schema, "table": table})
        unique = {(item["schema"], item["table"]): item for item in matches}
        return list(unique.values())

    def _ranked_gaps(self, diagnostics: list[DomainDiagnostic]) -> list[dict[str, Any]]:
        gaps: list[dict[str, Any]] = []
        for item in diagnostics:
            if item.status == "covered":
                continue
            severity = 100 - item.adjusted_score
            priority = "CRITICAL" if severity >= 90 else "HIGH" if severity >= 70 else "MEDIUM"
            action = "Connect live Brain tables to runtime validators and review-ready outputs."
            if item.brain_matches:
                action = f"Promote existing {item.domain} Brain tables into runtime validators and review-ready outputs."
            gaps.append(
                {
                    "gap_id": f"KG17-{item.domain.upper().replace(' ', '-')}-001",
                    "domain": item.domain,
                    "title": f"{item.domain} runtime coverage is {item.status}",
                    "priority": priority,
                    "severity_score": severity,
                    "adjusted_score": item.adjusted_score,
                    "runtime_score": item.runtime_score,
                    "brain_score": item.brain_score,
                    "evidence": item.evidence,
                    "proposed_action": action,
                    "source": "BUILD-017",
                }
            )
        return sorted(gaps, key=lambda item: item["severity_score"], reverse=True)
