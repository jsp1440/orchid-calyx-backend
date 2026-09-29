"""Fixture-backed tests for the Darwin Core Archive exporter.

No live database or network access: the exporter's DB helpers
(``table_exists`` / ``get_columns``) and cursor are faked, matching the
no-live-dependency convention used across this repo's build-packet tests
(see tests/test_build_093_harvester_migration.py).
"""

from __future__ import annotations

import os
import zipfile

import pytest

import darwin_core_export as dwc


class _FakeCursor:
    def __init__(self, colnames, rows):
        self._colnames = colnames
        self._rows = rows
        self.description = [(name,) for name in colnames]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        # Bounded-export contract: the LIMIT parameter is always threaded
        # through, never silently dropped.
        assert params is not None and len(params) == 1

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, colnames, rows):
        self._colnames = colnames
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._colnames, self._rows)

    def close(
        self,
    ):  # pragma: no cover - export_to_dwc_archive(conn=...) owns_conn=False
        raise AssertionError(
            "caller-supplied connections must not be closed by the exporter"
        )


_MERGED_COLUMNS = [
    "source",
    "source_id",
    "scientific_name",
    "genus",
    "species",
    "taxon_rank",
    "country",
    "latitude",
    "longitude",
    "photographer",
    "license",
    "url",
]


def _install_fake_schema(monkeypatch, *, occurrences=True, images=True):
    def fake_table_exists(conn, name, schema="public"):
        return {"occurrences": occurrences, "images": images}.get(name, False)

    def fake_get_columns(conn, name, schema="public"):
        if name == "occurrences":
            return [
                "source",
                "source_id",
                "scientific_name",
                "genus",
                "species",
                "taxon_rank",
            ]
        if name == "images":
            return [
                "source",
                "source_id",
                "scientific_name",
                "genus",
                "species",
                "country",
                "latitude",
                "longitude",
                "photographer",
                "license",
                "url",
            ]
        return []

    monkeypatch.setattr(dwc, "_table_exists", fake_table_exists)
    monkeypatch.setattr(dwc, "_get_columns", fake_get_columns)


def _gbif_row():
    return {
        "source": "gbif",
        "source_id": "12345",
        "scientific_name": "Cattleya labiata",
        "genus": "Cattleya",
        "species": "labiata",
        "taxon_rank": "SPECIES",
        "country": "Brazil",
        "latitude": -8.05,
        "longitude": -34.9,
        "photographer": "Jane Botanist",
        "license": "CC_BY_4_0",
        "url": "https://example.org/img.jpg",
    }


def test_to_dwc_record_preserves_license_and_provenance_but_redacts_coordinates_by_default():
    record = dwc.to_dwc_record(
        _gbif_row(),
        institution_code="FCOS",
        dataset_name="Test Dataset",
    )
    assert record["occurrenceID"] == "gbif:12345"
    assert record["scientificName"] == "Cattleya labiata"
    assert record["license"] == "CC_BY_4_0"
    assert record["collectionCode"] == "gbif"
    assert record["catalogNumber"] == "12345"
    assert record["decimalLatitude"] == ""
    assert record["decimalLongitude"] == ""
    assert record["country"] == "Brazil"
    assert record["basisOfRecord"] == "Occurrence"


def test_exact_coordinate_record_requires_flag_and_high_friction_ack(monkeypatch):
    monkeypatch.delenv("OC_ALLOW_EXACT_DWC_EXPORT", raising=False)
    with pytest.raises(PermissionError):
        dwc.to_dwc_record(
            _gbif_row(),
            institution_code="FCOS",
            dataset_name="Test Dataset",
            include_exact_coordinates=True,
        )

    monkeypatch.setenv("OC_ALLOW_EXACT_DWC_EXPORT", dwc.EXACT_COORDINATE_EXPORT_ACK)
    record = dwc.to_dwc_record(
        _gbif_row(),
        institution_code="FCOS",
        dataset_name="Test Dataset",
        include_exact_coordinates=True,
    )
    assert record["decimalLatitude"] == "-8.05"
    assert record["decimalLongitude"] == "-34.9"


def test_to_dwc_record_unknown_license_is_explicit_not_silent():
    row = {
        "source": "inaturalist",
        "source_id": "9",
        "scientific_name": "Vanilla planifolia",
    }
    record = dwc.to_dwc_record(
        row, institution_code="FCOS", dataset_name="Test Dataset"
    )
    assert record["license"] == dwc.UNKNOWN_LICENSE_MARKER
    assert record["basisOfRecord"] == "HumanObservation"


def test_fetch_merged_rows_full_outer_joins_by_source_and_source_id(monkeypatch):
    _install_fake_schema(monkeypatch)
    rows = [
        (
            "gbif",
            "1",
            "Cattleya labiata",
            "Cattleya",
            "labiata",
            "SPECIES",
            "Brazil",
            -8.05,
            -34.9,
            "",
            "CC0_1_0",
            "https://example.org/1.jpg",
        ),
        (None, None, None, None, None, None, None, None, None, None, None, None),
    ]
    conn = _FakeConn(_MERGED_COLUMNS, rows)
    merged = dwc._fetch_merged_rows(conn, limit=10)
    assert len(merged) == 2
    assert merged[0]["source"] == "gbif"


def test_write_occurrence_txt_and_meta_xml_field_order_match(tmp_path):
    records = [
        dwc.to_dwc_record(
            {"source": "gbif", "source_id": "1", "scientific_name": "Cattleya labiata"},
            institution_code="FCOS",
            dataset_name="Test Dataset",
        )
    ]
    out_file = tmp_path / "occurrence.txt"
    count = dwc.write_occurrence_txt(records, str(out_file))
    assert count == 1

    header = out_file.read_text(encoding="utf-8").splitlines()[0].split("\t")
    assert header == dwc.DWC_FIELDS

    meta_xml = dwc.build_meta_xml()
    # meta.xml field order must match the occurrence.txt column order exactly,
    # otherwise DwC-A consumers (e.g. GBIF's IPT validator) misassign columns.
    for index, field in enumerate(dwc.DWC_FIELDS):
        assert f'index="{index + 1}" term="{dwc._term_uri(field)}"' in meta_xml


def test_export_to_dwc_archive_defaults_to_coordinate_redaction(tmp_path, monkeypatch):
    _install_fake_schema(monkeypatch)
    rows = [
        (
            "gbif",
            "1",
            "Cattleya labiata",
            "Cattleya",
            "labiata",
            "SPECIES",
            "Brazil",
            -8.05,
            -34.9,
            "",
            "CC0_1_0",
            "https://example.org/1.jpg",
        ),
    ]
    conn = _FakeConn(_MERGED_COLUMNS, rows)
    output_dir = str(tmp_path / "dwc_export")

    result = dwc.export_to_dwc_archive(output_dir, limit=10, conn=conn)

    assert result["record_count"] == 1
    assert result["exact_coordinates_included"] is False
    assert os.path.exists(result["archive_file"])
    with zipfile.ZipFile(result["archive_file"]) as zf:
        names = set(zf.namelist())
        assert names == {"occurrence.txt", "meta.xml", "eml.xml"}
        occurrence_body = zf.read("occurrence.txt").decode("utf-8")
        assert "Cattleya labiata" in occurrence_body
        assert "CC0_1_0" in occurrence_body
        assert "-8.05" not in occurrence_body
        assert "-34.9" not in occurrence_body
        eml_body = zf.read("eml.xml").decode("utf-8")
        assert "Exact decimal coordinates are omitted" in eml_body


def test_export_exact_coordinates_requires_explicit_ack(tmp_path, monkeypatch):
    _install_fake_schema(monkeypatch)
    rows = [
        (
            "gbif",
            "1",
            "Cattleya labiata",
            "Cattleya",
            "labiata",
            "SPECIES",
            "Brazil",
            -8.05,
            -34.9,
            "",
            "CC0_1_0",
            "https://example.org/1.jpg",
        ),
    ]
    conn = _FakeConn(_MERGED_COLUMNS, rows)

    monkeypatch.delenv("OC_ALLOW_EXACT_DWC_EXPORT", raising=False)
    with pytest.raises(PermissionError):
        dwc.export_to_dwc_archive(
            str(tmp_path / "blocked"),
            limit=10,
            conn=conn,
            include_exact_coordinates=True,
        )

    monkeypatch.setenv("OC_ALLOW_EXACT_DWC_EXPORT", dwc.EXACT_COORDINATE_EXPORT_ACK)
    result = dwc.export_to_dwc_archive(
        str(tmp_path / "approved"),
        limit=10,
        conn=conn,
        include_exact_coordinates=True,
    )
    assert result["exact_coordinates_included"] is True
    with zipfile.ZipFile(result["archive_file"]) as zf:
        occurrence_body = zf.read("occurrence.txt").decode("utf-8")
        assert "-8.05" in occurrence_body
        assert "-34.9" in occurrence_body
        eml_body = zf.read("eml.xml").decode("utf-8")
        assert "Exact decimal coordinates are included" in eml_body


def test_export_to_dwc_archive_bounds_limit_default():
    # The exported limit must always be a positive, finite bound -- this
    # capability must never silently degrade into an unbounded full export.
    assert 0 < dwc.DEFAULT_EXPORT_LIMIT < 1_000_000
