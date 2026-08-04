from runtime.calyx_certification.concept_consumers import (
    REQUIRED_CONSUMERS,
    certify_concept_consumers,
)


def _report():
    return {
        "canonical_registry_id": "registry:orchid",
        "canonical_version": "v1",
        "consumers": {
            name: {
                "registry_id": "registry:orchid",
                "registry_version": "v1",
                "owner_isolation": True,
                "project_isolation": True,
                "deterministic_resolution": True,
            }
            for name in REQUIRED_CONSUMERS
        },
    }


def test_all_consumers_share_canonical_registry():
    result = certify_concept_consumers(_report())
    assert result["certified"] is True
    assert result["publication_authorized"] is False


def test_mismatch_fails_closed():
    report = _report()
    report["consumers"]["knowledge_graph"]["registry_version"] = "stale"
    result = certify_concept_consumers(report)
    assert result["certified"] is False
    assert "knowledge_graph:VERSION_MISMATCH" in result["blockers"]
