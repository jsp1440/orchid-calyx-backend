from __future__ import annotations

import math
import os
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import psycopg
from psycopg import sql

CONTRACT_VERSION = "oc-research-traits-v1"
MAX_DISTRIBUTIONS = 100
MAX_ROWS = 5000
SAFE_STATES = {
    "AVAILABLE",
    "PROVISIONAL",
    "VERIFIED",
    "CONTRADICTORY",
    "UNKNOWN",
    "UNAVAILABLE",
    "WITHHELD",
    "ABSENT",
    "REJECTED",
    "SUPERSEDED",
}
NON_VALUE_STATES = {"UNKNOWN", "UNAVAILABLE", "WITHHELD", "ABSENT"}
TRAIT_SOURCES = ("oc_views.trait_resolved_v4", "oc_traits.traits")
TAXON_SOURCES = ("oc_taxonomy.taxa", "public.orchid_taxonomy")
TAXON_ID_FIELDS = (
    "taxon_id",
    "canonical_taxon_id",
    "accepted_taxon_id",
    "taxonomy_id",
    "orchid_taxonomy_id",
    "id",
)
TAXON_NAME_FIELDS = (
    "scientific_name",
    "accepted_name",
    "canonical_name",
    "taxon_name",
    "name",
)
RANK_FIELDS = ("rank", "taxon_rank")
TRAIT_ID_FIELDS = ("trait_id", "id", "record_id")
TRAIT_LABEL_FIELDS = (
    "trait_name",
    "trait",
    "predicate",
    "measurement_type",
    "measurementtype",
    "attribute",
)
TRAIT_VALUE_FIELDS = (
    "trait_value",
    "value",
    "measurement_value",
    "measurementvalue",
    "object",
)
UNIT_FIELDS = ("unit", "units", "measurement_unit", "measurementunit")
CONFIDENCE_FIELDS = ("confidence_score", "confidence")
STATE_FIELDS = ("evidence_state", "review_state", "state", "status")
COUNT_FIELDS = ("support_count", "sample_size", "count")
SOURCE_ID_FIELDS = ("source_id", "dataset_id", "reference_id", "citation_id")
SOURCE_NAME_FIELDS = ("source_name", "dataset_name", "provider")
RECORD_ID_FIELDS = ("record_id", "evidence_id", "source_pk", "id")
SOURCE_URL_FIELDS = ("source_url", "source_uri", "reference_url", "url", "uri")
RETRIEVED_AT_FIELDS = ("retrieved_at", "updated_at", "created_at")
LICENSE_FIELDS = ("license", "license_name")


def _first(row: dict[str, Any], fields: Iterable[str]) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for field in fields:
        value = lowered.get(field.lower())
        if value not in (None, ""):
            return value
    return None


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _safe_number(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _safe_nonnegative_int(value: Any) -> int | None:
    number = _safe_number(value)
    if number is None or isinstance(number, float) and not number.is_integer():
        return None
    integer = int(number)
    if integer < 0 or integer > 9_007_199_254_740_991:
        return None
    return integer


def _safe_confidence(value: Any) -> float | None:
    number = _safe_number(value)
    if number is None:
        return None
    score = float(number)
    return score if 0.0 <= score <= 1.0 else None


def _safe_url(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.username or parsed.password:
        return None
    return text


def _state(row: dict[str, Any]) -> str:
    raw = _text(_first(row, STATE_FIELDS))
    if raw and raw.upper() in SAFE_STATES:
        return raw.upper()
    # A canonical persisted row establishes availability only. It does not
    # establish verification, biological presence, or scientific confidence.
    return "AVAILABLE"


def _receipt(row: dict[str, Any], source_table: str) -> dict[str, Any]:
    return {
        "source_id": _text(_first(row, SOURCE_ID_FIELDS)) or source_table,
        "source_name": _text(_first(row, SOURCE_NAME_FIELDS)),
        "record_id": _text(_first(row, RECORD_ID_FIELDS)),
        "source_url": _safe_url(_first(row, SOURCE_URL_FIELDS)),
        "retrieved_at": _text(_first(row, RETRIEVED_AT_FIELDS)),
        "license": _text(_first(row, LICENSE_FIELDS)),
    }


def aggregate_trait_rows(
    rows: list[dict[str, Any]],
    *,
    source_table: str,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str | None], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        label = _text(_first(row, TRAIT_LABEL_FIELDS))
        value = _first(row, TRAIT_VALUE_FIELDS)
        if not label or value in (None, ""):
            continue
        grouped[(label, _text(_first(row, UNIT_FIELDS)))].append(row)

    distributions: list[dict[str, Any]] = []
    for (label, unit), members in sorted(grouped.items(), key=lambda item: item[0][0].lower()):
        if len(distributions) >= MAX_DISTRIBUTIONS:
            break
        states = {_state(row) for row in members}
        evidence_state = (
            next(iter(states))
            if len(states) == 1
            else "CONTRADICTORY"
        )
        if evidence_state in NON_VALUE_STATES:
            distributions.append(
                {
                    "trait_id": label,
                    "label": label,
                    "unit": unit,
                    "evidence_state": evidence_state,
                    "confidence": None,
                    "sample_size": None,
                    "buckets": [],
                    "receipts": [],
                }
            )
            continue

        bucket_counts: dict[tuple[str, Any], int] = defaultdict(int)
        receipts: list[dict[str, Any]] = []
        confidence_values: list[float] = []
        explicit_sample_sizes: list[int] = []
        trait_id = _text(_first(members[0], TRAIT_ID_FIELDS)) or label
        for row in members:
            raw_value = _first(row, TRAIT_VALUE_FIELDS)
            numeric = _safe_number(raw_value)
            if numeric is not None:
                bucket_value: str | float | int | None = numeric
                bucket_key = ("number", numeric)
            else:
                bucket_value = _text(raw_value)
                bucket_key = ("string", bucket_value)
            if bucket_value is None:
                continue
            count = _safe_nonnegative_int(_first(row, COUNT_FIELDS))
            bucket_counts[bucket_key] += count if count is not None else 1
            confidence = _safe_confidence(_first(row, CONFIDENCE_FIELDS))
            if confidence is not None:
                confidence_values.append(confidence)
            sample_size = _safe_nonnegative_int(_first(row, ("sample_size", "support_count")))
            if sample_size is not None:
                explicit_sample_sizes.append(sample_size)
            receipt = _receipt(row, source_table)
            if receipt not in receipts and len(receipts) < 25:
                receipts.append(receipt)

        buckets = [
            {"value": key[1], "count": count}
            for key, count in sorted(bucket_counts.items(), key=lambda item: str(item[0][1]))
        ]
        sample_size = sum(explicit_sample_sizes) if explicit_sample_sizes else sum(bucket_counts.values())
        confidence = min(confidence_values) if confidence_values else None
        if evidence_state == "VERIFIED" and not all(
            receipt.get("source_id") and receipt.get("record_id") for receipt in receipts
        ):
            evidence_state = "PROVISIONAL"

        distributions.append(
            {
                "trait_id": trait_id,
                "label": label,
                "unit": unit,
                "evidence_state": evidence_state,
                "confidence": confidence,
                "sample_size": sample_size,
                "buckets": buckets,
                "receipts": receipts,
            }
        )
    return distributions


class ResearchTraitsService:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        connection_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL")
        self.connection_factory = connection_factory or psycopg.connect

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for research trait retrieval")
        return self.connection_factory(self.database_url)

    @staticmethod
    def _split_table(table: str) -> tuple[str, str]:
        return tuple(table.split(".", 1))  # type: ignore[return-value]

    def _table_exists(self, cur: Any, table: str) -> bool:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (table,))
        return bool(cur.fetchone()[0])

    def _columns(self, cur: Any, table: str) -> tuple[str, ...]:
        schema, name = self._split_table(table)
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s
            ORDER BY ordinal_position
            """,
            (schema, name),
        )
        return tuple(str(row[0]) for row in cur.fetchall())

    @staticmethod
    def _choose(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
        lowered = {column.lower(): column for column in columns}
        for candidate in candidates:
            if candidate.lower() in lowered:
                return lowered[candidate.lower()]
        return None

    def _resolve_taxon_ids(self, cur: Any, *, rank: str, name: str) -> list[str]:
        for table in TAXON_SOURCES:
            if not self._table_exists(cur, table):
                continue
            columns = self._columns(cur, table)
            id_col = self._choose(columns, TAXON_ID_FIELDS)
            name_col = self._choose(columns, TAXON_NAME_FIELDS)
            rank_col = self._choose(columns, RANK_FIELDS)
            if not id_col or not name_col:
                continue
            schema, table_name = self._split_table(table)
            if rank == "species":
                query = sql.SQL("SELECT {id}::text FROM {schema}.{table} WHERE {name} = %s LIMIT 2").format(
                    id=sql.Identifier(id_col),
                    schema=sql.Identifier(schema),
                    table=sql.Identifier(table_name),
                    name=sql.Identifier(name_col),
                )
                cur.execute(query, (name,))
            else:
                if rank_col:
                    query = sql.SQL(
                        "SELECT {id}::text FROM {schema}.{table} "
                        "WHERE ({name} = %s AND lower({rank}) = 'genus') "
                        "OR {name} LIKE %s ORDER BY {id} LIMIT %s"
                    ).format(
                        id=sql.Identifier(id_col),
                        schema=sql.Identifier(schema),
                        table=sql.Identifier(table_name),
                        name=sql.Identifier(name_col),
                        rank=sql.Identifier(rank_col),
                    )
                else:
                    query = sql.SQL(
                        "SELECT {id}::text FROM {schema}.{table} "
                        "WHERE {name} = %s OR {name} LIKE %s ORDER BY {id} LIMIT %s"
                    ).format(
                        id=sql.Identifier(id_col),
                        schema=sql.Identifier(schema),
                        table=sql.Identifier(table_name),
                        name=sql.Identifier(name_col),
                    )
                cur.execute(query, (name, f"{name} %", MAX_ROWS))
            ids = [str(row[0]) for row in cur.fetchall() if row and row[0] is not None]
            if ids:
                return list(dict.fromkeys(ids))[:MAX_ROWS]
        return []

    def _read_trait_rows(self, cur: Any, taxon_ids: list[str]) -> tuple[str | None, list[dict[str, Any]]]:
        for table in TRAIT_SOURCES:
            if not self._table_exists(cur, table):
                continue
            columns = self._columns(cur, table)
            taxon_col = self._choose(columns, TAXON_ID_FIELDS)
            label_col = self._choose(columns, TRAIT_LABEL_FIELDS)
            value_col = self._choose(columns, TRAIT_VALUE_FIELDS)
            if not taxon_col or not label_col or not value_col:
                continue
            schema, table_name = self._split_table(table)
            query = sql.SQL(
                "SELECT * FROM {schema}.{table} WHERE {taxon}::text = ANY(%s) LIMIT %s"
            ).format(
                schema=sql.Identifier(schema),
                table=sql.Identifier(table_name),
                taxon=sql.Identifier(taxon_col),
            )
            cur.execute(query, (taxon_ids, MAX_ROWS))
            names = [desc.name for desc in cur.description]
            rows = [dict(zip(names, row, strict=True)) for row in cur.fetchall()]
            return table, rows
        return None, []

    def get(self, *, rank: str, name: str) -> dict[str, Any]:
        subject = {"rank": rank, "name": name}
        try:
            with self._connect() as conn, conn.cursor() as cur:
                taxon_ids = self._resolve_taxon_ids(cur, rank=rank, name=name)
                if not taxon_ids:
                    return {
                        "contract_version": CONTRACT_VERSION,
                        "subject": subject,
                        "state": "UNKNOWN",
                        "generated_at": None,
                        "distributions": [],
                    }
                source_table, rows = self._read_trait_rows(cur, taxon_ids)
        except (psycopg.Error, RuntimeError):
            return {
                "contract_version": CONTRACT_VERSION,
                "subject": subject,
                "state": "UNAVAILABLE",
                "generated_at": None,
                "distributions": [],
            }

        if not source_table:
            return {
                "contract_version": CONTRACT_VERSION,
                "subject": subject,
                "state": "UNAVAILABLE",
                "generated_at": None,
                "distributions": [],
            }
        if not rows:
            return {
                "contract_version": CONTRACT_VERSION,
                "subject": subject,
                "state": "ABSENT",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "distributions": [],
            }
        distributions = aggregate_trait_rows(rows, source_table=source_table)
        return {
            "contract_version": CONTRACT_VERSION,
            "subject": subject,
            "state": "AVAILABLE" if distributions else "UNKNOWN",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "distributions": distributions,
        }
