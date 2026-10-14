"""Brain #189: one DOI identity rule shared by every scientific-synthesis comparison."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.scientific_synthesis import discovery, matrix
from app.scientific_synthesis.identifiers import normalize_doi

BARE = "10.1000/orchid.1"


@pytest.mark.parametrize(
    "value",
    [
        BARE,
        "  10.1000/ORCHID.1  ",
        "https://doi.org/10.1000/orchid.1",
        "http://doi.org/10.1000/orchid.1",
        "HTTPS://DOI.ORG/10.1000/ORCHID.1",
        "https://dx.doi.org/10.1000/orchid.1",
        "http://dx.doi.org/10.1000/orchid.1",
        "doi:10.1000/orchid.1",
        "DOI: 10.1000/orchid.1",
        "doi:   10.1000/orchid.1",
        "https://doi.org/doi:10.1000/orchid.1",
        "doi:https://doi.org/10.1000/orchid.1",
    ],
)
def test_every_common_doi_form_reduces_to_one_canonical_value(value):
    assert normalize_doi(value) == BARE


@pytest.mark.parametrize("value", [None, "", "   ", "doi:", "https://doi.org/", "doi:   "])
def test_an_absent_doi_is_none_never_an_empty_string(value):
    assert normalize_doi(value) is None


def test_the_rule_never_repairs_or_invents_a_doi():
    # Form only: a value that is not a DOI stays exactly as unrecognisable as it was.
    assert normalize_doi("not a doi") == "not a doi"
    assert normalize_doi("https://example.org/10.1000/orchid.1") == (
        "https://example.org/10.1000/orchid.1"
    )


def test_discovery_and_matrix_share_the_one_rule():
    # Guards against the modules drifting apart again.
    assert discovery._normalize_doi is normalize_doi
    assert matrix._normalize_doi is normalize_doi


def _paper(*identifiers, title=None):
    return SimpleNamespace(
        metadata=SimpleNamespace(
            identifiers=[SimpleNamespace(scheme=scheme, value=value) for scheme, value in identifiers],
            title=title,
        )
    )


def _bibliography(doi, title="Orchid foliar nitrogen uptake"):
    return SimpleNamespace(doi=doi, title=title)


def test_a_dx_resolver_identifier_still_proves_the_papers_identity():
    # Reproduces the divergence: the matrix used to keep "dx.doi.org/..." and so
    # refused (BIBLIOGRAPHIC_PAPER_IDENTITY_UNPROVEN) a paper that WAS the record.
    paper = _paper(("doi", "https://dx.doi.org/10.1000/ORCHID.1"))
    assert matrix._bibliography_matches_paper(paper, _bibliography(BARE)) is True


def test_a_different_doi_still_does_not_prove_identity():
    paper = _paper(("doi", "https://dx.doi.org/10.1000/other.2"))
    assert matrix._bibliography_matches_paper(paper, _bibliography(BARE)) is False


def test_identity_stays_unproven_when_the_paper_declares_a_doi_that_does_not_match():
    # A DOI the paper declares must match; the title fallback applies only when
    # the paper declares no DOI at all, so a matching title cannot override it.
    paper = _paper(("doi", "10.1000/other.2"), title="Orchid foliar nitrogen uptake")
    assert matrix._bibliography_matches_paper(paper, _bibliography(BARE)) is False


def test_a_missing_bibliography_doi_never_matches_a_declared_paper_doi():
    paper = _paper(("doi", BARE))
    assert matrix._bibliography_matches_paper(paper, _bibliography(None)) is False
    assert matrix._bibliography_matches_paper(paper, _bibliography("doi:")) is False
