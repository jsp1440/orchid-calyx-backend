"""Tests for string authors value handling in stage_literature_batch.

Tests ensure that when 'authors' is a single string, it is kept whole
rather than being split into characters.
"""

from runtime.literature_staging import stage_literature_batch


def test_string_authors_kept_whole():
    """A string authors value becomes a one-element tuple of the stripped string."""
    result = stage_literature_batch(
        [
            {
                "source_record_id": "paper-1",
                "title": "Test Paper",
                "authors": "Smith J, Doe A",
                "taxon_name": "Test Species",
            }
        ],
        source="test",
        canonical_lookup={"Test Species": "taxon:test-species"},
    )
    assert len(result.staged) == 1
    assert result.staged[0].authors == ("Smith J, Doe A",)


def test_blank_string_authors_gives_empty_tuple():
    """A blank string authors value (or whitespace only) gives an empty tuple."""
    result = stage_literature_batch(
        [
            {
                "source_record_id": "paper-1",
                "title": "Test Paper",
                "authors": " ",
                "taxon_name": "Test Species",
            }
        ],
        source="test",
        canonical_lookup={"Test Species": "taxon:test-species"},
    )
    assert len(result.staged) == 1
    assert result.staged[0].authors == ()


def test_list_authors_keeps_non_empty_entries():
    """A list of authors keeps non-empty entries in order."""
    result = stage_literature_batch(
        [
            {
                "source_record_id": "paper-1",
                "title": "Test Paper",
                "authors": ["Smith J", "", "Doe A"],
                "taxon_name": "Test Species",
            }
        ],
        source="test",
        canonical_lookup={"Test Species": "taxon:test-species"},
    )
    assert len(result.staged) == 1
    assert result.staged[0].authors == ("Smith J", "Doe A")


def test_string_authors_with_whitespace_stripped():
    """A string authors value with leading/trailing whitespace is stripped."""
    result = stage_literature_batch(
        [
            {
                "source_record_id": "paper-1",
                "title": "Test Paper",
                "authors": "  Smith J, Doe A  ",
                "taxon_name": "Test Species",
            }
        ],
        source="test",
        canonical_lookup={"Test Species": "taxon:test-species"},
    )
    assert len(result.staged) == 1
    assert result.staged[0].authors == ("Smith J, Doe A",)


def test_list_authors_with_whitespace_stripped():
    """List entries with whitespace are stripped."""
    result = stage_literature_batch(
        [
            {
                "source_record_id": "paper-1",
                "title": "Test Paper",
                "authors": ["  Smith J  ", "", "  Doe A  "],
                "taxon_name": "Test Species",
            }
        ],
        source="test",
        canonical_lookup={"Test Species": "taxon:test-species"},
    )
    assert len(result.staged) == 1
    assert result.staged[0].authors == ("Smith J", "Doe A")


def test_missing_authors_gives_empty_tuple():
    """Missing authors key results in empty tuple."""
    result = stage_literature_batch(
        [
            {
                "source_record_id": "paper-1",
                "title": "Test Paper",
                "taxon_name": "Test Species",
            }
        ],
        source="test",
        canonical_lookup={"Test Species": "taxon:test-species"},
    )
    assert len(result.staged) == 1
    assert result.staged[0].authors == ()


def test_none_authors_gives_empty_tuple():
    """None authors value results in empty tuple."""
    result = stage_literature_batch(
        [
            {
                "source_record_id": "paper-1",
                "title": "Test Paper",
                "authors": None,
                "taxon_name": "Test Species",
            }
        ],
        source="test",
        canonical_lookup={"Test Species": "taxon:test-species"},
    )
    assert len(result.staged) == 1
    assert result.staged[0].authors == ()


def test_empty_list_authors_gives_empty_tuple():
    """Empty list authors results in empty tuple."""
    result = stage_literature_batch(
        [
            {
                "source_record_id": "paper-1",
                "title": "Test Paper",
                "authors": [],
                "taxon_name": "Test Species",
            }
        ],
        source="test",
        canonical_lookup={"Test Species": "taxon:test-species"},
    )
    assert len(result.staged) == 1
    assert result.staged[0].authors == ()
