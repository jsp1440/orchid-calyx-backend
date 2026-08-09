from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.calyx_orchestrator.executor import canonical_checksum
from app.calyx_orchestrator.proposal_authorization import (
    ProposalAuthorizationBuilder,
    ProposalAuthorizationRegistry,
    ProposalDecision,
)
from app.calyx_orchestrator.sandbox_supervisor_evidence import canonical_sha256

REPOSITORY = "jsp1440/orchid-calyx-backend"
BASE_COMMIT = "a" * 40
PATCH_EXECUTOR = "isolated_workspace_patcher_v1"
PATCH_JOB_ID = "11111111-1111-1111-1111-111111111111"


def _patch_output() -> dict:
    return {
        "status": "delivered",
        "executed": True,
        "mode": "authoritative_isolated_workspace_patch",
        "repository": REPOSITORY,
        "branch": "autonomy/work-123",
        "checkout_commit_sha": BASE_COMMIT,
        "workspace_isolated": True,
        "workspace_disposable": True,
        "changes": [
            {
                "path": "app/example.py",
                "before_sha256": "b" * 64,
                "after_sha256": "c" * 64,
                "created": False,
                "size_bytes": 100,
            }
        ],
        "file_count": 1,
        "total_written_bytes": 100,
        "commit_created": False,
        "validation_commands_run": False,
        "side_effects": ["isolated_workspace_files_modified"],
    }


class _PersistedPatchService:
    def __init__(
        self,
        *,
        repository: str = REPOSITORY,
        branch: str = "autonomy/work-123",
        output: dict | None = None,
        executor_key: str = PATCH_EXECUTOR,
    ) -> None:
        value = _patch_output() if output is None else output
        self.record = SimpleNamespace(
            program_job_id=PATCH_JOB_ID,
            repository=repository,
            branch=branch,
            executor_key=executor_key,
            output_checksum=canonical_checksum(value),
            output=value,
        )

    def get_completed(self, *, program_job_id: str):
        if program_job_id != PATCH_JOB_ID:
            raise LookupError("PERSISTED_PATCH_EXECUTION_NOT_FOUND")
        return self.record


def _validations() -> list[dict]:
    return [
        {
            "preset": "ruff",
            "request_digest": "d" * 64,
            "receipt_digest": "e" * 64,
            "policy_digest": "f" * 64,
            "targets": [{"path": "app/example.py", "sha256": "c" * 64}],
        }
    ]


def _manifest(*, proposed_branch: str = "autonomy/proposal/work-123") -> dict:
    output = _patch_output()
    payload = {
        "schema": "calyx-git-proposal-manifest-v2",
        "patch_program_job_id": PATCH_JOB_ID,
        "repository": REPOSITORY,
        "base_commit_sha": BASE_COMMIT,
        "source_autonomy_branch": "autonomy/work-123",
        "proposed_branch": proposed_branch,
        "patch_output_checksum": canonical_checksum(output),
        "changes": [
            {
                "path": "app/example.py",
                "before_sha256": "b" * 64,
                "after_sha256": "c" * 64,
                "created": False,
                "size_bytes": 100,
            }
        ],
        "validations": _validations(),
        "commit_title": "Bounded change",
        "pr_title": "Bounded change",
        "summary": "Proposal evidence.",
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


def _build(
    *,
    manifest: dict | None = None,
    patch_service: _PersistedPatchService | None = None,
    requested_by: str = "principal:requester",
    review_class: str = "security",
    reviewer_id: str = "principal:security-reviewer",
    reviewer_roles: tuple[str, ...] = ("security",),
    decision: ProposalDecision = ProposalDecision.APPROVED,
):
    builder = ProposalAuthorizationBuilder(patch_service or _PersistedPatchService())
    return builder.build(
        manifest_snapshot=_manifest() if manifest is None else manifest,
        requested_by=requested_by,
        review_class=review_class,
        reviewer_id=reviewer_id,
        reviewer_roles=reviewer_roles,
        decision=decision,
        rationale="Reviewed exact proposal evidence.",
        evidence_uris=("review:ticket-123",),
        decided_at=datetime(2026, 8, 8, 22, 0, tzinfo=timezone.utc),
    )


def test_record_is_deterministic_and_grants_no_mutation_authority() -> None:
    first = _build()
    second = _build()
    assert first.authorization_digest == second.authorization_digest
    snapshot = first.snapshot()
    assert snapshot["decision"] == "approved"
    assert snapshot["patch_program_job_id"] == PATCH_JOB_ID
    assert snapshot["producer_id"] == f"executor:{PATCH_EXECUTOR}"
    assert snapshot["git_mutation_authorized"] is False
    assert snapshot["commit_authorized"] is False
    assert snapshot["push_authorized"] is False
    assert snapshot["pull_request_creation_authorized"] is False
    assert snapshot["automatic_merge_authorized"] is False
    assert snapshot["deployment_authorized"] is False
    assert snapshot["publication_authorized"] is False
    assert snapshot["taxonomy_activation_authorized"] is False
    assert snapshot["production_database_mutation_authorized"] is False
    assert snapshot["production_graph_mutation_authorized"] is False


def test_manifest_digest_tampering_is_rejected() -> None:
    manifest = _manifest()
    manifest["summary"] = "tampered"
    with pytest.raises(PermissionError, match="MANIFEST_DIGEST_MISMATCH"):
        _build(manifest=manifest)


def test_hand_built_manifest_without_validation_evidence_is_rejected() -> None:
    manifest = _manifest()
    manifest["validations"] = []
    payload = dict(manifest)
    payload.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_sha256(payload)
    with pytest.raises(PermissionError, match="VALIDATION_REQUIRED"):
        _build(manifest=manifest)


def test_manifest_with_uncovered_python_change_is_rejected() -> None:
    manifest = _manifest()
    manifest["validations"][0]["targets"] = [
        {"path": "app/other.py", "sha256": "c" * 64}
    ]
    payload = dict(manifest)
    payload.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_sha256(payload)
    with pytest.raises(PermissionError, match="RUFF_COVERAGE_INCOMPLETE"):
        _build(manifest=manifest)


def test_noncanonical_manifest_authority_flag_is_rejected() -> None:
    manifest = _manifest()
    manifest["git_mutation_performed"] = True
    payload = dict(manifest)
    payload.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_sha256(payload)
    with pytest.raises(PermissionError, match="NONCANONICAL_MANIFEST"):
        _build(manifest=manifest)


def test_persisted_patch_checksum_must_match_manifest() -> None:
    output = _patch_output()
    output["total_written_bytes"] = 101
    with pytest.raises(PermissionError, match="PERSISTED_PATCH_MISMATCH"):
        _build(patch_service=_PersistedPatchService(output=output))


def test_persisted_patch_identity_must_match_manifest() -> None:
    service = _PersistedPatchService(repository="other/repository")
    with pytest.raises(PermissionError, match="PERSISTED_PATCH_MISMATCH"):
        _build(patch_service=service)


def test_manifest_patch_job_id_must_resolve_persisted_execution() -> None:
    manifest = _manifest()
    manifest["patch_program_job_id"] = "22222222-2222-2222-2222-222222222222"
    payload = dict(manifest)
    payload.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_sha256(payload)
    with pytest.raises(PermissionError, match="PERSISTED_PATCH_REQUIRED"):
        _build(manifest=manifest)


def test_reviewer_cannot_self_approve_requester() -> None:
    with pytest.raises(PermissionError, match="SELF_APPROVAL_PROHIBITED"):
        _build(
            requested_by="principal:security-reviewer",
            reviewer_id="principal:security-reviewer",
        )


def test_reviewer_cannot_self_approve_patch_producer() -> None:
    with pytest.raises(PermissionError, match="SELF_APPROVAL_PROHIBITED"):
        _build(reviewer_id=f"executor:{PATCH_EXECUTOR}")


def test_reviewer_must_hold_requested_review_role() -> None:
    with pytest.raises(PermissionError, match="REVIEWER_ROLE_REQUIRED"):
        _build(reviewer_roles=("operational",))


def test_old_record_does_not_authorize_changed_manifest_digest() -> None:
    record = _build()
    changed = _manifest(proposed_branch="autonomy/proposal/work-124")
    with pytest.raises(PermissionError, match="STALE_MANIFEST"):
        record.verify_for_manifest(changed)


def test_rejection_is_immutable_for_manifest_and_review_class() -> None:
    registry = ProposalAuthorizationRegistry()
    rejected = _build(decision=ProposalDecision.REJECTED)
    registry.record(rejected)
    approved = _build(decision=ProposalDecision.APPROVED)
    with pytest.raises(ValueError, match="AUTHORITATIVE_DECISION_ALREADY_RECORDED"):
        registry.record(approved)
    assert (
        registry.require(
            manifest_digest=rejected.manifest_digest,
            review_class=rejected.review_class,
        ).decision
        == ProposalDecision.REJECTED
    )


def test_review_class_is_limited_to_governed_repository_classes() -> None:
    with pytest.raises(PermissionError, match="REVIEW_CLASS_NOT_ALLOWED"):
        _build(review_class="scientific", reviewer_roles=("scientific",))


def test_evidence_and_timezone_are_required() -> None:
    builder = ProposalAuthorizationBuilder(_PersistedPatchService())
    with pytest.raises(ValueError, match="EVIDENCE_INVALID"):
        builder.build(
            manifest_snapshot=_manifest(),
            requested_by="principal:requester",
            review_class="security",
            reviewer_id="principal:security-reviewer",
            reviewer_roles=("security",),
            decision="approved",
            rationale="Reviewed exact proposal evidence.",
            evidence_uris=(),
            decided_at=datetime(2026, 8, 8, 22, 0, tzinfo=timezone.utc),
        )
    with pytest.raises(ValueError, match="TIMEZONE_REQUIRED"):
        builder.build(
            manifest_snapshot=_manifest(),
            requested_by="principal:requester",
            review_class="security",
            reviewer_id="principal:security-reviewer",
            reviewer_roles=("security",),
            decision="approved",
            rationale="Reviewed exact proposal evidence.",
            evidence_uris=("review:ticket-123",),
            decided_at=datetime.fromisoformat("2026-08-08T22:00:00"),
        )
