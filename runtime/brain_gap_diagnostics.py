"""BUILD-017 Brain-backed knowledge gap diagnostics.

This module upgrades BUILD-016 from runtime-only gap detection to live Brain-aware
coverage diagnostics. Database access is optional: when DATABASE_URL or psycopg is
unavailable the endpoints return a degraded result instead of failing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:  # pragma: no cover - deployment dependent
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]

from .knowledge_gap_discovery import DOMAIN_KEYWORDS, KnowledgeGapDiscoveryEngine


DOMAIN_TABLE_HINTS: dict[str, list[str]] = {
    "Taxonomy": ["taxon", "taxonomy", "species", "genus", "synonym", "world_plants"],
    "Images": ["image", "media", "photo", "asset", "vision"],
    "Occurrences": ["occurrence", "atlas", "gbif", "inat", "geo", "location"],
    "Pollination": ["pollination", "pollinator", "interaction", "globi"],
    "Mycorrhiza": ["mycorrhiza", "fungal", "fungus"],
    "Conservation": ["conservation", "iucn", "threat", "habitat", "climate"],
    "Literature": ["literature", "citation", "reference", "paper", "doc", "claim"],
    "Traits": ["trait", "morphology", "phenology", "flower"],
    "Governance": ["governance", "review", "audit", "provenance", "claim", "validation"],
}


@dataclass
class BrainTableMatch:
    schema: str
    table: str
    estimated_rows: int | None
    matched_keywords: list[str]


_UNSET = object()


class BrainGapDiagnostics:
    """Inspect live Brain tables and connect them to BUILD-016 gap domains."""

    def __init__(self, database_url: str | None = _UNSET) -> None:  # type: ignore[assignment]
        if database_url is _UNSET:
            self.database_url: str | None = os.environ.get("DATABASE_URL")
        else:
            self.database_url = database_url

    def status(self) -> dict[str, Any]:
        if not self.database_url:
            return self._degraded("DATABASE_URL is not configured.")
        if psycopg is None:
            return self._degraded("psycopg is unavailable in this runtime image.")
        return {
            "build": "BUILD-017",
            "status": "available",
            "brain_connection": "configured",
            "diagnostics": ["table inventory", "domain table matching", "row-count estimates", "gap enrichment"],
        }

    def diagnose(self) -> dict[str, Any]:
        status = self.status()
        if status.get("status") == "degraded":
            return status

        try:
            tables = self._load_tables()
        except Exception as exc:
            return self._degraded(f"Brain table inspection failed: {exc}")

        domain_tables = self._match_domain_tables(tables)
        coverage = self._coverage_from_tables(domain_tables)
        gaps = KnowledgeGapDiscoveryEngine().latest().get("gaps", [])
        enriched_gaps = self._enrich_gaps(gaps, domain_tables, coverage)
        payload = {
            "build": "BUILD-017",
            "status": "brain_gap_diagnostics_ready",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "brain_connection": "connected",
            "table_count": len(tables),
            "domains": coverage,
            "matched_tables": domain_tables,
            "enriched_gaps": enriched_gaps,
            "recommendations": self._recommendations(enriched_gaps),
        }
        return payload

    def domains(self) -> dict[str, Any]:
        payload = self.diagnose()
        return {"build": "BUILD-017", "status": payload.get("status"), "domains": payload.get("domains", {})}

    def gaps(self) -> dict[str, Any]:
        payload = self.diagnose()
        gaps = self._payload_gaps(payload)
        return {"build": "BUILD-017", "status": payload.get("status"), "count": len(gaps), "gaps": gaps}

    def queue(self, limit: int = 10) -> dict[str, Any]:
        gaps = self.gaps().get("gaps", [])[:limit]
        queue = [
            {
                "queue_rank": index + 1,
                "gap_id": gap.get("gap_id"),
                "domain": gap.get("domain"),
                "priority": gap.get("priority"),
                "task": gap.get("recommended_next_step") or gap.get("proposed_action"),
                "brain_tables": len(gap.get("brain_tables", [])),
            }
            for index, gap in enumerate(gaps)
        ]
        return {"build": "BUILD-017", "queue_depth": len(queue), "queue": queue}

    def dashboard(self) -> dict[str, Any]:
        payload = self.diagnose()
        gaps = self._payload_gaps(payload)
        return {
            "build": "BUILD-017",
            "status": payload.get("status"),
            "brain_connection": payload.get("brain_connection", "unavailable"),
            "table_count": payload.get("table_count", 0),
            "domain_count": len(payload.get("domains", {})),
            "enriched_gap_count": len(gaps),
            "top_gaps": gaps[:5],
            "recommendations": payload.get("recommendations", [])[:5],
            "fallback": payload.get("fallback"),
        }

    def _payload_gaps(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        enriched = payload.get("enriched_gaps")
        if isinstance(enriched, list):
            return enriched
        fallback = payload.get("fallback")
        if isinstance(fallback, dict):
            fallback_gaps = fallback.get("top_gaps") or fallback.get("gaps") or []
            if isinstance(fallback_gaps, list):
                return fallback_gaps
        return []

    def _load_tables(self) -> list[dict[str, Any]]:
        assert self.database_url is not None
        assert psycopg is not None
        with psycopg.connect(self.database_url, connect_timeout=10) as conn:  # type: ignore[union-attr]
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.table_schema,
                           t.table_name,
                           COALESCE(c.reltuples::bigint, 0) AS estimated_rows
                    FROM information_schema.tables t
                    LEFT JOIN pg_namespace n ON n.nspname = t.table_schema
                    LEFT JOIN pg_class c ON c.relname = t.table_name
                                        AND c.relnamespace = n.oid
                    WHERE t.table_schema NOT IN ('pg_catalog', 'information_schema')
                      AND t.table_type = 'BASE TABLE'
                    ORDER BY t.table_schema, t.table_name
                    LIMIT 500
                    """
                )
                return [
                    {"schema": row[0], "table": row[1], "estimated_rows": int(row[2]) if row[2] is not None else None}
                    for row in cur.fetchall()
                ]

    def _match_domain_tables(self, tables: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        matches: dict[str, list[dict[str, Any]]] = {domain: [] for domain in DOMAIN_TABLE_HINTS}
        for domain, keywords in DOMAIN_TABLE_HINTS.items():
            for table in tables:
                haystack = f"{table.get('schema', '')}.{table.get('table', '')}".lower()
                matched = [keyword for keyword in keywords if keyword in haystack]
                if matched:
                    matches[domain].append(
                        {
                            "schema": table.get("schema"),
                            "table": table.get("table"),
                            "estimated_rows": table.get("estimated_rows"),
                            "matched_keywords": matched,
                        }
                    )
        return matches

    def _coverage_from_tables(self, domain_tables: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
        coverage: dict[str, dict[str, Any]] = {}
        for domain, tables in domain_tables.items():
            total_rows = sum(max(0, int(table.get("estimated_rows") or 0)) for table in tables)
            table_count = len(tables)
            score = min(100, table_count * 20 + (20 if total_rows > 0 else 0))
            coverage[domain] = {
                "table_count": table_count,
                "estimated_rows": total_rows,
                "coverage_score": score,
                "status": "connected" if score >= 60 else "partial" if table_count else "not_connected",
                "keywords": DOMAIN_KEYWORDS.get(domain, []),
            }
        return coverage

    def _enrich_gaps(
        self,
        gaps: list[dict[str, Any]],
        domain_tables: dict[str, list[dict[str, Any]]],
        coverage: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        enriched = []
        for gap in gaps:
            domain = gap.get("domain", "")
            tables = domain_tables.get(domain, [])
            domain_coverage = coverage.get(domain, {})
            table_count = len(tables)
            if table_count:
                next_step = f"Map {domain.lower()} gap to {table_count} candidate Brain table(s) and add field-level completeness checks."
            else:
                next_step = f"Create or register Brain source tables for {domain.lower()} and define ingestion provenance."
            enriched.append(
                {
                    **gap,
                    "source": "BUILD-017",
                    "brain_status": domain_coverage.get("status", "not_connected"),
                    "brain_tables": tables[:20],
                    "brain_table_count": table_count,
                    "estimated_rows": domain_coverage.get("estimated_rows", 0),
                    "recommended_next_step": next_step,
                }
            )
        return sorted(enriched, key=lambda item: (item.get("brain_table_count", 0), -int(item.get("severity_score", 0))))

    def _recommendations(self, enriched_gaps: list[dict[str, Any]]) -> list[dict[str, str]]:
        recommendations: list[dict[str, str]] = []
        for gap in enriched_gaps[:8]:
            recommendations.append(
                {
                    "priority": gap.get("priority", "MEDIUM"),
                    "domain": gap.get("domain", "Unknown"),
                    "recommendation": gap.get("recommended_next_step", "Review gap."),
                }
            )
        return recommendations

    def _degraded(self, message: str) -> dict[str, Any]:
        fallback = KnowledgeGapDiscoveryEngine().dashboard()
        fallback_gaps = fallback.get("top_gaps") or fallback.get("gaps") or []
        return {
            "build": "BUILD-017",
            "status": "degraded",
            "brain_connection": "unavailable",
            "message": message,
            "fallback": fallback,
            "enriched_gaps": fallback_gaps,
            "recommendations": [
                {"priority": "HIGH", "recommendation": "Configure live Brain database access for BUILD-017 diagnostics."}
            ],
        }
