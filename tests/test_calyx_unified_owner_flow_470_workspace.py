from __future__ import annotations

from types import SimpleNamespace

from app.routers import calyx_unified_owner_flow as flow

PROJECT_ID = "11111111-1111-4111-8111-111111111111"


class ExistingDb:
    def scalar(self, statement):
        return SimpleNamespace(project_id=PROJECT_ID)


class EmptyDb:
    def scalar(self, statement):
        return None


def test_workspace_resolver_reuses_existing_owner_demo_project(monkeypatch):
    class ForbiddenWorkspace:
        def __init__(self, db):
            pass

        def create_project(self, *args, **kwargs):
            raise AssertionError("existing workspace must be reused")

    monkeypatch.setattr(flow, "ResearchWorkspaceService", ForbiddenWorkspace)
    project_id, created = flow._resolve_project_id(ExistingDb(), "owner-a", None)
    assert project_id == PROJECT_ID
    assert created is False


def test_workspace_resolver_creates_canonical_project_before_mission(monkeypatch):
    captured = {}

    class FakeWorkspace:
        def __init__(self, db):
            pass

        def create_project(self, owner, payload):
            captured["owner"] = owner
            captured["title"] = payload.title
            captured["question"] = payload.research_question
            return {"project_id": PROJECT_ID}

    monkeypatch.setattr(flow, "ResearchWorkspaceService", FakeWorkspace)
    project_id, created = flow._resolve_project_id(EmptyDb(), "owner-a", None)
    assert project_id == PROJECT_ID
    assert created is True
    assert captured == {
        "owner": "owner-a",
        "title": flow.DEMO_PROJECT_TITLE,
        "question": flow.LAELIA_ANCEPS_QUESTION,
    }


def test_supplied_workspace_is_validated_for_authenticated_owner(monkeypatch):
    captured = {}

    class FakeWorkspace:
        def __init__(self, db):
            pass

        def get_project(self, project_id, owner):
            captured.update(project_id=project_id, owner=owner)
            return {"project_id": PROJECT_ID}

    monkeypatch.setattr(flow, "ResearchWorkspaceService", FakeWorkspace)
    project_id, created = flow._resolve_project_id(EmptyDb(), "owner-a", PROJECT_ID)
    assert project_id == PROJECT_ID
    assert created is False
    assert captured == {"project_id": PROJECT_ID, "owner": "owner-a"}
