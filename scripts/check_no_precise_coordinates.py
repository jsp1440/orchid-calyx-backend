"""Refuse tracked data files that carry precise occurrence coordinates.

This repository is public. Tracked data files must not carry raw occurrence
coordinates: the public Atlas generalises rare, threatened and
collection-sensitive taxa, unresolved taxa fail closed to a coarse cell, and
CITES Appendix I taxa are generalised to at least 0.1 degree. A committed
data file bypasses every one of those runtime safeguards.

Every tracked file with a scanned suffix (:data:`SCANNED_SUFFIXES`) is read,
including members of zip, gzip and tar archives, and fails when it carries a
latitude/longitude-like value finer than two decimal places:

* delimited text (``.csv``/``.tsv``): UTF-8 with or without a BOM, the
  delimiter sniffed from ``, ; <tab> |``, a header row found anywhere (not
  only on the first row), comma decimals (``12,3456``), exponent notation,
  and WKT geometries in any cell;
* ``.xlsx``/``.xlsm`` with the same header search on every sheet;
* JSON, GeoJSON, JSON Lines and YAML: coordinate-like keys holding a value,
  a list or a dict of values (pandas ``orient="columns"``), pandas
  ``orient="split"`` tables, ``[lon, lat]`` arrays under coordinate-like or
  position-list keys (``points``, ``path``, ...), aligned anonymous numeric
  pairs (see :data:`ANONYMOUS_PAIR_MIN_ROWS`), ``x``/``y`` pairs in a
  geometry context, and every GeoJSON geometry type;
* notebooks (``.ipynb``): each cell source and each output (``text/plain``,
  ``text/html``, stream text, JSON) through the same detectors: printed and
  delimited tables, DataFrame reprs and HTML tables, JSON, Python literals
  (``pd.DataFrame({"lat": [...]})``, ``folium.Marker([lat, lon])``);
* SQL dumps: ``INSERT ... (cols) VALUES`` and ``COPY ... FROM stdin`` rows,
  WKT literals and ``ST_MakePoint``/``ST_Point`` calls;
* KML/KMZ and GPX; HTML (Leaflet markers, ``L.latLng``/``new L.LatLng``,
  polylines and polygons, embedded GeoJSON, folium ``location=``, tables).

Field names include Spanish/Portuguese/Italian spellings (``Latitud``,
``Longitud``) and abbreviations (``lat.``, ``long.``).

Anything that cannot be verified fails closed: an unreadable or oversized
file, a Parquet file without ``pyarrow``, a corrupt archive, or a tracked
path that is missing from the working tree (a sparse checkout).

Only files on the explicit :data:`ALLOWLIST` of small synthetic test fixtures
are exempt. The report names files, fields and counts only. It never prints
a coordinate value, so its output is safe to paste into a public pull
request.

Not scanned (documented follow-ups in
``docs/privacy/TRACKED-LOCALITY-REMEDIATION.md``): source code (``.py``,
``.js``, ``.ts``), Markdown, UTF-16 text, degree-minute-second notation,
unlabelled ``x``/``y`` outside a geometry context, and ``INSERT`` statements
without a column list.

Exit codes: 0 clean, 1 precise coordinates (or an unverifiable file) found,
2 usage error.
"""

from __future__ import annotations

import argparse
import ast
import csv
import gzip
import html
import io
import json
import re
import subprocess
import sys
import tarfile
import zipfile
import zlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import BinaryIO

DELIMITED_SUFFIXES = frozenset({".csv", ".tsv"})
JSON_SUFFIXES = frozenset({".json", ".geojson", ".topojson"})
JSON_LINES_SUFFIXES = frozenset({".jsonl", ".ndjson", ".geojsonl"})
YAML_SUFFIXES = frozenset({".yaml", ".yml"})
WORKBOOK_SUFFIXES = frozenset({".xlsx", ".xlsm"})
HTML_SUFFIXES = frozenset({".html", ".htm"})
XML_SUFFIXES = frozenset({".kml", ".gpx"})
ZIP_SUFFIXES = frozenset({".zip", ".kmz"})
TAR_SUFFIXES = frozenset({".tar", ".tgz"})
SCANNED_SUFFIXES = (
    DELIMITED_SUFFIXES
    | JSON_SUFFIXES
    | JSON_LINES_SUFFIXES
    | YAML_SUFFIXES
    | WORKBOOK_SUFFIXES
    | HTML_SUFFIXES
    | XML_SUFFIXES
    | ZIP_SUFFIXES
    | TAR_SUFFIXES
    | {".parquet", ".sql", ".ipynb", ".gz"}
)

# Values at or coarser than this many decimal places are generalised enough
# for a public repository (0.01 degree is roughly 1 km).
MAX_PUBLIC_DECIMALS = 2

# A file (or archive member) larger than this is not loaded into memory; it
# fails closed as unverifiable. Delimited text is streamed and has no limit.
MAX_IN_MEMORY_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_DEPTH = 3

# Explicit allowlist: repository path -> justification. Only small test
# fixtures under ``tests/`` whose coordinates are synthetic may be listed.
# An entry that no longer produces a hit is reported as stale and fails, so
# the list cannot silently outlive the fixture it excused.
ALLOWLIST: dict[str, str] = {}
ALLOWLIST_PREFIX = "tests/"
ALLOWLIST_MAX_BYTES = 64 * 1024

# --------------------------------------------------------------------------
# Field names
# --------------------------------------------------------------------------

# English, plus the Spanish/Portuguese/Italian spellings that Latin American
# herbarium and Excel exports use ("Latitud", "Longitud", "lat.", "long.").
_LAT_TOKENS = frozenset(
    {"lat", "latitude", "lati", "decimallatitude", "latitud", "latitudine"}
)
_LON_TOKENS = frozenset(
    {
        "lon",
        "lng",
        "longitude",
        "long",
        "decimallongitude",
        "longitud",
        "longitudine",
    }
)
# A field that measures something about a coordinate rather than holding one.
_NOT_A_COORDINATE_TOKENS = frozenset(
    {"uncertainty", "error", "err", "precision", "accuracy", "resolution", "delta"}
)
# Keys whose value is a coordinate pair, a position array or a geometry.
PAIR_KEYS = frozenset(
    {
        "coordinates",
        "coordinate",
        "coords",
        "coord",
        "latlng",
        "latlon",
        "latlong",
        "lnglat",
        "lonlat",
        "location",
        "point",
        "geopoint",
        "geolocation",
        "center",
        "centre",
        "centroid",
        "bbox",
        "geo",
    }
)
# Keys whose value is a sequence of positions: every position is checked.
POSITION_LIST_KEYS = frozenset(
    {
        "points",
        "positions",
        "path",
        "paths",
        "route",
        "track",
        "trace",
        "vertices",
        "locations",
        "sites",
        "markers",
        "polyline",
        "polygon",
        "line",
        "ring",
        "rings",
        "shape",
        "geometry",
        "geometries",
    }
)
# Anonymous numeric pairs (a bare ``[[a, b], ...]`` array under no telling
# key, or pandas ``orient="values"`` rows) are only counted when at least
# ANONYMOUS_PAIR_MIN_ROWS rows, and ANONYMOUS_PAIR_MIN_SHARE of all rows,
# hold a coordinate-plausible pair finer than the floor in the same two
# adjacent columns. One or two such pairs are common in ordinary numeric data
# (chart points, ratios); five aligned rows of in-range values with three or
# more decimals is the shape of a point list. A short anonymous list escapes
# this rule; one under a coordinate or position key does not.
ANONYMOUS_PAIR_MIN_ROWS = 5
ANONYMOUS_PAIR_MIN_SHARE = 0.8
# Parent keys that put an ``{"x": ..., "y": ...}`` object in geographic context.
_XY_CONTEXT_KEYS = frozenset(
    {"geometry", "geom", "location", "loc", "point", "geo", "geopoint", "coords"}
    | {"coordinates", "coordinate", "coord", "centroid", "center", "centre"}
)
_XY_CRS_KEYS = frozenset({"spatialreference", "crs", "srid", "wkid"})
GEOMETRY_TYPES = frozenset(
    {
        "point",
        "multipoint",
        "linestring",
        "multilinestring",
        "polygon",
        "multipolygon",
    }
)


def _tokens(key: object) -> list[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key).strip())
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if token]


def _compact(key: object) -> str:
    return "".join(_tokens(key))


def coordinate_axis(key: object) -> str | None:
    """Return ``"lat"``/``"lon"`` for a latitude/longitude-like field name."""

    tokens = _tokens(key)
    if not tokens or _NOT_A_COORDINATE_TOKENS.intersection(tokens):
        return None
    compact = "".join(tokens)
    if compact in PAIR_KEYS:
        return None
    has_lat = bool(_LAT_TOKENS.intersection(tokens)) or compact in _LAT_TOKENS
    lon_tokens = set(_LON_TOKENS.intersection(tokens))
    # "long" is an ordinary English word; only a bare "long" column counts.
    if "long" in lon_tokens and tokens != ["long"]:
        lon_tokens.discard("long")
    has_lon = bool(lon_tokens) or compact in _LON_TOKENS
    if has_lat and not has_lon:
        return "lat"
    if has_lon and not has_lat:
        return "lon"
    return None


def is_pair_key(key: object) -> bool:
    tokens = _tokens(key)
    if not tokens:
        return False
    compact = "".join(tokens)
    if compact in PAIR_KEYS:
        return True
    return bool(_LAT_TOKENS.intersection(tokens)) and bool(
        {"lon", "lng", "long", "longitude", "longitud"}.intersection(tokens)
    )


# --------------------------------------------------------------------------
# Values
# --------------------------------------------------------------------------

_NUM = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_NUMBER_TEXT = re.compile(rf"^\s*({_NUM})\s*°?\s*[NSEWnsew]?\s*$")
_COMMA_DECIMAL_TEXT = re.compile(r"^\s*([+-]?\d{1,3}),(\d+)\s*°?\s*[NSEWnsew]?\s*$")
_PAIR_TEXT = re.compile(rf"^\s*\(?\s*({_NUM})\s*[,; ]\s*({_NUM})\s*\)?\s*$")


def parse_number(value: object) -> Decimal | None:
    """Parse a coordinate-like value; comma decimals and exponents are accepted."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        text = repr(value)
    elif isinstance(value, str):
        text = value
    else:
        return None
    match = _NUMBER_TEXT.match(text)
    if match:
        text = match.group(1)
    else:
        comma = _COMMA_DECIMAL_TEXT.match(text)
        if comma is None:
            return None
        text = f"{comma.group(1)}.{comma.group(2)}"
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def decimal_places(number: Decimal) -> int:
    """Significant decimal places; trailing zeros are not precision."""

    if number == 0:
        return 0
    exponent = number.normalize().as_tuple().exponent
    return max(0, -exponent) if isinstance(exponent, int) else 0


def is_precise(value: object, axis: str) -> bool:
    number = parse_number(value)
    if number is None or decimal_places(number) <= MAX_PUBLIC_DECIMALS:
        return False
    return abs(number) <= (90 if axis == "lat" else 180)


def pair_is_precise(first: object, second: object) -> bool:
    """A two-number position in either axis order, finer than the floor."""

    a, b = parse_number(first), parse_number(second)
    if a is None or b is None:
        return False
    if abs(a) > 180 or abs(b) > 180 or min(abs(a), abs(b)) > 90:
        return False
    return max(decimal_places(a), decimal_places(b)) > MAX_PUBLIC_DECIMALS


def pair_text_is_precise(value: object) -> bool:
    if not isinstance(value, str):
        return False
    match = _PAIR_TEXT.match(value)
    return bool(match) and pair_is_precise(match.group(1), match.group(2))


@dataclass
class FileFinding:
    path: str
    precise_values: int = 0
    fields: set[str] = field(default_factory=set)
    error: str | None = None

    def hit(self, label: str, count: int = 1) -> None:
        if count:
            self.precise_values += count
            self.fields.add(label)

    def fail_closed(self, reason: str) -> None:
        if self.error is None:
            self.error = reason

    def describe(self) -> str:
        if self.error:
            return f"{self.path}: cannot verify ({self.error})"
        return (
            f"{self.path}: {self.precise_values} coordinate hit(s) finer than "
            f"{MAX_PUBLIC_DECIMALS} dp in {', '.join(sorted(self.fields))}"
        )


# --------------------------------------------------------------------------
# Free-text patterns (HTML, KML/GPX, SQL, notebooks, strings in documents)
# --------------------------------------------------------------------------

_POSITION_ARRAY = re.compile(rf"\[\s*({_NUM})\s*,\s*({_NUM})(?:\s*,\s*{_NUM})?\s*\]")
_WKT = re.compile(
    r"\b(?:MULTI)?(?:POINT|LINESTRING|POLYGON)\s*(?:ZM|Z|M)?\s*\(([-+\d\s.,()eE]*)\)",
    re.IGNORECASE,
)
_WKT_POSITION = re.compile(rf"({_NUM})\s+({_NUM})")
_LEAFLET_POINT = re.compile(
    rf"L\.(?:circleMarker|marker|circle|latLng|LatLng|latlng)\(\s*\[?\s*({_NUM})\s*,"
    rf"\s*({_NUM})"
)
# folium.Marker([lat, lon]), CircleMarker(location=(lat, lon)), location=[...]
_FOLIUM_POINT = re.compile(
    rf"(?:\b(?:Marker|CircleMarker|Circle|Map)\(\s*(?:location\s*=\s*)?|"
    rf"\blocation\s*=\s*)[\[(]\s*({_NUM})\s*,\s*({_NUM})"
)
_LEAFLET_SHAPE = re.compile(
    r"L\.(?:polyline|polygon|rectangle)\(\s*(\[[-+\d\s.,\[\]eE]*\])"
)
_TEXT_GEOJSON_COORDINATES = re.compile(
    r"[\"']?coordinates[\"']?\s*:\s*(\[[-+\d\s.,\[\]eE]*\])", re.IGNORECASE
)
_POSTGIS_POINT = re.compile(
    rf"ST_(?:Make)?Point\s*\(\s*({_NUM})\s*,\s*({_NUM})", re.IGNORECASE
)
_KML_COORDINATES = re.compile(r"<(?:\w+:)?coordinates\s*>([^<]*)<", re.IGNORECASE)
_KML_GX_COORD = re.compile(rf"<gx:coord\s*>\s*({_NUM})\s+({_NUM})", re.IGNORECASE)
_XML_TAG = re.compile(r"<[A-Za-z][^<>]*>")
_XML_ATTRIBUTE = re.compile(r"([\w:.-]+)\s*=\s*[\"']([^\"']*)[\"']")
_XML_ELEMENT = re.compile(r"<(?:\w+:)?([A-Za-z_][\w.-]*)\s*>\s*([^<]{1,64}?)\s*</")
_KEY_VALUE = re.compile(
    rf"[\"']?([A-Za-z_][\w.-]{{0,63}})[\"']?\s*(?::|=|=>)\s*[\"']?({_NUM})(?![\w.])"
)


def _positions_in_array_text(text: str, finding: FileFinding, label: str) -> None:
    for match in _POSITION_ARRAY.finditer(text):
        if pair_is_precise(match.group(1), match.group(2)):
            finding.hit(label)


def scan_text(text: str, finding: FileFinding, *, key_values: bool) -> None:
    """Scan free text for coordinate literals in the notations above."""

    for match in _WKT.finditer(text):
        for position in _WKT_POSITION.finditer(match.group(1)):
            if pair_is_precise(position.group(1), position.group(2)):
                finding.hit("wkt")
    for match in _POSTGIS_POINT.finditer(text):
        if pair_is_precise(match.group(1), match.group(2)):
            finding.hit("st_point")
    for match in _LEAFLET_POINT.finditer(text):
        if pair_is_precise(match.group(1), match.group(2)):
            finding.hit("leaflet.marker")
    for match in _FOLIUM_POINT.finditer(text):
        if pair_is_precise(match.group(1), match.group(2)):
            finding.hit("folium.location")
    for match in _LEAFLET_SHAPE.finditer(text):
        _positions_in_array_text(match.group(1), finding, "leaflet.shape")
    for match in _TEXT_GEOJSON_COORDINATES.finditer(text):
        _positions_in_array_text(match.group(1), finding, "geojson.coordinates")
    if key_values:
        for match in _KEY_VALUE.finditer(text):
            axis = coordinate_axis(match.group(1))
            if axis and is_precise(match.group(2), axis):
                finding.hit(f"text.{axis}")


def scan_xml_text(text: str, finding: FileFinding) -> None:
    """KML/GPX: ``<coordinates>``, ``<gx:coord>``, ``lat=``/``lon=`` attributes."""

    for match in _KML_COORDINATES.finditer(text):
        for position in match.group(1).split():
            parts = position.split(",")
            if len(parts) >= 2 and pair_is_precise(parts[0], parts[1]):
                finding.hit("kml.coordinates")
    for match in _KML_GX_COORD.finditer(text):
        if pair_is_precise(match.group(1), match.group(2)):
            finding.hit("kml.gx_coord")
    for tag in _XML_TAG.finditer(text):
        for name, value in _XML_ATTRIBUTE.findall(tag.group(0)):
            axis = coordinate_axis(name.split(":")[-1])
            if axis and is_precise(value, axis):
                finding.hit(f"xml.@{axis}")
    for name, value in _XML_ELEMENT.findall(text):
        axis = coordinate_axis(name)
        if axis and is_precise(value, axis):
            finding.hit(f"xml.{axis}")


# --------------------------------------------------------------------------
# Structured documents (JSON, YAML, notebooks)
# --------------------------------------------------------------------------


def _scan_positions(node: object, finding: FileFinding, label: str) -> None:
    """Every position nested anywhere in a coordinate array."""

    stack = [node]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if isinstance(current, (dict, list, tuple)):
            if id(current) in seen:
                continue
            seen.add(id(current))
        if isinstance(current, dict):
            stack.extend(current.values())
            continue
        if not isinstance(current, (list, tuple)):
            if pair_text_is_precise(current):
                finding.hit(label)
            continue
        if len(current) in (2, 3) and not any(
            isinstance(item, (list, tuple, dict)) for item in current
        ):
            if pair_is_precise(current[0], current[1]):
                finding.hit(label)
            continue
        if len(current) == 4 and not any(
            isinstance(item, (list, tuple, dict)) for item in current
        ):
            # A bounding box: [west, south, east, north].
            if pair_is_precise(current[0], current[1]) or pair_is_precise(
                current[2], current[3]
            ):
                finding.hit(label)
            continue
        stack.extend(current)


def _scalars(value: object, limit: int = 1_000_000) -> Iterator[object]:
    """Every scalar nested in a list/dict value (pandas ``orient="columns"``)."""

    stack = [value]
    seen = 0
    while stack and seen < limit:
        current = stack.pop()
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, (list, tuple)):
            stack.extend(current)
        else:
            seen += 1
            yield current


def _is_row(item: object) -> bool:
    return (
        isinstance(item, (list, tuple))
        and 2 <= len(item) <= 64
        and not any(isinstance(cell, (list, tuple, dict)) for cell in item)
    )


def scan_anonymous_rows(rows: list[object], finding: FileFinding) -> None:
    """Aligned numeric pairs in an unlabelled array; see ANONYMOUS_PAIR_MIN_ROWS."""

    if len(rows) < ANONYMOUS_PAIR_MIN_ROWS or not all(_is_row(row) for row in rows):
        return
    width = min(len(row) for row in rows)  # type: ignore[arg-type]
    best = 0
    for column in range(width - 1):
        count = sum(
            1
            for row in rows
            if pair_is_precise(row[column], row[column + 1])  # type: ignore[index]
        )
        best = max(best, count)
    if best >= ANONYMOUS_PAIR_MIN_ROWS and best >= ANONYMOUS_PAIR_MIN_SHARE * len(rows):
        finding.hit("anonymous.pairs", best)


def _scan_split_table(document: dict, finding: FileFinding) -> bool:
    """pandas ``orient="split"``: ``{"columns": [...], "data": [[...], ...]}``."""

    columns, data = document.get("columns"), document.get("data")
    if not (
        isinstance(columns, list)
        and isinstance(data, list)
        and all(isinstance(column, str) for column in columns)
    ):
        return False
    table = TableScanner(finding)
    table.row(columns)
    for row in data:
        if isinstance(row, (list, tuple)):
            table.row(row)
    return True


def walk_document(node: object, finding: FileFinding) -> None:
    stack: list[tuple[str, object]] = [("", node)]
    seen: set[int] = set()
    while stack:
        parent_key, current = stack.pop()
        if isinstance(current, (dict, list, tuple)):
            # YAML anchors can make a document reference itself.
            if id(current) in seen:
                continue
            seen.add(id(current))
        if isinstance(current, (list, tuple)):
            scan_anonymous_rows(list(current), finding)
            stack.extend((parent_key, item) for item in current)
            continue
        if isinstance(current, str):
            scan_text(current, finding, key_values=False)
            continue
        if not isinstance(current, dict):
            continue
        _scan_split_table(current, finding)
        geometry_type = current.get("type")
        if (
            isinstance(geometry_type, str)
            and geometry_type.lower() in GEOMETRY_TYPES
            and "coordinates" in current
        ):
            _scan_positions(
                current["coordinates"], finding, f"geometry.{geometry_type}"
            )
        lowered = {_compact(key): key for key in current}
        if "x" in lowered and "y" in lowered:
            has_context = _compact(parent_key) in _XY_CONTEXT_KEYS or bool(
                _XY_CRS_KEYS.intersection(lowered)
            )
            if has_context and pair_is_precise(
                current[lowered["x"]], current[lowered["y"]]
            ):
                finding.hit("x/y")
        for key, value in current.items():
            if (
                key == "coordinates"
                and isinstance(geometry_type, str)
                and geometry_type.lower() in GEOMETRY_TYPES
            ):
                continue
            axis = coordinate_axis(key)
            if axis and not isinstance(value, (dict, list, tuple)):
                if is_precise(value, axis) or pair_text_is_precise(value):
                    finding.hit(_compact(key) or axis)
                continue
            if axis:
                # {"lat": [...]} and pandas {"lat": {"0": v, ...}}.
                label = _compact(key) or axis
                for scalar in _scalars(value):
                    if is_precise(scalar, axis) or pair_text_is_precise(scalar):
                        finding.hit(label)
                continue
            if _compact(key) in POSITION_LIST_KEYS and isinstance(value, (list, tuple)):
                _scan_positions(value, finding, _compact(key))
                stack.append((str(key), value))
                continue
            if is_pair_key(key) and isinstance(value, (list, tuple, str)):
                _scan_positions(value, finding, _compact(key))
                if isinstance(value, str):
                    scan_text(value, finding, key_values=False)
                continue
            if isinstance(value, (dict, list, tuple, str)):
                stack.append((str(key), value))


def _load_json(text: str) -> object:
    return json.loads(text, parse_float=Decimal)


def scan_json_text(text: str, finding: FileFinding) -> None:
    try:
        document = _load_json(text)
    except (json.JSONDecodeError, RecursionError):
        # Not strict JSON (comments, a template): scan it as text instead.
        scan_text(text, finding, key_values=True)
        return
    walk_document(document, finding)


def scan_json_lines_text(text: str, finding: FileFinding) -> None:
    for line in text.splitlines():
        if line.strip():
            scan_json_text(line, finding)


def scan_yaml_text(text: str, finding: FileFinding) -> None:
    try:
        import yaml
    except ImportError:
        scan_text(text, finding, key_values=True)
        return
    try:
        documents = list(yaml.safe_load_all(text))
    except yaml.YAMLError:
        scan_text(text, finding, key_values=True)
        return
    for document in documents:
        walk_document(document, finding)


def _joined(value: object) -> str:
    if isinstance(value, list):
        return "".join(str(item) for item in value)
    return value if isinstance(value, str) else ""


def scan_notebook_text(text: str, finding: FileFinding) -> None:
    """Every cell source and output, through the same detectors as files."""

    try:
        notebook = _load_json(text)
    except (json.JSONDecodeError, RecursionError):
        finding.fail_closed("notebook is not valid JSON")
        return
    cells = notebook.get("cells", []) if isinstance(notebook, dict) else []
    for cell in cells if isinstance(cells, list) else []:
        if not isinstance(cell, dict):
            continue
        scan_text_document(_joined(cell.get("source")), finding, python=True)
        outputs = cell.get("outputs")
        for output in outputs if isinstance(outputs, list) else []:
            if not isinstance(output, dict):
                continue
            # stream output (print(df), print(df.to_csv())) and error text
            scan_text_document(_joined(output.get("text")), finding, python=False)
            data = output.get("data")
            for mime, payload in (data if isinstance(data, dict) else {}).items():
                if "json" in str(mime) and not isinstance(payload, (str, list)):
                    walk_document(payload, finding)
                else:
                    scan_text_document(_joined(payload), finding, python=False)


def scan_text_document(text: str, finding: FileFinding, *, python: bool) -> None:
    """Free text that may hold a table, JSON, HTML or (for sources) Python."""

    if not text.strip():
        return
    scan_text(text, finding, key_values=True)
    stripped = text.strip()
    if stripped[:1] in "[{":
        try:
            walk_document(_load_json(stripped), finding)
        except (json.JSONDecodeError, RecursionError):
            pass
    if "<t" in text.lower():
        scan_html_tables(text, finding)
    scan_text_tables(text, finding)
    if python:
        scan_python_literals(text, finding)


_HTML_ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr\s*>", re.IGNORECASE | re.DOTALL)
_HTML_CELL = re.compile(r"<t([hd])\b[^>]*>(.*?)</t[hd]\s*>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_TEXT = re.compile(r"<[^>]+>")


def scan_html_tables(text: str, finding: FileFinding) -> None:
    """``<table>`` rows, such as a notebook's DataFrame HTML output."""

    table = TableScanner(finding)
    for row in _HTML_ROW.finditer(text):
        cells = [
            html.unescape(_HTML_TAG_TEXT.sub("", cell)).strip()
            for _kind, cell in _HTML_CELL.findall(row.group(1))
        ]
        if cells:
            table.row(cells)


def scan_text_tables(text: str, finding: FileFinding) -> None:
    """Printed tables: delimited text (to_csv) or whitespace-aligned reprs."""

    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return
    sample = "\n".join(lines[:50])
    delimiter = _sniff_delimiter(sample, "")
    if delimiter:
        table = TableScanner(finding)
        for row in csv.reader(lines, delimiter=delimiter):
            table.row(row)
    # A DataFrame repr: the header has one cell fewer than the rows, because
    # the index column is unnamed.
    table = TableScanner(finding)
    header_width = 0
    for line in lines:
        cells = line.split()
        if table._header_columns(cells):
            header_width = len(cells)
            table.row(cells)
            continue
        if header_width and len(cells) == header_width + 1:
            cells = cells[1:]
        table.row(cells)


def scan_python_literals(source: str, finding: FileFinding) -> None:
    """Literal dicts/lists and ``name = number`` in (notebook) Python source."""

    code = "\n".join(
        "" if line.lstrip().startswith(("%", "!")) else line
        for line in source.splitlines()
    )
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError):
        return
    stack: list[ast.AST] = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
            try:
                walk_document(ast.literal_eval(node), finding)
                continue
            except (ValueError, TypeError, SyntaxError, RecursionError):
                pass
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    walk_document({target.id: node.value.value}, finding)
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg:
                    try:
                        value = ast.literal_eval(keyword.value)
                    except (ValueError, TypeError, SyntaxError, RecursionError):
                        continue
                    walk_document({keyword.arg: value}, finding)
        stack.extend(ast.iter_child_nodes(node))


# --------------------------------------------------------------------------
# Tables (delimited text, workbooks, SQL rows)
# --------------------------------------------------------------------------

_WKT_HINT = re.compile(r"(?:POINT|LINESTRING|POLYGON)\s*[ZM]*\s*\(", re.IGNORECASE)


class TableScanner:
    """Rows of cells; any row naming a coordinate column becomes the header."""

    def __init__(self, finding: FileFinding) -> None:
        self.finding = finding
        self.columns: list[tuple[int, str, str | None]] = []

    def _header_columns(self, row: list[object]) -> list[tuple[int, str, str | None]]:
        # A header row holds names, not numbers, and names are short. Free
        # text that happens to mention "latitude" does not replace the header.
        if any(parse_number(cell) is not None for cell in row):
            return []
        columns = []
        for index, cell in enumerate(row):
            if not isinstance(cell, str) or len(cell) > 64 or len(_tokens(cell)) > 6:
                continue
            axis = coordinate_axis(cell)
            if axis:
                columns.append((index, _compact(cell), axis))
            elif is_pair_key(cell):
                columns.append((index, _compact(cell), None))
        return columns

    def row(self, row: Iterable[object]) -> None:
        cells = list(row)
        header = self._header_columns(cells)
        if header:
            self.columns = header
            return
        for index, name, axis in self.columns:
            if index >= len(cells):
                continue
            value = cells[index]
            if (axis and is_precise(value, axis)) or pair_text_is_precise(value):
                self.finding.hit(name)
        for cell in cells:
            if isinstance(cell, str) and _WKT_HINT.search(cell):
                scan_text(cell, self.finding, key_values=False)


def _sniff_delimiter(sample: str, default: str) -> str:
    candidates = ",;\t|"
    try:
        return csv.Sniffer().sniff(sample, delimiters=candidates).delimiter
    except csv.Error:
        pass
    lines = [line for line in sample.splitlines()[:20] if line.strip()]
    if not lines:
        return default
    counts = {
        delimiter: min(line.count(delimiter) for line in lines)
        for delimiter in candidates
    }
    best = max(counts, key=lambda delimiter: counts[delimiter])
    return best if counts[best] else default


def scan_delimited(
    opener: Callable[[], BinaryIO], name: str, finding: FileFinding
) -> None:
    default = "\t" if name.lower().endswith(".tsv") else ","
    with opener() as raw:
        sample = raw.read(64 * 1024).decode("utf-8-sig", errors="replace")
    delimiter = _sniff_delimiter(sample, default)
    table = TableScanner(finding)
    with opener() as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
        csv.field_size_limit(MAX_IN_MEMORY_BYTES)
        for row in csv.reader(text, delimiter=delimiter):
            table.row(row)


def scan_workbook(data: bytes, finding: FileFinding) -> None:
    try:
        import openpyxl
    except ImportError:
        finding.fail_closed("openpyxl is not installed")
        return
    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(data), read_only=True, data_only=True
        )
    except Exception as exc:  # noqa: BLE001 - any failure is "cannot verify"
        finding.fail_closed(f"workbook did not open: {type(exc).__name__}")
        return
    try:
        for sheet in workbook.worksheets:
            table = TableScanner(finding)
            for row in sheet.iter_rows(values_only=True):
                table.row(row)
    finally:
        workbook.close()


def scan_parquet(data: bytes, finding: FileFinding) -> None:
    try:
        import pyarrow.parquet as pq
    except ImportError:
        finding.fail_closed("pyarrow is not installed, so the file cannot be verified")
        return
    try:
        parquet = pq.ParquetFile(io.BytesIO(data))
        header = list(parquet.schema_arrow.names)
        table = TableScanner(finding)
        table.row(header)
        for batch in parquet.iter_batches():
            columns = [column.to_pylist() for column in batch.columns]
            for values in zip(*columns, strict=True):
                table.row(values)
    except Exception as exc:  # noqa: BLE001 - ArrowInvalid, OSError, ...
        finding.fail_closed(f"parquet did not read: {type(exc).__name__}")


_SQL_INSERT = re.compile(
    r"INSERT\s+INTO\s+[\w.\"`\[\]]+\s*\(([^)]*)\)\s*VALUES\s*", re.IGNORECASE
)
_SQL_COPY = re.compile(
    r"^COPY\s+[\w.\"]+\s*\(([^)]*)\)\s+FROM\s+stdin[^\n]*\n(.*?)^\\\.$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


def _sql_tuples(text: str, start: int) -> Iterator[list[str]]:
    """Yield the value tuples of one INSERT ... VALUES statement."""

    index, length = start, len(text)
    while index < length:
        while index < length and text[index] in " \t\r\n,":
            index += 1
        if index >= length or text[index] != "(":
            return
        index += 1
        values: list[str] = []
        current: list[str] = []
        depth = 0
        while index < length:
            char = text[index]
            if char == "'":
                end = index + 1
                while end < length:
                    if text[end] == "'" and text[end + 1 : end + 2] == "'":
                        end += 2
                        continue
                    if text[end] == "'":
                        break
                    end += 1
                current.append(text[index + 1 : end].replace("''", "'"))
                index = end + 1
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    values.append("".join(current).strip())
                    index += 1
                    break
                depth -= 1
            elif char == "," and depth == 0:
                values.append("".join(current).strip())
                current = []
                index += 1
                continue
            current.append(char)
            index += 1
        yield values


def scan_sql_text(text: str, finding: FileFinding) -> None:
    for match in _SQL_INSERT.finditer(text):
        columns = [column.strip().strip('"`[]') for column in match.group(1).split(",")]
        table = TableScanner(finding)
        table.row(columns)
        for values in _sql_tuples(text, match.end()):
            table.row(values)
    for match in _SQL_COPY.finditer(text):
        columns = [column.strip().strip('"') for column in match.group(1).split(",")]
        table = TableScanner(finding)
        table.row(columns)
        for line in match.group(2).splitlines():
            table.row(line.split("\t"))
    scan_text(text, finding, key_values=False)


# --------------------------------------------------------------------------
# Dispatch, archives
# --------------------------------------------------------------------------


def _suffix(name: str) -> str:
    return Path(name).suffix.lower()


def _read_capped(opener: Callable[[], BinaryIO], finding: FileFinding) -> bytes | None:
    with opener() as handle:
        data = handle.read(MAX_IN_MEMORY_BYTES + 1)
    if len(data) > MAX_IN_MEMORY_BYTES:
        finding.fail_closed(f"larger than {MAX_IN_MEMORY_BYTES} bytes")
        return None
    return data


def _scan_zip(data: bytes, name: str, finding: FileFinding, depth: int) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if info.is_dir() or _suffix(info.filename) not in SCANNED_SUFFIXES:
                    continue
                if info.flag_bits & 0x1:
                    finding.fail_closed(f"encrypted member {info.filename}")
                    continue

                def opener(info: zipfile.ZipInfo = info) -> BinaryIO:
                    return archive.open(info)

                try:
                    scan_source(opener, f"{name}!{info.filename}", finding, depth + 1)
                except (zipfile.BadZipFile, zlib.error, EOFError, OSError) as exc:
                    finding.fail_closed(
                        f"member {info.filename} did not read: {type(exc).__name__}"
                    )
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError) as exc:
        finding.fail_closed(f"archive did not open: {type(exc).__name__}")


def _scan_tar(
    opener: Callable[[], BinaryIO], name: str, finding: FileFinding, depth: int
) -> None:
    try:
        with opener() as raw, tarfile.open(fileobj=raw, mode="r|*") as archive:
            for member in archive:
                if not member.isfile() or _suffix(member.name) not in SCANNED_SUFFIXES:
                    continue
                if member.size > MAX_IN_MEMORY_BYTES:
                    finding.fail_closed(f"member {member.name} is too large to verify")
                    continue
                extracted = archive.extractfile(member)
                payload = extracted.read() if extracted else b""
                scan_source(
                    lambda payload=payload: io.BytesIO(payload),
                    f"{name}!{member.name}",
                    finding,
                    depth + 1,
                )
    except (tarfile.TarError, EOFError, OSError, zlib.error) as exc:
        finding.fail_closed(f"archive did not open: {type(exc).__name__}")


def scan_source(
    opener: Callable[[], BinaryIO], name: str, finding: FileFinding, depth: int = 0
) -> None:
    """Scan one file or archive member, dispatched on its name's suffix."""

    if depth > MAX_ARCHIVE_DEPTH:
        finding.fail_closed("archives nested too deeply")
        return
    lowered = name.lower()
    suffix = _suffix(name)
    if lowered.endswith((".tar.gz", ".tgz")) or suffix == ".tar":
        _scan_tar(opener, name, finding, depth)
        return
    if suffix == ".gz":
        inner = name[: -len(".gz")]
        if _suffix(inner) not in SCANNED_SUFFIXES:
            return

        def gunzip() -> BinaryIO:
            return gzip.GzipFile(fileobj=opener())  # type: ignore[return-value]

        try:
            scan_source(gunzip, inner, finding, depth + 1)
        except (gzip.BadGzipFile, EOFError, OSError, zlib.error) as exc:
            finding.fail_closed(f"gzip did not read: {type(exc).__name__}")
        return
    if suffix in DELIMITED_SUFFIXES:
        scan_delimited(opener, name, finding)
        return
    data = _read_capped(opener, finding)
    if data is None:
        return
    if suffix in ZIP_SUFFIXES:
        _scan_zip(data, name, finding, depth)
    elif suffix in WORKBOOK_SUFFIXES:
        scan_workbook(data, finding)
    elif suffix == ".parquet":
        scan_parquet(data, finding)
    else:
        text = data.decode("utf-8-sig", errors="replace")
        if suffix in JSON_SUFFIXES:
            scan_json_text(text, finding)
        elif suffix in JSON_LINES_SUFFIXES:
            scan_json_lines_text(text, finding)
        elif suffix in YAML_SUFFIXES:
            scan_yaml_text(text, finding)
        elif suffix == ".ipynb":
            scan_notebook_text(text, finding)
        elif suffix == ".sql":
            scan_sql_text(text, finding)
        elif suffix in XML_SUFFIXES:
            scan_xml_text(text, finding)
            scan_text(text, finding, key_values=False)
        elif suffix in HTML_SUFFIXES:
            scan_text(text, finding, key_values=True)
            scan_html_tables(text, finding)


def scan_file(path: Path, display: str | None = None) -> FileFinding:
    """Scan one file; the finding counts precise values and never holds them."""

    finding = FileFinding(path=display or str(path))
    try:
        scan_source(lambda: path.open("rb"), path.name, finding)
    except (OSError, zlib.error, EOFError) as exc:
        finding.fail_closed(f"unreadable: {type(exc).__name__}")
    except (RecursionError, MemoryError) as exc:
        finding.fail_closed(f"not scannable: {type(exc).__name__}")
    return finding


def tracked_files(root: Path) -> list[str]:
    output = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout
    return [
        entry.decode("utf-8", "surrogateescape")
        for entry in output.split(b"\0")
        if entry
    ]


def is_scanned(relative: str) -> bool:
    lowered = relative.lower()
    return _suffix(relative) in SCANNED_SUFFIXES or lowered.endswith(".tar.gz")


def check(
    root: Path,
    paths: Iterable[str],
    allowlist: dict[str, str] | None = None,
) -> tuple[list[FileFinding], list[str]]:
    """Return (violations, problems with the allowlist itself)."""

    allowed = ALLOWLIST if allowlist is None else allowlist
    violations: list[FileFinding] = []
    allowlist_problems: list[str] = []
    hits: set[str] = set()
    for relative in paths:
        if not is_scanned(relative):
            continue
        absolute = root / relative
        if absolute.is_symlink():
            # Git stores a symlink as its target path, which holds no data.
            continue
        if not absolute.is_file():
            # A tracked path that is absent (sparse checkout, deleted but not
            # staged) cannot be verified, so it fails rather than being skipped.
            violations.append(
                FileFinding(
                    path=relative, error="tracked but missing from the working tree"
                )
            )
            continue
        finding = scan_file(absolute, relative)
        if not finding.precise_values and not finding.error:
            continue
        hits.add(relative)
        if relative in allowed and not finding.error:
            if not relative.startswith(ALLOWLIST_PREFIX):
                allowlist_problems.append(
                    f"{relative}: allowlisted but not under {ALLOWLIST_PREFIX}"
                )
            elif absolute.stat().st_size > ALLOWLIST_MAX_BYTES:
                allowlist_problems.append(
                    f"{relative}: allowlisted but larger than {ALLOWLIST_MAX_BYTES} bytes"
                )
            elif not allowed[relative].strip():
                allowlist_problems.append(
                    f"{relative}: allowlist entry has no justification"
                )
            continue
        violations.append(finding)
    for relative in sorted(set(allowed) - hits):
        allowlist_problems.append(
            f"{relative}: stale allowlist entry (file absent or no longer holds precise coordinates)"
        )
    return violations, allowlist_problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root (default: this script's repository)",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="repository-relative paths to scan (default: every tracked file)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not (root / ".git").exists():
        print(f"error: {root} is not a git checkout", file=sys.stderr)
        return 2
    paths = args.paths or tracked_files(root)
    violations, allowlist_problems = check(root, paths)
    out = io.StringIO()
    for finding in violations:
        print(f"PRECISE COORDINATES: {finding.describe()}", file=out)
    for problem in allowlist_problems:
        print(f"ALLOWLIST: {problem}", file=out)
    if violations or allowlist_problems:
        print(
            "Tracked data files must not carry occurrence coordinates finer than "
            f"{MAX_PUBLIC_DECIMALS} decimal places. Remove the file, generalise it, or "
            "(synthetic test fixtures only) add it to ALLOWLIST with a justification.",
            file=out,
        )
        sys.stdout.write(out.getvalue())
        return 1
    print("OK: no tracked data file carries precise occurrence coordinates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
