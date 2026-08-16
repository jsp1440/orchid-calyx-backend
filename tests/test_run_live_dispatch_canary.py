"""Tests for scripts/run_live_dispatch_canary.py - the driver the
live-dispatch-canary GitHub Actions workflow runs. Exercises the real
enqueue/preflight/execute chain against a real local Postgres database
(created and dropped by this test, never a persistent or production one)
with the GitHub transport faked - the same evidence tier established by
test_github_agent_zero_credential_live_shape_proof.py.

Requires a local PostgreSQL reachable at localhost:5432 with a postgres/
postgres superuser - the same instance every other canonical test in this
repository already assumes.
"""
from __future__ import annotations

import subprocess
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.calyx_orchestrator.github_proposal_mutation_adapter import (
    GitHubTransportResponse,
)
from app.database import Base
from scripts import run_live_dispatch_canary as canary


def _create_throwaway_database() -> str:
    name = f"calyx_canary_test_{uuid.uuid4().hex[:12]}"
    subprocess.run(
        ["psql", "postgresql://postgres:postgres@localhost:5432/postgres", "-c", f"CREATE DATABASE {name};"],
        check=True,
        capture_output=True,
    )
    return f"postgresql://postgres:postgres@localhost:5432/{name}"


def _drop_database(database_url: str) -> None:
    name = database_url.rsplit("/", 1)[-1]
    subprocess.run(
        ["psql", "postgresql://postgres:postgres@localhost:5432/postgres", "-c", f"DROP DATABASE IF EXISTS {name};"],
        check=False,
        capture_output=True,
    )


@pytest.fixture()
def throwaway_database_url():
    url = _create_throwaway_database()
    yield url
    _drop_database(url)


@pytest.fixture()
def prepared_engine(throwaway_database_url):
    for migration in canary.MIGRATIONS:
        sql = migration.read_text(encoding="utf-8")
        engine = create_engine(throwaway_database_url)
        with engine.begin() as conn:
            conn.execute(text(sql))
        engine.dispose()
    engine = create_engine(throwaway_database_url)
    # This throwaway database only needs the default ("public") schema
    # tables the orchestrator itself uses - not the handful of unrelated
    # business-domain tables mapped onto their own dedicated Postgres
    # schemas (e.g. research_station.*), which would each need their own
    # CREATE SCHEMA step this test has no reason to replicate.
    public_schema_tables = [table for table in Base.metadata.sorted_tables if table.schema is None]
    Base.metadata.create_all(engine, tables=public_schema_tables, checkfirst=True)
    yield engine
    engine.dispose()


def test_enqueue_mission_selects_exactly_one_candidate_and_is_idempotent(prepared_engine) -> None:
    with Session(prepared_engine) as db:
        first_id = canary._enqueue_mission(db)
        second_id = canary._enqueue_mission(db)
    assert first_id == second_id  # re-running enqueue within one run never creates a duplicate candidate

    with Session(prepared_engine) as db:
        from app.calyx_orchestrator.program_models import CalyxProgramJob

        rows = db.query(CalyxProgramJob).filter(CalyxProgramJob.job_key == canary.JOB_KEY).all()
    assert len(rows) == 1
    assert rows[0].repository == canary.REPOSITORY
    assert rows[0].branch == canary.BRANCH
    assert rows[0].role_key == "github_coding_agent"


def test_dry_run_preflight_never_touches_the_network(prepared_engine) -> None:
    from app.calyx_orchestrator.github_agent_ci_policy import RequiredCiCheckPolicy
    from app.calyx_orchestrator.github_agent_composition import (
        build_production_github_coding_agent_dispatch_cycle,
    )
    from app.calyx_orchestrator.github_agent_dispatch_cycle import (
        GitHubCodingRuntimePolicy,
    )
    from app.calyx_orchestrator.github_coding_executor import BudgetClass

    with Session(prepared_engine) as db:
        canary._enqueue_mission(db)

        cycle = build_production_github_coding_agent_dispatch_cycle(
            db=db,
            transport=canary._NeverCalledTransport(),
            policy=GitHubCodingRuntimePolicy(
                enabled=True,
                owner_allowlist=frozenset({canary.OWNER}),
                repository_allowlist=frozenset({canary.REPOSITORY}),
                max_budget_class=BudgetClass.TINY,
            ),
            required_checks=RequiredCiCheckPolicy(required_checks=frozenset({canary.REQUIRED_CHECK_NAME})),
        )
        # execute=False against a transport that raises on any call - if
        # this path ever touched the network, the test would fail here,
        # not merely assert something about it afterward.
        result = cycle.run_once(owner=canary.OWNER, execute=False, confirmation="")

    assert result.state == "preflight_ready"


def test_main_refuses_execute_without_exact_confirmation_before_any_migration(
    monkeypatch: pytest.MonkeyPatch, throwaway_database_url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", throwaway_database_url)
    monkeypatch.setenv("CALYX_LIVE_DISPATCH_EXECUTE", "true")
    monkeypatch.setenv("CALYX_LIVE_DISPATCH_CONFIRMATION", "wrong-confirmation-value")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("must refuse before ever applying a migration")

    monkeypatch.setattr(canary, "_apply_migrations", fail_if_called)

    assert canary.main() == 1


def test_main_execute_refuses_without_coding_agent_credential(
    monkeypatch: pytest.MonkeyPatch, prepared_engine, throwaway_database_url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", throwaway_database_url)
    monkeypatch.setenv("CALYX_LIVE_DISPATCH_EXECUTE", "true")
    monkeypatch.setenv("CALYX_LIVE_DISPATCH_CONFIRMATION", canary.EXECUTE_CONFIRMATION)
    monkeypatch.delenv("CALYX_GITHUB_CODING_AGENT_TOKEN", raising=False)
    # Even a broad/generic token present must not be picked up as a
    # substitute credential by the real load_coding_agent_transport().
    monkeypatch.setenv("GITHUB_TOKEN", "should-never-be-used-for-this-path")
    monkeypatch.setattr(canary, "_apply_migrations", lambda database_url: None)

    assert canary.main() == 1


def test_main_execute_runs_the_real_dispatch_against_a_fake_transport_only(
    monkeypatch: pytest.MonkeyPatch, prepared_engine, throwaway_database_url: str, capsys
) -> None:
    """Proves the full driver path - enqueue, credential load (faked),
    execute_one_shot_mission, real convergence-inspection call sequence -
    reaches a live dispatch shape with zero real network access. Mirrors
    the fake-transport response sequence already established in
    test_github_agent_one_shot_operator.py's happy path."""
    from dataclasses import dataclass, field

    @dataclass
    class FakeTransport:
        responses: list
        calls: list = field(default_factory=list)

        def request(self, method, path, *, json_body=None, params=None):
            self.calls.append((method, path))
            return self.responses.pop(0)

    fake_transport = FakeTransport(
        [
            GitHubTransportResponse(200, {"object": {"sha": "a" * 40}}),
            GitHubTransportResponse(200, []),
            GitHubTransportResponse(200, []),
            GitHubTransportResponse(201, {"number": 9001}),
        ]
    )

    monkeypatch.setenv("DATABASE_URL", throwaway_database_url)
    monkeypatch.setenv("CALYX_LIVE_DISPATCH_EXECUTE", "true")
    monkeypatch.setenv("CALYX_LIVE_DISPATCH_CONFIRMATION", canary.EXECUTE_CONFIRMATION)
    monkeypatch.setattr(canary, "_apply_migrations", lambda database_url: None)
    monkeypatch.setattr(canary, "load_coding_agent_transport", lambda: fake_transport)

    assert canary.main() == 0
    output = capsys.readouterr().out
    assert '"state": "agent_assigned"' in output
    assert fake_transport.calls[-1] == ("POST", f"/repos/{canary.REPOSITORY}/issues")


def test_script_source_contains_no_merge_deploy_or_publication_call() -> None:
    """Static guard on the driver script itself: no code path in it may
    call a merge, deployment, or publication API - the real
    automatic_merge_authorized/deployment_authorized/publication_authorized/
    production_graph_mutation_authorized=False guarantees already enforced
    inside app/calyx_orchestrator/assignment_factory.py and
    git_mutation_authorization.py are for the underlying dispatch cycle;
    this asserts the new driver script does not attempt to route around
    them with its own direct call. Checked against executable lines only -
    the module's own header comment discusses "deployment"/"merges" in
    prose to explain what does NOT happen, which is not a call site."""
    import ast
    import inspect

    source = inspect.getsource(canary)
    tree = ast.parse(source)
    code_lines = {node.lineno for node in ast.walk(tree) if hasattr(node, "lineno")}
    source_lines = source.splitlines()
    executable_source = "\n".join(
        source_lines[lineno - 1]
        for lineno in sorted(code_lines)
        if lineno - 1 < len(source_lines) and not source_lines[lineno - 1].strip().startswith("#")
    )
    for banned in ("merge_pull_request", ".merge(", "publish_", "materialize"):
        assert banned not in executable_source, f"driver script must not call {banned!r}"


def test_only_run_once_returns_agent_assigned_never_a_merged_or_deployed_state(
    monkeypatch: pytest.MonkeyPatch, prepared_engine, throwaway_database_url: str, capsys
) -> None:
    """Re-confirms, on the exact same fake-transport run this test module
    already exercises, that the terminal state the script can print for a
    fresh dispatch is agent_assigned - never anything implying a merge,
    deployment, or publication occurred - and that running main() a second
    time against the SAME already-consumed program_job_id (simulating a
    stale rerun instead of a fresh workflow_dispatch) reconciles/observes
    the existing dispatch rather than ever creating a SECOND GitHub issue.
    This is the real, documented behavior of GitHubCodingAgentDispatchCycle:
    once a dispatch record exists, run_once always calls observer.observe()
    regardless of the execute flag - a second call is not refused outright,
    but it is structurally incapable of assigning a second issue, because
    the executor's assignment path is only reached when no dispatch record
    exists yet. The real, cross-run protection against ever getting a
    duplicate ephemeral database to retry against comes from the workflow
    architecture itself (a brand-new throwaway database per
    workflow_dispatch trigger), not from an in-process refusal."""
    from dataclasses import dataclass, field

    @dataclass
    class FakeTransport:
        responses: list
        calls: list = field(default_factory=list)

        def request(self, method, path, *, json_body=None, params=None):
            self.calls.append((method, path))
            return self.responses.pop(0)

    monkeypatch.setenv("DATABASE_URL", throwaway_database_url)
    monkeypatch.setenv("CALYX_LIVE_DISPATCH_EXECUTE", "true")
    monkeypatch.setenv("CALYX_LIVE_DISPATCH_CONFIRMATION", canary.EXECUTE_CONFIRMATION)
    monkeypatch.setattr(canary, "_apply_migrations", lambda database_url: None)

    first_transport = FakeTransport(
        [
            GitHubTransportResponse(200, {"object": {"sha": "a" * 40}}),
            GitHubTransportResponse(200, []),
            GitHubTransportResponse(200, []),
            GitHubTransportResponse(201, {"number": 4242}),
        ]
    )
    monkeypatch.setattr(canary, "load_coding_agent_transport", lambda: first_transport)
    assert canary.main() == 0
    first_output = capsys.readouterr().out
    assert '"state": "agent_assigned"' in first_output
    assert "merged" not in first_output.lower()
    assert "deployed" not in first_output.lower()

    # A second main() call reuses _enqueue_mission's idempotent lookup and
    # finds the SAME program_job_id and the SAME dispatch record. run_once
    # takes the observe() branch this time (a GET on the issue timeline),
    # never the assignment branch again - so whatever it does, it must not
    # contain a second POST to /issues.
    second_transport = FakeTransport([GitHubTransportResponse(200, [])])
    monkeypatch.setattr(canary, "load_coding_agent_transport", lambda: second_transport)
    canary.main()
    issue_creation_calls = [call for call in second_transport.calls if call == ("POST", f"/repos/{canary.REPOSITORY}/issues")]
    assert issue_creation_calls == []
