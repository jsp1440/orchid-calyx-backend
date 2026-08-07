from __future__ import annotations

import hashlib
import json
import subprocess
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
    PersistentProgramRepository,
    ProgramJobSpec,
)
from app.calyx_orchestrator.sandbox_authorization import SandboxAuthorization
from app.calyx_orchestrator.sandboxed_validation_executor import (
    SANDBOXED_VALIDATION_ROLE,
)
from app.calyx_orchestrator.static_validation_executor import STATIC_VALIDATION_ROLE
from app.database import Base

REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/patch-exec-validation"
COMMIT = "d" * 40
POLICY_DIGEST = "e" * 64


class TestSandboxSupervisor:
    def authorize(self, *, workspace_root, repository, branch, marker):
        assert workspace_root.is_dir()
        assert repository == REPOSITORY
        assert branch == BRANCH
        assert marker["repository_read_only_during_validation"] is True
        return SandboxAuthorization(
            authorization_id="integration-auth",
            evidence_uri="sandbox-supervisor:integration-auth",
            policy_digest=POLICY_DIGEST,
        )


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
    (root / ".git" / "refs" / "heads" / "autonomy" / "patch-exec-validation").write_text(
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
    (root / ".calyx-validation-sandbox.json").write_text(
        json.dumps(
            {
                "schema": "calyx-validation-sandbox-v1",
                "repository": REPOSITORY,
                "branch": BRANCH,
                "disposable": True,
                "network_disabled": True,
                "credentials_absent": True,
                "shell_disabled": True,
                "package_installation_disabled": True,
                "subprocess_confinement_enforced": True,
                "repository_read_only_during_validation": True,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return root


def _registry(root: Path) -> AuthoritativeExecutorRegistry:
    return AuthoritativeExecutorRegistry(
        workspace_root=root,
        repository_name=REPOSITORY,
        sandbox_validation_authorizer=TestSandboxSupervisor(),
    )


def test_program_cycle_patch_static_validate_then_run_fixed_pytest_preset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = _workspace(tmp_path)
    target = root / "tests" / "test_autonomous_example.py"
    before = b"def test_value():\n    assert 1 == 1\n"
    after = b"def test_value():\n    assert 2 == 2\n"
    target.write_bytes(before)
    observed: list[tuple[str, ...]] = []

    def fake_run(argv, **kwargs):
        observed.append(tuple(argv))
        assert kwargs["shell"] is False
        assert kwargs["cwd"] == root
        assert kwargs["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
        return subprocess.CompletedProcess(argv, 0, b"1 passed\n", b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with _db() as db:
        repository = PersistentProgramRepository(db)
        program = repository.create_program(
            owner="owner",
            title="Bounded autonomous executable-validation cycle",
            objective="Patch one isolated test, statically validate it, then run the fixed pytest preset.",
            jobs=(
                ProgramJobSpec(
                    "patch",
                    ISOLATED_PATCH_ROLE,
                    "Apply exact patch",
                    REPOSITORY,
                    BRANCH,
                    True,
                    {
                        "patches": [
                            {
                                "path": "tests/test_autonomous_example.py",
                                "before_sha256": _sha(before),
                                "content_utf8": after.decode("utf-8"),
                            }
                        ]
                    },
                ),
                ProgramJobSpec(
                    "static",
                    STATIC_VALIDATION_ROLE,
                    "Validate exact postimage and syntax",
                    REPOSITORY,
                    BRANCH,
                    False,
                    {
                        "files": [
                            {
                                "path": "tests/test_autonomous_example.py",
                                "sha256": _sha(after),
                            }
                        ]
                    },
                ),
                ProgramJobSpec(
                    "execute-tests",
                    SANDBOXED_VALIDATION_ROLE,
                    "Run bounded fixed pytest preset",
                    REPOSITORY,
                    BRANCH,
                    False,
                    {
                        "validation": {
                            "preset": "pytest",
                            "targets": ["tests/test_autonomous_example.py"],
                            "expected_sha256": {
                                "tests/test_autonomous_example.py": _sha(after)
                            },
                            "timeout_seconds": 30,
                        }
                    },
                ),
            ),
            dependencies=(("patch", "static"), ("static", "execute-tests")),
        )
        repository.start(owner="owner", program_id=program.program_id)

        result = run_deterministic_program_cycle(
            db,
            owner="owner",
            worker_id="autonomy-worker",
            max_jobs=6,
            registry=_registry(root),
        )

        assert result.stop_reason == "idle"
        assert result.completed_jobs == 3
        assert [item.job_key for item in result.jobs] == ["patch", "static", "execute-tests"]
        assert result.jobs[0].workspace_mutation is True
        assert result.jobs[1].repository_code_execution is False
        assert result.jobs[2].repository_code_execution is True
        assert result.as_dict()["repository_code_execution_performed"] is True
        assert result.as_dict()["automatic_merge"] is False
        assert result.as_dict()["automatic_deployment"] is False
        assert target.read_bytes() == after
        assert len(observed) == 1
        assert observed[0][1:6] == (
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
        )

        db.refresh(program)
        assert program.status == "completed"
        jobs = db.query(CalyxProgramJob).filter(
            CalyxProgramJob.program_id == program.program_id
        ).all()
        assert [job.outcome for job in sorted(jobs, key=lambda item: item.created_at)] == [
            "DELIVERED",
            "DELIVERED",
            "DELIVERED",
        ]


def test_failed_executable_validation_blocks_program(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = _workspace(tmp_path)
    target = root / "tests" / "test_autonomous_example.py"
    content = b"def test_value():\n    assert False\n"
    target.write_bytes(content)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1, b"failed\n", b""),
    )

    with _db() as db:
        repository = PersistentProgramRepository(db)
        program = repository.create_program(
            owner="owner",
            title="Fail closed executable validation",
            objective="A failed test must block the governed program.",
            jobs=(
                ProgramJobSpec(
                    "execute-tests",
                    SANDBOXED_VALIDATION_ROLE,
                    "Run bounded fixed pytest preset",
                    REPOSITORY,
                    BRANCH,
                    False,
                    {
                        "validation": {
                            "preset": "pytest",
                            "targets": ["tests/test_autonomous_example.py"],
                            "expected_sha256": {
                                "tests/test_autonomous_example.py": _sha(content)
                            },
                            "timeout_seconds": 30,
                        }
                    },
                ),
            ),
            dependencies=(),
        )
        repository.start(owner="owner", program_id=program.program_id)
        result = run_deterministic_program_cycle(
            db,
            owner="owner",
            worker_id="autonomy-worker",
            max_jobs=2,
            registry=_registry(root),
        )
        assert result.completed_jobs == 1
        assert result.jobs[0].outcome == "BLOCKED"
        db.refresh(program)
        assert program.status == "blocked"


def test_default_registry_will_not_claim_executable_validation_job(tmp_path: Path):
    root = _workspace(tmp_path)
    target = root / "tests" / "test_autonomous_example.py"
    content = b"def test_value():\n    assert True\n"
    target.write_bytes(content)

    with _db() as db:
        repository = PersistentProgramRepository(db)
        program = repository.create_program(
            owner="owner",
            title="No supervisor",
            objective="Executable validation must stay queued without a trusted supervisor.",
            jobs=(
                ProgramJobSpec(
                    "execute-tests",
                    SANDBOXED_VALIDATION_ROLE,
                    "Run bounded fixed pytest preset",
                    REPOSITORY,
                    BRANCH,
                    False,
                    {
                        "validation": {
                            "preset": "pytest",
                            "targets": ["tests/test_autonomous_example.py"],
                            "expected_sha256": {
                                "tests/test_autonomous_example.py": _sha(content)
                            },
                        }
                    },
                ),
            ),
            dependencies=(),
        )
        repository.start(owner="owner", program_id=program.program_id)
        result = run_deterministic_program_cycle(
            db,
            owner="owner",
            worker_id="autonomy-worker",
            max_jobs=2,
            registry=AuthoritativeExecutorRegistry(
                workspace_root=root,
                repository_name=REPOSITORY,
            ),
        )
        assert result.completed_jobs == 0
        assert result.stop_reason == "idle"
        job = db.query(CalyxProgramJob).filter(
            CalyxProgramJob.program_id == program.program_id
        ).one()
        assert job.status == "queued"
        assert job.attempt_count == 0
