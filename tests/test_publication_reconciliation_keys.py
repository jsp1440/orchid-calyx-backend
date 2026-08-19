from __future__ import annotations

from app.calyx_conversation.literature_ingest import document_from_external_record
from app.calyx_conversation.scholarly_metadata_ingest import document_from_crossref_work


def test_europe_pmc_and_crossref_share_doi_publication_key() -> None:
    epmc = document_from_external_record(
        {
            "title": "Pollination biology of an orchid",
            "abstract": "A sufficiently long abstract about orchid pollination and floral biology.",
            "doi": "10.1234/Example.DOI",
            "pmid": "12345",
            "publication_date": "2025-01-01",
        },
        query="orchid pollination",
    )
    crossref = document_from_crossref_work(
        {
            "title": ["Pollination biology of an orchid"],
            "DOI": "https://doi.org/10.1234/example.doi",
            "published": {"date-parts": [[2025, 1, 1]]},
        },
        query="orchid pollination",
    )

    assert epmc is not None
    assert crossref is not None
    assert epmc.metadata["canonical_publication_key"] == "doi:10.1234/example.doi"
    assert crossref.metadata["canonical_publication_key"] == epmc.metadata["canonical_publication_key"]


def test_europe_pmc_uses_pmid_when_doi_absent() -> None:
    document = document_from_external_record(
        {
            "title": "Orchid mycorrhizal study",
            "abstract": "A sufficiently long abstract discussing orchid mycorrhizal fungal relationships.",
            "pmid": "987654",
        },
        query="orchid mycorrhiza",
    )
    assert document is not None
    assert document.metadata["canonical_publication_key"] == "pmid:987654"
