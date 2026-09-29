"""Synthetic labeled treatments: verbatim review candidates, not botanical facts."""
from types import SimpleNamespace

import pytest

from app.literature_extraction.extractors.morphology import (
    MORPHOLOGY_PREDICATES,
    CanonicalMorphologyExtractor,
)
from app.literature_extraction.normalization import _classify_domain
from runtime.knowledge_graph.canonical_taxonomy import CanonicalRegistry, CanonicalTaxon


async def extract(tmp_path, text):
    path = tmp_path / "monograph.txt"
    path.write_text(text, encoding="utf-8")
    taxa = {
        i: CanonicalTaxon(i, name, name, None, "species", "accepted", False)
        for i, name in enumerate(("Paphiopedilum delenatii", "Paphiopedilum armeniacum"), 1)
    }
    registry = CanonicalRegistry(None, taxa, {t.canonical_name: i for i, t in taxa.items()})
    paper = SimpleNamespace(analysis_manifest=SimpleNamespace(warnings=[]))
    await CanonicalMorphologyExtractor(registry).run(SimpleNamespace(source_path=path), paper)
    return paper


@pytest.mark.asyncio
async def test_labeled_treatments_preserve_exact_independent_spans(tmp_path):
    statements = [
        "Paphiopedilum delenatii description: Terrestrial herb; leaves elliptic, mottled green.",
        "Paphiopedilum delenatii diagnosis: Staminode ovate; petals narrow.",
        "Paphiopedilum delenatii leaf: Elliptic, 10–12 cm long.",
        "Paphiopedilum delenatii leaf: Elliptic, 14-16 cm long.",
        "Paphiopedilum armeniacum flower: Solitary, yellow.",
        "Paphiopedilum armeniacum sepal: Dorsal sepal ovate.",
        "Paphiopedilum armeniacum petal: Spreading, pubescent.",
        "Paphiopedilum armeniacum lip: Inflated, yellow.",
        "Paphiopedilum armeniacum column: Short, glabrous.",
        "Paphiopedilum armeniacum staminode: Ovate, yellow.",
        "Paphiopedilum armeniacum inflorescence: Erect, single flower.",
        "Paphiopedilum armeniacum habit: Terrestrial perennial herb.",
        "Paphiopedilum armeniacum habitat: Shaded montane forest.",
        "Paphiopedilum armeniacum elevation: 1000-1500 m.",
        "Paphiopedilum armeniacum phenology: Flowering march to may.",
        "Paphiopedilum armeniacum substrate: Limestone rocks, humus.",
        "Paphiopedilum armeniacum diagnostic comparison: Petals narrower; staminode broader.",
        "Paphiopedilum armeniacum key couplet: 1. Leaves mottled; flowers yellow.",
        "Paphiopedilum armeniacum variation: Petals sometimes pale yellow.",
        "Paphiopedilum armeniacum character: Lip inflated.",
        "Paphiopedilum armeniacum column length 2-3 mm.",
    ]
    text = "\n".join(statements)
    paper = await extract(tmp_path, text)
    assert [claim.statement for claim in paper.claims] == statements
    assert [e.name for e in paper.entities][:4] == ["Paphiopedilum delenatii"] * 4
    assert all(claim.predicate in MORPHOLOGY_PREDICATES for claim in paper.claims)
    assert all(_classify_domain(claim) == "trait" for claim in paper.claims)
    assert all(claim.provenance.review_status == "unreviewed" for claim in paper.claims)
    for evidence in paper.evidence:
        assert text[evidence.span.char_start:evidence.span.char_end] == evidence.excerpt
    assert "10–12" in paper.claims[2].statement
    assert "14-16" in paper.claims[3].statement


@pytest.mark.asyncio
async def test_sensitive_or_unsupported_labeled_prose_withheld_with_count_only_warning(tmp_path):
    text = "\n".join([  # noqa: FLY002 - one fixture line per rejected case
        "Paphiopedilum delenatii habitat: Secret Valley near station 123.",
        "Paphiopedilum delenatii habitat: 12.345 N, 67.890 E.",
        "Paphiopedilum delenatii description: GPS 12.345,67.890; glabrous.",
        "Paphiopedilum delenatii substrate: https://private.example/location.",
        "Paphiopedilum delenatii habitat: 12.345, 67.890 forest.",
        "Paphiopedilum delenatii habitat: Green Forest.",
        "Paphiopedilum unknown leaf: Elliptic.",
        "Leaves elliptic; inferred taxon from heading is forbidden.",
    ])
    paper = await extract(tmp_path, text)
    assert not paper.claims and not paper.evidence and not paper.sections
    assert paper.analysis_manifest.warnings == [
        "canonical_morphology: 6 unsupported labeled spans withheld; expert extraction review required",
        "canonical_morphology: 1 unresolved or ambiguous taxon spans withheld; taxonomy review required"
    ]
    assert "Valley" not in str(paper.analysis_manifest.warnings)
