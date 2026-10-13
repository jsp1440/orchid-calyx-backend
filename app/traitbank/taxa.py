"""Canonical taxon identity for TraitBank, read-only.

TraitBank does not own taxonomy. It reuses the canonical resolution already
used by ``/api/research/traits`` (``app.research_traits.service``): the same
source tables in the same priority order (``oc_taxonomy.taxa``, then
``public.orchid_taxonomy``) and the same refusal of ambiguous species names.
Nothing here creates, edits or activates a taxon.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from psycopg import sql

from app.research_traits.service import (
    RANK_FIELDS,
    TAXON_ID_FIELDS,
    TAXON_NAME_FIELDS,
    TAXON_SOURCES,
    ResearchTraitsService,
)


@dataclass(frozen=True)
class CanonicalTaxon:
    taxon_id: str
    name: str
    source_table: str


class CanonicalTaxa(Protocol):
    def get_many(self, cur: Any, taxon_ids: list[str]) -> dict[str, CanonicalTaxon]: ...

    def resolve_species(self, cur: Any, name: str) -> str | None: ...

    def genus_ids(self, cur: Any, genus: str) -> list[str]: ...


class PostgresCanonicalTaxa:
    """Reads the canonical taxonomy tables through the research-traits helpers."""

    def __init__(self) -> None:
        # Only the stateless table/column helpers and the name resolver are
        # used; no connection is opened by this instance.
        self._rt = ResearchTraitsService(database_url="postgresql://unused")

    def _sources(self, cur: Any) -> list[tuple[str, str, str, str | None]]:
        found = []
        for table in TAXON_SOURCES:
            if not self._rt._table_exists(cur, table):
                continue
            columns = self._rt._columns(cur, table)
            id_col = self._rt._choose(columns, TAXON_ID_FIELDS)
            name_col = self._rt._choose(columns, TAXON_NAME_FIELDS)
            if id_col and name_col:
                found.append(
                    (table, id_col, name_col, self._rt._choose(columns, RANK_FIELDS))
                )
        return found

    def get_many(self, cur: Any, taxon_ids: list[str]) -> dict[str, CanonicalTaxon]:
        wanted = sorted(set(taxon_ids))
        result: dict[str, CanonicalTaxon] = {}
        for table, id_col, name_col, _ in self._sources(cur):
            missing = [t for t in wanted if t not in result]
            if not missing:
                break
            schema, name = table.split(".", 1)
            query = sql.SQL(
                "SELECT {id}::text, {name} FROM {schema}.{table} WHERE {id}::text = ANY(%s)"
            ).format(
                id=sql.Identifier(id_col),
                name=sql.Identifier(name_col),
                schema=sql.Identifier(schema),
                table=sql.Identifier(name),
            )
            cur.execute(query, (missing,))
            for taxon_id, label in cur.fetchall():
                result.setdefault(
                    str(taxon_id), CanonicalTaxon(str(taxon_id), str(label), table)
                )
        return result

    def resolve_species(self, cur: Any, name: str) -> str | None:
        ids = self._rt._resolve_taxon_ids(cur, rank="species", name=name)
        return ids[0] if len(ids) == 1 else None

    def genus_ids(self, cur: Any, genus: str) -> list[str]:
        return self._rt._resolve_taxon_ids(cur, rank="genus", name=genus)

# Hosted autonomy-loop acceptance input 2 (2026-10-13), pushed after the controlled
# restart: the resumed worker must discover and verify it exactly once.
