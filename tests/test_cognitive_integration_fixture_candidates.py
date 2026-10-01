"""The Catasetum macrocarpum fixture candidate must stay true to the repository.

The record cites crosswalk and registry rows by file and line. These tests read
those files, so a citation that drifts from the data -- or a record that starts
"resolving" the case -- fails here rather than being repeated as fact.
"""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "app/cognitive_integration/fixture_candidates/catasetum_macrocarpum_identity.json"
REGISTRY = ROOT / "docs/crosswalks/canonical_taxon_registry.csv"
BACKBONE = ROOT / "docs/crosswalks/orchid_taxonomy_to_backbone_crosswalk.csv"


def _record() -> dict:
    return json.loads(RECORD.read_text(encoding="utf-8"))


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_case_is_review_required_with_both_candidates_and_no_selection():
    record = _record()
    assert record["decision_state"] == "REVIEW_REQUIRED"
    assert record["selected_taxon_id"] is None
    assert [c["taxon_id"] for c in record["candidates"]] == ["46599", "27265"]
    assert record["expected_reasoning_outcome"]["must_preserve_candidates"] == ["46599", "27265"]
    assert "select a taxon_id" in record["expected_reasoning_outcome"]["must_not"]
    for key in ("evidence_supports", "evidence_does_not_establish", "why_review_required"):
        assert record[key], key


def test_registry_row_is_cited_exactly():
    row = _record()["registry_evidence"]["matching_row"]
    line = _lines(REGISTRY)[row["line"] - 1]
    fields = next(csv.reader([line]))
    assert fields[:6] == [
        row["canonical_id"], row["canonical_name"], row["scientific_name"],
        row["authorship"], row["rank"], row["status"],
    ]
    assert fields[9] == row["authorities"]
    assert int(fields[8]) == row["authority_mappings_count"]


def test_every_synonym_of_the_registry_row_is_listed():
    record = _record()
    accepted = record["registry_evidence"]["matching_row"]["canonical_id"]
    with REGISTRY.open(encoding="utf-8") as handle:
        synonyms = [r for r in csv.DictReader(handle) if r["accepted_canonical_id"] == accepted]
    listed = record["registry_evidence"]["synonyms_pointing_here"]
    assert len(listed) == len(synonyms)
    for row in synonyms:
        assert any(row["canonical_id"] in entry and row["scientific_name"] in entry for entry in listed)


def test_registry_ids_are_a_different_space_from_production_ids():
    mismatch = _record()["identifier_space_mismatch"]["registry_rows_with_the_candidate_numbers"]
    with REGISTRY.open(encoding="utf-8") as handle:
        by_id = {r["canonical_id"]: r for r in csv.DictReader(handle)}
    for candidate in ("46599", "27265"):
        assert "Catasetum" not in by_id[candidate]["canonical_name"]
        assert any(entry.split(": ", 1)[1].startswith(f"{candidate} {by_id[candidate]['scientific_name']}")
                   for entry in mismatch)


def test_backbone_crosswalk_rows_are_cited_exactly():
    record = _record()
    with BACKBONE.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_source = {r["source_identifier"]: r for r in rows if r["source_authority"] == "public.orchid_taxonomy"}
    first, second = record["candidates"]
    assert ",".join(by_source["46599"].values()) == first["backbone_crosswalk"]["row"]
    assert "27265" not in by_source and second["backbone_crosswalk"]["row"] is None
    assert f"{len(rows)} data rows" in second["backbone_crosswalk"]["note"]
