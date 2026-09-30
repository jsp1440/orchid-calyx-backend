#!/usr/bin/env python3
"""Read-only scan of trait tables for sensitive-locality material.

Scans the research-trait sources (``app.research_traits.service.TRAIT_SOURCES``)
plus ``public.record_traits`` for columns and trait labels that carry
coordinates (decimal, DMS, UTM/MGRS, Open Location / plus codes), type
locality, collection site or fine elevation (``elev_m``, ``elev_raw_value``).

The screens are the member-view screens in ``app/matrix_member_views.py``;
nothing here defines its own locality pattern. ``app/member_redaction.py`` is a
positive allow-list (every caller string is redacted), so it has no detection
screen to reuse.

Read-only and bounded: the session and transaction are ``READ ONLY``, each
statement has a timeout, and each source is sampled with ``LIMIT``. The report
carries counts, source and column names and trait-label names only. It NEVER
contains a sampled value, and a label is printed only in a plain identifier
shape (anything else is counted as ``withheld_labels``). The connection string
is never printed.

Exit codes: 0 nothing flagged, 1 something flagged, 2 could not scan.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.matrix_member_views import (
    _ALT_TOKEN,
    _COORDINATE_CASED,
    _COORDINATE_SHAPES,
    _ELEVATION_TOKENS,
    _SENSITIVE_WORDS,
    _TOKEN_SPLIT,
    _WHITESPACE,
    _screen_form,
    _screen_hit,
)
from app.research_traits.service import TRAIT_LABEL_FIELDS, TRAIT_SOURCES

EXTRA_SOURCES = ("public.record_traits",)
SOURCES = (*TRAIT_SOURCES, *EXTRA_SOURCES)
DEFAULT_LIMIT = 5000
MAX_LIMIT = 50_000
STATEMENT_TIMEOUT_MS = 30_000
# Screens run on bounded text only.
MAX_SCREENED_CHARS = 4096
TEXT_TYPES = frozenset(
    {"text", "character varying", "character", "json", "jsonb", "name"}
)
NUMERIC_TYPES = frozenset(
    {"numeric", "integer", "bigint", "smallint", "real", "double precision"}
)
# A label is printed only in this shape: letters, spaces and simple separators,
# no digits, colons, quotes, marks or "@". Anything else is counted, not shown.
PRINTABLE_LABEL = re.compile(r"[A-Za-z][A-Za-z _./()-]{0,63}")

CATALOG_RELATION_SQL = (
    "SELECT c.oid FROM pg_catalog.pg_class c "
    "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = %s AND c.relname = %s AND c.relkind IN ('r', 'v', 'm', 'p', 'f')"
)
CATALOG_COLUMNS_SQL = (
    "SELECT a.attname, format_type(a.atttypid, NULL) "
    "FROM pg_catalog.pg_attribute a "
    "WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum"
)


def screen_categories(text: str) -> list[str]:
    """Which member-view screens a string trips (empty list when clean).

    Mirrors ``matrix_member_views._screen_hit`` on the raw and NFKC screen
    forms, split by screen so the report can say what kind of material it is.
    """

    text = text[:MAX_SCREENED_CHARS]
    found: set[str] = set()
    for form in (text, _screen_form(text)):
        if not _screen_hit(form):
            continue
        if _COORDINATE_SHAPES.search(form) or _COORDINATE_CASED.search(form):
            found.add("coordinates")
        if _SENSITIVE_WORDS.search(form):
            found.add("sensitive_vocabulary")
        tokens = _TOKEN_SPLIT.sub(" ", form)
        if _ELEVATION_TOKENS.search(tokens) or (
            _WHITESPACE.search(form) is None and _ALT_TOKEN.search(tokens)
        ):
            found.add("elevation_token")
    return sorted(found)


def _split(source: str) -> tuple[str, str]:
    schema, _, table = source.partition(".")
    return schema, table


def scan_source(cur, source: str, limit: int) -> dict[str, object]:
    from psycopg import sql

    schema, table = _split(source)
    cur.execute(CATALOG_RELATION_SQL, (schema, table))
    row = cur.fetchone()
    if row is None:
        return {"source": source, "present": False}
    columns = cur.execute(CATALOG_COLUMNS_SQL, (row[0],)).fetchall()
    columns = [
        (name, kind) for name, kind in columns if kind in TEXT_TYPES | NUMERIC_TYPES
    ]
    if not columns:
        return {
            "source": source,
            "present": True,
            "sampled_rows": 0,
            "columns_scanned": 0,
        }

    name_flags = {name: screen_categories(name) for name, _ in columns}
    label_columns = [name for name, _ in columns if name.lower() in TRAIT_LABEL_FIELDS]
    select = sql.SQL(", ").join(
        sql.SQL("{}::text").format(sql.Identifier(name)) for name, _ in columns
    )
    query = sql.SQL("SELECT {} FROM {}.{} LIMIT {}").format(
        select, sql.Identifier(schema), sql.Identifier(table), sql.Literal(limit)
    )
    rows = cur.execute(query).fetchall()

    flagged_columns = {
        name: {"column": name, "matched": cats, "non_null_in_sample": 0}
        for name, cats in name_flags.items()
        if cats
    }
    value_hits: dict[str, dict[str, object]] = {}
    labels: dict[str, dict[str, object]] = {}
    withheld_labels = 0
    rows_flagged = 0
    for values in rows:
        row_flagged = False
        for (name, kind), value in zip(columns, values, strict=True):
            if value is None:
                continue
            if name in flagged_columns:
                flagged_columns[name]["non_null_in_sample"] += 1
                row_flagged = True
            if kind not in TEXT_TYPES:
                continue  # numbers are judged by their column name only
            cats = screen_categories(value)
            if not cats:
                continue
            row_flagged = True
            if name in label_columns:
                if PRINTABLE_LABEL.fullmatch(value) and "coordinates" not in cats:
                    entry = labels.setdefault(
                        value,
                        {"label": value, "column": name, "matched": cats, "rows": 0},
                    )
                    entry["rows"] += 1
                else:
                    withheld_labels += 1
            else:
                hit = value_hits.setdefault(
                    name, {"column": name, "rows": 0, "matched": set()}
                )
                hit["rows"] += 1
                hit["matched"].update(cats)
        rows_flagged += row_flagged

    return {
        "source": source,
        "present": True,
        "sampled_rows": len(rows),
        "sample_limit": limit,
        "columns_scanned": len(columns),
        "rows_flagged": rows_flagged,
        "flagged_columns": list(flagged_columns.values()),
        "value_hits": [
            {**hit, "matched": sorted(hit["matched"])} for hit in value_hits.values()
        ],
        "flagged_labels": sorted(labels.values(), key=lambda item: item["label"]),
        "withheld_labels": withheld_labels,
    }


def scan(conn, limit: int = DEFAULT_LIMIT) -> dict[str, object]:
    limit = max(1, min(int(limit), MAX_LIMIT))
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(f"SET LOCAL statement_timeout = {int(STATEMENT_TIMEOUT_MS)}")
        sources = [scan_source(cur, source, limit) for source in SOURCES]
    conn.rollback()
    flagged = sum(int(s.get("rows_flagged", 0)) for s in sources)
    return {
        "status": "FLAGGED" if flagged else "CLEAN",
        "read_only": True,
        "sample_limit": limit,
        "rows_flagged": flagged,
        "sources": sources,
        "values_included": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url-env", default="DATABASE_URL")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args(argv)
    dsn = os.environ.get(args.database_url_env, "").strip()
    if not dsn:
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": f"{args.database_url_env} is not set",
                }
            )
        )
        return 2
    try:
        import psycopg

        with psycopg.connect(dsn, connect_timeout=10, autocommit=False) as conn:
            conn.read_only = True
            report = scan(conn, args.limit)
    except Exception as exc:  # noqa: BLE001 - reported by type, never the DSN or a value
        print(json.dumps({"status": "UNAVAILABLE", "reason": type(exc).__name__}))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["status"] == "FLAGGED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
