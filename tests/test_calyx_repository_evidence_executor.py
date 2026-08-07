from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.executor import GovernedAssignment
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.program_cycle import run_deterministic_program_cycle
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.calyx_orchestrator.program_repository import PersistentProgramRepository, ProgramJobSpec
from app.calyx_orchestrator.repository_evidence_executor import (
    EvidenceTarget,
    REPOSITORY_EVIDENCE_ROLE,
    RepositoryEvidenceExecutor,
)
from app.database import Base

REPOSITORY = "jsp1440/orchid-calyx-backend"


def _workspace(root: Path) -> None:
    (root / "AGENTS.md").write_text("governance\n", encoding="utf-8")
    (root / "requirements.txt").write_text("fastapi\n", encoding="utf-8")


def _assignment(*, mutating: bool = False, repository: str = REPOSITORY) -> GovernedAssignment:
    return GovernedAssignment(
        assignment_id="job-1",
        program_id="program-1",
        job_key="evidence",
        role_key=REPOSITORY_EVIDENCE_ROLE,
        objective="Capture repository control-file evidence",
        inputs={"job": {"repository": repository, "mutating_intent": mutating}},
        evidence_uris=("calyx:program/program-1",),
    )


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[CalyxProgram.__table__, CalyxProgramJob.__table__, CalyxProgramDependency.__table__],
    )
    return Session(engine)


def test_reader_returns_deterministic_hash_metadata_without_contents(tmp_path: Path):
    _workspace(tmp_path)
    executor = RepositoryEvidenceExecutor(workspace_root=tmp_path, repository_name=REPOSITORY)
    first = executor.execute(_assignment())
    second = executor.execute(_assignment())
    assert first.output_checksum == second.output_checksum
    assert first.output["contents_included"] is False
    assert first.output["side_effects"] == []
    files = first.output["files"]
    assert isinstance(files, list)
    assert [item["path"] for item in files] == ["AGENTS.md", "requirements.txt"]
    assert all(len(str(item["sha256"])) == 64 for item in files)
    assert all("content" not in item for item in files)
    assert first.executor_key == "repository_evidence_reader_v1"


def test_reader_rejects_mutation_repository_mismatch_and_path_escape(tmp_path: Path):
    _workspace(tmp_path)
    executor = RepositoryEvidenceExecutor(workspace_root=tmp_path, repository_name=REPOSITORY)
    with pytest.raises(PermissionError, match="REPOSITORY_EVIDENCE_MUTATION_PROHIBITED"):
        executor.execute(_assignment(mutating=True))
    with pytest.raises(PermissionError, match="REPOSITORY_EVIDENCE_REPOSITORY_MISMATCH"):
        executor.execute(_assignment(repository="other/repo"))

    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    escaping = RepositoryEvidenceExecutor(
        workspace_root=tmp_path,
        repository_name=REPOSITORY,
        targets=(EvidenceTarget("../outside.txt", required=True),),
    )
    with pytest.raises(PermissionError, match="REPOSITORY_EVIDENCE_PATH_ESCAPE"):
        escaping.execute(_assignment())


def test_reader_rejects_symlink_and_reports_missing_optional(tmp_path: Path):
    _workspace(tmp_path)
    outside = tmp_path.parent / "outside-agents.txt"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "AGENTS.md").unlink()
    (tmp_path / "AGENTS.md").symlink_to(outside)
    executor = RepositoryEvidenceExecutor(workspace_root=tmp_path, repository_name=REPOSITORY)
    with pytest.raises(PermissionError):
        executor.execute(_assignment())

    (tmp_path / "AGENTS.md").unlink()
    (tmp_path / "AGENTS.md").write_text("governance\n", encoding="utf-8")
    receipt = executor.execute(_assignment())
    assert "README.md" in receipt.output["missing_optional"]


def test_autonomous_cycle_completes_registered_repository_evidence_job(tmp_path: Path):
    _workspace(tmp_path)
    with _db() as db:
        repository = PersistentProgramRepository(db)
        program = repository.create_program(
            owner="owner",
            title="Repository evidence program",
            objective="Capture immutable repository control-file hashes.",
            jobs=[
                ProgramJobSpec(
                    "evidence",
                    REPOSITORY_EVIDENCE_ROLE,
                    "Capture repository evidence",
                    REPOSITORY,
                    "main",
                    False,
                )
            ],
            dependencies=[],
        )
        repository.start(owner="owner", program_id=program.program_id)
        registry = AuthoritativeExecutorRegistry(
            workspace_root=tmp_path,
            repository_name=REPOSITORY,
        )
        result = run_deterministic_program_cycle(
            db,
            owner="owner",
            worker_id="evidence-worker",
            registry=registry,
        )
        assert result.completed_jobs == 1
        assert result.jobs[0].executor_key == "repository_evidence_reader_v1"
        job = db.query(CalyxProgramJob).filter(CalyxProgramJob.program_id == program.program_id).one()
        assert job.status == "completed"
        assert job.outcome == "DELIVERED"
        assert job.evidence_json and "repository_evidence_reader_v1" in job.evidence_json
