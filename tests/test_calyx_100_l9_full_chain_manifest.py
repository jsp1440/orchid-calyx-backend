from runtime.calyx_certification.full_chain_manifest import (
    REQUIRED_STAGES,
    validate_acceptance_manifest,
)


def _passing_manifest():
    return {
        "stages": {
            stage: {
                "passed": True,
                "artifact_id": f"artifact:{stage}",
                "provenance": {"source": "fixture", "hash": stage},
            }
            for stage in REQUIRED_STAGES
        },
        "invariants": {
            "idempotent_duplicate_delivery": True,
            "cross_owner_denied": True,
            "stale_write_rejected": True,
            "approval_invalidated_after_mutation": True,
            "source_hash_mismatch_rejected": True,
            "private_reasoning_rejected": True,
        },
    }


def test_complete_manifest_certifies_without_authorizing_production():
    result = validate_acceptance_manifest(_passing_manifest())
    assert result["certified"] is True
    assert result["blockers"] == []
    assert result["production_action_authorized"] is False


def test_missing_stage_and_failed_invariant_block_certification():
    manifest = _passing_manifest()
    del manifest["stages"]["controlled_publication"]
    manifest["invariants"]["cross_owner_denied"] = False
    result = validate_acceptance_manifest(manifest)
    assert result["certified"] is False
    assert "controlled_publication:MISSING" in result["blockers"]
    assert "invariant:cross_owner_denied:FAILED" in result["blockers"]
