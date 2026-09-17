from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

from app.web_collection.models import (
    CollectionEntry,
    CollectionEntryProvenance,
    CollectionEntryStatus,
    TaxonomicRank,
)

CANONICAL_TAXONOMY_SOURCE = "public.orchid_taxonomy"
CANONICAL_IMAGE_SOURCE = "public.orchid_images"


class CollectionRepository(Protocol):
    def search(self, query: str, *, offset: int, limit: int) -> tuple[list[CollectionEntry], int]: ...

    def browse(
        self,
        *,
        family: str | None,
        genus: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[CollectionEntry], int]: ...

    def get(self, taxon_id: str) -> CollectionEntry | None: ...


def _entry(row: dict[str, Any]) -> CollectionEntry:
    taxon_id = str(row["id"])
    return CollectionEntry(
        taxon_id=taxon_id,
        taxon_name=str(row["scientific_name"]),
        common_names=[],
        taxonomic_rank=TaxonomicRank.SPECIES,
        family="Orchidaceae",
        genus=str(row["genus"]) if row.get("genus") is not None else None,
        status=CollectionEntryStatus.CANONICAL_RECORD,
        description=None,
        habitat_notes=None,
        distribution_notes=None,
        image_count=int(row.get("image_count") or 0),
        provenance=CollectionEntryProvenance(
            source_table=CANONICAL_TAXONOMY_SOURCE,
            source_record_id=taxon_id,
            identity_state="canonical_table_record",
        ),
    )


class PostgresCollectionRepository:
    """Read-only public collection queries over the canonical operational tables."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(
            self._dsn,
            row_factory=dict_row,
            connect_timeout=8,
        )

    @staticmethod
    def _assert_sources(cur: Any) -> None:
        cur.execute(
            "SELECT to_regclass(%s) IS NOT NULL AS taxonomy_present, "
            "to_regclass(%s) IS NOT NULL AS images_present",
            (CANONICAL_TAXONOMY_SOURCE, CANONICAL_IMAGE_SOURCE),
        )
        availability = cur.fetchone()
        if not availability or not availability["taxonomy_present"]:
            raise RuntimeError(f"canonical taxonomy source {CANONICAL_TAXONOMY_SOURCE} is unavailable")

    @staticmethod
    def _query(
        cur: Any,
        *,
        where_sql: str,
        params: Sequence[Any],
        offset: int,
        limit: int,
    ) -> tuple[list[CollectionEntry], int]:
        cur.execute(
            f"SELECT COUNT(*) AS total FROM public.orchid_taxonomy t WHERE {where_sql}",
            tuple(params),
        )
        total = int(cur.fetchone()["total"])
        cur.execute(
            f"""
            SELECT t.id, t.scientific_name, t.genus,
                   COUNT(i.id) FILTER (
                       WHERE i.image_url IS NOT NULL
                         AND COALESCE(i.is_duplicate, false) = false
                   ) AS image_count
            FROM public.orchid_taxonomy t
            LEFT JOIN public.orchid_images i ON i.taxonomy_id = t.id
            WHERE {where_sql}
            GROUP BY t.id, t.scientific_name, t.genus
            ORDER BY lower(t.scientific_name), t.id
            OFFSET %s LIMIT %s
            """,
            (*params, offset, limit),
        )
        return [_entry(dict(row)) for row in cur.fetchall()], total

    def search(self, query: str, *, offset: int, limit: int) -> tuple[list[CollectionEntry], int]:
        normalized = " ".join(query.split())
        where_sql = "TRUE"
        params: tuple[Any, ...] = ()
        if normalized:
            where_sql = "(t.scientific_name ILIKE %s OR t.genus ILIKE %s)"
            pattern = f"%{normalized}%"
            params = (pattern, pattern)
        with self._connect() as conn, conn.cursor() as cur:
            self._assert_sources(cur)
            return self._query(
                cur,
                where_sql=where_sql,
                params=params,
                offset=offset,
                limit=limit,
            )

    def browse(
        self,
        *,
        family: str | None,
        genus: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[CollectionEntry], int]:
        normalized_family = " ".join((family or "").split())
        if normalized_family and normalized_family.casefold() != "orchidaceae":
            return [], 0
        normalized_genus = " ".join((genus or "").split())
        where_sql = "TRUE"
        params: tuple[Any, ...] = ()
        if normalized_genus:
            where_sql = "lower(t.genus) = lower(%s)"
            params = (normalized_genus,)
        with self._connect() as conn, conn.cursor() as cur:
            self._assert_sources(cur)
            return self._query(
                cur,
                where_sql=where_sql,
                params=params,
                offset=offset,
                limit=limit,
            )

    def get(self, taxon_id: str) -> CollectionEntry | None:
        with self._connect() as conn, conn.cursor() as cur:
            self._assert_sources(cur)
            cur.execute(
                """
                SELECT t.id, t.scientific_name, t.genus,
                       COUNT(i.id) FILTER (
                           WHERE i.image_url IS NOT NULL
                             AND COALESCE(i.is_duplicate, false) = false
                       ) AS image_count
                FROM public.orchid_taxonomy t
                LEFT JOIN public.orchid_images i ON i.taxonomy_id = t.id
                WHERE CAST(t.id AS text) = %s
                GROUP BY t.id, t.scientific_name, t.genus
                """,
                (taxon_id,),
            )
            row = cur.fetchone()
            return _entry(dict(row)) if row else None
