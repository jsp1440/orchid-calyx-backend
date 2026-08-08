from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.calyx_orchestrator.executor import canonical_checksum
from app.calyx_orchestrator.git_proposal_manifest import GitProposalManifestBuilder
from app.calyx_orchestrator.sandbox_supervisor_evidence import (
    SupervisorValidationReceipt,
    ValidationRequestEnvelope,
)

REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/work-123"
COMMIT = "a" * 40
APP_HASH = "b" * 64
TEST_HASH = "c" * 64
POLICY_HASH = "d" * 64
EMPTY_HASH = hashlib.sha256(b"").hexdigest()


def _patch_receipt() -> dict:
    output = {
        "status": "delivered",
        "executed": True,
        "mode": "authoritative_isolated_workspace_patch",
        "repository": REPOSITORY,
        "branch": BRANCH,
        "checkout_commit_sha": COMMIT,
        "workspace_isolated": True,
        "workspace_disposable": True,
        "changes": [
            {
                "path": "app/example.py",
                "before_sha256": "e" * 64,
                "after_sha256": APP_HASH,
                "created": False,
                "size_bytes": 100,
            },
            {
                "path": "tests/test_example.py",
                "before_sha256": "absent",
                "after_sha256": TEST_HASH,
                "created": True,
                "size_bytes": 80,
            },
        ],
        "file_count": 2,
        "total_written_bytes": 180,
        "commit_created": False,
        "validation_commands_run": False,
        "side_effects": ["isolated_workspace_files_modified"],
    }
    return {"output": output, "output_checksum": canonical_checksum(output)}


def _validation(
    preset: str,
    targets: list[dict[str, str]],
    *,
    outcome: str = "delivered",
    policy_digest: str = POLICY_HASH,
) -> dict:
    request = {
        "repository": REPOSITORY,
        "branch": BRANCH,
        "checkout_commit_sha": COMMIT,
        "preset": preset,
        "targets": targets,
        "timeout_seconds": 60,
    }
    envelope = ValidationRequestEnvelope.build(**request)
    receipt = {
        "request_digest": envelope.request_digest,
        "authorization_id": f"sandbox-auth-{preset}",
        "policy_digest": policy_digest,
        "evidence_uri": f"sandbox-worker:worker-{preset}",
        "outcome": outcome,
        "return_code": 0 if outcome == "delivered" else 1,
        "stdout_sha256": EMPTY_HASH,
        "stderr_sha256": EMPTY_HASH,
        "issued_at": datetime(2026, 8, 8, 20, 0, tzinfo=timezone.utc).isoformat(),
    }
    return {"request": request, "receipt": receipt}


def _validations() -> list[dict]:
    return [
        _validation(
            "ruff",
            [
                {"path": "app/example.py", "sha256": APP_HASH},
                {"path": "tests/test_example.py", "sha256": TEST_HASH},
            ],
        ),
        _validation(
            "pytest",
            [{"path": "tests/test_example.py", "sha256": TEST_HASH}],
        ),
    ]


class _PersistedSupervisorService:
    def __init__(self, evidence: list[dict]) -> None:
        self.records = {}
        for entry in evidence:
            request = ValidationRequestEnvelope.build(**entry["request"])
            receipt = SupervisorValidationReceipt.from_mapping(entry["receipt"])
            self.records[request.request_digest] = SimpleNamespace(
                request_digest=request.request_digest,
                repository=request.repository,
                branch=request.branch,
                checkout_commit_sha=request.checkout_commit_sha,
                preset=request.preset,
                targets_json=json.dumps(
                    [item.as_dict() for item in request.targets], sort_keys=True
                ),
                timeout_seconds=request.timeout_seconds,
                status="completed" if receipt.outcome == "delivered" else "blocked",
                outcome=receipt.outcome,
                receipt_digest=receipt.receipt_digest,
                policy_digest=receipt.policy_digest,
                authorization_id=receipt.authorization_id,
                evidence_uri=receipt.evidence_uri,
            )

    def get_completed_by_digest(self, *, request_digest: str):
        record = self.records.get(request_digest)
        if record is None or record.status != "completed":
            raise LookupError("SANDBOX_VALIDATION_COMPLETED_RECORD_NOT_FOUND")
        return record


def _builder(evidence: list[dict] | None = None) -> GitProposalManifestBuilder:
    values = _validations() if evidence is None else evidence
    return GitProposalManifestBuilder(
        _PersistedSupervisorService(values),
        allowed_policy_digests=[POLICY_HASH],
    )


def _build(builder: GitProposalManifestBuilder, validations: list[dict]):
    return builder.build(
        patch_receipt=_patch_receipt(),
        validations=validations,
        proposed_branch="autonomy/proposal/work-123",
        commit_title="Improve bounded validation",
        pr_title="Improve bounded validation",
        summary="Evidence-bound proposal only.",
    )


def test_manifest_is_deterministic_and_performs_no_git_mutation() -> None:
    evidence = _validations()
    builder = _builder(evidence)
    manifest = _build(builder, evidence)
    repeat = _build(builder, list(reversed(evidence)))

    assert manifest.manifest_digest == repeat.manifest_digest
    snapshot = manifest.snapshot()
    assert snapshot["git_mutation_performed"] is False
    assert snapshot["commit_created"] is False
    assert snapshot["push_performed"] is False
    assert snapshot["pull_request_created"] is False
    assert snapshot["automatic_merge_authorized"] is False
    assert snapshot["deployment_authorized"] is False
    assert snapshot["publication_authorized"] is False
    assert len(snapshot["manifest_digest"]) == 64


def test_patch_output_checksum_must_match_exact_output() -> None:
    receipt = _patch_receipt()
    receipt["output"]["changes"][0]["size_bytes"] = 101
    evidence = _validations()
    with pytest.raises(PermissionError, match="PATCH_OUTPUT_CHECKSUM_MISMATCH"):
        _builder(evidence).build(
            patch_receipt=receipt,
            validations=evidence,
            proposed_branch="autonomy/proposal/work-123",
            commit_title="Improve bounded validation",
            pr_title="Improve bounded validation",
            summary="Evidence-bound proposal only.",
        )


def test_ruff_must_cover_every_python_postimage_hash() -> None:
    validations = [
        _validation(
            "ruff",
            [{"path": "tests/test_example.py", "sha256": TEST_HASH}],
        ),
        _validation(
            "pytest",
            [{"path": "tests/test_example.py", "sha256": TEST_HASH}],
        ),
    ]
    with pytest.raises(PermissionError, match="RUFF_COVERAGE_INCOMPLETE"):
        _build(_builder(validations), validations)


def test_pytest_must_cover_each_changed_test_exact_postimage() -> None:
    unrelated_hash = "f" * 64
    validations = [
        _validation(
            "ruff",
            [
                {"path": "app/example.py", "sha256": APP_HASH},
                {"path": "tests/test_example.py", "sha256": TEST_HASH},
            ],
        ),
        _validation(
            "pytest",
            [{"path": "tests/test_unrelated.py", "sha256": unrelated_hash}],
        ),
    ]
    with pytest.raises(PermissionError, match="PYTEST_COVERAGE_INCOMPLETE"):
        _build(_builder(validations), validations)


def test_validation_identity_and_success_are_required() -> None:
    failed = _validation(
        "ruff",
        [
            {"path": "app/example.py", "sha256": APP_HASH},
            {"path": "tests/test_example.py", "sha256": TEST_HASH},
        ],
        outcome="blocked",
    )
    with pytest.raises(PermissionError, match="SUCCESSFUL_VALIDATION_REQUIRED"):
        _build(_builder([failed]), [failed])


def test_forged_serialized_receipt_is_rejected_without_matching_persisted_record() -> (
    None
):
    persisted = _validations()
    supplied = _validations()
    supplied[0]["receipt"]["authorization_id"] = "sandbox-auth-forged"
    with pytest.raises(PermissionError, match="PERSISTED_VALIDATION_MISMATCH"):
        _build(_builder(persisted), supplied)


def test_missing_persisted_supervisor_record_is_rejected() -> None:
    supplied = _validations()
    service = _PersistedSupervisorService([])
    builder = GitProposalManifestBuilder(
        service,
        allowed_policy_digests=[POLICY_HASH],
    )
    with pytest.raises(PermissionError, match="PERSISTED_VALIDATION_REQUIRED"):
        _build(builder, supplied)


def test_unapproved_sandbox_policy_digest_is_rejected() -> None:
    supplied = _validations()
    builder = GitProposalManifestBuilder(
        _PersistedSupervisorService(supplied),
        allowed_policy_digests=["9" * 64],
    )
    with pytest.raises(PermissionError, match="VALIDATION_POLICY_NOT_ALLOWED"):
        _build(builder, supplied)


@pytest.mark.parametrize(
    "branch",
    [
        "main",
        "autonomy/proposal/bad branch",
        "autonomy/proposal/bad~branch",
        "autonomy/proposal/bad@{branch",
        "autonomy/proposal/.hidden",
        "autonomy/proposal/bad.lock",
        "autonomy/proposal/bad\\branch",
        "autonomy/proposal/bad..branch",
        "autonomy/proposal/bad/",
    ],
)
def test_proposed_branch_must_be_git_valid_proposal_namespace(branch: str) -> None:
    evidence = _validations()
    with pytest.raises(PermissionError, match="BRANCH_INVALID"):
        _builder(evidence).build(
            patch_receipt=_patch_receipt(),
            validations=evidence,
            proposed_branch=branch,
            commit_title="Improve bounded validation",
            pr_title="Improve bounded validation",
            summary="Evidence-bound proposal only.",
        )
