from __future__ import annotations

import pytest

from app.calyx_conversation.climate_context import climate_context_relevant


@pytest.mark.parametrize(
    "message,expected",
    [
        # False cases: matches that are part of larger words (should NOT match)
        ("How do I train my orchid?", False),  # "train" contains "rain"
        ("My pot does not drain well", False),  # "drain" contains "rain"
        ("Use a moisture sensor near the plant", False),  # "sensor" contains "enso"
        ("The brain of the operation", False),  # "brain" contains "rain"
        # True cases: actual climate terms on word boundaries (should match)
        ("Will it rain this winter?", True),  # "rain" is standalone
        ("What is the rainfall outlook?", True),  # "rainfall" is standalone
        ("Is ENSO active?", True),  # "ENSO" is standalone
        ("La Niña forecast", True),  # "La Niña" is standalone
        ("El Nino and orchids", True),  # "El Nino" is standalone
        ("Seasonal care tips", True),  # "seasonal" is standalone
        # Additional edge cases
        ("rain-related conditions", True),  # "rain" followed by hyphen (not word char)
        ("rainfall.", True),  # "rainfall" followed by period (not word char)
        ("ENSO-driven patterns", True),  # "ENSO" followed by hyphen
        ("el nino", True),  # lowercase match
        ("EL NINO", True),  # uppercase match
        ("El Niño", True),  # mixed case with accent
        ("la nina", True),  # lowercase match
        ("LA NINA", True),  # uppercase match
        ("La Niña", True),  # mixed case with accent
        ("climate change", True),  # "climate" is standalone
        ("winter weather", True),  # "winter" is standalone
        ("forecast today", True),  # "forecast" is standalone
        ("precipitation expected", True),  # "precipitation" is standalone
        ("wet winter conditions", True),  # "wet winter" phrase
        ("dry winter months", True),  # "dry winter" phrase
        ("outlook for next season", True),  # "outlook" is standalone
        # False cases with terms as substrings
        ("trainee orchid grower", False),  # "trainee" contains "rain"
        ("mainstream gardening", False),  # "mainstream" contains "rain"
        ("drain plugin for watering", False),  # "drain" is but "plugin" contains no term
        ("endoscope examination", False),  # "endoscope" contains "enso"
        ("brain tumor research", False),  # not climate-related
        ("grained texture", False),  # "grained" contains "rain"
        ("strainer for water", False),  # "strainer" contains "rain"
        ("sensory perception", False),  # "sensory" contains "enso"
        ("tension headaches", False),  # "tension" doesn't contain any climate terms
    ],
)
def test_climate_context_relevant_word_boundaries(message: str, expected: bool):
    """Test that climate_context_relevant matches only complete words/terms, not substrings."""
    assert climate_context_relevant(message) is expected
