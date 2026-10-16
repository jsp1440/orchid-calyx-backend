"""Tests for whitespace-only field observation notes and blank taxon hints."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.field_observation.schemas import FieldObservationCreate


def test_note_with_whitespace_only_raises_validation_error():
    """A note that is empty after stripping whitespace raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        FieldObservationCreate(
            observed_at="2026-01-01T10:00:00",
            note=" ",
        )
    assert "note must contain at least one non-whitespace character" in str(exc_info.value)


def test_note_with_mixed_whitespace_only_raises_validation_error():
    """A note with mixed whitespace characters only raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        FieldObservationCreate(
            observed_at="2026-01-01T10:00:00",
            note="\n\t  \r",
        )
    assert "note must contain at least one non-whitespace character" in str(exc_info.value)


def test_note_with_real_text_is_accepted():
    """A note with real text, including leading/trailing whitespace, is accepted."""
    obs = FieldObservationCreate(
        observed_at="2026-01-01T10:00:00",
        note=" Two plants ",
    )
    assert obs.note == " Two plants "


def test_taxon_hint_blank_becomes_none():
    """A taxon_hint that is blank after stripping becomes None."""
    obs = FieldObservationCreate(
        observed_at="2026-01-01T10:00:00",
        note="Valid note",
        taxon_hint=" ",
    )
    assert obs.taxon_hint is None


def test_taxon_hint_mixed_whitespace_becomes_none():
    """A taxon_hint with mixed whitespace only becomes None."""
    obs = FieldObservationCreate(
        observed_at="2026-01-01T10:00:00",
        note="Valid note",
        taxon_hint="\n\t  ",
    )
    assert obs.taxon_hint is None


def test_taxon_hint_with_real_text_is_unchanged():
    """A taxon_hint with real text is stored exactly as given."""
    obs = FieldObservationCreate(
        observed_at="2026-01-01T10:00:00",
        note="Valid note",
        taxon_hint="Laelia purpurata",
    )
    assert obs.taxon_hint == "Laelia purpurata"


def test_taxon_hint_with_leading_trailing_whitespace_is_preserved():
    """A taxon_hint with leading/trailing whitespace is preserved."""
    obs = FieldObservationCreate(
        observed_at="2026-01-01T10:00:00",
        note="Valid note",
        taxon_hint=" Laelia purpurata ",
    )
    assert obs.taxon_hint == " Laelia purpurata "


def test_taxon_hint_default_none_stays_none():
    """A taxon_hint that is None by default stays None."""
    obs = FieldObservationCreate(
        observed_at="2026-01-01T10:00:00",
        note="Valid note",
    )
    assert obs.taxon_hint is None


def test_taxon_hint_empty_string_becomes_none():
    """A taxon_hint that is an empty string becomes None."""
    obs = FieldObservationCreate(
        observed_at="2026-01-01T10:00:00",
        note="Valid note",
        taxon_hint="",
    )
    assert obs.taxon_hint is None


def test_combined_note_and_taxon_hint_validation():
    """Both note and taxon_hint are validated in the same create call."""
    # Valid note, blank taxon_hint
    obs = FieldObservationCreate(
        observed_at="2026-01-01T10:00:00",
        note="Valid note with text",
        taxon_hint=" ",
    )
    assert obs.note == "Valid note with text"
    assert obs.taxon_hint is None

    # Invalid note
    with pytest.raises(ValidationError):
        FieldObservationCreate(
            observed_at="2026-01-01T10:00:00",
            note=" ",
            taxon_hint="Laelia purpurata",
        )
