from runtime.calyx_certification.ledger_certification import (
    REQUIRED_LEDGER_CAPABILITIES,
    certify_reasoning_ledger,
)


def _passing_evidence():
    return {
        "capabilities": {name: True for name in REQUIRED_LEDGER_CAPABILITIES},
        "postgresql_test_run_id": "pg-run:1",
        "artifact_hash": "sha256:abc",
    }


def test_complete_ledger_evidence_certifies_without_publication():
    result = certify_reasoning_ledger(_passing_evidence())
    assert result["certified"] is True
    assert result["blockers"] == []
    assert result["publication_authorized"] is False
    assert result["private_reasoning_stored"] is False


def test_stale_approval_and_isolation_must_be_proven():
    evidence = _passing_evidence()
    evidence["capabilities"]["stale_approval_invalidation"] = False
    evidence["capabilities"]["owner_isolation"] = False
    result = certify_reasoning_ledger(evidence)
    assert result["certified"] is False
    assert "stale_approval_invalidation:NOT_PROVEN" in result["blockers"]
    assert "owner_isolation:NOT_PROVEN" in result["blockers"]


def test_missing_postgresql_run_and_hash_fail_closed():
    result = certify_reasoning_ledger({"capabilities": {}})
    assert result["certified"] is False
    assert "POSTGRESQL_TEST_RUN_ID_MISSING" in result["blockers"]
    assert "ARTIFACT_HASH_MISSING" in result["blockers"]
