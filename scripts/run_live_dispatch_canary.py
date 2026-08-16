#!/usr/bin/env python3
"""Driver for the live-dispatch-canary-002 GitHub Actions workflow.

Runs inside `.github/workflows/live-dispatch-canary.yml` only - a
`workflow_dispatch`-only workflow with no schedule and no other trigger.
This script itself never decides whether to run; it only decides, once
invoked, whether to *mutate* (`execute=true`) or only *preflight*
(`execute=false`, the default) - and even in the execute path it performs
exactly one dispatch of exactly one hardcoded mission, then exits. There is
no loop, no retry, no second mission, and no code path that merges,
deploys, publishes, or mutates a Knowledge Graph.

Database: the workflow provisions a throwaway PostgreSQL instance local to
the runner (mirroring the pattern already established in
`.github/workflows/build-088e-validation.yml`) and passes its URL as
DATABASE_URL. This script applies the two named dispatch-table migrations
to that database (and only that database) before enqueuing the mission.

Credential: read exactly once, only in the execute=true path, only via
`app.calyx_orchestrator.github_agent_credential.load_coding_agent_transport`
- which itself reads only `CALYX_GITHUB_CODING_AGENT_TOKEN` and fails
closed with no fallback to any other credential name. This script never
reads a GitHub token itself and never logs, prints, or serializes one.

Cross-run duplicate protection: the throwaway database is fresh on every
workflow run, so it cannot remember an earlier live dispatch. Before ever
creating the canary issue, `_refuse_if_canary_already_dispatched` lists
GitHub's own issues for this repository (using the same already-loaded
credential) and refuses if any existing, open or closed, issue title already
matches `live-dispatch-canary-002` - a real, durable, GitHub-side marker, not
a database-only one. This deliberately uses the plain repository issues-list
endpoint rather than the Search API: a live run of this workflow (run
31939565523, 2026-08-16) observed the Search API (`GET /search/issues`)
return HTTP 422 for this repository's coding-agent credential - that HTTP
422 is an observed fact from that run's logs. The credential in use was a
fine-grained personal access token scoped to a single private repository,
and GitHub has a documented history of Search API incompatibilities with
that token type; that specific mechanism is the leading hypothesis for the
422, not a confirmed root cause - it has not been independently reproduced
or isolated against the Search API in controlled conditions. The fix does
not depend on which explanation is correct: the issues-list endpoint used
here does not exhibit the failure observed in that run, regardless of its
ultimate cause.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.github_agent_ci_policy import RequiredCiCheckPolicy
from app.calyx_orchestrator.github_agent_composition import (
    build_production_github_coding_agent_dispatch_cycle,
)
from app.calyx_orchestrator.github_agent_credential import (
    GitHubCodingAgentCredentialError,
    load_coding_agent_transport,
)
from app.calyx_orchestrator.github_agent_dispatch_cycle import (
    EXECUTE_CONFIRMATION,
    GitHubCodingRuntimePolicy,
)
from app.calyx_orchestrator.github_agent_one_shot_operator import (
    OneShotExecutionError,
    OneShotExecutionRequest,
    execute_one_shot_mission,
)
from app.calyx_orchestrator.github_coding_executor import (
    GITHUB_CODING_ROLE,
    BudgetClass,
)
from app.calyx_orchestrator.program_models import CalyxProgramJob
from app.calyx_orchestrator.program_repository import (
    PersistentProgramRepository,
    ProgramJobSpec,
)
from app.database import Base

OWNER = "jsp1440"
REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "agent/live-dispatch-canary-002"
JOB_KEY = "live-dispatch-canary-002"
REQUIRED_CHECK_NAME = "publication-pipeline-operational-readiness"
MISSION_BRIEF = (
    "Create exactly one new file, docs/live-dispatch-canary.md, containing "
    "one sentence identifying it as a canary file verifying the live "
    "GitHub Copilot coding-agent dispatch mechanism, with today's date. "
    "Touch no other file."
)

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = [
    REPO_ROOT / "migrations" / "20260814_phase_2_github_agent_dispatch.sql",
    REPO_ROOT / "migrations" / "20260815_phase_2_github_agent_dispatch_branch.sql",
]


class CanaryAlreadyDispatchedError(RuntimeError):
    """Raised when GitHub itself already shows evidence of a prior
    live-dispatch-canary-002 execution. A fresh throwaway database has no
    memory of an earlier workflow run, so the durable, cross-run duplicate
    check has to live on GitHub's own side, not in the database."""


_DUPLICATE_CHECK_MAX_PAGES = 20
_DUPLICATE_CHECK_PAGE_SIZE = 100


def _refuse_if_canary_already_dispatched(transport) -> None:
    """The real GitHub issue this mission creates is always titled
    f"{mission_id} - {objective[:160]}" (see
    GitHubCopilotCloudProvider._assign_issue), and mission_id is always
    exactly JOB_KEY for this canary - so a title containing JOB_KEY is an
    exact, durable, GitHub-side marker of a prior real dispatch. Paginates
    through GET /repos/{repo}/issues?state=all (a plain repository issues
    listing, not the Search API - see the module docstring for why) so a
    since-closed canary issue still blocks a repeat, and so an issue that
    happens to be many pages back is not missed. Called before any mutating
    call in the execute path; any non-200 response, a response shaped
    unlike a list, or exceeding the page cap without reaching the end are
    all treated as inconclusive and also refuse, rather than assuming "no
    duplicate" on an uncertain answer."""
    for page in range(1, _DUPLICATE_CHECK_MAX_PAGES + 1):
        response = transport.request(
            "GET",
            f"/repos/{REPOSITORY}/issues",
            params={
                "state": "all",
                "per_page": str(_DUPLICATE_CHECK_PAGE_SIZE),
                "page": str(page),
            },
        )
        if response.status_code != 200:
            raise CanaryAlreadyDispatchedError(
                f"CANARY_DUPLICATE_CHECK_INCONCLUSIVE:http_{response.status_code}"
            )
        items = response.payload if isinstance(response.payload, list) else None
        if items is None:
            raise CanaryAlreadyDispatchedError(
                "CANARY_DUPLICATE_CHECK_INCONCLUSIVE:unexpected_response_shape"
            )
        for item in items:
            title = item.get("title") if isinstance(item, dict) else None
            if isinstance(title, str) and JOB_KEY in title:
                raise CanaryAlreadyDispatchedError(
                    f"CANARY_ALREADY_DISPATCHED:existing GitHub issue "
                    f"#{item.get('number')!r} already matches {JOB_KEY!r} - "
                    "refusing to create a second one"
                )
        if len(items) < _DUPLICATE_CHECK_PAGE_SIZE:
            return
    raise CanaryAlreadyDispatchedError(
        f"CANARY_DUPLICATE_CHECK_INCONCLUSIVE:exceeded_{_DUPLICATE_CHECK_MAX_PAGES}"
        "_pages_without_reaching_the_end"
    )


class _NeverCalledTransport:
    """Used only in the execute=false (preflight) path. Proves - by
    construction, not just by claim - that a dry run cannot make a live
    GitHub call: any attempt raises immediately."""

    def request(self, method, path, *, json_body=None, params=None):  # pragma: no cover
        raise AssertionError(
            "preflight (execute=false) run must never touch the network"
        )


def _apply_migrations(database_url: str) -> None:
    for migration in MIGRATIONS:
        sql = migration.read_text(encoding="utf-8")
        result = subprocess.run(
            ["psql", database_url, "-v", "ON_ERROR_STOP=1"],
            input=sql,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            print(result.stdout, file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            raise RuntimeError(f"MIGRATION_FAILED:{migration.name}")
        print(f"Applied migration: {migration.name}")


def _enqueue_mission(db: Session) -> str:
    existing = (
        db.query(CalyxProgramJob)
        .filter(CalyxProgramJob.job_key == JOB_KEY)
        .one_or_none()
    )
    if existing is not None:
        return existing.program_job_id

    repo = PersistentProgramRepository(db)
    program = repo.create_program(
        owner=OWNER,
        title="live-dispatch-canary-002",
        objective=(
            "Verify the live GitHub Copilot coding-agent dispatch mechanism "
            "with a single, trivial, reversible, inert-content mission per "
            "Orchid-Continuum-Brain OPS-0012 Section 6."
        ),
        jobs=[
            ProgramJobSpec(
                job_key=JOB_KEY,
                role_key=GITHUB_CODING_ROLE,
                title=(
                    "live-dispatch-canary-002 - verify GitHub coding-agent "
                    "dispatch mechanism (backend, CI-observable)"
                ),
                repository=REPOSITORY,
                branch=BRANCH,
                mutating=True,
                inputs={
                    "budget_class": "TINY",
                    "mission_id": JOB_KEY,
                    "mission_brief": MISSION_BRIEF,
                },
            )
        ],
        dependencies=[],
    )
    repo.start(owner=OWNER, program_id=program.program_id)
    db.commit()
    job = db.query(CalyxProgramJob).filter(CalyxProgramJob.job_key == JOB_KEY).one()
    return job.program_job_id


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 1

    execute = os.environ.get("CALYX_LIVE_DISPATCH_EXECUTE", "false").strip().lower() == "true"
    confirmation = os.environ.get("CALYX_LIVE_DISPATCH_CONFIRMATION", "").strip()

    if execute and confirmation != EXECUTE_CONFIRMATION:
        print(
            "REFUSED: execute=true requires the exact confirmation string; "
            "refusing before touching any database or credential.",
            file=sys.stderr,
        )
        return 1

    _apply_migrations(database_url)

    engine = create_engine(database_url)
    # The throwaway runner database only needs the default ("public")
    # schema tables the orchestrator itself uses - not the handful of
    # unrelated business-domain tables mapped onto their own dedicated
    # Postgres schemas (e.g. research_station.*), which would each need
    # their own CREATE SCHEMA step this canary has no reason to replicate.
    public_schema_tables = [table for table in Base.metadata.sorted_tables if table.schema is None]
    Base.metadata.create_all(engine, tables=public_schema_tables, checkfirst=True)

    with Session(engine) as db:
        program_job_id = _enqueue_mission(db)
        print(f"program_job_id: {program_job_id}")

        if not execute:
            required_checks = RequiredCiCheckPolicy(required_checks=frozenset({REQUIRED_CHECK_NAME}))
            runtime_policy = GitHubCodingRuntimePolicy(
                enabled=True,
                owner_allowlist=frozenset({OWNER}),
                repository_allowlist=frozenset({REPOSITORY}),
                max_budget_class=BudgetClass.TINY,
            )
            cycle = build_production_github_coding_agent_dispatch_cycle(
                db=db,
                transport=_NeverCalledTransport(),
                policy=runtime_policy,
                required_checks=required_checks,
            )
            result = cycle.run_once(owner=OWNER, execute=False, confirmation="")
            print(json.dumps({"mode": "preflight", "state": result.state, "program_job_id": result.program_job_id}))
            return 0

        try:
            transport = load_coding_agent_transport()
        except GitHubCodingAgentCredentialError as exc:
            print(f"REFUSED (fail-closed): {exc}", file=sys.stderr)
            return 1

        try:
            _refuse_if_canary_already_dispatched(transport)
        except CanaryAlreadyDispatchedError as exc:
            print(f"REFUSED (fail-closed): {exc}", file=sys.stderr)
            return 1

        request = OneShotExecutionRequest(
            owner=OWNER,
            repository=REPOSITORY,
            expected_program_job_id=program_job_id,
            budget_class=BudgetClass.TINY,
            required_checks=RequiredCiCheckPolicy(required_checks=frozenset({REQUIRED_CHECK_NAME})),
            confirmation=confirmation,
        )
        try:
            result = execute_one_shot_mission(db=db, transport=transport, request=request)
        except OneShotExecutionError as exc:
            print(f"REFUSED (fail-closed): {exc}", file=sys.stderr)
            return 1

        print(json.dumps({"mode": "execute", "state": result.state, "program_job_id": result.program_job_id}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
