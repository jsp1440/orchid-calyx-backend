from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.isolated_patch_executor import ISOLATED_PATCH_ROLE
from app.calyx_orchestrator.program_cycle import run_deterministic_program_cycle
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.calyx_orchestrator.program_repository import (
    MAX_JOB_INPUT_BYTES,
    PersistentProgramRepository,
    ProgramJobSpec,
)
from app.calyx_orchestrator.static_validation_executor import STATIC_VALIDATION_ROLE
from app.database import Base

REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/patch-validation-integration"
COMMIT = "c" * 40


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "worktree"
    (root / ".git" / "refs" / "heads" / "autonomy").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text(f"ref: refs/heads/{BRANCH}\n", encoding="ascii")
    (root / ".git" / "refs" / "heads" / "autonomy" / "patch-validation-integration").write_text(
        COMMIT + "\n",
        encoding="ascii",
    )
    (root / "app").mkdir()
    (root / "tests").mkdir()
    (root / "docs" / "brain").mkdir(parents=True)
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
    return root


def test_program_cycle_applies_patch_then_static_validates_result(tmp_path: Path):
    root = _workspace(tmp_path)
    target = root / "app" / "autonomous_example.py"
    before = b"VALUE = 1\n"
    after = b"VALUE = 2\n"
    target.write_bytes(before)

    with _db() as db:
        repository = PersistentProgramRepository(db)
        program = repository.create_program(
            owner="owner",
            title="Bounded autonomous patch validation",
            objective="Modify one isolated Python file and statically validate its exact result.",
            jobs=(
                ProgramJobSpec(
                    "patch",
                    ISOLATED_PATCH_ROLE,
                    "Apply exact preimage-bound patch",
                    REPOSITORY,
                    BRANCH,
                    True,
                    {
                        "patches": [
                            {
                                "path": "app/autonomous_example.py",
                                "before_sha256": _sha(before),
                                "content_utf8": after.decode("utf-8"),
                            }
                        ]
                    },
                ),
                ProgramJobSpec(
                    "validate",
                    STATIC_VALIDATION_ROLE,
                    "Validate exact post-patch hash and Python syntax",
                    REPOSITORY,
                    BRANCH,
                    False,
                    {
                        "files": [
                            {
                                "path": "app/autonomous_example.py",
                                "sha256": _sha(after),
                            }
                        ]
                    },
                ),
            ),
            dependencies=(("patch", "validate"),),
        )
        repository.start(owner="owner", program_id=program.program_id)

        registry = AuthoritativeExecutorRegistry(
            workspace_root=root,
            repository_name=REPOSITORY,
        )
        result = run_deterministic_program_cycle(
            db,
            owner="owner",
            worker_id="autonomous-integration-worker",
            max_jobs=4,
            registry=registry,
        )

        assert result.stop_reason == "idle"
        assert result.completed_jobs == 2
        assert [item.job_key for item in result.jobs] == ["patch", "validate"]
        assert result.jobs[0].workspace_mutation is True
        assert result.jobs[1].workspace_mutation is False
        assert all(item.repository_code_execution is False for item in result.jobs)
        assert target.read_bytes() == after
        summary = result.as_dict()
        assert summary["workspace_mutation_performed"] is True
        assert summary["repository_code_execution_performed"] is False
        assert summary["automatic_merge"] is False
        assert summary["automatic_deployment"] is False
        assert summary["automatic_publication"] is False

        db.refresh(program)
        assert program.status == "completed"
        jobs = db.query(CalyxProgramJob).filter(
            CalyxProgramJob.program_id == program.program_id
        ).all()
        assert all(job.status == "completed" for job in jobs)
        assert all(job.outcome == "DELIVERED" for job in jobs)
        assert all(job.input_json for job in jobs)


def test_program_snapshot_redacts_input_contents_but_binds_manifest_hash(tmp_path: Path):
    _workspace(tmp_path)
    secret_like_content = "not-a-secret-but-should-not-be-in-snapshot"
    with _db() as db:
        repository = PersistentProgramRepository(db)
        program = repository.create_program(
            owner="owner",
            title="Snapshot redaction",
            objective="Verify persisted job payload is not echoed in operator snapshots.",
            jobs=(
                ProgramJobSpec(
                    "patch",
                    ISOLATED_PATCH_ROLE,
                    "Patch",
                    REPOSITORY,
                    BRANCH,
                    True,
                    {"patches": [{"content_utf8": secret_like_content}]},
                ),
            ),
            dependencies=(),
        )
        snapshot = repository.snapshot(owner="owner", program_id=program.program_id)
        job = snapshot["jobs"][0]
        assert job["input_manifest_present"] is True
        assert len(job["input_manifest_sha256"]) == 64
        assert job["input_manifest_keys"] == ["patches"]
        assert secret_like_content not in json.dumps(snapshot)


def test_program_job_inputs_affect_fingerprint_and_are_bounded():
    base = ProgramJobSpec("job", "role", "Title", REPOSITORY, BRANCH, False, {"value": 1})
    changed = ProgramJobSpec("job", "role", "Title", REPOSITORY, BRANCH, False, {"value": 2})
    assert base.fingerprint != changed.fingerprint

    oversized = "x" * (MAX_JOB_INPUT_BYTES + 1)
    with pytest.raises(ValueError, match="INPUTS_TOO_LARGE"):
        _ = ProgramJobSpec(
            "job",
            "role",
            "Title",
            REPOSITORY,
            BRANCH,
            False,
            {"payload": oversized},
        ).serialized_inputs


def test_program_job_inputs_require_canonical_json_object():
    with pytest.raises(ValueError, match="NOT_CANONICAL_JSON"):
        _ = ProgramJobSpec(
            "job",
            "role",
            "Title",
            REPOSITORY,
            BRANCH,
            False,
            {"bad": {1, 2, 3}},
        ).serialized_inputs
