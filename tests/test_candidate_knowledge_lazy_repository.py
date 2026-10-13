"""Candidate-knowledge components resolve on first use, never at import."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]

_PROBE = """
import psycopg

calls = []
def refuse(*args, **kwargs):
    calls.append(1)
    raise psycopg.OperationalError("probe: no database here")
psycopg.connect = refuse

import app.candidate_knowledge.dependencies as dependencies
import app.candidate_knowledge.routes
import app.candidate_knowledge.lookup
import app.parallel_platform.brain_candidate_handoff
import app.parallel_platform.reasoning_contract_bridge
print("after_import", len(calls))

from fastapi import HTTPException
try:
    dependencies.get_candidate_components()
except HTTPException as exc:
    print("first_use", len(calls), exc.status_code, exc.detail["code"])
try:
    dependencies.get_candidate_components()
except HTTPException:
    print("second_use", len(calls))
"""


def test_import_never_contacts_the_database_and_first_use_does_once():
    env = {**os.environ, "DATABASE_URL": "postgresql://probe:probe@127.0.0.1:1/none"}
    result = subprocess.run(
        [sys.executable, "-B", "-c", _PROBE],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    lines = dict(line.split(" ", 1) for line in result.stdout.strip().splitlines())
    assert lines["after_import"] == "0"
    first_calls, status, code = lines["first_use"].split()
    assert int(first_calls) >= 1
    assert (status, code) == ("503", "CANDIDATE_DATABASE_UNAVAILABLE")
    # A failure is remembered for the process, exactly as the import-time build was.
    assert lines["second_use"] == first_calls


@pytest.fixture()
def fresh_dependencies(monkeypatch):
    from app.candidate_knowledge import dependencies

    monkeypatch.setattr(dependencies, "_RESOLVED", None)
    return dependencies


def test_resolution_happens_once_under_concurrency(fresh_dependencies, monkeypatch):
    from app.candidate_knowledge.repository import MemoryCandidateRepository

    built = []

    def build():
        built.append(1)
        return MemoryCandidateRepository()

    monkeypatch.setattr(fresh_dependencies, "_build_repository", build)
    results = []
    threads = [
        threading.Thread(
            target=lambda: results.append(fresh_dependencies.get_candidate_components())
        )
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert built == [1]
    assert len({id(repo) for repo, _ in results}) == 1


def test_same_repository_class_for_the_same_configuration(
    fresh_dependencies, monkeypatch
):
    from app.candidate_knowledge.repository import MemoryCandidateRepository

    monkeypatch.setattr(fresh_dependencies, "configured_database_url", lambda: None)
    repository, service = fresh_dependencies.get_candidate_components()
    assert type(repository) is MemoryCandidateRepository
    assert service.repo is repository


def test_build_failure_is_the_existing_503(fresh_dependencies, monkeypatch):
    def broken():
        raise RuntimeError("database down")

    monkeypatch.setattr(fresh_dependencies, "_build_repository", broken)
    with pytest.raises(HTTPException) as raised:
        fresh_dependencies.get_candidate_components()
    assert raised.value.status_code == 503
    assert raised.value.detail == {"code": "CANDIDATE_DATABASE_UNAVAILABLE"}
    assert fresh_dependencies._REPOSITORY is None
    assert fresh_dependencies._REPOSITORY_ERROR == "CANDIDATE_DATABASE_UNAVAILABLE"


def test_legacy_attribute_names_still_resolve(fresh_dependencies, monkeypatch):
    from app.candidate_knowledge.repository import MemoryCandidateRepository

    monkeypatch.setattr(fresh_dependencies, "configured_database_url", lambda: None)
    assert isinstance(fresh_dependencies._REPOSITORY, MemoryCandidateRepository)
    assert fresh_dependencies._SERVICE.repo is fresh_dependencies._REPOSITORY
    assert fresh_dependencies._REPOSITORY_ERROR is None
    with pytest.raises(AttributeError):
        fresh_dependencies.not_an_attribute  # noqa: B018


def test_routes_resolve_lazily_and_keep_assigned_values(
    fresh_dependencies, monkeypatch
):
    from app.candidate_knowledge import routes
    from app.candidate_knowledge.lookup import serving_repository
    from app.candidate_knowledge.repository import MemoryCandidateRepository
    from app.candidate_knowledge.service import CandidateExtractionService

    monkeypatch.setattr(fresh_dependencies, "configured_database_url", lambda: None)
    monkeypatch.setattr(routes, "REPOSITORY", routes._UNRESOLVED)
    monkeypatch.setattr(routes, "SERVICE", routes._UNRESOLVED)
    monkeypatch.setattr(routes, "REPOSITORY_ERROR", None)
    assert isinstance(serving_repository(), MemoryCandidateRepository)

    assigned = MemoryCandidateRepository()
    monkeypatch.setattr(routes, "REPOSITORY", assigned)
    monkeypatch.setattr(routes, "SERVICE", CandidateExtractionService(assigned))
    assert routes._available()[0] is assigned

    monkeypatch.setattr(routes, "REPOSITORY", None)
    monkeypatch.setattr(routes, "SERVICE", None)
    with pytest.raises(HTTPException) as raised:
        routes._available()
    assert raised.value.status_code == 503
