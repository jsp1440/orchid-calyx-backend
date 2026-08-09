from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.assignment_factory import governed_assignment_from_claimed_job
from app.calyx_orchestrator.engineering_core import TerminalOutcome
from app.calyx_orchestrator.execution_bridge import LeaseExecutionBridge
from app.calyx_orchestrator.executor import (
    ExecutionReceipt,
    ExecutionState,
    canonical_checksum,
)
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.isolated_patch_executor import (
    ISOLATED_PATCH_ROLE,
    IsolatedWorkspacePatchExecutor,
)
from app.calyx_orchestrator.persisted_patch_execution import (
    PersistedPatchExecutionService,
)
from app.calyx_orchestrator.program_cycle import run_deterministic_program_cycle
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.calyx_orchestrator.program_repository import (
    PersistentProgramRepository,
    ProgramJobSpec,
)
from app.calyx_orchestrator.program_worker import PersistentProgramWorker
from app.database import Base

REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/work-123"
COMMIT = "a" * 40
PATCH_CONTENT = "print('bounded change')\n"
PATCH_BYTES = PATCH_CONTENT.encode("utf-8")
PATCH_AFTER = hashlib.sha256(PATCH_BYTES).hexdigest()
PATCH_BEFORE = "b" * 64


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CalyxProgram.__table__,
            CalyxProgramJob.__table__,
            CalyxProgramDependency.__table__,
        ],
    )
    return Session(engine)


def _patch_inputs(*, before_sha256: str = PATCH_BEFORE) -> dict[str, object]:
    return {
        "patches": [
            {
                "path": "app/example.py",
                "before_sha256": before_sha256,
                "content_utf8": PATCH_CONTENT,
            }
        ]
    }


def _output(*, repository: str = REPOSITORY, branch: str = BRANCH) -> dict[str, object]:
    return {
        "status": "delivered",
        "executed": True,
        "mode": "authoritative_isolated_workspace_patch",
        "repository": repository,
        "branch": branch,
        "checkout_commit_sha": COMMIT,
        "workspace_isolated": True,
        "workspace_disposable": True,
        "changes": [
            {
                "path": "app/example.py",
                "before_sha256": PATCH_BEFORE,
                "after_sha256": PATCH_AFTER,
                "created": False,
                "size_bytes": len(PATCH_BYTES),
            }
        ],
        "file_count": 1,
        "total_written_bytes": len(PATCH_BYTES),
        "commit_created": False,
        "validation_commands_run": False,
        "side_effects": ["isolated_workspace_files_modified"],
    }


def _completed_job(
    db: Session,
    *,
    role_key: str = ISOLATED_PATCH_ROLE,
    executor_key: str = IsolatedWorkspacePatchExecutor.executor_key,
    job_repository: str = REPOSITORY,
    job_branch: str = BRANCH,
    output_repository: str = REPOSITORY,
    output_branch: str = BRANCH,
) -> CalyxProgramJob:
    repository = PersistentProgramRepository(db)
    program = repository.create_program(
        owner="owner",
        title="persisted patch",
        objective="persist authoritative patch evidence",
        jobs=[
            ProgramJobSpec(
                "patch",
                role_key,
                "patch",
                job_repository,
                job_branch,
                True,
                inputs=_patch_inputs(),
            )
        ],
        dependencies=[],
    )
    repository.start(owner="owner", program_id=program.program_id)
    claimed = PersistentProgramWorker(db).claim(worker_id="worker")
    assert claimed is not None and claimed.lease_token
    assignment = governed_assignment_from_claimed_job(
        db,
        owner="owner",
        job=claimed,
    )
    output = _output(repository=output_repository, branch=output_branch)
    receipt = ExecutionReceipt(
        assignment_id=claimed.program_job_id,
        program_id=program.program_id,
        job_key=claimed.job_key,
        executor_key=executor_key,
        state=ExecutionState.DELIVERED,
        outcome=TerminalOutcome.DELIVERED,
        input_checksum=assignment.verified_input_checksum(),
        output_checksum=canonical_checksum(output),
        output=output,
        evidence_uris=("github:issue/692",),
    )
    return LeaseExecutionBridge(db).complete_from_receipt(
        program_job_id=claimed.program_job_id,
        worker_id="worker",
        lease_token=claimed.lease_token,
        receipt=receipt,
    )


def _workspace(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "worktree"
    (root / ".git" / "refs" / "heads" / "autonomy").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text(
        f"ref: refs/heads/{BRANCH}\n", encoding="ascii"
    )
    (root / ".git" / "refs" / "heads" / "autonomy" / "work-123").write_text(
        COMMIT + "\n", encoding="ascii"
    )
    (root / "app").mkdir()
    before = "print('before')\n"
    (root / "app" / "example.py").write_text(before, encoding="utf-8")
    (root / ".calyx-isolated-workspace.json").write_text(
        json.dumps(
            {
                "schema": "calyx-isolated-workspace-v1",
                "repository": REPOSITORY,
                "branch": BRANCH,
                "disposable": True,
                "workspace_write_authorized": True,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return root, hashlib.sha256(before.encode("utf-8")).hexdigest()


def test_resolves_real_persisted_isolated_patch_execution() -> None:
    with _db() as db:
        completed = _completed_job(db)
        resolved = PersistedPatchExecutionService(db).get_completed(
            program_job_id=completed.program_job_id
        )
        assert resolved.program_job_id == completed.program_job_id
        assert resolved.repository == REPOSITORY
        assert resolved.branch == BRANCH
        assert resolved.executor_key == IsolatedWorkspacePatchExecutor.executor_key
        assert len(resolved.input_checksum) == 64
        assert resolved.output_checksum == canonical_checksum(_output())
        assert resolved.output["checkout_commit_sha"] == COMMIT


def test_real_program_cycle_can_execute_and_persist_isolated_patch(
    tmp_path: Path,
) -> None:
    root, before_sha = _workspace(tmp_path)
    with _db() as db:
        repository = PersistentProgramRepository(db)
        program = repository.create_program(
            owner="owner",
            title="real isolated patch cycle",
            objective="prove assignment capability to persisted receipt integration",
            jobs=[
                ProgramJobSpec(
                    "patch",
                    ISOLATED_PATCH_ROLE,
                    "bounded isolated patch",
                    REPOSITORY,
                    BRANCH,
                    True,
                    inputs=_patch_inputs(before_sha256=before_sha),
                )
            ],
            dependencies=[],
        )
        repository.start(owner="owner", program_id=program.program_id)
        registry = AuthoritativeExecutorRegistry(
            workspace_root=root,
            repository_name=REPOSITORY,
        )
        result = run_deterministic_program_cycle(
            db,
            owner="owner",
            worker_id="worker",
            max_jobs=1,
            registry=registry,
        )
        assert result.completed_jobs == 1
        assert result.jobs[0].executor_key == IsolatedWorkspacePatchExecutor.executor_key
        assert result.jobs[0].workspace_mutation is True
        assert (root / "app" / "example.py").read_text(encoding="utf-8") == PATCH_CONTENT

        completed = db.query(CalyxProgramJob).filter_by(program_id=program.program_id).one()
        resolved = PersistedPatchExecutionService(db).get_completed(
            program_job_id=completed.program_job_id
        )
        assert resolved.output["changes"][0]["after_sha256"] == PATCH_AFTER
        evidence = json.loads(completed.evidence_json or "{}")
        assert evidence["input_checksum"] == resolved.input_checksum


def test_isolated_patch_assignment_gets_workspace_write_only_for_patch_role() -> None:
    with _db() as db:
        repository = PersistentProgramRepository(db)
        patch_program = repository.create_program(
            owner="owner",
            title="patch",
            objective="patch",
            jobs=[
                ProgramJobSpec(
                    "patch",
                    ISOLATED_PATCH_ROLE,
                    "patch",
                    REPOSITORY,
                    BRANCH,
                    True,
                    inputs=_patch_inputs(),
                )
            ],
            dependencies=[],
        )
        repository.start(owner="owner", program_id=patch_program.program_id)
        patch_job = PersistentProgramWorker(db).claim(worker_id="worker")
        assert patch_job is not None
        patch_assignment = governed_assignment_from_claimed_job(
            db, owner="owner", job=patch_job
        )
        assert "workspace_write" in patch_assignment.requested_capabilities
        assert patch_assignment.inputs["governance"]["mode"] == (
            "bounded_isolated_workspace_mutation"
        )


def test_missing_or_wrong_role_patch_job_is_rejected() -> None:
    with _db() as db:
        service = PersistedPatchExecutionService(db)
        with pytest.raises(LookupError, match="PATCH_PROGRAM_JOB_NOT_FOUND"):
            service.get_completed(program_job_id="missing")
        completed = _completed_job(db, role_key="brain_engineer")
        with pytest.raises(PermissionError, match="PATCH_PROGRAM_JOB_ROLE_INVALID"):
            service.get_completed(program_job_id=completed.program_job_id)


def test_wrong_executor_identity_is_rejected() -> None:
    with _db() as db:
        completed = _completed_job(db, executor_key="caller_fabricated_executor")
        with pytest.raises(PermissionError, match="PATCH_PROGRAM_JOB_EXECUTOR_INVALID"):
            PersistedPatchExecutionService(db).get_completed(
                program_job_id=completed.program_job_id
            )


def test_repository_or_branch_mismatch_is_rejected() -> None:
    with _db() as db:
        completed = _completed_job(db, output_repository="other/repository")
        with pytest.raises(PermissionError, match="PATCH_PROGRAM_JOB_IDENTITY_MISMATCH"):
            PersistedPatchExecutionService(db).get_completed(
                program_job_id=completed.program_job_id
            )


def test_tampered_persisted_output_is_rejected() -> None:
    with _db() as db:
        completed = _completed_job(db)
        evidence = json.loads(completed.evidence_json or "{}")
        evidence["output"]["total_written_bytes"] = len(PATCH_BYTES) + 1
        completed.evidence_json = json.dumps(evidence, sort_keys=True)
        db.commit()
        with pytest.raises(
            PermissionError, match="PATCH_PROGRAM_JOB_OUTPUT_CHECKSUM_MISMATCH"
        ):
            PersistedPatchExecutionService(db).get_completed(
                program_job_id=completed.program_job_id
            )


def test_coherently_rehashed_output_still_must_match_governed_patch_inputs() -> None:
    with _db() as db:
        completed = _completed_job(db)
        evidence = json.loads(completed.evidence_json or "{}")
        evidence["output"]["changes"][0]["after_sha256"] = "d" * 64
        evidence["output_checksum"] = canonical_checksum(evidence["output"])
        completed.evidence_json = json.dumps(evidence, sort_keys=True)
        db.commit()
        with pytest.raises(
            PermissionError, match="PATCH_PROGRAM_JOB_INPUT_OUTPUT_MISMATCH"
        ):
            PersistedPatchExecutionService(db).get_completed(
                program_job_id=completed.program_job_id
            )


def test_persisted_receipt_identity_must_match_program_job_row() -> None:
    with _db() as db:
        completed = _completed_job(db)
        evidence = json.loads(completed.evidence_json or "{}")
        evidence["assignment_id"] = "other-job"
        completed.evidence_json = json.dumps(evidence, sort_keys=True)
        db.commit()
        with pytest.raises(
            PermissionError, match="PATCH_PROGRAM_JOB_RECEIPT_IDENTITY_MISMATCH"
        ):
            PersistedPatchExecutionService(db).get_completed(
                program_job_id=completed.program_job_id
            )


def test_persisted_input_checksum_must_be_canonical_sha256() -> None:
    with _db() as db:
        completed = _completed_job(db)
        evidence = json.loads(completed.evidence_json or "{}")
        evidence["input_checksum"] = "not-a-checksum"
        completed.evidence_json = json.dumps(evidence, sort_keys=True)
        db.commit()
        with pytest.raises(ValueError, match="PATCH_PROGRAM_JOB_INPUT_CHECKSUM_INVALID"):
            PersistedPatchExecutionService(db).get_completed(
                program_job_id=completed.program_job_id
            )


def test_valid_shape_but_wrong_input_checksum_is_rejected() -> None:
    with _db() as db:
        completed = _completed_job(db)
        evidence = json.loads(completed.evidence_json or "{}")
        evidence["input_checksum"] = "0" * 64
        completed.evidence_json = json.dumps(evidence, sort_keys=True)
        db.commit()
        with pytest.raises(
            PermissionError, match="PATCH_PROGRAM_JOB_INPUT_CHECKSUM_MISMATCH"
        ):
            PersistedPatchExecutionService(db).get_completed(
                program_job_id=completed.program_job_id
            )
