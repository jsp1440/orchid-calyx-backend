from __future__ import annotations

import pytest

from app.calyx_orchestrator.engineering_core import TerminalOutcome
from app.calyx_orchestrator.program_core import (
    EngineeringProgram,
    ProgramJobSpec,
    ProgramJobStatus,
    ProgramStatus,
)


def _six_job_program() -> EngineeringProgram:
    prerequisite_keys = (
        "ci-repair-audit",
        "backend-api-verification",
        "frontend-live-data-plan",
        "graph-staging-proof",
        "brain-ledger-mission",
    )
    jobs = [
        ProgramJobSpec(
            job_key="ci-repair-audit",
            role_key="build_devops_engineer",
            title="CI repair audit",
            repository="jsp1440/orchid-calyx-backend",
        ),
        ProgramJobSpec(
            job_key="backend-api-verification",
            role_key="backend_engineer",
            title="Protected backend API verification",
            repository="jsp1440/orchid-calyx-backend",
        ),
        ProgramJobSpec(
            job_key="frontend-live-data-plan",
            role_key="frontend_engineer",
            title="Frontend live-data presentation repair plan",
            repository="jsp1440/orchid-continuum-frontend",
        ),
        ProgramJobSpec(
            job_key="graph-staging-proof",
            role_key="knowledge_graph_engineer",
            title="Bounded graph staging-readiness proof",
            repository="jsp1440/orchid-calyx-backend",
        ),
        ProgramJobSpec(
            job_key="brain-ledger-mission",
            role_key="brain_engineer",
            title="Fixture-backed Brain retrieval-to-ledger mission",
            repository="jsp1440/orchid-calyx-backend",
        ),
        ProgramJobSpec(
            job_key="director-report",
            role_key="engineering_director",
            title="Consolidated Engineering Director report",
            repository="jsp1440/orchid-calyx-backend",
            depends_on=prerequisite_keys,
        ),
    ]
    return EngineeringProgram.create(
        program_id="program-1",
        owner="owner@example.org",
        title="Phase 1 demonstration",
        jobs=jobs,
    )


def test_program_starts_five_jobs_and_holds_director_report() -> None:
    program = _six_job_program()
    program.start()

    assert program.status == ProgramStatus.RUNNING
    ready = {
        key for key, state in program.jobs.items() if state.status == ProgramJobStatus.READY
    }
    assert ready == {
        "ci-repair-audit",
        "backend-api-verification",
        "frontend-live-data-plan",
        "graph-staging-proof",
        "brain-ledger-mission",
    }
    assert program.jobs["director-report"].status == ProgramJobStatus.WAITING


def test_director_report_releases_only_after_all_prerequisites_complete() -> None:
    program = _six_job_program()
    program.start()
    prerequisite_keys = [
        key for key in program.jobs if key != "director-report"
    ]

    for key in prerequisite_keys[:-1]:
        released = program.complete_job(key, outcome=TerminalOutcome.DELIVERED)
        assert released == ()
        assert program.jobs["director-report"].status == ProgramJobStatus.WAITING

    released = program.complete_job(
        prerequisite_keys[-1], outcome=TerminalOutcome.NO_OP
    )
    assert released == ("director-report",)
    assert program.jobs["director-report"].status == ProgramJobStatus.READY


def test_failed_prerequisite_blocks_downstream_without_execution() -> None:
    program = _six_job_program()
    program.start()

    program.complete_job("ci-repair-audit", outcome=TerminalOutcome.BLOCKED)

    assert program.jobs["director-report"].status == ProgramJobStatus.TERMINAL
    assert program.jobs["director-report"].outcome == TerminalOutcome.BLOCKED
    assert program.jobs["director-report"].evidence == (
        "PREREQUISITE_NOT_SUCCESSFUL",
    )


def test_program_completes_after_director_report() -> None:
    program = _six_job_program()
    program.start()
    for key in program.jobs:
        if key != "director-report":
            program.complete_job(key, outcome=TerminalOutcome.DELIVERED)
    program.complete_job("director-report", outcome=TerminalOutcome.DELIVERED)

    assert program.status == ProgramStatus.COMPLETED


def test_cycle_and_unknown_dependency_are_rejected() -> None:
    with pytest.raises(ValueError, match="CYCLIC_PROGRAM_DEPENDENCY"):
        EngineeringProgram.create(
            program_id="cyclic",
            owner="owner",
            title="cyclic",
            jobs=[
                ProgramJobSpec(
                    job_key="a",
                    role_key="backend_engineer",
                    title="a",
                    repository="repo",
                    depends_on=("b",),
                ),
                ProgramJobSpec(
                    job_key="b",
                    role_key="frontend_engineer",
                    title="b",
                    repository="repo",
                    depends_on=("a",),
                ),
            ],
        )

    with pytest.raises(ValueError, match="UNKNOWN_DEPENDENCY:missing"):
        EngineeringProgram.create(
            program_id="missing",
            owner="owner",
            title="missing",
            jobs=[
                ProgramJobSpec(
                    job_key="a",
                    role_key="backend_engineer",
                    title="a",
                    repository="repo",
                    depends_on=("missing",),
                )
            ],
        )


def test_duplicate_terminal_completion_is_rejected() -> None:
    program = _six_job_program()
    program.start()
    program.complete_job("ci-repair-audit", outcome=TerminalOutcome.DELIVERED)

    with pytest.raises(ValueError, match="PROGRAM_JOB_NOT_COMPLETABLE"):
        program.complete_job("ci-repair-audit", outcome=TerminalOutcome.DELIVERED)


def test_pause_resume_and_cancel_are_explicit() -> None:
    program = _six_job_program()
    program.start()
    program.pause()
    assert program.status == ProgramStatus.PAUSED

    program.start()
    program.cancel()
    assert program.status == ProgramStatus.CANCELLED
    assert program.jobs["director-report"].status == ProgramJobStatus.CANCELLED
