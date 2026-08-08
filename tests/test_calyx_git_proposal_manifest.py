from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from app.calyx_orchestrator.executor import canonical_checksum
from app.calyx_orchestrator.git_proposal_manifest import GitProposalManifestBuilder
from app.calyx_orchestrator.sandbox_supervisor_evidence import ValidationRequestEnvelope

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


def _validation(preset: str, targets: list[dict[str, str]], *, outcome: str = "delivered") -> dict:
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
        "policy_digest": POLICY_HASH,
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


def test_manifest_is_deterministic_and_performs_no_git_mutation() -> None:
    builder = GitProposalManifestBuilder()
    manifest = builder.build(
        patch_receipt=_patch_receipt(),
        validations=_validations(),
        proposed_branch="autonomy/proposal/work-123",
        commit_title="Improve bounded validation",
        pr_title="Improve bounded validation",
        summary="Evidence-bound proposal only.",
    )
    repeat = builder.build(
        patch_receipt=_patch_receipt(),
        validations=list(reversed(_validations())),
        proposed_branch="autonomy/proposal/work-123",
        commit_title="Improve bounded validation",
        pr_title="Improve bounded validation",
        summary="Evidence-bound proposal only.",
    )

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
    with pytest.raises(PermissionError, match="PATCH_OUTPUT_CHECKSUM_MISMATCH"):
        GitProposalManifestBuilder().build(
            patch_receipt=receipt,
            validations=_validations(),
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
        GitProposalManifestBuilder().build(
            patch_receipt=_patch_receipt(),
            validations=validations,
            proposed_branch="autonomy/proposal/work-123",
            commit_title="Improve bounded validation",
            pr_title="Improve bounded validation",
            summary="Evidence-bound proposal only.",
        )


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
        GitProposalManifestBuilder().build(
            patch_receipt=_patch_receipt(),
            validations=[failed],
            proposed_branch="autonomy/proposal/work-123",
            commit_title="Improve bounded validation",
            pr_title="Improve bounded validation",
            summary="Evidence-bound proposal only.",
        )


def test_proposed_branch_is_proposal_only_namespace() -> None:
    with pytest.raises(PermissionError, match="BRANCH_INVALID"):
        GitProposalManifestBuilder().build(
            patch_receipt=_patch_receipt(),
            validations=_validations(),
            proposed_branch="main",
            commit_title="Improve bounded validation",
            pr_title="Improve bounded validation",
            summary="Evidence-bound proposal only.",
        )
