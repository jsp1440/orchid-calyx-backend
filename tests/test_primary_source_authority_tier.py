"""Tests for app/intake/primary_source.py -- _authority_tier function.

This module tests the _authority_tier function to ensure that:
- Publisher hosts are classified by domain suffix, not substring
- Specific domains (oup.com, cambridge.org, nature.com, science.org) match
  exact domain or subdomains only
- Unrelated hosts are correctly classified as UNKNOWN
"""

from __future__ import annotations

import pytest

from app.intake.primary_source import _authority_tier


class TestAuthorityTierDomainSuffix:
    """Test _authority_tier classification by domain suffix."""

    @pytest.mark.parametrize(
        "host,expected_tier",
        [
            # Test cases for oup.com, cambridge.org, nature.com, science.org
            # Should return PRIMARY for exact domain or subdomain
            ("nature.com", "PRIMARY"),
            ("www.nature.com", "PRIMARY"),
            ("academic.oup.com", "PRIMARY"),
            ("oup.com", "PRIMARY"),
            ("www.cambridge.org", "PRIMARY"),
            ("cambridge.org", "PRIMARY"),
            ("www.science.org", "PRIMARY"),
            ("science.org", "PRIMARY"),
            # Should return UNKNOWN for unrelated hosts containing these strings
            ("www.marketinggroup.com", "UNKNOWN"),
            ("popscience.org", "UNKNOWN"),
            ("signature.com", "UNKNOWN"),
            # Additional test cases for other publisher rules
            ("springer.com", "PRIMARY"),
            ("www.springer.com", "PRIMARY"),
            ("wiley.com", "PRIMARY"),
            ("www.wiley.com", "PRIMARY"),
            ("elsevier.com", "PRIMARY"),
            ("www.elsevier.com", "PRIMARY"),
            # Test .gov, .edu, .ac.uk, .gov.uk, .europa.eu rules
            ("example.gov", "AUTHORITATIVE"),
            ("www.example.gov.uk", "AUTHORITATIVE"),
            ("example.europa.eu", "AUTHORITATIVE"),
            ("example.edu", "PRIMARY"),
            ("www.example.ac.uk", "PRIMARY"),
            ("doi.org", "PRIMARY"),
            ("dx.doi.org", "PRIMARY"),
            # Edge cases
            (None, "UNKNOWN"),
            ("", "UNKNOWN"),
            ("unknown.example.com", "UNKNOWN"),
            # Case insensitivity
            ("NATURE.COM", "PRIMARY"),
            ("WWW.NATURE.COM", "PRIMARY"),
            ("Academic.OUP.COM", "PRIMARY"),
        ],
    )
    def test_authority_tier_classification(self, host: str | None, expected_tier: str) -> None:
        """Test that hosts are classified correctly by domain suffix."""
        assert _authority_tier(host) == expected_tier
