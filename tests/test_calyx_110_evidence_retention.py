from runtime.calyx_certification.evidence_retention import (
    validate_evidence_retention,
)


def test_immutable_retention_passes():
    result = validate_evidence_retention(
        {
            "artifact_hash": "h",
            "storage_uri": "s3://bucket/a",
            "retention_until": "2033-01-01",
            "immutable": True,
        }
    )
    assert result["retained"] is True


def test_mutable_evidence_fails():
    result = validate_evidence_retention(
        {
            "artifact_hash": "h",
            "storage_uri": "u",
            "retention_until": "x",
            "immutable": False,
        }
    )
    assert "evidence_not_immutable" in result["blockers"]
