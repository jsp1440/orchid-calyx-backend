from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.calyx_orchestrator.git_mutation_authorization import (
    GitMutationAuthorizationGate,
)
from app.calyx_orchestrator.sandbox_supervisor_evidence import canonical_sha256

SECRET = b"x" * 32
OWNER = "owner:jsp1440"
BASE = "a" * 40
HASH_A = "b" * 64
HASH_B = "c" * 64
RECEIPT = "d" * 64


def _manifest() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "calyx-git-proposal-manifest-v1",
        "repository": "jsp1440/orchid-calyx-backend",
        "base_commit_sha": BASE,
        "source_autonomy_branch": "autonomy/work/job-1",
        "proposed_branch": "autonomy/proposal/job-1",
        "patch_output_checksum": "e" * 64,
        "changes": [
            {
                "path": "app/example.py",
                "before_sha256": HASH_A,
                "after_sha256": HASH_B,
                "created": False,
                "size_bytes": 12,
            }
        ],
        "validations": [
            {
                "preset": "ruff",
                "request_digest": "f" * 64,
                "receipt_digest": RECEIPT,
                "policy_digest": "1" * 64,
                "targets": [{"path": "app/example.py", "sha256": HASH_B}],
            }
        ],
        "commit_title": "Implement bounded change",
        "pr_title": "Implement bounded change",
        "summary": "Validated autonomous engineering proposal.",
        "git_mutation_performed": False,
        "commit_created": False,
        "push_performed": False,
        "pull_request_created": False,
        "automatic_merge_authorized": False,
        "deployment_authorized": False,
        "publication_authorized": False,
        "production_database_mutation_authorized": False,
        "production_graph_mutation_authorized": False,
    }
    return {**payload, "manifest_digest": canonical_sha256(payload)}


def _times() -> tuple[datetime, str, str]:
    now = datetime(2026, 8, 8, 22, 0, tzinfo=timezone.utc)
    issued = now.isoformat()
    expires = (now + timedelta(minutes=10)).isoformat()
    return now, issued, expires


def test_build_request_binds_exact_manifest_and_safe_actions() -> None:
    now, _, expires = _times()
    request = GitMutationAuthorizationGate.build_request(
        _manifest(),
        actions=("create_branch", "create_commit", "push_branch", "open_pull_request"),
        expires_at=expires,
        now=now,
    )
    snapshot = request.snapshot()
    assert snapshot["repository"] == "jsp1440/orchid-calyx-backend"
    assert snapshot["base_commit_sha"] == BASE
    assert snapshot["proposed_branch"] == "autonomy/proposal/job-1"
    assert snapshot["merge_authorized"] is False
    assert snapshot["deployment_authorized"] is False
    assert snapshot["publication_authorized"] is False
    assert len(snapshot["request_digest"]) == 64


def test_request_rejects_manifest_tampering() -> None:
    now, _, expires = _times()
    manifest = _manifest()
    manifest["pr_title"] = "tampered"
    with pytest.raises(PermissionError, match="MANIFEST_DIGEST_MISMATCH"):
        GitMutationAuthorizationGate.build_request(
            manifest,
            actions=("open_pull_request",),
            expires_at=expires,
            now=now,
        )


def test_request_rejects_prohibited_or_unknown_action() -> None:
    now, _, expires = _times()
    with pytest.raises(PermissionError, match="ACTION_NOT_ALLOWED"):
        GitMutationAuthorizationGate.build_request(
            _manifest(),
            actions=("merge_pull_request",),
            expires_at=expires,
            now=now,
        )


def test_request_rejects_authority_contaminated_manifest() -> None:
    now, _, expires = _times()
    manifest = _manifest()
    manifest["automatic_merge_authorized"] = True
    payload = dict(manifest)
    payload.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_sha256(payload)
    with pytest.raises(PermissionError, match="AUTHORITY_CONTAMINATED"):
        GitMutationAuthorizationGate.build_request(
            manifest,
            actions=("open_pull_request",),
            expires_at=expires,
            now=now,
        )


def test_verified_owner_grant_is_exact_request_bound() -> None:
    now, issued, expires = _times()
    gate = GitMutationAuthorizationGate(owner_principal=OWNER, hmac_secret=SECRET)
    request = gate.build_request(
        _manifest(),
        actions=("create_branch", "create_commit", "push_branch", "open_pull_request"),
        expires_at=expires,
        now=now,
    )
    grant = gate.sign_for_test_or_operator(
        request_digest=request.request_digest,
        decision="approved",
        issued_at=issued,
        expires_at=expires,
    )
    verified = gate.verify_grant(request, grant, now=now)
    assert verified.decision == "approved"
    assert verified.approved_by == OWNER


def test_denied_grant_fails_closed() -> None:
    now, issued, expires = _times()
    gate = GitMutationAuthorizationGate(owner_principal=OWNER, hmac_secret=SECRET)
    request = gate.build_request(
        _manifest(),
        actions=("open_pull_request",),
        expires_at=expires,
        now=now,
    )
    grant = gate.sign_for_test_or_operator(
        request_digest=request.request_digest,
        decision="denied",
        issued_at=issued,
        expires_at=expires,
    )
    with pytest.raises(PermissionError, match="NOT_APPROVED"):
        gate.verify_grant(request, grant, now=now)


def test_tampered_signature_and_wrong_owner_fail_closed() -> None:
    now, issued, expires = _times()
    gate = GitMutationAuthorizationGate(owner_principal=OWNER, hmac_secret=SECRET)
    request = gate.build_request(
        _manifest(),
        actions=("open_pull_request",),
        expires_at=expires,
        now=now,
    )
    grant = gate.sign_for_test_or_operator(
        request_digest=request.request_digest,
        decision="approved",
        issued_at=issued,
        expires_at=expires,
    )
    grant["signature"] = "0" * 64
    with pytest.raises(PermissionError, match="SIGNATURE_INVALID"):
        gate.verify_grant(request, grant, now=now)

    valid = gate.sign_for_test_or_operator(
        request_digest=request.request_digest,
        decision="approved",
        issued_at=issued,
        expires_at=expires,
    )
    valid["approved_by"] = "owner:someone-else"
    with pytest.raises(PermissionError, match="APPROVER_MISMATCH"):
        gate.verify_grant(request, valid, now=now)


def test_expired_or_overlong_authorization_fails_closed() -> None:
    now, _, expires = _times()
    gate = GitMutationAuthorizationGate(owner_principal=OWNER, hmac_secret=SECRET)
    request = gate.build_request(
        _manifest(),
        actions=("open_pull_request",),
        expires_at=expires,
        now=now,
    )
    grant = gate.sign_for_test_or_operator(
        request_digest=request.request_digest,
        decision="approved",
        issued_at=now.isoformat(),
        expires_at=expires,
    )
    with pytest.raises(PermissionError, match="EXPIRED_OR_INVALID"):
        gate.verify_grant(request, grant, now=now + timedelta(minutes=10))

    with pytest.raises(PermissionError, match="EXPIRY_INVALID"):
        gate.build_request(
            _manifest(),
            actions=("open_pull_request",),
            expires_at=(now + timedelta(hours=2)).isoformat(),
            now=now,
        )
