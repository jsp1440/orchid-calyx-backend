"""Accession number generation must handle sequences beyond 9999.

After OC-YYYY-9999, the next number should be OC-YYYY-10000, not OC-YYYY-10000
again. The sequence part must support four or more digits to avoid duplicates
when the number grows beyond four digits.
"""

from runtime.conservatory_store import ConservatoryStore


def test_sequences_with_more_than_four_digits():
    """When a sequence has 5+ digits, it should still be recognized and incremented."""
    # Simulate rows with a 5-digit sequence number (OC-2026-10000)
    rows = [
        {
            "id": "plant-1",
            "accession_number": "OC-2026-9999",
            "display_name": "Plant 1",
            "accepted_scientific_name": None,
            "location": None,
            "notes": None,
            "qr_identifier": "calyx:plant:plant-1",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "id": "plant-2",
            "accession_number": "OC-2026-10000",
            "display_name": "Plant 2",
            "accepted_scientific_name": None,
            "location": None,
            "notes": None,
            "qr_identifier": "calyx:plant:plant-2",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
    ]

    # The next accession should be OC-2026-10001, not OC-2026-10000 (duplicate)
    next_accession = ConservatoryStore._next_accession(rows, 2026)
    assert next_accession == "OC-2026-10001", (
        f"Expected OC-2026-10001 but got {next_accession}. "
        "The regex should match 4 or more digits in the sequence part."
    )


def test_sequences_ending_at_9999():
    """When the highest sequence is 9999, the next should be 10000."""
    rows = [
        {
            "id": "plant-1",
            "accession_number": "OC-2026-9999",
            "display_name": "Plant 1",
            "accepted_scientific_name": None,
            "location": None,
            "notes": None,
            "qr_identifier": "calyx:plant:plant-1",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
    ]

    next_accession = ConservatoryStore._next_accession(rows, 2026)
    assert next_accession == "OC-2026-10000"


def test_sequences_with_leading_zeros():
    """Sequences with leading zeros should still increment correctly."""
    rows = [
        {
            "id": "plant-1",
            "accession_number": "OC-2026-0007",
            "display_name": "Plant 1",
            "accepted_scientific_name": None,
            "location": None,
            "notes": None,
            "qr_identifier": "calyx:plant:plant-1",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
    ]

    next_accession = ConservatoryStore._next_accession(rows, 2026)
    assert next_accession == "OC-2026-0008"


def test_different_years_are_not_mixed():
    """Sequences for different years should not interfere with each other."""
    rows = [
        {
            "id": "plant-1",
            "accession_number": "OC-2025-0042",
            "display_name": "Plant 1",
            "accepted_scientific_name": None,
            "location": None,
            "notes": None,
            "qr_identifier": "calyx:plant:plant-1",
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
        },
    ]

    # When querying for 2026, the 2025 entry should not affect the result
    next_accession = ConservatoryStore._next_accession(rows, 2026)
    assert next_accession == "OC-2026-0001"
