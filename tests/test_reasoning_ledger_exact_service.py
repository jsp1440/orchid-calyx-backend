from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.reasoning_ledger.operational_service import (
    OperationalReasoningLedgerService,
    ProjectNotFoundError,
)


class Repository:
    def __init__(self, revision):
        self.revision = revision
        self.calls = []

    def exact_revision(self, ledger_id, owner, version):
        self.calls.append(("exact", ledger_id, owner, version))
        return self.revision, []

    def project_id(self, ledger_id, owner):
        self.calls.append(("project", ledger_id, owner))
        return "project-1"

    def history(self, *_args):
        raise AssertionError("exact retrieval must not load history")

    def audit_history(self, *_args):
        raise AssertionError("exact retrieval must not load audit history")


class Projects:
    def __init__(self, *, archived=False):
        self.archived = archived
        self.calls = []

    def require_owned(self, project_id, owner):
        self.calls.append((project_id, owner))
        if self.archived:
            raise ProjectNotFoundError("PROJECT_NOT_FOUND")
        return SimpleNamespace(project_id=project_id)


def service(revision, *, archived=False):
    instance = object.__new__(OperationalReasoningLedgerService)
    instance.repository = Repository(revision)
    instance.projects = Projects(archived=archived)
    return instance


def test_exact_revision_validates_the_active_project_boundary():
    revision = SimpleNamespace(project_id="project-1", version=2)
    instance = service(revision)

    result, available = instance.exact_revision("ledger-1", "owner", 2)

    assert result is revision
    assert available == []
    assert instance.projects.calls == [("project-1", "owner")]
    assert instance.repository.calls == [("exact", "ledger-1", "owner", 2)]


def test_exact_revision_rejects_an_archived_project_without_history_load():
    revision = SimpleNamespace(project_id="project-1", version=2)
    instance = service(revision, archived=True)

    with pytest.raises(ProjectNotFoundError):
        instance.exact_revision("ledger-1", "owner", 2)

    assert instance.repository.calls == [("exact", "ledger-1", "owner", 2)]
