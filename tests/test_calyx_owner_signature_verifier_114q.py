from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.calyx_orchestrator.git_mutation_authorization import (
    GitMutationAuthorizationGate,
    GitMutationAuthorizationGrant,
    GitMutationAuthorizationRequest,
)
from app.calyx_orchestrator.owner_signature_verifier import (
    OWNER_REVOKED_KEY_IDS_ENV,
    OWNER_VERIFY_KEYS_ENV,
    Ed25519OwnerGrantSignatureVerifier,
    OwnerVerificationKey,
    owner_grant_signing_bytes,
)

NOW = datetime(2026, 8, 8, 23, 30, tzinfo=timezone.utc)
OWNER = "principal:owner"
BASE_REF = "main"


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _keypair(key_id: str):
    private = Ed25519PrivateKey.generate()
    raw_public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    verification = OwnerVerificationKey.from_base64url(
        key_id=key_id,
        public_key=_b64url(raw_public),
    )
    return private, verification


def _sign(private: Ed25519PrivateKey, key_id: str, payload: dict) -> str:
    signature = private.sign(owner_grant_signing_bytes(payload))
    return f"ed25519:{key_id}:{_b64url(signature)}"


def _request() -> GitMutationAuthorizationRequest:
    return GitMutationAuthorizationRequest(
        manifest_digest="a" * 64,
        patch_program_job_id="patch-job-123",
        repository="jsp1440/orchid-calyx-backend",
        base_commit_sha="b" * 40,
        base_ref=BASE_REF,
        proposed_branch="autonomy/proposal/work-123",
        change_hashes=(("app/example.py", "c" * 64),),
        validation_receipt_digests=("d" * 64,),
        review_authorization_digests=("e" * 64, "f" * 64),
        actions=("open_pull_request",),
        expires_at=(NOW + timedelta(minutes=15)).isoformat(),
    )


def _unsigned_grant(request: GitMutationAuthorizationRequest) -> dict[str, str]:
    return {
        "schema": "calyx-git-mutation-authorization-grant-v1",
        "request_digest": request.request_digest,
        "decision": "approved",
        "approved_by": OWNER,
        "issued_at": NOW.isoformat(),
        "expires_at": request.expires_at,
    }


def test_request_digest_binds_durable_patch_program_job_id() -> None:
    original = _request()
    changed = GitMutationAuthorizationRequest(
        manifest_digest=original.manifest_digest,
        patch_program_job_id="patch-job-other",
        repository=original.repository,
        base_commit_sha=original.base_commit_sha,
        base_ref=original.base_ref,
        proposed_branch=original.proposed_branch,
        change_hashes=original.change_hashes,
        validation_receipt_digests=original.validation_receipt_digests,
        review_authorization_digests=original.review_authorization_digests,
        actions=original.actions,
        expires_at=original.expires_at,
    )
    assert original.request_digest != changed.request_digest


def test_request_digest_binds_base_ref() -> None:
    original = _request()
    changed = GitMutationAuthorizationRequest(
        manifest_digest=original.manifest_digest,
        patch_program_job_id=original.patch_program_job_id,
        repository=original.repository,
        base_commit_sha=original.base_commit_sha,
        base_ref="release",
        proposed_branch=original.proposed_branch,
        change_hashes=original.change_hashes,
        validation_receipt_digests=original.validation_receipt_digests,
        review_authorization_digests=original.review_authorization_digests,
        actions=original.actions,
        expires_at=original.expires_at,
    )
    assert original.request_digest != changed.request_digest


def test_exact_ed25519_signature_verifies() -> None:
    private, key = _keypair("owner-2026-01")
    verifier = Ed25519OwnerGrantSignatureVerifier(keys={key.key_id: key})
    payload = _unsigned_grant(_request())
    signature = _sign(private, key.key_id, payload)
    assert verifier.verify(payload=payload, signature=signature) is True
    assert verifier.active_key_ids == ("owner-2026-01",)


def test_tampered_payload_wrong_key_and_malformed_signature_fail_closed() -> None:
    private, key = _keypair("owner-a")
    _, other_key = _keypair("owner-b")
    verifier = Ed25519OwnerGrantSignatureVerifier(
        keys={key.key_id: key, other_key.key_id: other_key}
    )
    payload = _unsigned_grant(_request())
    signature = _sign(private, key.key_id, payload)
    tampered = dict(payload)
    tampered["decision"] = "denied"
    assert verifier.verify(payload=tampered, signature=signature) is False
    assert (
        verifier.verify(
            payload=payload,
            signature=signature.replace("owner-a", "owner-b", 1),
        )
        is False
    )
    assert verifier.verify(payload=payload, signature="garbage") is False
    assert verifier.verify(payload=payload, signature="rsa:owner-a:abc") is False


def test_revocation_and_rotation_are_explicit_and_fail_closed() -> None:
    old_private, old_key = _keypair("owner-old")
    new_private, new_key = _keypair("owner-new")
    verifier = Ed25519OwnerGrantSignatureVerifier(
        keys={old_key.key_id: old_key, new_key.key_id: new_key},
        revoked_key_ids=frozenset({"owner-old"}),
    )
    payload = _unsigned_grant(_request())
    assert (
        verifier.verify(
            payload=payload,
            signature=_sign(old_private, old_key.key_id, payload),
        )
        is False
    )
    assert (
        verifier.verify(
            payload=payload,
            signature=_sign(new_private, new_key.key_id, payload),
        )
        is True
    )
    assert verifier.active_key_ids == ("owner-new",)
    assert verifier.revoked_key_ids == ("owner-old",)


def test_duplicate_public_key_material_cannot_bypass_revocation_by_alias() -> None:
    private, revoked_key = _keypair("owner-revoked")
    raw_public = revoked_key.public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    active_alias = OwnerVerificationKey.from_base64url(
        key_id="owner-active-alias",
        public_key=_b64url(raw_public),
    )
    with pytest.raises(ValueError, match="DUPLICATE_KEY_MATERIAL"):
        Ed25519OwnerGrantSignatureVerifier(
            keys={
                revoked_key.key_id: revoked_key,
                active_alias.key_id: active_alias,
            },
            revoked_key_ids=frozenset({revoked_key.key_id}),
        )
    payload = _unsigned_grant(_request())
    relabeled = _sign(private, "owner-active-alias", payload)
    assert relabeled.startswith("ed25519:owner-active-alias:")


def test_environment_loader_contains_only_public_material_and_requires_config() -> None:
    private, key = _keypair("owner-live")
    del private
    raw_public = key.public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    environ = {
        OWNER_VERIFY_KEYS_ENV: json.dumps({"owner-live": _b64url(raw_public)}),
        OWNER_REVOKED_KEY_IDS_ENV: "",
    }
    verifier = Ed25519OwnerGrantSignatureVerifier.from_environ(environ)
    assert verifier.active_key_ids == ("owner-live",)
    with pytest.raises(RuntimeError, match="KEYS_NOT_CONFIGURED"):
        Ed25519OwnerGrantSignatureVerifier.from_environ({})
    with pytest.raises(RuntimeError, match="KEYRING_INVALID"):
        Ed25519OwnerGrantSignatureVerifier.from_environ(
            {
                OWNER_VERIFY_KEYS_ENV: environ[OWNER_VERIFY_KEYS_ENV],
                OWNER_REVOKED_KEY_IDS_ENV: "owner-live",
            }
        )


def test_gate_accepts_valid_external_signature_and_rejects_revoked_signer() -> None:
    private, key = _keypair("owner-current")
    request = _request()
    payload = _unsigned_grant(request)
    grant = {**payload, "signature": _sign(private, key.key_id, payload)}
    gate = GitMutationAuthorizationGate(
        owner_principal=OWNER,
        signature_verifier=Ed25519OwnerGrantSignatureVerifier(keys={key.key_id: key}),
        clock=lambda: NOW + timedelta(minutes=1),
    )
    verified = gate.verify_grant(request, grant)
    assert isinstance(verified, GitMutationAuthorizationGrant)

    _, replacement = _keypair("owner-replacement")
    revoked_gate = GitMutationAuthorizationGate(
        owner_principal=OWNER,
        signature_verifier=Ed25519OwnerGrantSignatureVerifier(
            keys={key.key_id: key, replacement.key_id: replacement},
            revoked_key_ids=frozenset({key.key_id}),
        ),
        clock=lambda: NOW + timedelta(minutes=1),
    )
    with pytest.raises(PermissionError, match="SIGNATURE_INVALID"):
        revoked_gate.verify_grant(request, grant)


def test_signature_parser_preserves_case_sensitive_envelope() -> None:
    private, key = _keypair("Owner-Key-A")
    request = _request()
    payload = _unsigned_grant(request)
    signature = _sign(private, key.key_id, payload)
    assert any(character.isupper() for character in signature)
    grant = GitMutationAuthorizationGrant.from_mapping(
        {**payload, "signature": signature}
    )
    assert grant.signature == signature


def test_runtime_verifier_surface_exposes_no_signing_api() -> None:
    _, key = _keypair("owner-public-only")
    verifier = Ed25519OwnerGrantSignatureVerifier(keys={key.key_id: key})
    for name in ("sign", "approve", "mint", "private_key", "secret"):
        assert not hasattr(verifier, name)
