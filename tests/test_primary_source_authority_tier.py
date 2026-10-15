"""Tests for _authority_tier function in app/intake/primary_source.py.

Tests the domain suffix matching behavior for publisher hosts.
"""

from __future__ import annotations

import pytest

from app.intake.primary_source import _authority_tier


@pytest.mark.parametrize(
    "host,expected_tier",
    [
        # Test cases for problematic substring matching (should now be UNKNOWN)
        ("www.marketinggroup.com", "UNKNOWN"),  # contains "oup.com" as substring but shouldn't match
        ("popscience.org", "UNKNOWN"),  # contains "science.org" as substring but shouldn't match
        ("signature.com", "UNKNOWN"),  # contains "nature.com" as substring but shouldn't match
        # Test cases for correct matches (exact domain or subdomain)
        ("academic.oup.com", "PRIMARY"),
        ("nature.com", "PRIMARY"),
        ("www.nature.com", "PRIMARY"),
        ("www.cambridge.org", "PRIMARY"),
        ("www.science.org", "PRIMARY"),
        ("oup.com", "PRIMARY"),
        ("cambridge.org", "PRIMARY"),
        ("science.org", "PRIMARY"),
        # Test cases for publisher substring matches (springer, wiley, elsevier)
        ("springer.com", "PRIMARY"),
        ("www.springer.com", "PRIMARY"),
        ("link.springer.com", "PRIMARY"),
        ("wiley.com", "PRIMARY"),
        ("www.wiley.com", "PRIMARY"),
        ("onlinelibrary.wiley.com", "PRIMARY"),
        ("elsevier.com", "PRIMARY"),
        ("www.elsevier.com", "PRIMARY"),
        ("sciencedirect.elsevier.com", "PRIMARY"),
        # Test cases for .gov/.edu/.ac.uk/.gov.uk/.europa.eu
        ("example.gov", "AUTHORITATIVE"),
        ("www.example.gov", "AUTHORITATIVE"),
        ("example.gov.uk", "AUTHORITATIVE"),
        ("www.example.gov.uk", "AUTHORITATIVE"),
        ("example.europa.eu", "AUTHORITATIVE"),
        ("example.edu", "PRIMARY"),
        ("www.example.edu", "PRIMARY"),
        ("example.ac.uk", "PRIMARY"),
        ("www.example.ac.uk", "PRIMARY"),
        # Test cases for DOI
        ("doi.org", "PRIMARY"),
        ("dx.doi.org", "PRIMARY"),
        # Edge cases
        ("", "UNKNOWN"),
        (None, "UNKNOWN"),
        ("example.com", "UNKNOWN"),
        ("random.org", "UNKNOWN"),
    ],
)
def test_authority_tier(host: str | None, expected_tier: str) -> None:
    """Test _authority_tier with various hosts."""
    assert _authority_tier(host) == expected_tier
