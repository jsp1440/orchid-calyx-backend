from pathlib import Path

import pytest

from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.service import extract_and_persist


SOURCE = """Orchid Root and Floral Morphology Vocabulary Study
Ada Botanist
Journal of Orchid Language, 2026

Abstract
Velamen and pollinia were examined in orchid roots and flowers.

Keywords: velamen; pollinia; rostellum; orchid morphology

Introduction
The velamen surrounds aerial orchid roots.

Materials and Methods
PCR microscopy documented the velamen, rostellum, labellum, and pseudobulb.

Results
The rostellum and labellum were consistently visible, and pollinia were recorded.

Discussion
These terms are useful for standardized orchid morphology descriptions.

Conclusion
Velamen terminology should be linked to reviewed glossary concepts.
"""


@pytest.mark.asyncio
async def test_literature_pipeline_emits_deterministic_glossary_candidates(
    tmp_path: Path,
) -> None:
    source = tmp_path / "orchid_glossary.txt"
    source.write_text(SOURCE, encoding="utf-8")
    repository = LiteratureResultRepository(tmp_path / "results")

    first = await extract_and_persist(source, repository)
    second = await extract_and_persist(source, repository)

    first_terms = {term.normalized_term: term for term in first.glossary_terms}
    second_terms = {term.normalized_term: term for term in second.glossary_terms}

    assert set(first_terms) >= {
        "velamen",
        "pollinium",
        "rostellum",
        "labellum",
        "pseudobulb",
        "orchid morphology",
        "pcr",
    }
    assert {key: value.term_id for key, value in first_terms.items()} == {
        key: value.term_id for key, value in second_terms.items()
    }
    assert all(term.status == "candidate" for term in first.glossary_terms)
    assert all(term.glossary_entry_id is None for term in first.glossary_terms)
    assert all(term.provenance.extractor == "glossary" for term in first.glossary_terms)
    assert all(term.provenance.extractor_version == "0.1.0" for term in first.glossary_terms)

    for normalized in {"velamen", "pollinium", "rostellum", "labellum", "pseudobulb"}:
        assert first_terms[normalized].mentions
        for span in first_terms[normalized].mentions:
            assert span.char_start is not None and span.char_end is not None
            surface = SOURCE[span.char_start : span.char_end].casefold()
            if normalized == "pollinium":
                assert surface in {"pollinium", "pollinia"}
            elif normalized == "labellum":
                assert surface in {"labellum", "labella"}
            elif normalized == "pseudobulb":
                assert surface in {"pseudobulb", "pseudobulbs"}
            else:
                assert surface == normalized


@pytest.mark.asyncio
async def test_glossary_candidates_remain_noncanonical_and_api_serializable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "orchid_glossary.txt"
    source.write_text(SOURCE, encoding="utf-8")
    result = await extract_and_persist(
        source, LiteratureResultRepository(tmp_path / "results")
    )

    payload = result.model_dump(mode="json")
    assert payload["glossary_terms"]
    assert all(item["status"] == "candidate" for item in payload["glossary_terms"])
    assert all(item["glossary_entry_id"] is None for item in payload["glossary_terms"])
