from __future__ import annotations

import hashlib
from datetime import timedelta
from urllib.parse import unquote

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.github_proposal_mutation_adapter import (
    GitHubProposalMutationAdapter,
    GitHubProposalTransportError,
    GitHubTransportResponse,
    RequestsGitHubTransport,
    _blob_sha,
    _expected_commit_sha,
)
from app.calyx_orchestrator.git_proposal_mutation_executor import (
    GitProposalMutationExecutor,
)
from app.calyx_orchestrator.git_proposal_mutation_journal import (
    DurableGitProposalMutationJournal,
    GitProposalMutationJournalEventRecord,
)
from app.database import Base
from tests.test_calyx_git_proposal_execution_plan_114r import (
    BASE_COMMIT,
    BASE_REF,
    NOW,
    PATCH_AFTER,
    PATCH_BYTES,
    REPOSITORY,
)
from tests.test_calyx_git_proposal_mutation_executor_114s import _execution_inputs

BASE_TREE = "c" * 40
OLD_BLOB = "b" * 40
TREE_AFTER = "d" * 40
BASE_DATE = "2026-08-09T00:00:00Z"


class MappingPostimages:
    def __init__(self, content: bytes = PATCH_BYTES) -> None:
        self.content = content

    def resolve_postimage(self, *, patch_program_job_id: str, path: str) -> bytes:
        assert patch_program_job_id
        assert path == "app/example.py"
        return self.content


class FakeGitHubTransport:
    def __init__(self) -> None:
        self.refs = {BASE_REF: BASE_COMMIT}
        self.commits: dict[str, dict[str, object]] = {
            BASE_COMMIT: {
                "sha": BASE_COMMIT,
                "tree": {"sha": BASE_TREE},
                "parents": [],
                "message": "base",
                "committer": {"date": BASE_DATE},
            }
        }
        self.trees: dict[str, list[dict[str, object]]] = {
            BASE_TREE: [
                {
                    "path": "app/example.py",
                    "mode": "100644",
                    "type": "blob",
                    "sha": OLD_BLOB,
                }
            ]
        }
        self.pulls: list[dict[str, object]] = []
        self.calls: list[tuple[str, str]] = []
        self.force_wrong_blob = False
        self.force_wrong_push = False
        self.force_non_draft_pr = False

    def request(self, method, path, *, json_body=None, params=None):
        self.calls.append((method, path))
        if method == "GET" and "/git/ref/" in path:
            ref = unquote(path.split("/git/ref/", 1)[1])
            assert ref.startswith("heads/")
            branch = ref.removeprefix("heads/")
            if branch not in self.refs:
                return GitHubTransportResponse(404, {})
            return GitHubTransportResponse(
                200,
                {"ref": f"refs/heads/{branch}", "object": {"sha": self.refs[branch]}},
            )
        if method == "POST" and path.endswith("/git/refs"):
            assert json_body is not None
            branch = str(json_body["ref"]).removeprefix("refs/heads/")
            if branch in self.refs:
                return GitHubTransportResponse(422, {})
            self.refs[branch] = str(json_body["sha"])
            return GitHubTransportResponse(201, {"ref": json_body["ref"]})
        if method == "GET" and "/git/commits/" in path:
            sha = path.rsplit("/", 1)[1]
            payload = self.commits.get(sha)
            return GitHubTransportResponse(200, payload) if payload else GitHubTransportResponse(404, {})
        if method == "POST" and path.endswith("/git/blobs"):
            assert json_body is not None
            import base64

            content = base64.b64decode(str(json_body["content"]))
            sha = "e" * 40 if self.force_wrong_blob else _blob_sha(content)
            return GitHubTransportResponse(201, {"sha": sha})
        if method == "GET" and "/git/trees/" in path:
            sha = path.rsplit("/", 1)[1]
            tree = self.trees.get(sha)
            if tree is None:
                return GitHubTransportResponse(404, {})
            return GitHubTransportResponse(200, {"sha": sha, "tree": tree, "truncated": False})
        if method == "POST" and path.endswith("/git/trees"):
            assert json_body is not None
            base_tree = str(json_body["base_tree"])
            current = {str(item["path"]): dict(item) for item in self.trees[base_tree]}
            for item in json_body["tree"]:
                current[str(item["path"])] = dict(item)
            self.trees[TREE_AFTER] = list(current.values())
            return GitHubTransportResponse(201, {"sha": TREE_AFTER})
        if method == "POST" and path.endswith("/git/commits"):
            assert json_body is not None
            parent = str(json_body["parents"][0])
            tree = str(json_body["tree"])
            message = str(json_body["message"])
            date = str(json_body["author"]["date"])
            sha = _expected_commit_sha(
                tree_sha=tree,
                parent_sha=parent,
                message=message,
                author_date=date,
            )
            self.commits[sha] = {
                "sha": sha,
                "tree": {"sha": tree},
                "parents": [{"sha": parent}],
                "message": message,
                "committer": {"date": date},
            }
            return GitHubTransportResponse(201, {"sha": sha})
        if method == "PATCH" and "/git/refs/" in path:
            assert json_body is not None
            ref = unquote(path.split("/git/refs/", 1)[1])
            branch = ref.removeprefix("heads/")
            self.refs[branch] = (
                "f" * 40 if self.force_wrong_push else str(json_body["sha"])
            )
            return GitHubTransportResponse(200, {"object": {"sha": self.refs[branch]}})
        if method == "GET" and path.endswith("/pulls"):
            assert params is not None
            head_branch = str(params["head"]).split(":", 1)[1]
            base_ref = str(params["base"])
            matches = [
                pull
                for pull in self.pulls
                if pull["head"]["ref"] == head_branch and pull["base"]["ref"] == base_ref
            ]
            return GitHubTransportResponse(200, matches)
        if method == "POST" and path.endswith("/pulls"):
            assert json_body is not None
            branch = str(json_body["head"])
            base_ref = str(json_body["base"])
            pull = {
                "number": len(self.pulls) + 1,
                "html_url": f"https://github.com/{REPOSITORY}/pull/{len(self.pulls) + 1}",
                "draft": False if self.force_non_draft_pr else bool(json_body["draft"]),
                "head": {"ref": branch, "sha": self.refs[branch]},
                "base": {"ref": base_ref, "sha": self.refs[base_ref]},
            }
            self.pulls.append(pull)
            return GitHubTransportResponse(201, pull)
        raise AssertionError((method, path, json_body, params))


def _journal() -> DurableGitProposalMutationJournal:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[GitProposalMutationJournalEventRecord.__table__])
    return DurableGitProposalMutationJournal(Session(engine))


def _run_end_to_end(transport: FakeGitHubTransport):
    journal = _journal()
    adapter = GitHubProposalMutationAdapter(
        transport=transport,
        postimages=MappingPostimages(),
        evidence=journal,
        repository_allowlist=(REPOSITORY,),
    )
    store, gate, request, grant, manifest, plan, _ = _execution_inputs()
    receipt = GitProposalMutationExecutor(
        adapter=adapter,
        repository_allowlist=(REPOSITORY,),
        journal=journal,
    ).execute(
        plan=plan,
        manifest_snapshot=manifest,
        review_store=store,
        authorization_gate=gate,
        request=request,
        grant_mapping=grant,
        now=NOW + timedelta(minutes=1),
    )
    return receipt, journal, adapter, plan


def test_live_adapter_executes_exact_branch_commit_push_and_draft_pr() -> None:
    transport = FakeGitHubTransport()
    receipt, journal, _, plan = _run_end_to_end(transport)
    assert receipt.status == "completed"
    assert receipt.completed_actions == (
        "create_branch",
        "create_commit",
        "push_branch",
        "open_pull_request",
    )
    assert len(transport.pulls) == 1
    assert transport.pulls[0]["draft"] is True
    assert transport.pulls[0]["head"]["sha"] == transport.refs[plan.proposed_branch]
    assert journal.latest(plan_digest=plan.plan_digest) == receipt


def test_completed_retry_creates_no_duplicate_remote_objects_or_pr() -> None:
    transport = FakeGitHubTransport()
    receipt, journal, adapter, plan = _run_end_to_end(transport)
    call_count = len(transport.calls)
    store, gate, request, grant, manifest, verified_plan, _ = _execution_inputs()
    replayed = GitProposalMutationExecutor(
        adapter=adapter,
        repository_allowlist=(REPOSITORY,),
        journal=journal,
    ).execute(
        plan=verified_plan,
        manifest_snapshot=manifest,
        review_store=store,
        authorization_gate=gate,
        request=request,
        grant_mapping=grant,
        now=NOW + timedelta(minutes=1),
    )
    assert replayed == receipt
    assert verified_plan.plan_digest == plan.plan_digest
    assert len(transport.calls) == call_count
    assert len(transport.pulls) == 1


def test_branch_creation_is_idempotent_only_for_exact_reviewed_base() -> None:
    transport = FakeGitHubTransport()
    journal = _journal()
    adapter = GitHubProposalMutationAdapter(
        transport=transport,
        postimages=MappingPostimages(),
        evidence=journal,
        repository_allowlist=(REPOSITORY,),
    )
    _, _, _, _, _, plan, _ = _execution_inputs()
    operation = plan.operations[0]
    first = adapter.apply_proposal_operation(plan_digest=plan.plan_digest, operation=operation)
    second = adapter.apply_proposal_operation(plan_digest=plan.plan_digest, operation=operation)
    assert first["status"] == "created"
    assert second["status"] == "already_exists_exact"
    transport.refs[plan.proposed_branch] = "f" * 40
    with pytest.raises(PermissionError, match="BRANCH_ALREADY_EXISTS_MISMATCH"):
        adapter.apply_proposal_operation(plan_digest=plan.plan_digest, operation=operation)


def test_wrong_postimage_hash_fails_before_blob_or_commit_creation() -> None:
    transport = FakeGitHubTransport()
    journal = _journal()
    adapter = GitHubProposalMutationAdapter(
        transport=transport,
        postimages=MappingPostimages(b"wrong content\n"),
        evidence=journal,
        repository_allowlist=(REPOSITORY,),
    )
    _, _, _, _, _, plan, _ = _execution_inputs()
    adapter.apply_proposal_operation(plan_digest=plan.plan_digest, operation=plan.operations[0])
    with pytest.raises(PermissionError, match="POSTIMAGE_HASH_MISMATCH"):
        adapter.apply_proposal_operation(plan_digest=plan.plan_digest, operation=plan.operations[1])
    assert not any(path.endswith("/git/blobs") for _, path in transport.calls)


def test_blob_sha_and_push_sha_mismatches_fail_closed() -> None:
    transport = FakeGitHubTransport()
    transport.force_wrong_blob = True
    journal = _journal()
    adapter = GitHubProposalMutationAdapter(
        transport=transport,
        postimages=MappingPostimages(),
        evidence=journal,
        repository_allowlist=(REPOSITORY,),
    )
    _, _, _, _, _, plan, _ = _execution_inputs()
    adapter.apply_proposal_operation(plan_digest=plan.plan_digest, operation=plan.operations[0])
    with pytest.raises(PermissionError, match="BLOB_SHA_MISMATCH"):
        adapter.apply_proposal_operation(plan_digest=plan.plan_digest, operation=plan.operations[1])

    transport = FakeGitHubTransport()
    transport.force_wrong_push = True
    with pytest.raises(PermissionError, match="PUSH_VERIFY_FAILED"):
        _run_end_to_end(transport)


def test_base_move_and_non_draft_pr_are_rejected() -> None:
    transport = FakeGitHubTransport()
    journal = _journal()
    adapter = GitHubProposalMutationAdapter(
        transport=transport,
        postimages=MappingPostimages(),
        evidence=journal,
        repository_allowlist=(REPOSITORY,),
    )
    store, gate, request, grant, manifest, plan, _ = _execution_inputs()
    executor = GitProposalMutationExecutor(
        adapter=adapter,
        repository_allowlist=(REPOSITORY,),
        journal=journal,
    )
    # Stop after push using the full executor by making the PR base move just before PR creation.
    original_request = transport.request

    def moving_request(method, path, *, json_body=None, params=None):
        if method == "GET" and path.endswith("/git/ref/heads%2Fmain"):
            transport.refs[BASE_REF] = "f" * 40
        return original_request(method, path, json_body=json_body, params=params)

    transport.request = moving_request  # type: ignore[method-assign]
    with pytest.raises(Exception, match="GITHUB_ADAPTER_PR_BASE_MOVED"):
        executor.execute(
            plan=plan,
            manifest_snapshot=manifest,
            review_store=store,
            authorization_gate=gate,
            request=request,
            grant_mapping=grant,
            now=NOW + timedelta(minutes=1),
        )

    transport = FakeGitHubTransport()
    transport.force_non_draft_pr = True
    with pytest.raises(Exception, match="GITHUB_ADAPTER_PR_VERIFY_FAILED"):
        _run_end_to_end(transport)


def test_repository_allowlist_and_proposal_branch_namespace_fail_closed() -> None:
    transport = FakeGitHubTransport()
    journal = _journal()
    adapter = GitHubProposalMutationAdapter(
        transport=transport,
        postimages=MappingPostimages(),
        evidence=journal,
        repository_allowlist=(REPOSITORY,),
    )
    _, _, _, _, _, plan, _ = _execution_inputs()
    operation = plan.operations[0]
    wrong_repo = type(operation)(
        action=operation.action,
        parameters={**operation.parameters, "repository": "other/repo"},
    )
    with pytest.raises(PermissionError, match="REPOSITORY_NOT_ALLOWED"):
        adapter.apply_proposal_operation(plan_digest=plan.plan_digest, operation=wrong_repo)
    wrong_branch = type(operation)(
        action=operation.action,
        parameters={**operation.parameters, "branch": "main"},
    )
    with pytest.raises(PermissionError, match="BRANCH_NOT_ALLOWED"):
        adapter.apply_proposal_operation(plan_digest=plan.plan_digest, operation=wrong_branch)


def test_transport_never_exposes_token_in_repr_or_exception() -> None:
    token = "ghs_super_secret_value"

    class FailingSession:
        def request(self, *args, **kwargs):
            del args, kwargs
            raise requests.RequestException(f"network failed with {token}")

    transport = RequestsGitHubTransport(token=token, session=FailingSession())  # type: ignore[arg-type]
    assert token not in repr(transport)
    with pytest.raises(GitHubProposalTransportError) as raised:
        transport.request("GET", "/repos/jsp1440/orchid-calyx-backend")
    assert token not in str(raised.value)


def test_change_hash_fixture_is_exact() -> None:
    assert hashlib.sha256(PATCH_BYTES).hexdigest() == PATCH_AFTER
