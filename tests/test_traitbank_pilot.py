"""TRAITBANK-PILOT-001 gates. Offline: no test opens a network connection."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from scripts import traitbank_pilot as pilot

ROOT = Path(__file__).resolve().parents[1]


def _manifest(**source_overrides) -> dict:
    manifest = pilot.load_manifest()
    src = dict(manifest["sources"][0])
    src.update(source_overrides)
    return {**manifest, "sources": [src]}


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _opener(payload: bytes):
    calls = []

    def opener(url, timeout):
        calls.append(url)
        return _FakeResponse(payload)

    opener.calls = calls
    return opener


def test_manifest_is_awaiting_approval_and_no_source_is_fetchable_yet():
    manifest = pilot.load_manifest()
    assert manifest["status"] == "awaiting_owner_approval"
    assert all(s["status"] != "approved_for_fetch" for s in manifest["sources"])


def test_fetch_is_refused_without_owner_approval_before_any_connection(tmp_path):
    opener = _opener(b"x")
    for reference, approved in (("", True), ("issue#1", False)):
        with pytest.raises(
            pilot.PilotRefused, match="OWNER_APPROVAL_REQUIRED_BEFORE_DOWNLOAD"
        ):
            pilot.fetch(
                _manifest(
                    status="approved_for_fetch", url="https://data.invalid/x.zip"
                ),
                "eol-all-trait-data-zenodo-13305577",
                tmp_path,
                approval_reference=reference,
                owner_approved=approved,
                opener=opener,
            )
    with pytest.raises(pilot.PilotRefused, match="SOURCE_NOT_APPROVED_FOR_FETCH"):
        pilot.fetch(
            pilot.load_manifest(),
            "eol-all-trait-data-zenodo-13305577",
            tmp_path,
            approval_reference="issue#1",
            owner_approved=True,
            opener=opener,
        )
    assert opener.calls == []


def test_fetch_enforces_workdir_byte_cap_and_checksum(tmp_path):
    approved = {"status": "approved_for_fetch", "url": "https://data.invalid/x.zip"}
    with pytest.raises(pilot.PilotRefused, match="WORKDIR_INSIDE_REPOSITORY"):
        pilot.fetch(
            _manifest(**approved),
            "eol-all-trait-data-zenodo-13305577",
            ROOT / "tmp-pilot",
            approval_reference="r",
            owner_approved=True,
            opener=_opener(b"x"),
        )
    with pytest.raises(pilot.PilotRefused, match="DOWNLOAD_EXCEEDS_MAX_BYTES"):
        pilot.fetch(
            _manifest(**approved, max_bytes=3),
            "eol-all-trait-data-zenodo-13305577",
            tmp_path,
            approval_reference="r",
            owner_approved=True,
            opener=_opener(b"12345"),
        )
    assert not list(tmp_path.iterdir())  # no partial file left behind
    with pytest.raises(pilot.PilotRefused, match="CHECKSUM_MISMATCH"):
        pilot.fetch(
            _manifest(**approved, sha256="0" * 64),
            "eol-all-trait-data-zenodo-13305577",
            tmp_path,
            approval_reference="r",
            owner_approved=True,
            opener=_opener(b"abc"),
        )
    pinned = hashlib.sha256(b"abc").hexdigest()
    ok = pilot.fetch(
        _manifest(**approved, sha256=pinned),
        "eol-all-trait-data-zenodo-13305577",
        tmp_path,
        approval_reference="issue#1",
        owner_approved=True,
        opener=_opener(b"abc"),
    )
    assert (
        ok["checksum"] == "verified_against_manifest"
        and Path(ok["path"]).read_bytes() == b"abc"
    )


def test_pilot_database_must_be_separate_and_named_as_such():
    with pytest.raises(pilot.PilotRefused, match="URL_REQUIRED"):
        pilot.pilot_database_url({})
    with pytest.raises(pilot.PilotRefused, match="MUST_DIFFER_FROM_DATABASE_URL"):
        pilot.pilot_database_url(
            {
                "TRAITBANK_PILOT_DATABASE_URL": "postgresql://h/tb_pilot",
                "DATABASE_URL": "postgresql://h/tb_pilot",
            }
        )
    with pytest.raises(pilot.PilotRefused, match="NAME_MUST_CONTAIN_PILOT_OR_TEST"):
        pilot.pilot_database_url(
            {"TRAITBANK_PILOT_DATABASE_URL": "postgresql://h/orchids"}
        )
    assert pilot.pilot_database_url(
        {"TRAITBANK_PILOT_DATABASE_URL": "postgresql://h/traitbank_pilot"}
    )


def _archive(tmp_path: Path, traits_csv: str, pages_csv: str | None = None) -> Path:
    path = tmp_path / "archive.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("trait_bank/traits.csv", traits_csv)
        if pages_csv is not None:
            archive.writestr("trait_bank/pages.csv", pages_csv)
    return path


def test_inspect_accepts_the_eol_layout_and_refuses_anything_else(tmp_path):
    good = _archive(
        tmp_path,
        "eol_pk,page_id,predicate,measurement,units\nR1,1,spur length,30,cm\n",
        "page_id,canonical\n1,Angraecum sesquipedale\n",
    )
    report = pilot.inspect(good)
    assert report["state"] == "LAYOUT_RECOGNISED" and report[
        "value_columns_present"
    ] == ["measurement"]
    (tmp_path / "bad").mkdir()
    bad = _archive(tmp_path / "bad", "id,name\n1,x\n")
    with pytest.raises(pilot.PilotRefused, match="UNRECOGNISED_LAYOUT"):
        pilot.inspect(bad)
    (tmp_path / "nopages").mkdir()
    no_pages = _archive(
        tmp_path / "nopages",
        "eol_pk,page_id,predicate,measurement\nR1,1,spur length,30\n",
    )
    with pytest.raises(pilot.PilotRefused, match="NO_TAXON_NAMES"):
        pilot.inspect(no_pages)


def test_records_join_names_from_pages_and_keep_eol_value_columns(tmp_path):
    path = _archive(
        tmp_path,
        "eol_pk,page_id,predicate,measurement,units\nR1,1,nectar spur length,30,cm\n",
        "page_id,canonical\n1,Angraecum sesquipedale\n",
    )
    (rec,) = pilot.harvester_records(path)
    assert rec["scientific_name"] == "Angraecum sesquipedale"
    assert rec["raw"]["measurement"] == "30" and rec["value_raw"] == ""
