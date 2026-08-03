from app.parallel_platform.brain_candidate_handoff import (
    BrainCandidateHandoffRequest,
    handoff_brain_candidate,
)


def request_payload(reasoning_id: str = "reasoning:test-1") -> BrainCandidateHandoffRequest:
    return BrainCandidateHandoffRequest(
        reasoning_id=reasoning_id,
        domain="ecology",
        subject="Cattleya labiata",
        predicate="associated_with_pollinator",
        object_value="Euglossine bee",
        confidence=0.72,
        evidence_text="A reviewed evidence record reports an association with an euglossine bee.",
        source_object_type="brain_reasoning_record",
        source_object_id=101,
        revision_id=1,
        extraction_run_id=1,
        source_anchors=[
            {
                "anchor_id": 9001,
                "logical_unit": "claim:test-1",
                "locator": {"source_hash": "sha256:test", "confidence": 0.72},
            }
        ],
        provenance={"rule_id": "ecology-association-v1", "evidence_ids": ["evidence:test-1"]},
    )


def test_brain_handoff_creates_review_required_unpublished_candidate():
    result = handoff_brain_candidate(request_payload())
    assert result["state"] in {"COMPLETED", "PARTIAL"}
    assert result["candidate_ids"]
    assert result["review_required"] is True
    assert result["published"] is False
    assert result["graph_mutation"] is False
    assert result["scientific_publication_authority"] is False


def test_brain_handoff_requires_exact_source_identity_and_anchor():
    payload = request_payload("reasoning:test-invalid").model_dump()
    payload["source_object_id"] = 0
    try:
        BrainCandidateHandoffRequest(**payload)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid canonical source identity was accepted")


def test_brain_handoff_requires_candidate_value():
    payload = request_payload("reasoning:test-no-value").model_dump()
    payload["object_value"] = None
    payload["numeric_value"] = None
    try:
        BrainCandidateHandoffRequest(**payload)
    except ValueError as exc:
        assert "CANDIDATE_VALUE_REQUIRED" in str(exc)
    else:
        raise AssertionError("candidate without a value was accepted")
