"""Tests for _authority_tier function in app/intake/primary_source.py.

Tests cover the domain suffix matching behavior for publisher hosts,
ensuring that only exact domain matches or proper subdomains return PRIMARY tier,
not arbitrary substring matches.
"""

from __future__ import annotations

import pytest

from app.intake.primary_source import _authority_tier


class TestAuthorityTierDomainSuffixMatching:
    """Test domain suffix matching for publisher domains."""

    @pytest.mark.parametrize(
        "host,expected_tier",
        [
            # Hosts that should NOT match (substring false positives)
            ("www.marketinggroup.com", "UNKNOWN"),
            ("popscience.org", "UNKNOWN"),
            ("signature.com", "UNKNOWN"),
            # Exact domain matches for primary publishers
            ("oup.com", "PRIMARY"),
            ("cambridge.org", "PRIMARY"),
            ("nature.com", "PRIMARY"),
            ("science.org", "PRIMARY"),
            # Proper subdomains of primary publishers
            ("academic.oup.com", "PRIMARY"),
            ("www.nature.com", "PRIMARY"),
            ("www.cambridge.org", "PRIMARY"),
            ("www.science.org", "PRIMARY"),
            ("journals.oup.com", "PRIMARY"),
            ("subdomain.nature.com", "PRIMARY"),
            # Edge cases - should not match
            ("notoup.com", "UNKNOWN"),
            ("oup.com.fake.org", "UNKNOWN"),
            ("cambridge.org.evil.com", "UNKNOWN"),
            ("nature.com.example.com", "UNKNOWN"),
            ("science.org.notreal.net", "UNKNOWN"),
            # Publisher with springer/wiley/elsevier substring matching still works
            ("www.springer.com", "PRIMARY"),
            ("springer.org", "PRIMARY"),
            ("wiley.com", "PRIMARY"),
            ("www.wiley.org", "PRIMARY"),
            ("elsevier.com", "PRIMARY"),
            ("www.elsevier.org", "PRIMARY"),
            # Government/Educational domains
            ("example.gov", "AUTHORITATIVE"),
            ("example.gov.uk", "AUTHORITATIVE"),
            ("example.europa.eu", "AUTHORITATIVE"),
            ("example.edu", "PRIMARY"),
            ("example.ac.uk", "PRIMARY"),
            ("doi.org", "PRIMARY"),
            ("dx.doi.org", "PRIMARY"),
            # None and empty
            (None, "UNKNOWN"),
            ("", "UNKNOWN"),
            # Unknown domains
            ("example.com", "UNKNOWN"),
            ("www.example.com", "UNKNOWN"),
            ("random.net", "UNKNOWN"),
        ],
    )
    def test_authority_tier_parametrized(self, host: str | None, expected_tier: str):
        """Test authority tier returns expected value for various hosts."""
        assert _authority_tier(host) == expected_tier

    def test_case_insensitive_domain_matching(self):
        """Test that domain matching is case-insensitive."""
        assert _authority_tier("OUP.COM") == "PRIMARY"
        assert _authority_tier("Cambridge.Org") == "PRIMARY"
        assert _authority_tier("WWW.NATURE.COM") == "PRIMARY"
        assert _authority_tier("Www.Science.Org") == "PRIMARY"

    def test_substring_false_positives_rejected(self):
        """Ensure that substring matches no longer return PRIMARY for domains."""
        # These should not match as PRIMARY anymore
        assert _authority_tier("www.marketinggroup.com") == "UNKNOWN"
        assert _authority_tier("popscience.org") == "UNKNOWN"
        assert _authority_tier("signature.com") == "UNKNOWN"
        # Note: Old logic would have matched these as substrings, but new logic
        # requires proper domain suffix matching (exact match or .domain pattern)

    def test_publisher_subdomains_match(self):
        """Test that various subdomains of primary publishers are recognized."""
        # OUP subdomains
        assert _authority_tier("academic.oup.com") == "PRIMARY"
        assert _authority_tier("journals.oup.com") == "PRIMARY"
        assert _authority_tier("a.b.oup.com") == "PRIMARY"
        # Nature subdomains
        assert _authority_tier("www.nature.com") == "PRIMARY"
        assert _authority_tier("journals.nature.com") == "PRIMARY"
        # Cambridge subdomains
        assert _authority_tier("www.cambridge.org") == "PRIMARY"
        assert _authority_tier("books.cambridge.org") == "PRIMARY"
        # Science subdomains
        assert _authority_tier("www.science.org") == "PRIMARY"
        assert _authority_tier("journals.science.org") == "PRIMARY"

    def test_exact_domain_matches(self):
        """Test that exact domain matches return PRIMARY."""
        assert _authority_tier("oup.com") == "PRIMARY"
        assert _authority_tier("cambridge.org") == "PRIMARY"
        assert _authority_tier("nature.com") == "PRIMARY"
        assert _authority_tier("science.org") == "PRIMARY"

    def test_similar_but_invalid_domains_rejected(self):
        """Test that similar but invalid domains are rejected."""
        # These have the domain as a suffix but with invalid prefix
        assert _authority_tier("notoup.com") == "UNKNOWN"
        assert _authority_tier("fake-oup.com") == "UNKNOWN"
        assert _authority_tier("oup.com.example.com") == "UNKNOWN"
        assert _authority_tier("cambridge.org.fake.net") == "UNKNOWN"

    def test_springer_wiley_elsevier_substring_matching_unchanged(self):
        """Test that springer/wiley/elsevier still use substring matching."""
        # These should still work with substring matching
        assert _authority_tier("springer.com") == "PRIMARY"
        assert _authority_tier("www.springer.org") == "PRIMARY"
        assert _authority_tier("wiley.com") == "PRIMARY"
        assert _authority_tier("www.wiley.org") == "PRIMARY"
        assert _authority_tier("elsevier.com") == "PRIMARY"
        assert _authority_tier("www.elsevier.org") == "PRIMARY"
        # The "springer", "wiley", "elsevier" markers should still match as substrings
        assert _authority_tier("springeropen.com") == "PRIMARY"
        assert _authority_tier("onlinelibrary.wiley.com") == "PRIMARY"
        assert _authority_tier("sciencedirect.elsevier.com") == "PRIMARY"
