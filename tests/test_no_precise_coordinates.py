"""Guard: no tracked data file carries precise occurrence coordinates.

The repository is public, so a committed occurrence file bypasses every
runtime locality safeguard. ``test_tracked_files_hold_no_precise_coordinates``
runs the guard over ``git ls-files``; the remaining tests pin the detector's
behaviour on small files built in a temporary directory.

Every coordinate value in this module is SYNTHETIC: invented numbers used
only to exercise the detector, not observations of any organism.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import check_no_precise_coordinates as guard

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_no_precise_coordinates.py"

# SYNTHETIC values. PRECISE_* have more than two significant decimals.
PRECISE_LAT = "12.3456"
PRECISE_LON = "-45.6789"
COARSE_LAT = "12.34"
COARSE_LON = "-45.60"


def _scan(tmp_path: Path, name: str, content: str | bytes) -> guard.FileFinding:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return guard.scan_file(path, name)


def test_tracked_files_hold_no_precise_coordinates():
    if not (REPO_ROOT / ".git").exists():
        pytest.fail(
            "the guard must run from a git checkout; refusing to pass without one"
        )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("OK:")


def test_removed_coordinate_files_are_not_tracked():
    tracked = set(guard.tracked_files(REPO_ROOT))
    for removed in (
        "orchid_points.csv",
        "ecuador_orchids.geojson",
        "ecuador_orchids.geojson.json",
        "orchid_atlas.html",
        "orchid_atlas.py",
        "orchid_api.py",
    ):
        assert removed not in tracked, removed


def test_allowlist_is_restricted_to_small_synthetic_test_fixtures():
    for path, justification in guard.ALLOWLIST.items():
        assert path.startswith(guard.ALLOWLIST_PREFIX), path
        assert "synthetic" in justification.lower(), path


@pytest.mark.parametrize(
    ("header", "delimiter"),
    [
        ("decimal_latitude,decimal_longitude", ","),
        ("Latitude,Longitude", ","),
        ("lat\tlng", "\t"),
        ("decimalLatitude,decimalLongitude", ","),
    ],
)
def test_delimited_precise_coordinates_are_found(tmp_path, header, delimiter):
    suffix = ".tsv" if delimiter == "\t" else ".csv"
    body = f"{header}\n{PRECISE_LAT}{delimiter}{PRECISE_LON}\n{COARSE_LAT}{delimiter}{COARSE_LON}\n"
    finding = _scan(tmp_path, f"points{suffix}", body)
    assert finding.precise_values == 2
    assert finding.error is None


def test_coarse_and_trailing_zero_values_pass(tmp_path):
    body = f"latitude,longitude\n{COARSE_LAT},{COARSE_LON}\n12.3000,-45.1000\n12,-45\n"
    assert _scan(tmp_path, "coarse.csv", body).precise_values == 0


def test_precise_numbers_in_non_coordinate_columns_pass(tmp_path):
    body = f"species_key,temp_mean,rain_mean\nx,{PRECISE_LAT},{PRECISE_LON}\n"
    assert _scan(tmp_path, "climate.csv", body).precise_values == 0


def test_out_of_range_values_are_not_coordinates(tmp_path):
    body = "lat,lon\n123.4567,456.7891\n"
    assert _scan(tmp_path, "notcoords.csv", body).precise_values == 0


def test_geojson_point_geometry_is_found(tmp_path):
    document = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(PRECISE_LON), float(PRECISE_LAT)],
                },
                "properties": {"scientific_name": "Synthetic example"},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(COARSE_LON), float(COARSE_LAT)],
                },
                "properties": {},
            },
        ],
    }
    finding = _scan(tmp_path, "points.geojson", json.dumps(document))
    assert finding.precise_values == 1
    assert finding.fields == {"geometry.Point"}


def test_nested_json_keys_and_string_values_are_found(tmp_path):
    document = {
        "records": [{"location": {"lat": PRECISE_LAT, "lng": float(PRECISE_LON)}}]
    }
    finding = _scan(tmp_path, "nested.json", json.dumps(document))
    assert finding.precise_values == 2
    assert finding.fields == {"lat", "lng"}


def test_json_without_coordinate_keys_is_not_parsed(tmp_path, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("a file with no coordinate key must not be parsed")

    monkeypatch.setattr(guard.json, "load", refuse)
    finding = _scan(
        tmp_path, "plain.json", json.dumps({"latency_ms": 12.3456, "notes": "lat"})
    )
    assert finding.precise_values == 0


def test_unparseable_json_with_coordinate_keys_fails_closed(tmp_path):
    finding = _scan(tmp_path, "broken.json", '{"latitude": 12.3456, ')
    assert finding.error is not None


def test_leaflet_markers_in_html_are_found_across_chunk_boundaries(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(guard, "_PROBE_CHUNK", 37)
    markers = "".join(
        f"var m{index} = L.circleMarker(\n  [{PRECISE_LAT}, {PRECISE_LON}],\n  {{}}).addTo(map);\n"
        for index in range(25)
    )
    coarse = f"L.circleMarker([{COARSE_LAT}, {COARSE_LON}]);\n"
    finding = _scan(tmp_path, "map.html", "<script>" + markers + coarse + "</script>")
    assert finding.precise_values == 25
    assert finding.fields == {"leaflet.marker"}


def test_xlsx_precise_coordinates_are_found(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["specimen", "decimal_latitude", "decimal_longitude"])
    sheet.append(["synthetic-1", float(PRECISE_LAT), float(PRECISE_LON)])
    sheet.append(["synthetic-2", float(COARSE_LAT), float(COARSE_LON)])
    path = tmp_path / "sheet.xlsx"
    workbook.save(path)
    finding = guard.scan_file(path, "sheet.xlsx")
    assert finding.precise_values == 2


def test_parquet_fails_closed_when_it_cannot_be_read(tmp_path):
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        finding = _scan(tmp_path, "points.parquet", b"PAR1 not a real file")
        assert finding.error is not None
        return
    pq = pytest.importorskip("pyarrow.parquet")
    import pyarrow as pa

    table = pa.table({"lat": [float(PRECISE_LAT)], "lon": [float(PRECISE_LON)]})
    path = tmp_path / "points.parquet"
    pq.write_table(table, path)
    assert guard.scan_file(path, "points.parquet").precise_values == 2


def _fixture_tree(tmp_path: Path) -> list[str]:
    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    (tmp_path / "data").mkdir()
    body = f"lat,lon\n{PRECISE_LAT},{PRECISE_LON}\n"
    (tmp_path / "tests" / "fixtures" / "synthetic.csv").write_text(body)
    (tmp_path / "data" / "occurrences.csv").write_text(body)
    return ["tests/fixtures/synthetic.csv", "data/occurrences.csv"]


def test_allowlisted_synthetic_fixture_passes_and_others_fail(tmp_path):
    paths = _fixture_tree(tmp_path)
    violations, problems = guard.check(
        tmp_path, paths, {"tests/fixtures/synthetic.csv": "SYNTHETIC detector fixture"}
    )
    assert [finding.path for finding in violations] == ["data/occurrences.csv"]
    assert problems == []


def test_allowlist_outside_tests_and_stale_entries_are_refused(tmp_path):
    paths = _fixture_tree(tmp_path)
    violations, problems = guard.check(
        tmp_path,
        paths,
        {
            "tests/fixtures/synthetic.csv": "SYNTHETIC detector fixture",
            "data/occurrences.csv": "SYNTHETIC but in the wrong place",
            "tests/fixtures/gone.csv": "SYNTHETIC, since deleted",
        },
    )
    assert violations == []
    assert any(
        "data/occurrences.csv" in problem and "not under" in problem
        for problem in problems
    )
    assert any("gone.csv" in problem and "stale" in problem for problem in problems)


def test_cli_report_never_prints_coordinate_values(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is required to build a temporary repository")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    body = f"decimal_latitude,decimal_longitude\n{PRECISE_LAT},{PRECISE_LON}\n"
    (tmp_path / "leak.csv").write_text(body)
    subprocess.run(["git", "-C", str(tmp_path), "add", "leak.csv"], check=True)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "leak.csv" in result.stdout
    for value in (
        PRECISE_LAT,
        PRECISE_LON,
        PRECISE_LAT[:5],
        PRECISE_LON.lstrip("-")[:5],
    ):
        assert value not in result.stdout + result.stderr
