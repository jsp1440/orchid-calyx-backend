from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import quote

import requests

from .git_proposal_execution_plan import GitProposalPlanOperation
from .git_proposal_mutation_executor import (
    ALLOWED_BRANCH_PREFIX,
    GitProposalMutationReceipt,
)

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_FILE_MODES = frozenset({"100644", "100755", "120000"})
_CALYX_GIT_NAME = "CALYX Autonomous Engineering"
_CALYX_GIT_EMAIL = "calyx-autonomy@users.noreply.github.com"


def _git_sha(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(normalized):
        raise PermissionError("GITHUB_ADAPTER_GIT_SHA_INVALID")
    return normalized


def _sha256(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise PermissionError("GITHUB_ADAPTER_SHA256_INVALID")
    return normalized


def _repository(value: object) -> str:
    normalized = str(value or "").strip()
    if not _REPOSITORY_RE.fullmatch(normalized):
        raise PermissionError("GITHUB_ADAPTER_REPOSITORY_INVALID")
    return normalized


def _branch(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized.startswith(ALLOWED_BRANCH_PREFIX):
        raise PermissionError("GITHUB_ADAPTER_BRANCH_NOT_ALLOWED")
    if normalized.startswith("/") or ".." in normalized.split("/") or "\x00" in normalized:
        raise PermissionError("GITHUB_ADAPTER_BRANCH_INVALID")
    return normalized


def _file_path(value: object) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    parts = normalized.split("/")
    if (
        not normalized
        or normalized.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or "\x00" in normalized
    ):
        raise PermissionError("GITHUB_ADAPTER_FILE_PATH_INVALID")
    return normalized


def _blob_sha(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


def _identity_from_iso8601(value: str) -> tuple[int, str]:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise PermissionError("GITHUB_ADAPTER_BASE_COMMIT_DATE_INVALID") from exc
    offset = parsed.utcoffset()
    if offset is None:
        raise PermissionError("GITHUB_ADAPTER_BASE_COMMIT_DATE_INVALID")
    seconds = int(offset.total_seconds())
    sign = "+" if seconds >= 0 else "-"
    seconds = abs(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return int(parsed.timestamp()), f"{sign}{hours:02d}{minutes:02d}"


def _expected_commit_sha(
    *,
    tree_sha: str,
    parent_sha: str,
    message: str,
    author_date: str,
) -> str:
    timestamp, timezone = _identity_from_iso8601(author_date)
    identity = f"{_CALYX_GIT_NAME} <{_CALYX_GIT_EMAIL}> {timestamp} {timezone}"
    payload = (
        f"tree {tree_sha}\n"
        f"parent {parent_sha}\n"
        f"author {identity}\n"
        f"committer {identity}\n"
        f"\n{message}\n"
    ).encode()
    header = f"commit {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()


@dataclass(frozen=True, slots=True)
class GitHubTransportResponse:
    status_code: int
    payload: object


class GitHubTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> GitHubTransportResponse: ...


class ProposalPostimageResolver(Protocol):
    def resolve_postimage(self, *, patch_program_job_id: str, path: str) -> bytes: ...


class ProposalEvidenceResolver(Protocol):
    def latest(self, *, plan_digest: str) -> GitProposalMutationReceipt | None: ...


class GitHubProposalTransportError(RuntimeError):
    """Remote GitHub failure deliberately stripped of credential-bearing details."""

    def __init__(self, code: str, *, status_code: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class RequestsGitHubTransport:
    """Least-surface GitHub REST transport. The token is never exposed in repr/errors."""

    def __init__(
        self,
        *,
        token: str,
        base_url: str = "https://api.github.com",
        timeout_seconds: float = 15.0,
        session: requests.Session | None = None,
    ) -> None:
        if not token.strip():
            raise ValueError("GITHUB_ADAPTER_TOKEN_REQUIRED")
        if timeout_seconds <= 0 or timeout_seconds > 60:
            raise ValueError("GITHUB_ADAPTER_TIMEOUT_INVALID")
        self._token = token.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(base_url={self._base_url!r}, "
            "token=<redacted>)"
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> GitHubTransportResponse:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("GITHUB_ADAPTER_REQUEST_PATH_INVALID")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "orchid-continuum-calyx-autonomy",
        }
        try:
            response = self._session.request(
                method.upper(),
                f"{self._base_url}{path}",
                headers=headers,
                json=None if json_body is None else dict(json_body),
                params=None if params is None else dict(params),
                timeout=self._timeout_seconds,
            )
        except requests.RequestException:
            raise GitHubProposalTransportError(
                "GITHUB_ADAPTER_TRANSPORT_REQUEST_FAILED"
            ) from None
        try:
            payload: object = response.json() if response.content else {}
        except ValueError:
            raise GitHubProposalTransportError(
                "GITHUB_ADAPTER_TRANSPORT_RESPONSE_INVALID",
                status_code=response.status_code,
            ) from None
        return GitHubTransportResponse(
            status_code=response.status_code,
            payload=payload,
        )


class GitHubProposalMutationAdapter:
    """GitHub-only adapter for the four reviewed draft-proposal mutation actions."""

    def __init__(
        self,
        *,
        transport: GitHubTransport,
        postimages: ProposalPostimageResolver,
        evidence: ProposalEvidenceResolver,
        repository_allowlist: Sequence[str],
    ) -> None:
        allowlist = frozenset(_repository(item) for item in repository_allowlist)
        if not allowlist:
            raise ValueError("GITHUB_ADAPTER_REPOSITORY_ALLOWLIST_REQUIRED")
        self._transport = transport
        self._postimages = postimages
        self._evidence = evidence
        self._repository_allowlist = allowlist

    def apply_proposal_operation(
        self,
        *,
        plan_digest: str,
        operation: GitProposalPlanOperation,
    ) -> Mapping[str, Any]:
        digest = _sha256(plan_digest)
        parameters = dict(operation.parameters)
        repository = _repository(parameters.get("repository"))
        if repository not in self._repository_allowlist:
            raise PermissionError("GITHUB_ADAPTER_REPOSITORY_NOT_ALLOWED")
        if operation.action == "create_branch":
            return self._create_branch(digest, repository, parameters)
        if operation.action == "create_commit":
            return self._create_commit(digest, repository, parameters)
        if operation.action == "push_branch":
            return self._push_branch(digest, repository, parameters)
        if operation.action == "open_pull_request":
            return self._open_pull_request(digest, repository, parameters)
        raise PermissionError("GITHUB_ADAPTER_ACTION_NOT_ALLOWED")

    def _create_branch(
        self,
        plan_digest: str,
        repository: str,
        parameters: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        del plan_digest
        branch = _branch(parameters.get("branch"))
        base_commit_sha = _git_sha(parameters.get("base_commit_sha"))
        existing = self._get_ref(repository, branch)
        if existing is not None:
            if existing != base_commit_sha:
                raise PermissionError("GITHUB_ADAPTER_BRANCH_ALREADY_EXISTS_MISMATCH")
            status = "already_exists_exact"
        else:
            response = self._transport.request(
                "POST",
                f"/repos/{repository}/git/refs",
                json_body={"ref": f"refs/heads/{branch}", "sha": base_commit_sha},
            )
            self._require_status(response, {201}, "GITHUB_ADAPTER_BRANCH_CREATE_FAILED")
            status = "created"
        verified = self._get_ref(repository, branch)
        if verified != base_commit_sha:
            raise PermissionError("GITHUB_ADAPTER_BRANCH_VERIFY_FAILED")
        return {
            "action": "create_branch",
            "status": status,
            "repository": repository,
            "branch": branch,
            "base_commit_sha": base_commit_sha,
        }

    def _create_commit(
        self,
        plan_digest: str,
        repository: str,
        parameters: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        branch = _branch(parameters.get("branch"))
        base_commit_sha = _git_sha(parameters.get("base_commit_sha"))
        patch_job = str(parameters.get("patch_program_job_id") or "").strip()
        commit_title = str(parameters.get("commit_title") or "").strip()
        if not patch_job or not commit_title:
            raise PermissionError("GITHUB_ADAPTER_COMMIT_METADATA_INVALID")
        if self._get_ref(repository, branch) != base_commit_sha:
            raise PermissionError("GITHUB_ADAPTER_COMMIT_BRANCH_BASE_MISMATCH")

        changes = self._change_hashes(parameters.get("change_hashes"))
        base_commit = self._get_mapping(
            repository,
            f"/repos/{repository}/git/commits/{base_commit_sha}",
            "GITHUB_ADAPTER_BASE_COMMIT_LOOKUP_FAILED",
        )
        base_tree_sha = _git_sha(self._nested(base_commit, "tree", "sha"))
        author_date = str(self._nested(base_commit, "committer", "date") or "").strip()
        _identity_from_iso8601(author_date)
        modes = self._base_tree_modes(repository, base_tree_sha)

        entries: list[dict[str, str]] = []
        for path, expected_hash in changes:
            content = self._postimages.resolve_postimage(
                patch_program_job_id=patch_job,
                path=path,
            )
            if not isinstance(content, bytes):
                raise TypeError("GITHUB_ADAPTER_POSTIMAGE_BYTES_REQUIRED")
            if hashlib.sha256(content).hexdigest() != expected_hash:
                raise PermissionError("GITHUB_ADAPTER_POSTIMAGE_HASH_MISMATCH")
            expected_blob_sha = _blob_sha(content)
            blob_response = self._transport.request(
                "POST",
                f"/repos/{repository}/git/blobs",
                json_body={
                    "content": base64.b64encode(content).decode("ascii"),
                    "encoding": "base64",
                },
            )
            self._require_status(
                blob_response,
                {201},
                "GITHUB_ADAPTER_BLOB_CREATE_FAILED",
            )
            blob_payload = self._mapping(blob_response.payload)
            if _git_sha(blob_payload.get("sha")) != expected_blob_sha:
                raise PermissionError("GITHUB_ADAPTER_BLOB_SHA_MISMATCH")
            mode = modes.get(path, "100644")
            if mode not in _SAFE_FILE_MODES:
                raise PermissionError("GITHUB_ADAPTER_FILE_MODE_NOT_ALLOWED")
            entries.append(
                {"path": path, "mode": mode, "type": "blob", "sha": expected_blob_sha}
            )

        tree_response = self._transport.request(
            "POST",
            f"/repos/{repository}/git/trees",
            json_body={"base_tree": base_tree_sha, "tree": entries},
        )
        self._require_status(tree_response, {201}, "GITHUB_ADAPTER_TREE_CREATE_FAILED")
        tree_sha = _git_sha(self._mapping(tree_response.payload).get("sha"))
        self._verify_tree_postimages(repository, tree_sha, entries)

        message = (
            f"{commit_title}\n\n"
            f"CALYX-Plan: {plan_digest}\n"
            f"Patch-Program-Job: {patch_job}"
        )
        expected_commit = _expected_commit_sha(
            tree_sha=tree_sha,
            parent_sha=base_commit_sha,
            message=message,
            author_date=author_date,
        )
        existing = self._get_commit(repository, expected_commit)
        if existing is not None:
            self._verify_commit(
                existing,
                expected_sha=expected_commit,
                tree_sha=tree_sha,
                parent_sha=base_commit_sha,
                message=message,
            )
            status = "already_exists_exact"
        else:
            identity = {
                "name": _CALYX_GIT_NAME,
                "email": _CALYX_GIT_EMAIL,
                "date": author_date,
            }
            commit_response = self._transport.request(
                "POST",
                f"/repos/{repository}/git/commits",
                json_body={
                    "message": message,
                    "tree": tree_sha,
                    "parents": [base_commit_sha],
                    "author": identity,
                    "committer": identity,
                },
            )
            self._require_status(
                commit_response,
                {201},
                "GITHUB_ADAPTER_COMMIT_CREATE_FAILED",
            )
            created_sha = _git_sha(self._mapping(commit_response.payload).get("sha"))
            if created_sha != expected_commit:
                raise PermissionError("GITHUB_ADAPTER_COMMIT_SHA_MISMATCH")
            status = "created"
        verified = self._get_commit(repository, expected_commit)
        if verified is None:
            raise PermissionError("GITHUB_ADAPTER_COMMIT_VERIFY_FAILED")
        self._verify_commit(
            verified,
            expected_sha=expected_commit,
            tree_sha=tree_sha,
            parent_sha=base_commit_sha,
            message=message,
        )
        return {
            "action": "create_commit",
            "status": status,
            "repository": repository,
            "branch": branch,
            "parent_commit_sha": base_commit_sha,
            "commit_sha": expected_commit,
            "patch_program_job_id": patch_job,
            "change_hashes": [
                {"path": path, "after_sha256": digest} for path, digest in changes
            ],
            "tree_sha": tree_sha,
        }

    def _push_branch(
        self,
        plan_digest: str,
        repository: str,
        parameters: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        branch = _branch(parameters.get("branch"))
        receipt = self._required_receipt(plan_digest, repository, branch)
        expected_commit = self._receipt_commit_sha(receipt)
        current = self._get_ref(repository, branch)
        if current == expected_commit:
            status = "already_exists_exact"
        elif current == receipt.base_commit_sha:
            response = self._transport.request(
                "PATCH",
                f"/repos/{repository}/git/refs/{quote(f'heads/{branch}', safe='')}",
                json_body={"sha": expected_commit, "force": False},
            )
            self._require_status(response, {200}, "GITHUB_ADAPTER_PUSH_FAILED")
            status = "created"
        else:
            raise PermissionError("GITHUB_ADAPTER_PUSH_BRANCH_STATE_MISMATCH")
        if self._get_ref(repository, branch) != expected_commit:
            raise PermissionError("GITHUB_ADAPTER_PUSH_VERIFY_FAILED")
        return {
            "action": "push_branch",
            "status": status,
            "repository": repository,
            "branch": branch,
            "commit_sha": expected_commit,
        }

    def _open_pull_request(
        self,
        plan_digest: str,
        repository: str,
        parameters: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        branch = _branch(parameters.get("head_branch"))
        base_ref = str(parameters.get("base_ref") or "").strip()
        base_commit_sha = _git_sha(parameters.get("base_commit_sha"))
        pr_title = str(parameters.get("pr_title") or "").strip()
        summary = str(parameters.get("summary") or "").strip()
        if not base_ref or not pr_title or not summary:
            raise PermissionError("GITHUB_ADAPTER_PR_METADATA_INVALID")
        receipt = self._required_receipt(plan_digest, repository, branch)
        if receipt.base_ref != base_ref or receipt.base_commit_sha != base_commit_sha:
            raise PermissionError("GITHUB_ADAPTER_PR_RECEIPT_BASE_MISMATCH")
        expected_commit = self._receipt_commit_sha(receipt)
        if self._get_ref(repository, branch) != expected_commit:
            raise PermissionError("GITHUB_ADAPTER_PR_HEAD_MISMATCH")
        if self._get_ref(repository, base_ref, proposal_only=False) != base_commit_sha:
            raise PermissionError("GITHUB_ADAPTER_PR_BASE_MOVED")

        owner = repository.split("/", 1)[0]
        existing = self._transport.request(
            "GET",
            f"/repos/{repository}/pulls",
            params={"state": "open", "head": f"{owner}:{branch}", "base": base_ref},
        )
        self._require_status(existing, {200}, "GITHUB_ADAPTER_PR_LOOKUP_FAILED")
        pulls = self._sequence(existing.payload)
        exact = [
            pull
            for pull in pulls
            if self._pull_matches(
                pull,
                branch=branch,
                base_ref=base_ref,
                base_commit_sha=base_commit_sha,
                head_sha=expected_commit,
                require_draft=True,
            )
        ]
        if len(exact) > 1 or (pulls and not exact):
            raise PermissionError("GITHUB_ADAPTER_PR_IDEMPOTENCY_MISMATCH")
        if exact:
            pull = exact[0]
            status = "already_exists_exact"
        else:
            body = (
                f"{summary}\n\n"
                f"---\nCALYX governed proposal\n"
                f"Plan digest: `{plan_digest}`\n"
                f"Patch program job: `{receipt.patch_program_job_id}`\n"
                "Merge is not authorized by this proposal execution."
            )
            response = self._transport.request(
                "POST",
                f"/repos/{repository}/pulls",
                json_body={
                    "title": pr_title,
                    "head": branch,
                    "base": base_ref,
                    "body": body,
                    "draft": True,
                    "maintainer_can_modify": False,
                },
            )
            self._require_status(response, {201}, "GITHUB_ADAPTER_PR_CREATE_FAILED")
            pull = self._mapping(response.payload)
            if not self._pull_matches(
                pull,
                branch=branch,
                base_ref=base_ref,
                base_commit_sha=base_commit_sha,
                head_sha=expected_commit,
                require_draft=True,
            ):
                raise PermissionError("GITHUB_ADAPTER_PR_VERIFY_FAILED")
            status = "created"
        number = pull.get("number")
        if type(number) is not int or number <= 0:
            raise PermissionError("GITHUB_ADAPTER_PR_NUMBER_INVALID")
        url = str(pull.get("html_url") or "").strip()
        return {
            "action": "open_pull_request",
            "status": status,
            "repository": repository,
            "branch": branch,
            "head_branch": branch,
            "base_ref": base_ref,
            "base_commit_sha": base_commit_sha,
            "head_commit_sha": expected_commit,
            "pull_request_number": number,
            "pull_request_url": url,
            "draft": True,
        }

    def _required_receipt(
        self,
        plan_digest: str,
        repository: str,
        branch: str,
    ) -> GitProposalMutationReceipt:
        receipt = self._evidence.latest(plan_digest=plan_digest)
        if receipt is None:
            raise PermissionError("GITHUB_ADAPTER_PRIOR_EVIDENCE_REQUIRED")
        if (
            receipt.plan_digest != plan_digest
            or receipt.repository != repository
            or receipt.proposed_branch != branch
        ):
            raise PermissionError("GITHUB_ADAPTER_PRIOR_EVIDENCE_MISMATCH")
        return receipt

    @staticmethod
    def _receipt_commit_sha(receipt: GitProposalMutationReceipt) -> str:
        matches = [
            item
            for item in receipt.operation_evidence
            if item.action == "create_commit"
        ]
        if len(matches) != 1:
            raise PermissionError("GITHUB_ADAPTER_COMMIT_EVIDENCE_REQUIRED")
        return _git_sha(matches[0].payload.get("commit_sha"))

    def _get_ref(
        self,
        repository: str,
        branch: str,
        *,
        proposal_only: bool = True,
    ) -> str | None:
        normalized = _branch(branch) if proposal_only else branch.strip()
        if not normalized:
            raise PermissionError("GITHUB_ADAPTER_REF_INVALID")
        response = self._transport.request(
            "GET",
            f"/repos/{repository}/git/ref/{quote(f'heads/{normalized}', safe='')}",
        )
        if response.status_code == 404:
            return None
        self._require_status(response, {200}, "GITHUB_ADAPTER_REF_LOOKUP_FAILED")
        payload = self._mapping(response.payload)
        return _git_sha(self._nested(payload, "object", "sha"))

    def _get_commit(self, repository: str, commit_sha: str) -> Mapping[str, Any] | None:
        response = self._transport.request(
            "GET",
            f"/repos/{repository}/git/commits/{commit_sha}",
        )
        if response.status_code == 404:
            return None
        self._require_status(response, {200}, "GITHUB_ADAPTER_COMMIT_LOOKUP_FAILED")
        return self._mapping(response.payload)

    def _base_tree_modes(self, repository: str, tree_sha: str) -> dict[str, str]:
        response = self._transport.request(
            "GET",
            f"/repos/{repository}/git/trees/{tree_sha}",
            params={"recursive": "1"},
        )
        self._require_status(response, {200}, "GITHUB_ADAPTER_TREE_LOOKUP_FAILED")
        payload = self._mapping(response.payload)
        if payload.get("truncated") is True:
            raise PermissionError("GITHUB_ADAPTER_BASE_TREE_TRUNCATED")
        modes: dict[str, str] = {}
        for raw in self._sequence(payload.get("tree")):
            item = self._mapping(raw)
            if item.get("type") != "blob":
                continue
            path = _file_path(item.get("path"))
            mode = str(item.get("mode") or "").strip()
            if mode in _SAFE_FILE_MODES:
                modes[path] = mode
        return modes

    def _verify_tree_postimages(
        self,
        repository: str,
        tree_sha: str,
        entries: Sequence[Mapping[str, str]],
    ) -> None:
        response = self._transport.request(
            "GET",
            f"/repos/{repository}/git/trees/{tree_sha}",
            params={"recursive": "1"},
        )
        self._require_status(response, {200}, "GITHUB_ADAPTER_TREE_VERIFY_FAILED")
        payload = self._mapping(response.payload)
        if payload.get("truncated") is True:
            raise PermissionError("GITHUB_ADAPTER_TREE_VERIFY_TRUNCATED")
        actual = {
            _file_path(item.get("path")): (
                str(item.get("mode") or "").strip(),
                _git_sha(item.get("sha")),
            )
            for raw in self._sequence(payload.get("tree"))
            if (item := self._mapping(raw)).get("type") == "blob"
        }
        for entry in entries:
            if actual.get(entry["path"]) != (entry["mode"], entry["sha"]):
                raise PermissionError("GITHUB_ADAPTER_TREE_POSTIMAGE_MISMATCH")

    @staticmethod
    def _verify_commit(
        payload: Mapping[str, Any],
        *,
        expected_sha: str,
        tree_sha: str,
        parent_sha: str,
        message: str,
    ) -> None:
        if _git_sha(payload.get("sha")) != expected_sha:
            raise PermissionError("GITHUB_ADAPTER_COMMIT_VERIFY_SHA_MISMATCH")
        if _git_sha(GitHubProposalMutationAdapter._nested(payload, "tree", "sha")) != tree_sha:
            raise PermissionError("GITHUB_ADAPTER_COMMIT_VERIFY_TREE_MISMATCH")
        parents = GitHubProposalMutationAdapter._sequence(payload.get("parents"))
        if len(parents) != 1 or _git_sha(
            GitHubProposalMutationAdapter._mapping(parents[0]).get("sha")
        ) != parent_sha:
            raise PermissionError("GITHUB_ADAPTER_COMMIT_VERIFY_PARENT_MISMATCH")
        if str(payload.get("message") or "") != message:
            raise PermissionError("GITHUB_ADAPTER_COMMIT_VERIFY_MESSAGE_MISMATCH")

    @staticmethod
    def _pull_matches(
        payload: Mapping[str, Any],
        *,
        branch: str,
        base_ref: str,
        base_commit_sha: str,
        head_sha: str,
        require_draft: bool,
    ) -> bool:
        try:
            head = GitHubProposalMutationAdapter._mapping(payload.get("head"))
            base = GitHubProposalMutationAdapter._mapping(payload.get("base"))
            return (
                str(head.get("ref") or "") == branch
                and _git_sha(head.get("sha")) == head_sha
                and str(base.get("ref") or "") == base_ref
                and _git_sha(base.get("sha")) == base_commit_sha
                and payload.get("draft") is require_draft
            )
        except (PermissionError, TypeError):
            return False

    @staticmethod
    def _change_hashes(value: object) -> tuple[tuple[str, str], ...]:
        items = GitHubProposalMutationAdapter._sequence(value)
        if not items:
            raise PermissionError("GITHUB_ADAPTER_CHANGE_HASHES_REQUIRED")
        changes: list[tuple[str, str]] = []
        seen: set[str] = set()
        for raw in items:
            item = GitHubProposalMutationAdapter._mapping(raw)
            path = _file_path(item.get("path"))
            if path in seen:
                raise PermissionError("GITHUB_ADAPTER_CHANGE_PATH_DUPLICATE")
            seen.add(path)
            changes.append((path, _sha256(item.get("after_sha256"))))
        return tuple(changes)

    def _get_mapping(self, repository: str, path: str, code: str) -> Mapping[str, Any]:
        response = self._transport.request("GET", path)
        self._require_status(response, {200}, code)
        return self._mapping(response.payload)

    @staticmethod
    def _require_status(
        response: GitHubTransportResponse,
        allowed: set[int],
        code: str,
    ) -> None:
        if response.status_code not in allowed:
            raise GitHubProposalTransportError(code, status_code=response.status_code)

    @staticmethod
    def _mapping(value: object) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("GITHUB_ADAPTER_RESPONSE_MAPPING_REQUIRED")
        return value

    @staticmethod
    def _sequence(value: object) -> Sequence[Any]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            raise TypeError("GITHUB_ADAPTER_RESPONSE_SEQUENCE_REQUIRED")
        return value

    @staticmethod
    def _nested(value: Mapping[str, Any], parent: str, child: str) -> object:
        nested = value.get(parent)
        if not isinstance(nested, Mapping):
            raise TypeError("GITHUB_ADAPTER_RESPONSE_MAPPING_REQUIRED")
        return nested.get(child)
