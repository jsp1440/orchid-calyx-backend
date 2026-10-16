from __future__ import annotations

import pytest

from app.literature_extraction.models import Claim, Provenance
from app.literature_extraction.normalization import _classify_domain


@pytest.mark.parametrize(
    "statement,expected_domain",
    [
        # Negative cases: markers inside words should NOT match
        ("The lip is bright orange.", "other"),  # "range" in "orange"
        ("The ghost orchid has no leaves.", "other"),  # "host" in "ghost"
        ("Petals are opposite the sepals.", "other"),  # "site" in "opposite"
        ("Seeds are dispersed by wind in flight.", "other"),  # "light" in "flight"
        # Positive cases: existing behavior unchanged
        ("Flowers are pollinated by bees.", "ecological_interaction"),  # "pollinat" matches
        ("Plants grow on mycorrhizal fungi.", "ecological_interaction"),  # "mycorrh" matches
        ("It occurs in Mexico.", "occurrence"),  # "occur" matches
        ("The species is endemic.", "taxonomy"),  # "species" matches
        ("Leaf length is 10 cm.", "trait"),  # "leaf" and "length" match
        ("Grows well under bright light.", "cultivation"),  # "light" matches at word start
    ],
)
def test_claim_domain_classification_word_boundary_matching(
    statement: str, expected_domain: str
) -> None:
    """Test that claim domain markers match at word starts, not inside words."""
    claim = Claim(
        claim_id="test-123",
        statement=statement,
        claim_type="observation",
        subject_ids=[],
        object_ids=[],
        evidence_ids=[],
        polarity="positive",
        provenance=Provenance(
            method="model_extracted", confidence=1.0, extractor="test"
        ),
    )
    assert _classify_domain(claim) == expected_domain
