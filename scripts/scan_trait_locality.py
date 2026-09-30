#!/usr/bin/env python3
"""Read-only scan of trait tables for sensitive-locality material.

Scans the research-trait sources (``app.research_traits.service.TRAIT_SOURCES``)
plus ``public.record_traits`` for columns, values and trait labels that carry
coordinates (decimal, DMS, UTM/MGRS, Open Location / plus codes), type
locality, collection site or fine elevation (``elev_m``, ``elev_raw_value``).

Whether a string is flagged is decided by the member-view screens in
``app/matrix_member_views.py``. This script adds only two scanner-local folds
in front of them, for forms those screens do not cover as written: an
upper-case fold (so lower-case MGRS/UTM references reach the case-sensitive
grid screen; only matches of 8 or more characters count, so short
hemisphere-like tokens such as ``2n`` do not) and a comma fold for
whitespace-separated decimal pairs (``9.12 -83.65``). Keyword patterns here
only NAME the category of a string the screens already flagged.
``app/member_redaction.py`` is a positive allow-list (every caller string is
redacted), so it has no detection screen to reuse.

Numeric columns are judged by name, plus one heuristic: a pair of non-integer
columns whose sampled values fit latitude/longitude ranges with 4 or more
decimals is reported as a possible coordinate pair.

Read-only and bounded: the session and transaction are ``READ ONLY``, each
statement has a timeout, and each source is sampled with ``LIMIT``.

The report carries counts, source and column names and a FIXED vocabulary of
category names only. It never contains a sampled value or a trait label, and
never the connection string.

Exit codes: 0 nothing flagged, 1 something flagged, 2 could not scan.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation
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
ARRAY_TYPES = frozenset({"text[]", "character varying[]", "character[]"})
INTEGER_TYPES = frozenset({"integer", "bigint", "smallint"})
FRACTIONAL_TYPES = frozenset({"numeric", "real", "double precision"})
NUMERIC_TYPES = INTEGER_TYPES | FRACTIONAL_TYPES

# The fixed category vocabulary: the only words the report uses to describe
# what was found.
KINDS = (
    "type_locality",
    "collection_site",
    "coordinate",
    "elevation",
    "other_sensitive",
)
CATEGORIES = frozenset(
    {f"{kind}_{where}" for kind in KINDS for where in ("column", "label", "value")}
    | {"possible_coordinate_pair"}
)
LIMITATIONS = (
    "Sample only: each source is read with LIMIT, so a clean result covers the sampled rows.",
    (
        "A place name with no locality vocabulary and no coordinate shape "
        "(for example a bare locality name) is not detected."
    ),
    (
        "Numbers are judged by column name and by the paired latitude/longitude "
        "heuristic only; a single coordinate column with an unrevealing name is not detected."
    ),
    (
        "Lower-case MGRS/UTM and whitespace-separated decimal pairs are detected by "
        "scanner-local folds, not by app/matrix_member_views.py."
    ),
)

# Scanner-local folds applied before the member-view screens.
_DECIMAL_PAIR_FOLD = re.compile(r"(\d[.,]\d{2,})\s+([-+−–]?\d{1,3}[.,]\d{2,})")
MIN_FOLDED_GRID_MATCH = 8
# Naming only: which category an already-flagged string belongs to.
_TYPE_LOCALITY = re.compile(r"type\W{0,3}locali|locus\W{0,3}typicus", re.IGNORECASE)
_COLLECTION = re.compile(r"collect|colect|coletad|recolet", re.IGNORECASE)
_COORDINATE_WORD = re.compile(
    r"coordinat|coorden|latitud|longitud|georef|\bgps", re.IGNORECASE
)
_ELEVATION_WORD = re.compile(r"elev|altitud|sea\s{0,3}level|\basl\b", re.IGNORECASE)

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
    """Which screens a string trips: ``coordinates``, ``sensitive_vocabulary``,
    ``elevation_token`` (empty list when clean).

    The member-view screens run on the raw and NFKC forms, then on the
    scanner-local folds described in the module docstring.
    """

    text = text[:MAX_SCREENED_CHARS]
    found: set[str] = set()
    for form in (text, _screen_form(text)):
        if _screen_hit(form):
            if _COORDINATE_SHAPES.search(form) or _COORDINATE_CASED.search(form):
                found.add("coordinates")
            if _SENSITIVE_WORDS.search(form):
                found.add("sensitive_vocabulary")
            tokens = _TOKEN_SPLIT.sub(" ", form)
            if _ELEVATION_TOKENS.search(tokens) or (
                _WHITESPACE.search(form) is None and _ALT_TOKEN.search(tokens)
            ):
                found.add("elevation_token")
        if _COORDINATE_SHAPES.search(_DECIMAL_PAIR_FOLD.sub(r"\1, \2", form)):
            found.add("coordinates")
        if any(
            len(match.group(0)) >= MIN_FOLDED_GRID_MATCH
            for match in _COORDINATE_CASED.finditer(form.upper())
        ):
            found.add("coordinates")
    return sorted(found)


def category(text: str, screens: list[str], where: str) -> str:
    """The fixed-vocabulary category of a string the screens flagged."""

    if _TYPE_LOCALITY.search(text):
        kind = "type_locality"
    elif _COLLECTION.search(text):
        kind = "collection_site"
    elif "coordinates" in screens or _COORDINATE_WORD.search(text):
        kind = "coordinate"
    elif "elevation_token" in screens or _ELEVATION_WORD.search(text):
        kind = "elevation"
    else:
        kind = "other_sensitive"
    return f"{kind}_{where}"


def _fraction(value: str) -> tuple[Decimal, int] | None:
    try:
        number = Decimal(value.strip())
    except (InvalidOperation, AttributeError):
        return None
    if not number.is_finite():
        return None
    exponent = number.normalize().as_tuple().exponent
    return number, max(0, -int(exponent))


def _coordinate_pair(a: tuple[Decimal, int], b: tuple[Decimal, int]) -> bool:
    (x, x_places), (y, y_places) = a, b
    if min(x_places, y_places) < 4 or max(abs(x), abs(y)) < 1:
        return False
    in_lon = abs(x) <= 180 and abs(y) <= 180
    return in_lon and (abs(x) <= 90 or abs(y) <= 90)


def _split(source: str) -> tuple[str, str]:
    schema, _, table = source.partition(".")
    return schema, table


def _hit(bucket: dict[str, dict[str, object]], name: str, column: str) -> None:
    entry = bucket.setdefault(name, {"rows": 0, "columns": set()})
    entry["rows"] += 1
    entry["columns"].add(column)


def _frozen(bucket: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    return {
        name: {"rows": entry["rows"], "columns": sorted(entry["columns"])}
        for name, entry in sorted(bucket.items())
    }


def scan_source(cur, source: str, limit: int) -> dict[str, object]:
    from psycopg import sql

    schema, table = _split(source)
    cur.execute(CATALOG_RELATION_SQL, (schema, table))
    row = cur.fetchone()
    if row is None:
        return {"source": source, "present": False}
    columns = cur.execute(CATALOG_COLUMNS_SQL, (row[0],)).fetchall()
    columns = [
        (name, kind)
        for name, kind in columns
        if kind in TEXT_TYPES | ARRAY_TYPES | NUMERIC_TYPES
    ]
    if not columns:
        return {
            "source": source,
            "present": True,
            "sampled_rows": 0,
            "columns_scanned": 0,
        }

    flagged_columns = {}
    for name, _ in columns:
        screens = screen_categories(name)
        if screens:
            flagged_columns[name] = {
                "column": name,
                "category": category(name, screens, "column"),
                "non_null_in_sample": 0,
            }
    label_columns = {name for name, _ in columns if name.lower() in TRAIT_LABEL_FIELDS}
    fractional = [name for name, kind in columns if kind in FRACTIONAL_TYPES]

    def expression(name: str, kind: str):
        if kind in ARRAY_TYPES:
            return sql.SQL("array_to_string({}, E'\\n')").format(sql.Identifier(name))
        return sql.SQL("{}::text").format(sql.Identifier(name))

    select = sql.SQL(", ").join(expression(name, kind) for name, kind in columns)
    query = sql.SQL("SELECT {} FROM {}.{} LIMIT {}").format(
        select, sql.Identifier(schema), sql.Identifier(table), sql.Literal(limit)
    )
    rows = cur.execute(query).fetchall()

    value_hits: dict[str, dict[str, object]] = {}
    label_hits: dict[str, dict[str, object]] = {}
    pairs: dict[tuple[str, str], int] = {}
    rows_flagged = 0
    for values in rows:
        row_flagged = False
        numbers = {}
        for (name, kind), value in zip(columns, values, strict=True):
            if value is None:
                continue
            if name in flagged_columns:
                flagged_columns[name]["non_null_in_sample"] += 1
                row_flagged = True
            if kind in NUMERIC_TYPES:
                if name in fractional:
                    parsed = _fraction(value)
                    if parsed is not None:
                        numbers[name] = parsed
                continue
            screens = screen_categories(value)
            if not screens:
                continue
            row_flagged = True
            if name in label_columns:
                _hit(label_hits, category(value, screens, "label"), name)
            else:
                _hit(value_hits, category(value, screens, "value"), name)
        for a, b in itertools.combinations(sorted(numbers), 2):
            if _coordinate_pair(numbers[a], numbers[b]):
                pairs[(a, b)] = pairs.get((a, b), 0) + 1
                row_flagged = True
        rows_flagged += row_flagged

    return {
        "source": source,
        "present": True,
        "sampled_rows": len(rows),
        "sample_limit": limit,
        "columns_scanned": len(columns),
        "rows_flagged": rows_flagged,
        "flagged_columns": list(flagged_columns.values()),
        "value_hits": _frozen(value_hits),
        "label_hits": _frozen(label_hits),
        "possible_coordinate_pairs": [
            {
                "category": "possible_coordinate_pair",
                "columns": list(pair),
                "rows": count,
            }
            for pair, count in sorted(pairs.items())
        ],
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
        "labels_included": False,
        "limitations": list(LIMITATIONS),
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
