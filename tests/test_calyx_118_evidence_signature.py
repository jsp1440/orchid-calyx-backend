from runtime.calyx_certification.evidence_signature import evaluate_evidence_signature


def test_accepts_verified_signature_and_hash():
    result = evaluate_evidence_signature(
        {
            "artifact_hash": "abc",
            "signature": "sig",
            "public_key_id": "key-1",
            "algorithm": "ed25519",
            "signature_verified": True,
            "artifact_hash_matches": True,
        }
    )
    assert result["signature_accepted"] is True


def test_rejects_unverified_signature():
    result = evaluate_evidence_signature(
        {
            "artifact_hash": "abc",
            "signature": "sig",
            "public_key_id": "key-1",
            "algorithm": "ed25519",
            "signature_verified": False,
            "artifact_hash_matches": True,
        }
    )
    assert "signature_not_verified" in result["blockers"]
