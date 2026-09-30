"""Guard: no tracked data file carries precise occurrence coordinates.

The repository is public, so a committed occurrence file bypasses every
runtime locality safeguard. ``test_tracked_files_hold_no_precise_coordinates``
runs the guard over ``git ls-files``; the remaining tests pin the detector's
behaviour on small files built in a temporary directory.

Every coordinate value in this module is SYNTHETIC: invented numbers used
only to exercise the detector, not observations of any organism.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts import check_no_precise_coordinates as guard

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_no_precise_coordinates.py"

# SYNTHETIC values. PRECISE_* have more than two significant decimals; the
# pair is a point in the open Atlantic Ocean, far from any orchid habitat.
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


def test_json_without_coordinate_keys_passes(tmp_path):
    finding = _scan(
        tmp_path, "plain.json", json.dumps({"latency_ms": 12.3456, "notes": "lat"})
    )
    assert finding.precise_values == 0


def test_unparseable_json_is_scanned_as_text(tmp_path):
    finding = _scan(tmp_path, "broken.json", '{"latitude": 12.3456, ')
    assert finding.precise_values == 1
    assert finding.fields == {"text.lat"}


def test_every_leaflet_marker_in_html_is_counted(tmp_path):
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


# --- delimited text: dialects, locales, header position, BOM ---------------


def _comma(value: str) -> str:
    return value.replace(".", ",")


@pytest.mark.parametrize(
    ("name", "body"),
    [
        pytest.param(
            "semicolon.csv",
            f"latitude;longitude\n{PRECISE_LAT};{PRECISE_LON}\n",
            id="semicolon-delimiter",
        ),
        pytest.param(
            "pipe.csv",
            f"lat|lon\n{PRECISE_LAT}|{PRECISE_LON}\n",
            id="pipe-delimiter",
        ),
        pytest.param(
            "spanish-excel.csv",
            f"id;latitude;longitude\nA;{_comma(PRECISE_LAT)};{_comma(PRECISE_LON)}\n",
            id="comma-decimals-semicolon",
        ),
        pytest.param(
            "quoted-comma-decimals.csv",
            f'latitude,longitude\n"{_comma(PRECISE_LAT)}","{_comma(PRECISE_LON)}"\n',
            id="comma-decimals-quoted",
        ),
        pytest.param(
            "exponent.csv",
            "decimalLatitude,decimalLongitude\n1.23456e1,-4.56789E+01\n",
            id="scientific-notation",
        ),
        pytest.param(
            "late-header.csv",
            "Export of synthetic records\nGenerated for a detector test\n\n"
            f"id,latitude_deg,longitude_deg\n1,{PRECISE_LAT},{PRECISE_LON}\n",
            id="header-not-on-first-row",
        ),
        pytest.param(
            "bom.csv",
            f"\ufefflatitude,longitude\n{PRECISE_LAT},{PRECISE_LON}\n",
            id="utf8-bom",
        ),
        pytest.param(
            "hemisphere.tsv",
            f"lat\tlng\n{PRECISE_LAT} N\t{PRECISE_LON.lstrip('-')}°W\n",
            id="degree-and-hemisphere-suffix",
        ),
    ],
)
def test_delimited_dialects_and_locales_are_found(tmp_path, name, body):
    finding = _scan(tmp_path, name, body.encode("utf-8"))
    assert finding.error is None
    assert finding.precise_values == 2, finding.fields


def test_bom_does_not_hide_the_first_column(tmp_path):
    body = f"\ufefflatitude,species\n{PRECISE_LAT},Synthetic example\n"
    finding = _scan(tmp_path, "bom-first-column.csv", body.encode("utf-8"))
    assert finding.precise_values == 1
    assert finding.fields == {"latitude"}


def test_free_text_mentioning_latitude_does_not_replace_the_header(tmp_path):
    body = (
        f"lat,lon,notes\n{PRECISE_LAT},{PRECISE_LON},x\n"
        "1.0,2.0,see latitude\n"
        f"{PRECISE_LAT},{PRECISE_LON},y\n"
    )
    assert _scan(tmp_path, "notes.csv", body).precise_values == 4


def test_wkt_and_pair_cells_are_found(tmp_path):
    body = (
        "id,geom,latlng\n"
        f'1,"POINT ({PRECISE_LON} {PRECISE_LAT})",\n'
        f'2,,"{PRECISE_LAT}, {PRECISE_LON}"\n'
        f'3,"SRID=4326;POINT({COARSE_LON} {COARSE_LAT})",\n'
    )
    finding = _scan(tmp_path, "wkt.csv", body)
    assert finding.precise_values == 2
    assert finding.fields == {"wkt", "latlng"}


def test_long_as_an_ordinary_word_is_not_a_longitude(tmp_path):
    body = f"long_term_mean,latency\n{PRECISE_LAT},{PRECISE_LON}\n"
    assert _scan(tmp_path, "climate.csv", body).precise_values == 0


def test_xlsx_header_search_and_comma_decimals(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Synthetic export"])
    sheet.append([])
    sheet.append(["specimen", "Latitud (lat)", "Longitud (lon)"])
    sheet.append(["synthetic-1", _comma(PRECISE_LAT), _comma(PRECISE_LON)])
    second = workbook.create_sheet("second")
    second.append(["decimal_latitude"])
    second.append([float(PRECISE_LAT)])
    path = tmp_path / "late-header.xlsx"
    workbook.save(path)
    assert guard.scan_file(path, "late-header.xlsx").precise_values == 3


# --- structured documents ---------------------------------------------------


@pytest.mark.parametrize(
    "geometry",
    [
        {"type": "LineString", "coordinates": [[-45.6789, 12.3456], [-45.0, 12.0]]},
        {
            "type": "Polygon",
            "coordinates": [[[-45.6789, 12.3456], [-45.0, 12.0], [-45.6789, 12.3456]]],
        },
        {"type": "MultiPoint", "coordinates": [[-45.6789, 12.3456]]},
        {
            "type": "MultiPolygon",
            "coordinates": [[[[-45.6789, 12.3456], [-45.0, 12.0]]]],
        },
        {
            "type": "GeometryCollection",
            "geometries": [{"type": "Point", "coordinates": [-45.6789, 12.3456]}],
        },
    ],
    ids=["linestring", "polygon", "multipoint", "multipolygon", "collection"],
)
def test_every_geojson_geometry_type_is_found(tmp_path, geometry):
    document = {"type": "Feature", "geometry": geometry, "properties": {}}
    finding = _scan(tmp_path, "shape.geojson", json.dumps(document))
    assert finding.precise_values >= 1


@pytest.mark.parametrize(
    "document",
    [
        {"site": {"coords": [-45.6789, 12.3456]}},
        {"site": {"latlng": "12.3456,-45.6789"}},
        {"geometry": {"x": -45.6789, "y": 12.3456}},
        {"pt": {"x": -45.6789, "y": 12.3456, "spatialReference": {"wkid": 4326}}},
        {"records": [{"verbatimLatitude": "1.23456e1"}]},
        {"shape": "POINT (-45.6789 12.3456)"},
        {"site_lat": 12.3456},
    ],
    ids=[
        "coords-array",
        "pair-string",
        "xy-geometry",
        "xy-crs",
        "exponent",
        "wkt",
        "prefixed",
    ],
)
def test_json_coordinate_shapes_are_found(tmp_path, document):
    assert _scan(tmp_path, "doc.json", json.dumps(document)).precise_values >= 1


def test_ui_xy_positions_are_not_coordinates(tmp_path):
    document = {"nodes": [{"position": {"x": 12.3456, "y": 45.6789}}]}
    assert _scan(tmp_path, "layout.json", json.dumps(document)).precise_values == 0


def test_json_lines_yaml_and_sql_are_scanned(tmp_path):
    jsonl = f'{{"id": 1}}\n{{"decimal_latitude": {PRECISE_LAT}}}\n'
    assert _scan(tmp_path, "rows.jsonl", jsonl).precise_values == 1
    yaml_text = f"site:\n  name: synthetic\n  latitude: {PRECISE_LAT}\n"
    assert _scan(tmp_path, "site.yaml", yaml_text).precise_values == 1
    sql = (
        "INSERT INTO oc_occurrences (id, decimal_latitude, decimal_longitude) VALUES\n"
        f"  (1, {PRECISE_LAT}, {PRECISE_LON}),\n"
        f"  (2, '{COARSE_LAT}', NULL);\n"
        "COPY public.sites (id, lat, lon) FROM stdin;\n"
        f"1\t{PRECISE_LAT}\t{PRECISE_LON}\n"
        "\\.\n"
        f"UPDATE t SET geom = ST_SetSRID(ST_MakePoint({PRECISE_LON}, {PRECISE_LAT}), 4326);\n"
    )
    finding = _scan(tmp_path, "dump.sql", sql)
    assert finding.precise_values == 5, finding.fields


def test_notebook_sources_and_outputs_are_scanned(tmp_path):
    notebook = {
        "cells": [
            {"cell_type": "code", "source": [f"lat = {PRECISE_LAT}\n"], "outputs": []},
            {
                "cell_type": "code",
                "source": ["m"],
                "outputs": [
                    {
                        "output_type": "display_data",
                        "data": {
                            "text/html": [
                                f"<script>L.marker([{PRECISE_LAT}, {PRECISE_LON}])</script>"
                            ],
                            "application/json": {"longitude": float(PRECISE_LON)},
                        },
                    }
                ],
            },
        ]
    }
    finding = _scan(tmp_path, "analysis.ipynb", json.dumps(notebook))
    # A literal can be found by more than one detector; each source is covered.
    assert {"leaflet.marker", "longitude", "lat"} <= finding.fields, finding.fields


def test_kml_and_gpx_are_scanned(tmp_path):
    kml = (
        "<kml><Placemark><Point><coordinates>"
        f"{PRECISE_LON},{PRECISE_LAT},0 {COARSE_LON},{COARSE_LAT},0"
        "</coordinates></Point></Placemark></kml>"
    )
    assert _scan(tmp_path, "sites.kml", kml).precise_values == 1
    gpx = (
        f'<gpx><wpt lat="{PRECISE_LAT}" lon="{PRECISE_LON}"><name>s</name></wpt>'
        f'<trk><trkseg><trkpt lon="{COARSE_LON}" lat="{COARSE_LAT}"/></trkseg></trk></gpx>'
    )
    assert _scan(tmp_path, "track.gpx", gpx).precise_values == 2


def test_html_latlng_polyline_and_embedded_geojson_are_found(tmp_path):
    html = (
        f"<script>var a = L.latLng({PRECISE_LAT}, {PRECISE_LON});"
        f"L.polyline([[{PRECISE_LAT}, {PRECISE_LON}], [{COARSE_LAT}, {COARSE_LON}]]);"
        'L.geoJson({"type": "Point", '
        f'"coordinates": [{PRECISE_LON}, {PRECISE_LAT}]}});</script>'
    )
    finding = _scan(tmp_path, "map.html", html)
    assert finding.fields == {"leaflet.marker", "leaflet.shape", "geojson.coordinates"}


# --- archives ----------------------------------------------------------------

_LEAK_CSV = f"lat,lon\n{PRECISE_LAT},{PRECISE_LON}\n".encode()


def test_zip_gzip_and_tar_members_are_scanned(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "no data here")
        archive.writestr("data/points.csv", _LEAK_CSV)
    assert _scan(tmp_path, "bundle.zip", buffer.getvalue()).precise_values == 2

    assert (
        _scan(tmp_path, "points.csv.gz", gzip.compress(_LEAK_CSV)).precise_values == 2
    )

    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo("inner/points.csv")
        info.size = len(_LEAK_CSV)
        archive.addfile(info, io.BytesIO(_LEAK_CSV))
    assert _scan(tmp_path, "bundle.tar.gz", tar_buffer.getvalue()).precise_values == 2

    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr("inner.zip", buffer.getvalue())
    assert _scan(tmp_path, "nested.zip", nested.getvalue()).precise_values == 2


def test_corrupt_archives_fail_closed(tmp_path):
    assert _scan(tmp_path, "broken.zip", b"PK not really").error is not None
    assert _scan(tmp_path, "broken.csv.gz", b"\x1f\x8b not gzip").error is not None


# --- fail closed ---------------------------------------------------------------


def test_parquet_read_errors_fail_closed_without_crashing(tmp_path, monkeypatch):
    class ArrowInvalid(ValueError):
        pass

    class FakeParquet:
        class ParquetFile:
            def __init__(self, *_args, **_kwargs):
                raise ArrowInvalid("synthetic failure")

    fake_pyarrow = type(sys)("pyarrow")
    fake_pyarrow.parquet = FakeParquet
    monkeypatch.setitem(sys.modules, "pyarrow", fake_pyarrow)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", FakeParquet)
    finding = _scan(tmp_path, "points.parquet", b"PAR1 synthetic")
    assert finding.error is not None
    assert "ArrowInvalid" in finding.error


def test_tracked_path_missing_from_the_working_tree_fails_closed(tmp_path):
    violations, problems = guard.check(tmp_path, ["data/sparse.csv", "code.py"], {})
    assert [finding.path for finding in violations] == ["data/sparse.csv"]
    assert "missing" in (violations[0].error or "")
    assert problems == []


def test_oversized_file_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "MAX_IN_MEMORY_BYTES", 16)
    finding = _scan(tmp_path, "big.json", json.dumps({"padding": "x" * 64}))
    assert finding.error is not None


# --- repair round 2: arrays under coordinate keys, pandas orients, notebooks --

_LAT_B = "12.4567"  # SYNTHETIC second Atlantic point
_LON_B = "-45.7891"


@pytest.mark.parametrize(
    "document",
    [
        {"lat": [float(PRECISE_LAT), float(_LAT_B)], "lon": [float(PRECISE_LON)]},
        # pandas DataFrame.to_json() default orient="columns"
        {"lat": {"0": float(PRECISE_LAT), "1": float(_LAT_B)}, "species": {"0": "x"}},
        # orient="split"
        {
            "columns": ["species", "decimalLatitude", "decimalLongitude"],
            "index": [0],
            "data": [["x", float(PRECISE_LAT), float(PRECISE_LON)]],
        },
        {"points": [[float(PRECISE_LON), float(PRECISE_LAT)]]},
        {"Latitud": "12,3456", "Longitud": "-45,6789"},
    ],
    ids=[
        "key-to-list",
        "pandas-columns",
        "pandas-split",
        "points-list",
        "spanish-keys",
    ],
)
def test_json_arrays_and_pandas_orients_are_found(tmp_path, document):
    assert _scan(tmp_path, "frame.json", json.dumps(document)).precise_values >= 1


def _rows(count: int) -> list[list[float]]:
    # SYNTHETIC: consecutive open-Atlantic points.
    return [[-45.6789 + index / 1000, 12.3456 + index / 1000] for index in range(count)]


def test_anonymous_pair_arrays_need_the_documented_minimum(tmp_path):
    minimum = guard.ANONYMOUS_PAIR_MIN_ROWS
    many = _scan(tmp_path, "values.json", json.dumps(_rows(minimum)))
    assert many.precise_values == minimum
    assert many.fields == {"anonymous.pairs"}
    few = _scan(tmp_path, "few.json", json.dumps(_rows(minimum - 1)))
    assert few.precise_values == 0
    # pandas orient="values": rows with a label column still align
    labelled = [["x", *row] for row in _rows(minimum)]
    assert _scan(tmp_path, "labelled.json", json.dumps(labelled)).precise_values
    # ordinary numeric pairs (coarse, or out of coordinate range) pass
    chart = [[index, round(index * 1.5, 2)] for index in range(40)]
    assert _scan(tmp_path, "chart.json", json.dumps(chart)).precise_values == 0
    big = [[index * 1000.123, index * 2000.456] for index in range(1, 40)]
    assert _scan(tmp_path, "big.json", json.dumps(big)).precise_values == 0


def test_yaml_coordinate_key_lists_are_found(tmp_path):
    text = f"site:\n  lat: [{PRECISE_LAT}, {_LAT_B}]\n  lon:\n    - {PRECISE_LON}\n"
    assert _scan(tmp_path, "sites.yml", text).precise_values == 3


def _notebook(*cells: dict) -> str:
    return json.dumps({"cells": list(cells), "metadata": {}, "nbformat": 4})


def test_notebook_dataframe_outputs_are_scanned(tmp_path):
    frame_text = (
        "     species  decimalLatitude  decimalLongitude\n"
        f"0  synthetic          {PRECISE_LAT}          {PRECISE_LON}\n"
        f"1  synthetic          {_LAT_B}          {_LON_B}\n"
    )
    frame_html = (
        '<table class="dataframe"><thead><tr><th></th><th>lat</th><th>lon</th>'
        f"</tr></thead><tbody><tr><th>0</th><td>{PRECISE_LAT}</td><td>{PRECISE_LON}</td>"
        "</tr></tbody></table>"
    )
    notebook = _notebook(
        {
            "cell_type": "code",
            "source": ["df"],
            "outputs": [
                {
                    "output_type": "execute_result",
                    "data": {"text/plain": [frame_text], "text/html": [frame_html]},
                }
            ],
        }
    )
    finding = _scan(tmp_path, "frame.ipynb", notebook)
    assert finding.precise_values >= 6, finding.fields


def test_notebook_printed_csv_and_python_literals_are_scanned(tmp_path):
    printed = f"id;Latitud;Longitud\n1;{_comma(PRECISE_LAT)};{_comma(PRECISE_LON)}\n"
    source = [
        "import folium\n",
        f'df = pd.DataFrame({{"lat": [{PRECISE_LAT}], "lng": [{PRECISE_LON}]}})\n',
        f"folium.Marker([{_LAT_B}, {_LON_B}]).add_to(m)\n",
    ]
    notebook = _notebook(
        {
            "cell_type": "code",
            "source": source,
            "outputs": [{"output_type": "stream", "name": "stdout", "text": [printed]}],
        }
    )
    finding = _scan(tmp_path, "analysis.ipynb", notebook)
    assert {"latitud", "longitud", "lat", "lng", "folium.location"} <= finding.fields


def test_new_leaflet_latlng_is_found(tmp_path):
    html_text = f"<script>var p = new L.LatLng({PRECISE_LAT}, {PRECISE_LON});</script>"
    assert _scan(tmp_path, "latlng.html", html_text).fields == {"leaflet.marker"}


@pytest.mark.parametrize(
    "header",
    ["Latitud;Longitud", "lat.;long.", "LATITUD;LONGITUD"],
    ids=["spanish", "abbreviated", "spanish-upper"],
)
def test_spanish_and_abbreviated_headers_are_found(tmp_path, header):
    body = f"{header}\n{_comma(PRECISE_LAT)};{_comma(PRECISE_LON)}\n"
    assert _scan(tmp_path, "export.csv", body).precise_values == 2


def _corrupt_deflate(payload: bytes) -> bytes:
    blob = bytearray(gzip.compress(payload * 50))
    for index in range(12, min(len(blob) - 8, 60)):
        blob[index] ^= 0xFF
    return bytes(blob)


def test_corrupt_compressed_members_fail_closed_without_crashing(tmp_path):
    assert _scan(tmp_path, "bad.csv.gz", _corrupt_deflate(_LEAK_CSV)).error is not None

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("points.csv", _LEAK_CSV * 50)
    blob = bytearray(buffer.getvalue())
    start = blob.index(b"points.csv") + len("points.csv")
    for index in range(start + 4, start + 40):
        blob[index] ^= 0xFF
    assert _scan(tmp_path, "bad.zip", bytes(blob)).error is not None

    assert (
        _scan(tmp_path, "bad.tar.gz", _corrupt_deflate(b"x" * 4096)).error is not None
    )


# --- retired canaries ------------------------------------------------------------

# SHA-256 (truncated) of each real-looking coordinate literal that test and code
# canaries used before they were replaced with synthetic open-ocean values. The
# values themselves are deliberately not written here; they remain in git
# history, which is an owner decision (docs/privacy/TRACKED-LOCALITY-REMEDIATION.md).
RETIRED_CANARY_DIGESTS = frozenset(
    [
        "063cc6230e2600367406e35b",
        "1cbb31b76c723a711cd0265c",
        "3031d72484c4cc66527ea780",
        "346d5e0d9ae9627ac1775b73",
        "35e632ae2df0125c1f3e1f81",
        "3648a4b2bf2c6f4b1bbeb9c9",
        "45ff757d6286fe94cfeb72ea",
        "474dd8c62667495b5d2b62ab",
        "47586cbd7db5fce67ef1320f",
        "56814bf10606611c1dadd338",
        "62dad444a814e182ca7566e9",
        "65d8e1c81d7a2b3c0cfb7aac",
        "83e622d6623d8e0d12ef38f2",
        "87d1b2791836181442cc7b2c",
        "886928fd2a566d875b0c2337",
        "8f1c19bd155d0683d827356c",
        "a38ae1c20f639ccda4b52ffc",
        "aa2bc555246bdd80e1b63159",
        "ab39bdc849570534a8e83b83",
        "b081308952086339a5be1c80",
        "b0be54ecab025c959401886b",
        "b1594d4011ed4c0fe8604ea6",
        "b2fd6dbb749f51b6e1431484",
        "b71b091e5f2592350283ead7",
        "bab30c07cc52e228991d3545",
        "be0acf63fe9723ad6fd14e34",
        "c376e74c3379e7aa6312747e",
        "d3bbdc6f92ed41cce4594ed5",
        "d405e16487cb7933675ee6ff",
        "d72f8bc0998d1eaf568248d1",
        "df4c87e137735350234e668e",
        "df8fca2d8b45609e37e96614",
        "e3be155501db51cff2cb35b4",
        "ebba6b3711db367581eab603",
        "f7959d61ef8f48d898b810fb",
        "fe11464133afbb46f9d792a2",
    ]
)
_LITERAL = re.compile(r"(?<!\d)(\d{1,3}\.\d{3,})(?!\d)|(\d{1,3}°\d{2}'[NSEW])")


def _digest(literal: str) -> str:
    return hashlib.sha256(f"oc-retired-canary:{literal}".encode()).hexdigest()[:24]


def test_retired_real_looking_canaries_do_not_return():
    assert len(RETIRED_CANARY_DIGESTS) >= 30
    offenders = []
    for relative in guard.tracked_files(REPO_ROOT):
        path = REPO_ROOT / relative
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
            continue
        text = path.read_bytes().decode("utf-8", errors="ignore")
        for match in _LITERAL.finditer(text):
            if _digest(match.group(1) or match.group(2)) in RETIRED_CANARY_DIGESTS:
                offenders.append(relative)
                break
    assert offenders == [], "a retired real-looking coordinate canary is back"
