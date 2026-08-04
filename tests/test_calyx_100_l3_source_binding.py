from runtime.calyx_certification.source_binding import evaluate_source_binding


def _binding():
    return {
        "paper_id": "paper:1",
        "analysis_id": "analysis:1",
        "evidence_id": "evidence:1",
        "source_revision_id": "revision:1",
        "extraction_run_id": "run:1",
        "source_anchor": "page:2",
        "source_hash": "sha256:abc",
        "ambiguous": False,
        "conflicting": False,
        "owner_isolated": True,
        "project_isolated": True,
        "idempotent": True,
    }


def test_complete_binding_allows_unpublished_candidate_handoff():
    result = evaluate_source_binding(_binding())
    assert result["binding_complete"] is True
    assert result["candidate_handoff_allowed"] is True
    assert result["candidate_published"] is False


def test_ambiguous_or_partial_binding_fails_closed():
    binding = _binding()
    binding["ambiguous"] = True
    binding["source_hash"] = None
    result = evaluate_source_binding(binding)
    assert result["binding_complete"] is False
    assert "AMBIGUOUS_BINDING" in result["blockers"]
    assert "SOURCE_HASH:MISSING" in result["blockers"]
