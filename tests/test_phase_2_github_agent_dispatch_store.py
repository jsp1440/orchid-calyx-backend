from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.github_agent_dispatch_store import (
    DurableGitHubAgentDispatchStore,
    GitHubAgentDispatchRecordRow,
)
from app.calyx_orchestrator.github_agent_lifecycle import (
    AgentLifecycleState,
    GitHubAgentDispatchRecord,
)


def make_store() -> tuple[Session, DurableGitHubAgentDispatchStore]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    GitHubAgentDispatchRecordRow.__table__.create(engine)
    session = Session(engine)
    return session, DurableGitHubAgentDispatchStore(session)


def record(**kwargs) -> GitHubAgentDispatchRecord:
    values = {
        "program_job_id": "job-1",
        "mission_id": "MISSION-1",
        "repository": "jsp1440/orchid-calyx-backend",
        "base_sha": "a" * 40,
        "provider": "github-copilot-cloud-agent",
        "issue_number": 1001,
    }
    values.update(kwargs)
    return GitHubAgentDispatchRecord(**values)


def test_first_dispatch_is_durable_and_idempotent() -> None:
    session, store = make_store()
    try:
        created = store.record(record())
        replay = store.record(record())
        assert replay == created
        assert store.get(program_job_id="job-1") == created
        assert session.query(GitHubAgentDispatchRecordRow).count() == 1
    finally:
        session.close()


def test_pr_identity_binds_once_and_cannot_change() -> None:
    session, store = make_store()
    try:
        store.record(record())
        with_pr = store.record(
            record(
                state=AgentLifecycleState.CI_PENDING,
                pull_request_number=1002,
                pull_request_url="https://github.com/jsp1440/orchid-calyx-backend/pull/1002",
                head_sha="b" * 40,
            )
        )
        assert with_pr.pull_request_number == 1002
        try:
            store.record(
                record(
                    state=AgentLifecycleState.CI_PENDING,
                    pull_request_number=1003,
                    head_sha="c" * 40,
                )
            )
        except PermissionError as exc:
            assert str(exc) == "GITHUB_AGENT_DISPATCH_DURABLE_PR_CHANGED"
        else:
            raise AssertionError("PR identity drift must fail closed")
    finally:
        session.close()


def test_repair_count_cannot_regress_or_jump() -> None:
    session, store = make_store()
    try:
        store.record(record(state=AgentLifecycleState.REPAIR_REQUIRED))
        store.record(
            record(
                state=AgentLifecycleState.CI_PENDING,
                repair_attempts=1,
                last_failure_class="ruff",
            )
        )
        for bad_count, expected in (
            (0, "GITHUB_AGENT_DISPATCH_REPAIR_COUNT_REGRESSED"),
            (3, "GITHUB_AGENT_DISPATCH_REPAIR_COUNT_JUMP"),
        ):
            try:
                store.record(
                    record(
                        state=AgentLifecycleState.CI_PENDING,
                        repair_attempts=bad_count,
                        last_failure_class="ruff",
                    )
                )
            except PermissionError as exc:
                assert str(exc) == expected
            else:
                raise AssertionError("repair counter invariant must fail closed")
    finally:
        session.close()


def test_branch_identity_round_trips_and_is_immutable() -> None:
    session, store = make_store()
    try:
        created = store.record(record(branch="agent/mission-001"))
        assert created.branch == "agent/mission-001"
        fetched = store.get(program_job_id="job-1")
        assert fetched is not None
        assert fetched.branch == "agent/mission-001"

        try:
            store.record(
                record(
                    state=AgentLifecycleState.AWAITING_PR,
                    branch="agent/a-different-branch",
                )
            )
        except PermissionError as exc:
            assert str(exc) == "GITHUB_AGENT_DISPATCH_DURABLE_IDENTITY_CHANGED"
        else:
            raise AssertionError("branch identity drift must fail closed")
    finally:
        session.close()


def test_branch_is_optional_and_defaults_to_none() -> None:
    session, store = make_store()
    try:
        created = store.record(record())
        assert created.branch is None
        fetched = store.get(program_job_id="job-1")
        assert fetched is not None
        assert fetched.branch is None
    finally:
        session.close()


def test_merged_record_is_immutable() -> None:
    session, store = make_store()
    try:
        merged = record(
            state=AgentLifecycleState.MERGED,
            pull_request_number=1002,
            pull_request_url="https://github.com/jsp1440/orchid-calyx-backend/pull/1002",
            head_sha="b" * 40,
        )
        store.record(merged)
        assert store.record(merged) == merged
        try:
            store.record(
                record(
                    state=AgentLifecycleState.MERGED,
                    pull_request_number=1002,
                    pull_request_url=merged.pull_request_url,
                    head_sha="c" * 40,
                )
            )
        except PermissionError as exc:
            assert str(exc) == "GITHUB_AGENT_DISPATCH_MERGED_IMMUTABLE"
        else:
            raise AssertionError("merged receipt must be immutable")
    finally:
        session.close()
