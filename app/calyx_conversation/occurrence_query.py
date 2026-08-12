"""Read-only structured occurrence queries for Calyx scientific turns.

This module recognizes a narrow, auditable class of distribution questions such
as "orchids in Ecuador above 3000 m" and evaluates them against the verified
bulk occurrence corpus.  Results are resolved to persisted Knowledge Graph taxon
nodes, so the relational evidence layer and graph identity remain connected.

The parser is deliberately conservative.  Unsupported natural-language forms
return ``not_requested`` rather than guessing a filter.  All SQL values are
parameterized and the module never mutates the graph or source corpus.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Literal

import psycopg

ElevationMode = Literal["above", "below", "between", "at"]

_COUNTRY = re.compile(
    r"\b(?:in|from|within)\s+([A-Z][A-Za-z .'-]{1,50}?)(?=\s+(?:that|which|where|above|over|below|under|between|at|occurr?|grow|found|recorded)\b|[?.!,]|$)"
)
_BETWEEN = re.compile(
    r"\bbetween\s+([0-9]{1,5}(?:\.[0-9]+)?)\s*(?:m|meters?|metres?)?\s+(?:and|to)\s+([0-9]{1,5}(?:\.[0-9]+)?)\s*(?:m|meters?|metres?)\b",
    re.I,
)
_ABOVE = re.compile(
    r"\b(?:above|over|higher\s+than|greater\s+than)\s+([0-9]{1,5}(?:\.[0-9]+)?)\s*(?:m|meters?|metres?)\b",
    re.I,
)
_BELOW = re.compile(
    r"\b(?:below|under|lower\s+than|less\s+than)\s+([0-9]{1,5}(?:\.[0-9]+)?)\s*(?:m|meters?|metres?)\b",
    re.I,
)
_AT = re.compile(
    r"\b(?:at|around)\s+([0-9]{1,5}(?:\.[0-9]+)?)\s*(?:m|meters?|metres?)\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class OccurrenceFilter:
    country: str
    elevation_mode: ElevationMode
    elevation_min_m: float | None = None
    elevation_max_m: float | None = None
    target_elevation_m: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "country": self.country,
            "elevation_mode": self.elevation_mode,
            "elevation_min_m": self.elevation_min_m,
            "elevation_max_m": self.elevation_max_m,
            "target_elevation_m": self.target_elevation_m,
        }


def parse_occurrence_filter(message: str) -> OccurrenceFilter | None:
    """Parse only explicit country + elevation constraints.

    This is intentionally not a general NLU parser.  A country and an explicit
    metric elevation constraint are both required before a database query is
    allowed.
    """
    text = str(message or "").strip()
    country_match = _COUNTRY.search(text)
    if not country_match:
        return None
    country = " ".join(country_match.group(1).split()).strip(" .,!?")
    if not country:
        return None

    between = _BETWEEN.search(text)
    if between:
        low, high = sorted((float(between.group(1)), float(between.group(2))))
        return OccurrenceFilter(country, "between", low, high, None)
    above = _ABOVE.search(text)
    if above:
        return OccurrenceFilter(country, "above", float(above.group(1)), None, None)
    below = _BELOW.search(text)
    if below:
        return OccurrenceFilter(country, "below", None, float(below.group(1)), None)
    at = _AT.search(text)
    if at:
        return OccurrenceFilter(country, "at", None, None, float(at.group(1)))
    return None


def _elevation_clause(filters: OccurrenceFilter) -> tuple[str, list[float]]:
    # Each occurrence may carry a point elevation or a reported min/max range.
    low_expr = "coalesce(o.minimum_elevation, o.elevation_meters, o.maximum_elevation)"
    high_expr = "coalesce(o.maximum_elevation, o.elevation_meters, o.minimum_elevation)"
    if filters.elevation_mode == "above":
        return f"{high_expr} >= %s", [float(filters.elevation_min_m)]
    if filters.elevation_mode == "below":
        return f"{low_expr} <= %s", [float(filters.elevation_max_m)]
    if filters.elevation_mode == "between":
        return (
            f"{high_expr} >= %s and {low_expr} <= %s",
            [float(filters.elevation_min_m), float(filters.elevation_max_m)],
        )
    target = float(filters.target_elevation_m)
    return f"{low_expr} <= %s and {high_expr} >= %s", [target, target]


def query_occurrence_constraints(
    message: str,
    *,
    dsn: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Return taxon-level occurrence evidence for an explicit geo/elevation query."""
    filters = parse_occurrence_filter(message)
    if filters is None:
        return {
            "status": "not_requested",
            "read_only": True,
            "knowledge_graph_mutation": False,
            "filter": None,
            "results": [],
        }

    resolved_dsn = (dsn or os.getenv("DATABASE_URL") or "").strip()
    if not resolved_dsn:
        return {
            "status": "unavailable",
            "reason": "DATABASE_URL_NOT_CONFIGURED",
            "read_only": True,
            "knowledge_graph_mutation": False,
            "filter": filters.to_dict(),
            "results": [],
        }

    resolved_limit = max(1, min(int(limit), 250))
    elevation_sql, elevation_params = _elevation_clause(filters)
    sql = f"""
        select o.taxonomy_id,
               o.scientific_name,
               k.kg_node_id,
               count(*)::bigint as occurrence_count,
               min(coalesce(o.minimum_elevation, o.elevation_meters, o.maximum_elevation)) as observed_min_elevation_m,
               max(coalesce(o.maximum_elevation, o.elevation_meters, o.minimum_elevation)) as observed_max_elevation_m,
               min(o.decimal_latitude) as sample_latitude,
               min(o.decimal_longitude) as sample_longitude
        from public.orchid_occurrence o
        join oc_graph.kg_nodes k
          on k.node_type = 'taxon'
         and k.is_active
         and k.source_pk = o.taxonomy_id::text
        where o.taxonomy_id is not null
          and lower(o.country) = lower(%s)
          and ({elevation_sql})
        group by o.taxonomy_id, o.scientific_name, k.kg_node_id
        order by occurrence_count desc, o.scientific_name
        limit %s
    """
    params: list[Any] = [filters.country, *elevation_params, resolved_limit]
    try:
        with psycopg.connect(resolved_dsn, connect_timeout=5) as conn, conn.cursor() as cur:
            conn.read_only = True
            cur.execute(sql, params)
            rows = cur.fetchall()
    except psycopg.Error as exc:
        return {
            "status": "unavailable",
            "reason": f"OCCURRENCE_QUERY_FAILED:{exc.__class__.__name__}",
            "read_only": True,
            "knowledge_graph_mutation": False,
            "filter": filters.to_dict(),
            "results": [],
        }

    results = [
        {
            "taxonomy_id": row[0],
            "scientific_name": row[1],
            "kg_node_id": int(row[2]),
            "occurrence_count": int(row[3]),
            "observed_min_elevation_m": float(row[4]) if row[4] is not None else None,
            "observed_max_elevation_m": float(row[5]) if row[5] is not None else None,
            "sample_latitude": float(row[6]) if row[6] is not None else None,
            "sample_longitude": float(row[7]) if row[7] is not None else None,
        }
        for row in rows
    ]
    return {
        "status": "available",
        "contract": "calyx-occurrence-constraint-query-v1",
        "read_only": True,
        "knowledge_graph_mutation": False,
        "source_relation": "public.orchid_occurrence",
        "graph_identity_relation": "oc_graph.kg_nodes",
        "filter": filters.to_dict(),
        "result_count": len(results),
        "results": results,
        "interpretation": "occurrence evidence filtered by explicit country/elevation constraints",
    }
