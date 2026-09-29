"""Generalised taxon query planning (CALYX-RECOVERY-001 Gate 3, defect D).

The planner matched a twelve-genus list. A question about any orchid outside
it produced no taxon, therefore no scientific query, therefore an empty result
that was indistinguishable from a bare corpus. Four of the five taxa in the
waiting acceptance mission were outside that list.
"""

from __future__ import annotations

import pytest

from app.calyx_conversation.external_literature import (
    _ORCHID_GENERA,
    _mentioned_genera,
    extract_taxa,
)

#: The taxa the waiting research mission asks about.
ACCEPTANCE_TAXA = [
    ("Calypso bulbosa", "Calypso"),
    ("Pleione humilis", "Pleione"),
    ("Ponerorchis graminifolia", "Ponerorchis"),
    ("Cephalanthera austiniae", "Cephalanthera"),
    ("Goodyera oblongifolia", "Goodyera"),
]


@pytest.mark.parametrize("binomial,genus", ACCEPTANCE_TAXA)
def test_taxa_outside_the_curated_list_are_planned(binomial, genus):
    question = f"Review the ecology and mycorrhizal associations of {binomial}"

    assert extract_taxa(question) == [binomial]
    assert _mentioned_genera(question) == [genus]


@pytest.mark.parametrize("binomial,genus", ACCEPTANCE_TAXA)
def test_the_fix_is_general_not_five_special_cases(binomial, genus):
    """None of these were added to the curated list to make the tests pass."""
    assert genus not in _ORCHID_GENERA


def test_an_arbitrary_binomial_the_continuum_has_never_seen_is_planned():
    # Not an orchid, and deliberately so: the rule is about scientific names,
    # not about a longer orchid list.
    assert extract_taxa("What is known about Fagus sylvatica mycorrhizae?") == [
        "Fagus sylvatica"
    ]


def test_the_epithet_rule_is_conservative_and_misses_some_real_names():
    """A known, deliberate limitation, recorded rather than hidden.

    "robur" is a real epithet ending in -ur, and the ending is not accepted,
    because -ur and -or admit too much ordinary English for a rule that has no
    taxonomy behind it. The cost is a missed search; the alternative cost is a
    scientific query fired at an English phrase, which returns nothing while
    looking like a result.

    The fix is not a longer suffix list. It is the resolver: canonical taxonomy
    settles what a name is, and the test below shows it overriding the rule.
    """
    assert extract_taxa("What is known about Quercus robur mycorrhizae?") == []


def test_a_resolver_recovers_a_name_the_lexical_rule_rejects():
    """Which is the point of having one."""

    class _Resolver:
        def resolve(self, text):
            return text if text == "Quercus robur" else None

    assert extract_taxa(
        "What is known about Quercus robur mycorrhizae?", resolver=_Resolver()
    ) == ["Quercus robur"]


def test_several_taxa_in_one_question_are_all_planned_in_order():
    question = "Compare Ponerorchis graminifolia with Goodyera oblongifolia"

    assert extract_taxa(question) == [
        "Ponerorchis graminifolia",
        "Goodyera oblongifolia",
    ]


@pytest.mark.parametrize(
    "question",
    [
        "Could this affect flowering?",
        "Which orchids grow in shade?",
        "Compare these plants with those species",
        "Review the evidence about winter rest",
        "What is known about carbon acquisition?",
        "These studies report growing conditions",
    ],
)
def test_ordinary_english_is_not_mistaken_for_a_taxon(question):
    """The false-positive class this guards against is real.

    "Could this" has the exact shape of a binomial. A planner that searched for
    it would return literature about nothing while looking like it had worked,
    which is worse than returning nothing, because it reads as a result.
    """
    assert extract_taxa(question) == []


def test_a_genus_in_the_curated_list_still_matches_on_its_own():
    """Existing single-genus questions must keep working unchanged."""
    assert _mentioned_genera("How should I grow Cattleya?") == ["Cattleya"]


def test_a_binomial_is_preferred_over_the_bare_genus_it_contains():
    taxa = extract_taxa("Could this affect Laelia anceps flowering?")

    assert taxa[0] == "Laelia anceps"
    assert _mentioned_genera("Could this affect Laelia anceps flowering?") == ["Laelia"]


def test_the_same_taxon_named_twice_is_planned_once():
    question = "Calypso bulbosa habitat, and the elevation range of Calypso bulbosa"

    assert extract_taxa(question) == ["Calypso bulbosa"]


def test_canonical_resolution_is_preferred_over_the_lexical_rules():
    """Taxonomy is a better authority on names than a regular expression."""

    class _Resolver:
        def resolve(self, text):
            return "Calypso bulbosa var. americana" if text == "Calypso bulbosa" else None

    taxa = extract_taxa(
        "Review Calypso bulbosa ecology", resolver=_Resolver()
    )
    assert taxa == ["Calypso bulbosa var. americana"]


def test_a_resolver_that_declines_falls_back_to_the_lexical_rules():
    class _Resolver:
        def resolve(self, text):
            return None

    assert extract_taxa("Review Calypso bulbosa ecology", resolver=_Resolver()) == [
        "Calypso bulbosa"
    ]


@pytest.mark.parametrize(
    "question",
    [
        "General enquiry Could this be interesting to look at?",
        "Regional survey of growing conditions",
        "Seasonal watering guidance",
        "Another question about culture",
    ],
)
def test_a_denylist_alone_was_not_enough(question):
    """"General enquiry" has the shape of a binomial and slipped the denylist.

    Found by the end-to-end pipeline test, not by this file: a request naming
    no taxon was searching for one anyway. The epithet must now also look like
    an epithet, which is a positive signal rather than another exclusion, and
    is why "enquiry", "conditions" and "guidance" are rejected without anyone
    having had to think of them first.
    """
    assert extract_taxa(question) == []


def test_a_bare_genus_is_not_returned_beside_its_own_binomial():
    """Same organism. Returning both made the runner read it twice."""
    assert extract_taxa("Could this affect Laelia anceps flowering?") == [
        "Laelia anceps"
    ]


def test_a_curated_genus_named_alone_and_a_binomial_elsewhere_both_survive():
    taxa = extract_taxa("Compare Cattleya with Calypso bulbosa")

    assert "Calypso bulbosa" in taxa
    assert "Cattleya" in taxa
