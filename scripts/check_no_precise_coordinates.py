"""Refuse tracked data files that carry precise occurrence coordinates.

This repository is public. Tracked data files must not carry raw occurrence
coordinates: the public Atlas generalises rare, threatened and
collection-sensitive taxa, unresolved taxa fail closed to a coarse cell, and
CITES Appendix I taxa are generalised to at least 0.1 degree. A committed
data file bypasses every one of those runtime safeguards.

The check scans every tracked ``.csv``, ``.tsv``, ``.geojson``, ``.json``,
``.parquet`` and ``.xlsx`` file for latitude/longitude-like columns or keys
(``decimal_latitude``, ``latitude``, ``lat``, ``lon``, ``lng``,
``longitude``, ... and GeoJSON ``Point``/``MultiPoint`` geometries) whose
values are finer than two decimal places. Tracked ``.html`` files are
checked for Leaflet markers (``L.circleMarker([lat, lon])`` and friends),
which is how a generated folium map embeds its points. Any hit fails, unless the file is
on the explicit :data:`ALLOWLIST` of small, synthetic test fixtures.

The report names files, columns and counts only. It never prints a
coordinate value, so its output is safe to paste into a public pull request.

Exit codes: 0 clean, 1 precise coordinates (or an unverifiable file) found,
2 usage error.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

SCANNED_SUFFIXES = frozenset(
    {".csv", ".tsv", ".geojson", ".json", ".parquet", ".xlsx", ".html", ".htm"}
)

# Values at or coarser than this many decimal places are generalised enough
# for a public repository (0.01 degree is roughly 1 km).
MAX_PUBLIC_DECIMALS = 2

LATITUDE_KEYS = frozenset({"decimal_latitude", "decimallatitude", "latitude", "lat"})
LONGITUDE_KEYS = frozenset(
    {"decimal_longitude", "decimallongitude", "longitude", "lon", "lng"}
)
COORDINATE_KEYS = LATITUDE_KEYS | LONGITUDE_KEYS
POINT_GEOMETRY_TYPES = frozenset({"point", "multipoint"})

# Explicit allowlist: repository path -> justification. Only small test
# fixtures under ``tests/`` whose coordinates are synthetic may be listed.
# An entry that no longer produces a hit is reported as stale and fails, so
# the list cannot silently outlive the fixture it excused.
ALLOWLIST: dict[str, str] = {}
ALLOWLIST_PREFIX = "tests/"
ALLOWLIST_MAX_BYTES = 64 * 1024

# A JSON key is always a quoted string followed by a colon. If none of these
# keys appears anywhere in a file's bytes, the file provably has no
# coordinate key and does not need to be parsed.
_JSON_KEY_PROBE = re.compile(
    rb'"(?:decimal_?latitude|decimal_?longitude|latitude|longitude|lat|lon|lng|'
    rb'coordinates)"\s*:',
    re.IGNORECASE,
)
_PROBE_CHUNK = 1 << 20
_PROBE_OVERLAP = 64

# A generated folium/Leaflet map embeds each point as a marker call.
_LEAFLET_MARKER = re.compile(
    rb"L\.(?:circleMarker|marker|circle)\(\s*\[\s*([+-]?\d+(?:\.\d+)?)\s*,"
    rb"\s*([+-]?\d+(?:\.\d+)?)\s*\]"
)

_DECIMAL_TEXT = re.compile(r"^\s*[+-]?\d{1,3}\.(\d+)\s*$")


@dataclass
class FileFinding:
    path: str
    precise_values: int = 0
    fields: set[str] = field(default_factory=set)
    error: str | None = None

    def describe(self) -> str:
        if self.error:
            return f"{self.path}: cannot verify ({self.error})"
        return (
            f"{self.path}: {self.precise_values} coordinate hit(s) finer than "
            f"{MAX_PUBLIC_DECIMALS} dp in {', '.join(sorted(self.fields))}"
        )


def _normalise_key(key: object) -> str:
    return str(key).strip().lower().replace("-", "_").replace(" ", "_")


def _decimal_places(value: object) -> int | None:
    """Return the significant decimal places of a numeric coordinate value.

    ``None`` means the value is not a number. Trailing zeros are not
    precision (``1.500`` has one significant decimal place).
    """

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return 0
    if isinstance(value, float):
        text = repr(value)
    elif isinstance(value, Decimal):
        text = format(value, "f")
    elif isinstance(value, str):
        text = value
    else:
        return None
    match = _DECIMAL_TEXT.match(text)
    if match is None:
        try:
            Decimal(text.strip())
        except (InvalidOperation, ValueError):
            return None
        return 0
    return len(match.group(1).rstrip("0"))


def _is_precise(value: object, *, latitude: bool) -> bool:
    places = _decimal_places(value)
    if places is None or places <= MAX_PUBLIC_DECIMALS:
        return False
    try:
        number = abs(Decimal(str(value).strip()))
    except (InvalidOperation, ValueError):
        return False
    return number <= (90 if latitude else 180)


def _scan_rows(
    header: list[str], rows: Iterable[Iterable[object]], finding: FileFinding
) -> None:
    columns = [
        (index, name, name in LATITUDE_KEYS)
        for index, name in enumerate(_normalise_key(column) for column in header)
        if name in COORDINATE_KEYS
    ]
    if not columns:
        return
    for row in rows:
        cells = list(row)
        for index, name, latitude in columns:
            if index < len(cells) and _is_precise(cells[index], latitude=latitude):
                finding.precise_values += 1
                finding.fields.add(name)


def _scan_delimited(path: Path, finding: FileFinding, delimiter: str) -> None:
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        header = next(reader, None)
        if header is None:
            return
        _scan_rows(header, reader, finding)


def _json_may_hold_coordinates(path: Path) -> bool:
    tail = b""
    with path.open("rb") as handle:
        while chunk := handle.read(_PROBE_CHUNK):
            window = tail + chunk
            if _JSON_KEY_PROBE.search(window):
                return True
            tail = window[-_PROBE_OVERLAP:]
    return False


def _walk_json(node: object, finding: FileFinding) -> None:
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, list):
            stack.extend(current)
            continue
        if not isinstance(current, dict):
            continue
        geometry_type = current.get("type")
        if (
            isinstance(geometry_type, str)
            and geometry_type.lower() in POINT_GEOMETRY_TYPES
            and "coordinates" in current
        ):
            _scan_geojson_positions(current["coordinates"], finding)
        for key, value in current.items():
            name = _normalise_key(key)
            if name in COORDINATE_KEYS and not isinstance(value, (dict, list)):
                if _is_precise(value, latitude=name in LATITUDE_KEYS):
                    finding.precise_values += 1
                    finding.fields.add(name)
            elif isinstance(value, (dict, list)):
                stack.append(value)


def _scan_geojson_positions(coordinates: object, finding: FileFinding) -> None:
    positions: list[object] = []
    if (
        isinstance(coordinates, list)
        and coordinates
        and not isinstance(coordinates[0], list)
    ):
        positions = [coordinates]
    elif isinstance(coordinates, list):
        positions = list(coordinates)
    for position in positions:
        if not isinstance(position, list) or len(position) < 2:
            continue
        longitude, latitude = position[0], position[1]
        if _is_precise(longitude, latitude=False) or _is_precise(
            latitude, latitude=True
        ):
            finding.precise_values += 1
            finding.fields.add("geometry.Point")


def _scan_json(path: Path, finding: FileFinding) -> None:
    if not _json_may_hold_coordinates(path):
        return
    with path.open(encoding="utf-8", errors="replace") as handle:
        try:
            document = json.load(handle, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            finding.error = (
                f"coordinate-like keys present but JSON did not parse: {exc.msg}"
            )
            return
    _walk_json(document, finding)


def _scan_html(path: Path, finding: FileFinding) -> None:
    # Marker calls are short, so a chunk overlap longer than one call is enough
    # to see every call once when streaming.
    tail = b""
    counted_until = 0
    offset = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_PROBE_CHUNK):
            window = tail + chunk
            window_start = offset - len(tail)
            for match in _LEAFLET_MARKER.finditer(window):
                if window_start + match.start() < counted_until:
                    continue
                latitude = match.group(1).decode("ascii")
                longitude = match.group(2).decode("ascii")
                if _is_precise(latitude, latitude=True) or _is_precise(
                    longitude, latitude=False
                ):
                    finding.precise_values += 1
                    finding.fields.add("leaflet.marker")
                counted_until = window_start + match.end()
            offset += len(chunk)
            tail = window[-_PROBE_OVERLAP * 4 :]


def _xlsx_rows(
    path: Path,
) -> Iterator[tuple[str, list[object], Iterator[Iterable[object]]]]:
    import openpyxl

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets:
            rows = sheet.iter_rows(values_only=True)
            header = next(rows, None)
            if header is not None:
                yield (
                    sheet.title,
                    [str(cell) if cell is not None else "" for cell in header],
                    rows,
                )
    finally:
        workbook.close()


def _scan_xlsx(path: Path, finding: FileFinding) -> None:
    try:
        sheets = list(_xlsx_rows(path))
    except ImportError:
        finding.error = "openpyxl is not installed"
        return
    except (zipfile.BadZipFile, OSError, KeyError, ValueError) as exc:
        finding.error = f"workbook did not open: {type(exc).__name__}"
        return
    for _title, header, rows in sheets:
        _scan_rows(header, rows, finding)


def _scan_parquet(path: Path, finding: FileFinding) -> None:
    try:
        import pyarrow.parquet as pq
    except ImportError:
        finding.error = "pyarrow is not installed, so the file cannot be verified"
        return
    parquet = pq.ParquetFile(path)
    header = list(parquet.schema_arrow.names)
    if not any(_normalise_key(name) in COORDINATE_KEYS for name in header):
        return
    for batch in parquet.iter_batches():
        columns = [
            batch.column(index).to_pylist() for index in range(batch.num_columns)
        ]
        _scan_rows(header, (list(row) for row in zip(*columns, strict=True)), finding)


def scan_file(path: Path, display: str | None = None) -> FileFinding:
    """Scan one data file; the finding counts precise values and never holds them."""

    finding = FileFinding(path=display or str(path))
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            _scan_delimited(path, finding, ",")
        elif suffix == ".tsv":
            _scan_delimited(path, finding, "\t")
        elif suffix in {".json", ".geojson"}:
            _scan_json(path, finding)
        elif suffix in {".html", ".htm"}:
            _scan_html(path, finding)
        elif suffix == ".xlsx":
            _scan_xlsx(path, finding)
        elif suffix == ".parquet":
            _scan_parquet(path, finding)
    except OSError as exc:
        finding.error = f"unreadable: {type(exc).__name__}"
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
        if Path(relative).suffix.lower() not in SCANNED_SUFFIXES:
            continue
        absolute = root / relative
        if not absolute.is_file():
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
