"""Permanent guards on what may be counted as an orchid occurrence.

The owner decision these encode:

    An occurrence is evidence that an orchid taxon occurred at a particular
    place -- observation, specimen, collection, or equivalent.

    Vendor listings do not qualify. Videos do not qualify merely because they
    carry taxon/location metadata. Taxon profiles do not qualify. Literature
    does not automatically qualify. Media does not automatically qualify.
    Elevation-bearing records do not become occurrences because elevation is
    present.

These tests exist so that decision cannot be quietly reversed by a candidate
list edit, a new ingest type, or a well-meaning promotion on row count.
"""

import pytest

from app.readiness import occurrence_semantics as sem

# --- The explicit owner exclusions -------------------------------------------

@pytest.mark.parametrize(
    "record_type",
    ["vendor_listing", "video", "taxon_profile", "species_profile"],
)
def test_the_named_exclusions_are_never_occurrences(record_type):
    assert sem.classify_record_type(record_type)[0] == sem.NON_OCCURRENCE
    assert not sem.is_occurrence(record_type)
    assert record_type not in sem.occurrence_type_values()
    assert record_type not in sem.occurrence_predicate()


@pytest.mark.parametrize(
    "record_type",
    ["media_record", "media_observation", "occurrence_photo", "observation_photo", "image", "photo"],
)
def test_media_does_not_automatically_qualify(record_type):
    """Media may accompany an occurrence; the media row is not the occurrence."""
    assert not sem.is_occurrence(record_type)


@pytest.mark.parametrize("record_type", ["literature", "publication"])
def test_literature_does_not_automatically_qualify(record_type):
    assert not sem.is_occurrence(record_type)


def test_conservation_assessment_is_not_an_occurrence():
    """A judgement about a taxon is not a record of it being somewhere."""
    assert not sem.is_occurrence("conservation_assessment")


# --- What does qualify --------------------------------------------------------

@pytest.mark.parametrize(
    "record_type",
    [
        "occurrence",
        "observation",
        "OBSERVATION",
        "HUMAN_OBSERVATION",
        "specimen",
        "PRESERVED_SPECIMEN",
        "MATERIAL_SAMPLE",
        "MACHINE_OBSERVATION",
        "collection",
    ],
)
def test_genuine_occurrence_evidence_qualifies(record_type):
    assert sem.is_occurrence(record_type)


def test_the_three_spellings_of_observation_are_all_admitted():
    """The corpus carries observation, OBSERVATION and HUMAN_OBSERVATION.

    They are the same evidence under an unnormalised vocabulary. Admitting only
    one would silently drop the other two.
    """
    for spelling in ("observation", "OBSERVATION", "HUMAN_OBSERVATION"):
        assert sem.is_occurrence(spelling), spelling


# --- Fail closed --------------------------------------------------------------

def test_an_unknown_record_type_is_ambiguous_not_an_occurrence():
    """A new ingest type must not be able to inflate occurrence counts by appearing."""
    state, reason = sem.classify_record_type("some_future_ingest_type")
    assert state == sem.AMBIGUOUS
    assert "not classified" in reason


def test_null_record_type_is_ambiguous():
    assert sem.classify_record_type(None)[0] == sem.AMBIGUOUS


def test_occurrence_stub_is_excluded_on_measured_evidence():
    """621,526 rows that assert no place, and are already counted elsewhere.

    Originally withheld as ambiguous. Production measurement resolved it: the
    stubs carry zero coordinates, zero event dates and zero elevations, and the
    188,292 that carry a GBIF key correspond to the 188,285 rows
    public.orchid_occurrence records as sourced from
    'records_source_record_id_backfill_safe'. They are ingest placeholders whose
    real content already lives in the canonical occurrence table.
    """
    state, reason = sem.classify_record_type("occurrence_stub")
    assert state == sem.NON_OCCURRENCE
    assert not sem.is_occurrence("occurrence_stub")
    assert "placeholder" in reason


def test_ambiguous_types_are_excluded_from_the_sql_predicate():
    predicate = sem.occurrence_predicate()
    for rt in sem.AMBIGUOUS_TYPES:
        assert f"'{rt}'" not in predicate, rt


# --- Semantics, not shape -----------------------------------------------------

def test_classification_does_not_depend_on_coordinates_elevation_or_identifiers():
    """Vendor listings carry coordinates, elevation and GBIF keys too.

    Classification takes only the declared type, so no amount of corroborating
    metadata can promote a non-occurrence.
    """
    import inspect

    source = inspect.getsource(sem.classify_record_type)
    for shape_field in ("latitude", "longitude", "elevation", "gbif", "coordinate"):
        assert shape_field not in source.lower(), shape_field


def test_the_predicate_is_an_allow_list_not_a_deny_list():
    """A deny-list would admit every future ingest type the moment it appeared."""
    predicate = sem.occurrence_predicate()
    assert " IN (" in predicate
    assert "NOT IN" not in predicate


def test_no_type_is_classified_twice():
    keys = list(sem.OCCURRENCE_TYPES) + list(sem.NON_OCCURRENCE_TYPES) + list(sem.AMBIGUOUS_TYPES)
    assert len(keys) == len(set(keys)), "a record_type appears in two buckets"


def test_every_classified_type_carries_a_reason():
    for bucket in (sem.OCCURRENCE_TYPES, sem.NON_OCCURRENCE_TYPES, sem.AMBIGUOUS_TYPES):
        for rt, reason in bucket.items():
            assert reason and len(reason) > 30, rt


def test_classify_all_reports_every_bucket():
    result = sem.classify_all(
        ["occurrence", "vendor_listing", "community_observation", "brand_new_type", None]
    )
    assert result["counts"][sem.OCCURRENCE] == 1
    assert result["counts"][sem.NON_OCCURRENCE] == 1
    assert result["counts"][sem.AMBIGUOUS] == 3
    assert "particular place" in result["definition"]


def test_the_predicate_admits_exactly_the_occurrence_bucket():
    predicate = sem.occurrence_predicate(alias="r")
    assert predicate.startswith("r.record_type IN (")
    for rt in sem.OCCURRENCE_TYPES:
        assert f"'{rt}'" in predicate, rt
    for rt in sem.NON_OCCURRENCE_TYPES:
        assert f"'{rt}'" not in predicate, rt


# --- Coverage of the real production vocabulary -------------------------------
#
# The complete set of record_type values measured in public.records on
# 2026-08-19, with row counts. Kept verbatim so that a type appearing in
# production without a classification fails here rather than silently becoming
# ambiguous in a metric nobody reads.

PRODUCTION_RECORD_TYPES = {
    "occurrence": 2_776_500, "observation": 927_446, "occurrence_stub": 621_526,
    "specimen": 139_330, "occurrence_photo": 103_007, "media_record": 96_832,
    "media_observation": 69_575, "taxon_profile": 64_764, "observation_photo": 53_998,
    "species_profile": 33_650, "HUMAN_OBSERVATION": 29_390, "video": 23_692,
    "conservation_assessment": 16_955, "OBSERVATION": 11_251, "vendor_listing": 10_066,
    "species_photo": 9_899, "taxonomy_record": 9_838, "cultivar": 1_274,
    "personal_collection": 945, "photo": 927, "hybrid_registration": 866,
    "living_collection": 716, "photo_gallery": 678, "genus_profile": 519,
    "personal_collection_hybrid": 426, "community_observation": 346,
    "breeder_catalog": 344, "knowledge_article": 190, "hybrid_photo": 168,
    "herbarium_specimen": 145, "image_collection": 119, "literature_title": 118,
    "hybrid_listing": 105, "photo_directory": 100, "dataset_metadata": 81,
    "judging_standard": 60, "culture_sheet": 52, "documentation": 36,
    "species_observation": 26, "genomic_record": 18, "vip_hybrid": 16,
    "literature_taxon": 16, "article": 6, "PRESERVED_SPECIMEN": 3,
    "literature": 2, "migration": 1,
}


def test_every_production_record_type_has_an_explicit_classification():
    """No production type may fall through to the unclassified default."""
    unclassified = [
        rt for rt in PRODUCTION_RECORD_TYPES
        if rt not in sem.OCCURRENCE_TYPES
        and rt not in sem.NON_OCCURRENCE_TYPES
        and rt not in sem.AMBIGUOUS_TYPES
    ]
    assert unclassified == [], f"unclassified production record types: {unclassified}"


def test_the_admitted_share_of_production_is_what_the_semantics_say():
    """Pin the actual arithmetic, so a reclassification is visible as a number."""
    admitted = sum(n for rt, n in PRODUCTION_RECORD_TYPES.items() if sem.is_occurrence(rt))
    total = sum(PRODUCTION_RECORD_TYPES.values())
    # occurrence 2,776,500 + observation 927,446 + specimen 139,330
    # + HUMAN_OBSERVATION 29,390 + OBSERVATION 11,251 + herbarium_specimen 145
    # + species_observation 26 + PRESERVED_SPECIMEN 3
    assert admitted == 3_884_091
    assert total == 5_006_022
    # Over a million rows of the spine are excluded on semantics alone.
    assert total - admitted == 1_121_931


def test_the_largest_excluded_types_are_the_ones_the_owner_named():
    excluded = sorted(
        ((n, rt) for rt, n in PRODUCTION_RECORD_TYPES.items() if not sem.is_occurrence(rt)),
        reverse=True,
    )
    top = [rt for _, rt in excluded[:6]]
    assert "occurrence_stub" in top
    assert "media_record" in top
    assert "taxon_profile" in top
    # And the named exclusions are all excluded, whatever their size.
    for rt in ("vendor_listing", "video", "species_profile", "conservation_assessment"):
        assert not sem.is_occurrence(rt)


def test_occurrence_stub_exclusion_is_justified_by_measurement_not_preference():
    """It is the single largest exclusion, so its reason has to carry the evidence."""
    _, reason = sem.classify_record_type("occurrence_stub")
    assert "621,526" in reason
    assert "zero coordinates" in reason
    assert "double-count" in reason
