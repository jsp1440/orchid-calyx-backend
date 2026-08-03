from app.parallel_platform.matrix_adapters import (
    DimensionEvidence,
    StaticMatrixEvidenceAdapter,
    hydrate_pairwise_dimensions,
)


def test_unavailable_dimensions_never_receive_zero_scores():
    result = hydrate_pairwise_dimensions("taxon:a", "taxon:b", ())
    assert result["taxonomy"].availability == "unavailable"
    assert result["taxonomy"].score is None


def test_static_adapter_supports_symmetric_pair_lookup():
    evidence = DimensionEvidence(
        dimension="taxonomy",
        availability="available",
        score=0.8,
        confidence=0.9,
        evidence=("edge:taxon-a-taxon-b",),
        provenance=("oc_graph",),
    )
    adapter = StaticMatrixEvidenceAdapter(
        dimension="taxonomy",
        records={("taxon:a", "taxon:b"): evidence},
    )
    result = adapter.compare("taxon:b", "taxon:a")
    assert result.score == 0.8
    assert result.evidence == ("edge:taxon-a-taxon-b",)


def test_dimension_contract_rejects_scored_unavailable_data():
    try:
        DimensionEvidence(dimension="ecology", availability="unavailable", score=0.0)
    except ValueError as exc:
        assert str(exc) == "UNAVAILABLE_DIMENSION_CANNOT_HAVE_SCORE"
    else:
        raise AssertionError("invalid unavailable score was accepted")
