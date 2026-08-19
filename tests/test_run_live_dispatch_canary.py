"""Tests for scripts/run_live_dispatch_canary.py - the driver the
live-dispatch-canary GitHub Actions workflow runs. Exercises the real
enqueue/preflight/execute chain against a real local Postgres database
(created and dropped by this test, never a persistent or production one)
with the GitHub transport faked - the same evidence tier established by
test_github_agent_zero_credential_live_shape_proof.py.

Requires a local PostgreSQL reachable via the DATABASE_URL already set for
this test run (tests/conftest.py defaults it to postgresql://test:test@
localhost:5432/test when unset) - the same connection every other canonical
test in this repository already assumes. The admin/superuser role and
password are whatever DATABASE_URL's own credentials are; this module never
hardcodes a role name, since CI providers name their Postgres superuser
differently (e.g. BUILD-087B's service container uses "build087", not
"postgres").
"""
from __future__ import annotations

import os
import subprocess
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.calyx_orchestrator.github_proposal_mutation_adapter import (
    GitHubTransportResponse,
    RequestsGitHubTransport,
)
from app.database import Base
from scripts import run_live_dispatch_canary as canary

NO_DUPLICATE_FOUND = GitHubTransportResponse(200, [])


@dataclass
class FakeTransport:
    responses: list
    calls: list = field(default_factory=list)

    def request(self, method, path, *, json_body=None, params=None):
        self.calls.append((method, path))
        return self.responses.pop(0)


def _admin_database_url() -> str:
    """The already-provisioned connection, repointed at the "postgres"
    maintenance database every Postgres cluster has by default - reusing
    whichever role this CI/dev environment actually configured rather than
    assuming a "postgres" superuser exists under that literal name."""
    base = os.environ.get("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    scheme, netloc, _path, query, fragment = urlsplit(base)
    return urlunsplit((scheme, netloc, "/postgres", query, fragment))


def _create_throwaway_database() -> str:
    name = f"calyx_canary_test_{uuid.uuid4().hex[:12]}"
    admin_url = _admin_database_url()
    subprocess.run(
        ["psql", admin_url, "-c", f"CREATE DATABASE {name};"],
        check=True,
        capture_output=True,
    )
    scheme, netloc, _path, query, fragment = urlsplit(admin_url)
    return urlunsplit((scheme, netloc, f"/{name}", query, fragment))


def _drop_database(database_url: str) -> None:
    name = urlsplit(database_url).path.lstrip("/")
    subprocess.run(
        ["psql", _admin_database_url(), "-c", f"DROP DATABASE IF EXISTS {name};"],
        check=False,
        capture_output=True,
    )


@pytest.fixture()
def throwaway_database_url():
    url = _create_throwaway_database()
    yield url
    _drop_database(url)


def _prepare(database_url: str):
    for migration in canary.MIGRATIONS:
        sql = migration.read_text(encoding="utf-8")
        engine = create_engine(database_url)
        with engine.begin() as conn:
            conn.execute(text(sql))
        engine.dispose()
    engine = create_engine(database_url)
    # This throwaway database only needs the default ("public") schema
    # tables the orchestrator itself uses - not the handful of unrelated
    # business-domain tables mapped onto their own dedicated Postgres
    # schemas (e.g. research_station.*), which would each need their own
    # CREATE SCHEMA step this test has no reason to replicate.
    public_schema_tables = [table for table in Base.metadata.sorted_tables if table.schema is None]
    Base.metadata.create_all(engine, tables=public_schema_tables, checkfirst=True)
    return engine


@pytest.fixture()
def prepared_engine(throwaway_database_url):
    engine = _prepare(throwaway_database_url)
    yield engine
    engine.dispose()


def _set_execute_env(monkeypatch: pytest.MonkeyPatch, database_url: str, *, confirmation: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("CALYX_LIVE_DISPATCH_EXECUTE", "true")
    monkeypatch.setenv("CALYX_LIVE_DISPATCH_CONFIRMATION", confirmation)
    monkeypatch.setattr(canary, "_apply_migrations", lambda database_url: None)


# ---------------------------------------------------------------------------
# Enqueue / preflight basics
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# A. execute=false never receives or reads the coding-agent secret
# ---------------------------------------------------------------------------

def test_preflight_path_never_calls_the_credential_loader(
    monkeypatch: pytest.MonkeyPatch, prepared_engine, throwaway_database_url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", throwaway_database_url)
    monkeypatch.setenv("CALYX_LIVE_DISPATCH_EXECUTE", "false")
    monkeypatch.setenv("CALYX_LIVE_DISPATCH_CONFIRMATION", "")
    monkeypatch.delenv("CALYX_GITHUB_CODING_AGENT_TOKEN", raising=False)
    monkeypatch.setattr(canary, "_apply_migrations", lambda database_url: None)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("execute=false must never call the credential loader")

    monkeypatch.setattr(canary, "load_coding_agent_transport", fail_if_called)

    assert canary.main() == 0


# ---------------------------------------------------------------------------
# B. missing secret fails closed before any mutating GitHub request
# ---------------------------------------------------------------------------

def test_main_execute_refuses_without_coding_agent_credential(
    monkeypatch: pytest.MonkeyPatch, prepared_engine, throwaway_database_url: str
) -> None:
    _set_execute_env(monkeypatch, throwaway_database_url, confirmation=canary.EXECUTE_CONFIRMATION)
    monkeypatch.delenv("CALYX_GITHUB_CODING_AGENT_TOKEN", raising=False)
    # Even a broad/generic token present must not be picked up as a
    # substitute credential by the real load_coding_agent_transport().
    monkeypatch.setenv("GITHUB_TOKEN", "should-never-be-used-for-this-path")
    monkeypatch.setenv("GH_TOKEN", "also-should-never-be-used")

    assert canary.main() == 1


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


# ---------------------------------------------------------------------------
# C. a first simulated execution creates the intended single canary mutation
# ---------------------------------------------------------------------------

def test_main_execute_runs_the_real_dispatch_against_a_fake_transport_only(
    monkeypatch: pytest.MonkeyPatch, prepared_engine, throwaway_database_url: str, capsys
) -> None:
    """Proves the full driver path - duplicate check, enqueue, credential
    load (faked), execute_one_shot_mission, real convergence-inspection
    call sequence - reaches a live dispatch shape with zero real network
    access. Mirrors the fake-transport response sequence already
    established in test_github_agent_one_shot_operator.py's happy path."""
    fake_transport = FakeTransport(
        [
            NO_DUPLICATE_FOUND,
            GitHubTransportResponse(200, {"object": {"sha": "a" * 40}}),
            GitHubTransportResponse(200, []),
            GitHubTransportResponse(200, []),
            GitHubTransportResponse(201, {"number": 9001}),
        ]
    )

    _set_execute_env(monkeypatch, throwaway_database_url, confirmation=canary.EXECUTE_CONFIRMATION)
    monkeypatch.setattr(canary, "load_coding_agent_transport", lambda: fake_transport)

    assert canary.main() == 0
    output = capsys.readouterr().out
    assert '"state": "agent_assigned"' in output
    assert fake_transport.calls[0] == ("GET", f"/repos/{canary.REPOSITORY}/issues")
    assert fake_transport.calls[-1] == ("POST", f"/repos/{canary.REPOSITORY}/issues")


# ---------------------------------------------------------------------------
# D. a second execution against a FRESH EMPTY database, with GitHub remote
#    state already showing the first canary, is refused before a second
#    issue is created
# ---------------------------------------------------------------------------

def test_second_execution_against_a_fresh_database_is_refused_when_github_already_shows_the_canary(
    monkeypatch: pytest.MonkeyPatch, throwaway_database_url: str, capsys
) -> None:
    """Simulates exactly the scenario a second, independent workflow_dispatch
    trigger produces: a brand-new throwaway database with no memory of the
    first run, but GitHub itself already has the canary issue from that
    first run. The durable, GitHub-side duplicate check must catch this
    even though the local database has no idea a first run ever happened."""
    engine = _prepare(throwaway_database_url)
    engine.dispose()

    already_exists_transport = FakeTransport(
        [GitHubTransportResponse(200, [{"number": 4242, "title": "live-dispatch-canary-002 - ..."}])]
    )

    _set_execute_env(monkeypatch, throwaway_database_url, confirmation=canary.EXECUTE_CONFIRMATION)
    monkeypatch.setattr(canary, "load_coding_agent_transport", lambda: already_exists_transport)

    assert canary.main() == 1
    stderr = capsys.readouterr().err
    assert "CANARY_ALREADY_DISPATCHED" in stderr
    # The refusal happened on the duplicate-check GET alone - no POST to
    # /issues was ever attempted.
    assert ("POST", f"/repos/{canary.REPOSITORY}/issues") not in already_exists_transport.calls
    assert already_exists_transport.calls == [("GET", f"/repos/{canary.REPOSITORY}/issues")]


def test_duplicate_check_refuses_closed_when_the_issue_list_call_itself_fails(
    monkeypatch: pytest.MonkeyPatch, prepared_engine, throwaway_database_url: str, capsys
) -> None:
    """An inconclusive answer from GitHub (e.g. a transient 5xx, or the
    HTTP 422 actually observed from the Search API in run 31939565523 - see
    the module docstring for what is fact versus hypothesis about that
    422's cause) must not be treated as "no duplicate" - it must refuse just
    as firmly as a real duplicate would, since proceeding on an uncertain
    answer is exactly the failure mode this guard exists to prevent."""
    inconclusive_transport = FakeTransport([GitHubTransportResponse(502, {"message": "server error"})])

    _set_execute_env(monkeypatch, throwaway_database_url, confirmation=canary.EXECUTE_CONFIRMATION)
    monkeypatch.setattr(canary, "load_coding_agent_transport", lambda: inconclusive_transport)

    assert canary.main() == 1
    stderr = capsys.readouterr().err
    assert "CANARY_DUPLICATE_CHECK_INCONCLUSIVE" in stderr
    assert ("POST", f"/repos/{canary.REPOSITORY}/issues") not in inconclusive_transport.calls


def test_duplicate_check_paginates_past_a_full_first_page_before_concluding_no_duplicate(
    monkeypatch: pytest.MonkeyPatch, prepared_engine, throwaway_database_url: str
) -> None:
    """A full first page (100 items, none matching) must not be mistaken
    for the end of the list - the check has to keep paging until a
    short/empty page proves there is nothing left."""
    full_page = [{"number": n, "title": f"unrelated issue {n}"} for n in range(100)]
    short_page = [{"number": 9999, "title": "also unrelated"}]
    paginating_transport = FakeTransport(
        [
            GitHubTransportResponse(200, full_page),
            GitHubTransportResponse(200, short_page),
            GitHubTransportResponse(200, {"object": {"sha": "a" * 40}}),
            GitHubTransportResponse(200, []),
            GitHubTransportResponse(200, []),
            GitHubTransportResponse(201, {"number": 9001}),
        ]
    )
    _set_execute_env(monkeypatch, throwaway_database_url, confirmation=canary.EXECUTE_CONFIRMATION)
    monkeypatch.setattr(canary, "load_coding_agent_transport", lambda: paginating_transport)

    assert canary.main() == 0
    issue_list_calls = [call for call in paginating_transport.calls if call == ("GET", f"/repos/{canary.REPOSITORY}/issues")]
    assert len(issue_list_calls) == 2


def test_duplicate_check_refuses_closed_when_the_page_cap_is_exceeded(
    monkeypatch: pytest.MonkeyPatch, prepared_engine, throwaway_database_url: str, capsys
) -> None:
    """A repository with an implausibly long, always-full issue history
    must not be paged through forever - and must not be treated as "no
    duplicate" just because the cap was hit without a match. Refusing is
    the safe outcome for an inconclusive scan."""
    full_page = [{"number": n, "title": f"unrelated issue {n}"} for n in range(100)]
    never_ending_transport = FakeTransport([GitHubTransportResponse(200, full_page)] * canary._DUPLICATE_CHECK_MAX_PAGES)

    _set_execute_env(monkeypatch, throwaway_database_url, confirmation=canary.EXECUTE_CONFIRMATION)
    monkeypatch.setattr(canary, "load_coding_agent_transport", lambda: never_ending_transport)

    assert canary.main() == 1
    stderr = capsys.readouterr().err
    assert "CANARY_DUPLICATE_CHECK_INCONCLUSIVE" in stderr
    assert len(never_ending_transport.calls) == canary._DUPLICATE_CHECK_MAX_PAGES


def test_duplicate_check_refuses_closed_on_unexpected_response_shape(
    monkeypatch: pytest.MonkeyPatch, prepared_engine, throwaway_database_url: str, capsys
) -> None:
    """A 200 response whose payload is not a list (e.g. an error body
    GitHub still returned with a 200 status, or a totally different
    endpoint shape) must not be treated as an empty list of issues."""
    malformed_transport = FakeTransport([GitHubTransportResponse(200, {"message": "not a list"})])

    _set_execute_env(monkeypatch, throwaway_database_url, confirmation=canary.EXECUTE_CONFIRMATION)
    monkeypatch.setattr(canary, "load_coding_agent_transport", lambda: malformed_transport)

    assert canary.main() == 1
    stderr = capsys.readouterr().err
    assert "CANARY_DUPLICATE_CHECK_INCONCLUSIVE" in stderr


# ---------------------------------------------------------------------------
# E. simultaneous-run protection is represented correctly in workflow config
#    (governance/static checks on the YAML and script live in
#    test_live_dispatch_canary_workflow_governance.py)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# F. generic GITHUB_TOKEN/GH_TOKEN cannot substitute
#    (covered directly in tests/test_github_agent_credential.py; re-asserted
#    end-to-end here via test_main_execute_refuses_without_coding_agent_credential)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# G. token values never appear in repr, stdout, stderr, or exceptions
# ---------------------------------------------------------------------------

def test_real_transport_repr_never_contains_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    distinctive_token = "distinctive-marker-9988776655-should-never-leak"
    monkeypatch.setenv("CALYX_GITHUB_CODING_AGENT_TOKEN", distinctive_token)
    transport = canary.load_coding_agent_transport()
    assert isinstance(transport, RequestsGitHubTransport)
    assert distinctive_token not in repr(transport)
    assert distinctive_token not in str(transport)


def test_no_secret_shaped_content_in_stdout_or_stderr_across_a_full_execute_run(
    monkeypatch: pytest.MonkeyPatch, prepared_engine, throwaway_database_url: str, capsys
) -> None:
    distinctive_token = "distinctive-marker-1122334455-should-never-leak"
    monkeypatch.setenv("CALYX_GITHUB_CODING_AGENT_TOKEN", distinctive_token)
    fake_transport = FakeTransport(
        [
            NO_DUPLICATE_FOUND,
            GitHubTransportResponse(200, {"object": {"sha": "a" * 40}}),
            GitHubTransportResponse(200, []),
            GitHubTransportResponse(200, []),
            GitHubTransportResponse(201, {"number": 5555}),
        ]
    )
    _set_execute_env(monkeypatch, throwaway_database_url, confirmation=canary.EXECUTE_CONFIRMATION)
    # Use the REAL load_coding_agent_transport (reads the env var above) but
    # swap the transport it returns for the fake one, so the credential is
    # genuinely loaded through the real code path while no real network call
    # happens.
    real_loader = canary.load_coding_agent_transport
    monkeypatch.setattr(canary, "load_coding_agent_transport", lambda: (real_loader(), fake_transport)[1])

    canary.main()
    captured = capsys.readouterr()
    assert distinctive_token not in captured.out
    assert distinctive_token not in captured.err


# ---------------------------------------------------------------------------
# H. automatic merge, deployment, publication, and production KG mutation
#    remain impossible
# ---------------------------------------------------------------------------

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
    time against the SAME already-consumed program_job_id and dispatch
    record (simulating a stale rerun instead of a fresh workflow_dispatch)
    is refused by the duplicate check itself before ever reaching the
    observe/assignment branches again."""
    _set_execute_env(monkeypatch, throwaway_database_url, confirmation=canary.EXECUTE_CONFIRMATION)

    first_transport = FakeTransport(
        [
            NO_DUPLICATE_FOUND,
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

    # A second main() call against the SAME database: the duplicate check
    # this time reports the canary already exists (as it genuinely would,
    # since the first call really did create it above), so this refuses
    # before ever reaching a second POST to /issues.
    second_transport = FakeTransport(
        [GitHubTransportResponse(200, [{"number": 4242, "title": "live-dispatch-canary-002 - ..."}])]
    )
    monkeypatch.setattr(canary, "load_coding_agent_transport", lambda: second_transport)
    assert canary.main() == 1
    issue_creation_calls = [call for call in second_transport.calls if call == ("POST", f"/repos/{canary.REPOSITORY}/issues")]
    assert issue_creation_calls == []
