from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.portfolio import orchestration_portfolio
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.calyx_orchestrator.program_repository import PersistentProgramRepository, ProgramJobSpec
from app.database import Base


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[CalyxProgram.__table__, CalyxProgramJob.__table__, CalyxProgramDependency.__table__],
    )
    return Session(engine)


def _program(db: Session, *, owner: str = "owner") -> CalyxProgram:
    repository = PersistentProgramRepository(db)
    program = repository.create_program(
        owner=owner,
        title="Knowledge Graph integration",
        objective="Run a governed graph dry run and review the evidence.",
        jobs=[
            ProgramJobSpec("graph", "knowledge_graph_engineer", "Run graph", "backend", "graph", True),
            ProgramJobSpec("review", "brain_engineer", "Review evidence", "backend", "brain", False),
        ],
        dependencies=[("graph", "review")],
    )
    repository.start(owner=owner, program_id=program.program_id)
    return program


def test_portfolio_projects_authoritative_program_scheduler_and_governance_state():
    with _db() as db:
        program = _program(db)
        result = orchestration_portfolio(db, owner="owner")
        assert result["contract"] == "calyx-orchestration-portfolio-v1"
        assert result["summary"]["program_count"] == 1
        assert result["summary"]["job_count"] == 2
        assert result["summary"]["dependency_count"] == 1
        assert result["summary"]["job_status_counts"] == {"queued": 1, "waiting": 1}
        assert result["scheduler"]["runnable_program_job_ids"]
        assert result["programs"][0]["program_id"] == program.program_id
        assert result["governance"]["read_only"] is True
        assert result["governance"]["automatic_merge"] is False
        assert result["governance"]["production_knowledge_graph_mutation"] is False


def test_portfolio_filters_by_program_and_architecture_without_cross_owner_leakage():
    with _db() as db:
        program = _program(db)
        _program(db, owner="other")
        by_program = orchestration_portfolio(db, owner="owner", program_id=program.program_id)
        assert [item["program_id"] for item in by_program["programs"]] == [program.program_id]
        by_architecture = orchestration_portfolio(db, owner="owner", architecture="knowledge_graph")
        assert by_architecture["summary"]["program_count"] == 1
        assert by_architecture["summary"]["role_counts"]["knowledge_graph_engineer"] == 1
        empty = orchestration_portfolio(db, owner="owner", architecture="atlas")
        assert empty["summary"]["program_count"] == 0
        assert empty["summary"]["job_count"] == 0


def test_portfolio_exposes_blockers_receipts_and_exact_next_actions():
    with _db() as db:
        program = _program(db)
        repository = PersistentProgramRepository(db)
        repository.record_outcome(
            owner="owner",
            program_id=program.program_id,
            job_key="graph",
            outcome="BLOCKED",
            evidence={
                "receipt_type": "execution",
                "executor_key": "deterministic_dry_run_v1",
                "input_checksum": "a" * 64,
                "output_checksum": "b" * 64,
                "evidence_uris": ["github:run/1"],
            },
            blocker="GRAPH_PREFLIGHT_FAILED",
            human_action="Repair the graph preflight and create a governed retry.",
        )
        result = orchestration_portfolio(db, owner="owner")
        assert result["summary"]["blocked_jobs"] == 2
        assert result["execution"]["receipt_type_counts"] == {"execution": 1}
        assert result["execution"]["executor_counts"] == {"deterministic_dry_run_v1": 1}
        assert result["evidence"]["artifact_like_receipts"] == 1
        assert result["evidence"]["evidence_uri_count"] == 1
        assert "Repair the graph preflight and create a governed retry." in result["next_actions"]


def test_portfolio_program_filter_fails_closed_for_unknown_or_other_owner_program():
    with _db() as db:
        program = _program(db, owner="other")
        try:
            orchestration_portfolio(db, owner="owner", program_id=program.program_id)
        except LookupError as exc:
            assert str(exc) == "PROGRAM_NOT_FOUND"
        else:
            raise AssertionError("cross-owner program filter was accepted")


def test_portfolio_route_is_mounted():
    from app.main import app

    assert "/orchestrator/portfolio" in {route.path for route in app.routes}
