from __future__ import annotations

import pytest

from app.calyx_conversation.climate_context import climate_context_relevant


@pytest.mark.parametrize(
    "message,expected",
    [
        # False cases: terms as substrings of words (should NOT match)
        ("How do I train my orchid?", False),
        ("My pot does not drain well", False),
        ("Use a moisture sensor near the plant", False),
        ("The brain of the operation", False),
        # True cases: terms on word boundaries (should match)
        ("Will it rain this winter?", True),
        ("What is the rainfall outlook?", True),
        ("Is ENSO active?", True),
        ("La Niña forecast", True),
        ("El Nino and orchids", True),
        ("Seasonal care tips", True),
        # Additional edge cases
        ("rain", True),
        ("RAIN", True),
        ("Rain.", True),
        ("rainfall", True),
        ("enso", True),
        ("ENSO", True),
        ("el nino", True),
        ("EL NINO", True),
        ("el niño", True),
        ("la nina", True),
        ("la niña", True),
        ("climate", True),
        ("winter", True),
        ("forecast", True),
        ("outlook", True),
        ("seasonal", True),
        ("precipitation", True),
        ("wet winter", True),
        ("dry winter", True),
        # False cases with terms embedded in words
        ("train", False),
        ("drain", False),
        ("brain", False),
        ("sensor", False),
        ("entraining", False),
        ("drainage", False),
        ("brainpower", False),
        ("sensory", False),
        # Mixed: some terms present as substrings but at least one on boundary
        ("Will it rain and train", True),  # rain is on boundary
        ("forecast the drain", True),  # forecast is on boundary
    ],
)
def test_climate_context_relevant(message: str, expected: bool) -> None:
    """Test that climate_context_relevant matches terms on word boundaries only."""
    assert climate_context_relevant(message) == expected
