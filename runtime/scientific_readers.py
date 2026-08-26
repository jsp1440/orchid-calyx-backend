"""Canonical domain readers for the recovery vertical slice.

:mod:`runtime.scientific_reads` defines what a reading is and how its origin is
declared. This module supplies the readers that actually go and look.

It introduces no new source system. The relation candidates come from
``runtime.scientific_intelligence.adapters``, which already encodes where each
domain lives across the deployments this repository targets, and the safe
identifier composition comes from the same place. What is added here is
taxon-scoped retrieval — the adapters count rows for a dashboard; a research
request needs the rows for one organism.

Three distinctions this module refuses to blur:

* **no relation found** is ``UNAVAILABLE``, not ``EMPTY``. A schema that does
  not carry a domain here has not told us the Continuum lacks the data.
* **a query that raised** is ``UNAVAILABLE``. An exception is not an absence.
* **a relation that exists and returned nothing** is ``EMPTY``, and only that
  case is a statement about the taxon.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from runtime.scientific_reads import (
    CANONICAL_DATABASE,
    ScientificReadThrough,
    ScientificReading,
    available,
    empty,
    unavailable,
)

#: How many rows one domain may contribute to a single request. A research
#: read is evidence for a synthesis, not a bulk export, and an unbounded
#: SELECT against an occurrence table is how a diagnostic becomes an incident.
ROW_LIMIT = 50

#: Column names that plausibly carry a scientific name, most specific first.
#: Probed against information_schema rather than assumed, because these tables
#: differ across the deployments the candidate lists already accommodate.
NAME_COLUMNS = (
    "accepted_scientific_name",
    "scientific_name",
    "taxon_name",
    "species_name",
    "canonical_name",
    "full_name",
    "name",
    "taxon",
    "species",
)


def _candidates() -> dict[str, Sequence[str]]:
    """Relation candidates per domain, taken from the existing adapters."""
    from runtime.scientific_intelligence import adapters as a

    return {
        "taxonomy": a._TAXONOMY_CANDIDATES,
        "occurrences": a._ATLAS_CANDIDATES,
        "geography": a._ATLAS_CANDIDATES,
        "elevation": a._ATLAS_CANDIDATES,
        "literature": a._LIT_DOC_CANDIDATES,
        "pollinators": a._POLLINATOR_CANDIDATES,
        "mycorrhiza": a._MYCORRHIZA_CANDIDATES,
    }


def _column_names(cur: Any, fq_table: str) -> list[str]:
    schema, _, table = fq_table.partition(".")
    cur.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    return [str(row[0]) for row in cur.fetchall()]


def _name_column(columns: Iterable[str]) -> str | None:
    lowered = {name.lower(): name for name in columns}
    for candidate in NAME_COLUMNS:
        if candidate in lowered:
            return lowered[candidate]
    return None


def _select_taxon_rows(cur: Any, fq_table: str, taxon: str) -> tuple[list[dict], str] | None:
    """Rows for one taxon, or None when this relation cannot be searched by name."""
    from psycopg import sql as psycopg_sql

    columns = _column_names(cur, fq_table)
    name_column = _name_column(columns)
    if name_column is None:
        return None

    schema, _, table = fq_table.partition(".")
    query = psycopg_sql.SQL(
        "SELECT * FROM {}.{} WHERE lower({}) = lower(%s) LIMIT %s"
    ).format(
        psycopg_sql.Identifier(schema),
        psycopg_sql.Identifier(table),
        psycopg_sql.Identifier(name_column),
    )
    cur.execute(query, (taxon, ROW_LIMIT))
    rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    return rows, name_column


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def canonical_reader(domain: str, candidates: Sequence[str]) -> Callable[[str], ScientificReading]:
    """A reader that looks in the first candidate relation that exists."""

    def _read(taxon: str) -> ScientificReading:
        url = _database_url()
        if not url:
            return unavailable(domain, "DATABASE_URL is not configured for this process")

        import psycopg

        from runtime.scientific_intelligence.adapters import _table_exists

        try:
            with psycopg.connect(url, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    relation = next(
                        (name for name in candidates if _table_exists(cur, name)), None
                    )
                    if relation is None:
                        # Not "no data". This schema does not carry the domain
                        # under any name this repository knows.
                        return unavailable(
                            domain,
                            "no canonical relation found among "
                            f"{len(candidates)} known candidates",
                        )

                    selected = _select_taxon_rows(cur, relation, taxon)
                    if selected is None:
                        return unavailable(
                            domain,
                            f"{relation} has no recognisable scientific-name column",
                        )
                    rows, name_column = selected
                    provenance = {
                        "relation": relation,
                        "name_column": name_column,
                        "row_limit": ROW_LIMIT,
                        "truncated": len(rows) == ROW_LIMIT,
                        "taxon_queried": taxon,
                    }
                    if not rows:
                        return empty(
                            domain,
                            CANONICAL_DATABASE,
                            f"{relation} holds no row for {taxon}",
                        )
                    return available(domain, CANONICAL_DATABASE, rows, provenance)
        except Exception as exc:  # noqa: BLE001
            # An exception has not proved the domain is empty.
            return unavailable(domain, f"{type(exc).__name__}: {exc}")

    return _read


def build_read_through(
    *, readers: dict[str, Callable[[str], ScientificReading]] | None = None
) -> ScientificReadThrough:
    """The production read-through, with every bindable domain bound.

    Domains with no canonical relation candidate in this repository are left
    unbound on purpose. An unbound domain reports ``UNAVAILABLE`` with its
    reason, which is true; binding a reader that always answers "nothing"
    would be a lie shaped like coverage.
    """
    bound: dict[str, Callable[[str], ScientificReading]] = {}
    for domain, candidates in _candidates().items():
        bound[domain] = canonical_reader(domain, candidates)
    if readers:
        bound.update(readers)
    return ScientificReadThrough(bound)


def bound_domains() -> tuple[str, ...]:
    """Domains this repository can bind a canonical reader for."""
    return tuple(sorted(_candidates()))


def unbound_domains() -> tuple[str, ...]:
    """Domains with no canonical relation candidate anywhere in the repository.

    Reported rather than hidden: these are the parts of the recovery slice that
    have no canonical read path yet, and a readiness summary that omitted them
    would overstate what the executor can do.
    """
    from runtime.scientific_reads import DOMAINS

    return tuple(sorted(set(DOMAINS) - set(_candidates())))
