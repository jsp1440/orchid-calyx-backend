"""Guards the five-state classification the production audit capture reports.

The deployed payload emits three relationship states: ``present``, ``absent``
and ``unmeasured``. That last value covers three materially different
situations -- no measurement path was written, the database was unreachable, or
a measurement path ran and could not find the relation it needed. The capture
script separates them, because "we never looked" and "we looked and could not
see" call for different work and neither is a finding of absence.

The invariant these tests exist to hold is the one the whole AUDIT-MEASUREMENT
line exists for: no non-measurement may ever be reported as absence.
"""

import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "production_overall_audit",
    pathlib.Path(__file__).resolve().parents[1] / "scripts" / "production_overall_audit.py",
)
capture = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(capture)


UNMEASURED_DETAIL = (
    "No measurement path is implemented in this audit for this relationship. "
    "State is unknown; this is not a finding that the relationship is absent."
)
DB_UNREACHABLE_DETAIL = (
    "Live database was not reachable for this audit run; relationship states are "
    "unknown rather than absent."
)


def test_present_is_reported_as_measured_present():
    result = capture.classify("taxonomy_to_images", {"state": "present", "linked_images": 12})
    assert result["state"] == "measured-present"


def test_absent_is_reported_as_measured_absent():
    result = capture.classify("taxonomy_to_images", {"state": "absent"})
    assert result["state"] == "measured-absent"


def test_no_measurement_path_is_unmeasured_not_absent():
    result = capture.classify(
        "taxonomy_to_climate", {"state": "unmeasured", "detail": UNMEASURED_DETAIL}
    )
    assert result["state"] == "unmeasured"
    assert "absent" not in result["state"]


def test_database_unreachable_is_unavailable_not_absent():
    """A dead database must never read as a finding about the data."""
    result = capture.classify(
        "taxonomy_to_occurrences",
        {"state": "unmeasured", "detail": DB_UNREACHABLE_DETAIL},
    )
    assert result["state"] == "unavailable"


def test_missing_relation_is_unavailable_not_unmeasured():
    """A written measurement path that could not find its table is not 'unwritten'.

    Reporting this as ``unmeasured`` would send someone to write a measurement
    that already exists, instead of to the schema question that actually blocked it.
    """
    result = capture.classify(
        "taxonomy_to_images",
        {
            "state": "unmeasured",
            "detail": "Required taxonomy or image table was not found.",
        },
    )
    assert result["state"] == "unavailable"
    assert "not found" in result["reason"]


def test_unrecognized_state_is_an_error_not_an_absence():
    result = capture.classify("taxonomy_to_habitat", {"state": "probably_fine"})
    assert result["state"] == "error"


def test_missing_evidence_object_is_an_error_not_an_absence():
    result = capture.classify("taxonomy_to_habitat", None)
    assert result["state"] == "error"


@pytest.mark.parametrize(
    "entry",
    [
        {"state": "unmeasured", "detail": UNMEASURED_DETAIL},
        {"state": "unmeasured", "detail": DB_UNREACHABLE_DETAIL},
        {"state": "unmeasured", "detail": "Canonical taxonomy primary key was not found."},
        {"state": "bogus"},
        None,
    ],
)
def test_no_non_measurement_is_ever_reported_as_absent(entry):
    """The single invariant this whole capture exists to protect."""
    assert capture.classify("taxonomy_to_conservation", entry)["state"] != "measured-absent"


def test_all_ten_relationships_are_covered():
    assert len(capture.RELATIONSHIPS) == 10
    assert len(set(capture.RELATIONSHIPS)) == 10


def test_previous_audit_baseline_claims_all_ten_missing():
    """The comparison baseline must match what the previous audit actually said."""
    assert set(capture.PREVIOUS_AUDIT_CLAIM) == set(capture.RELATIONSHIPS)
    assert set(capture.PREVIOUS_AUDIT_CLAIM.values()) == {"missing"}
