from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

_SAFE_BRANCH = re.compile(r"^[a-z0-9][a-z0-9._/-]{2,120}$")
_SAFE_PATH = re.compile(r"^(?!/)(?!.*\.\.)(?!\.github/workflows/)[A-Za-z0-9._/-]{1,240}$")


class GitHubAutomationError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileChange:
    path: str
    content: str
    message: str

    def validate(self) -> None:
        if not _SAFE_PATH.fullmatch(self.path):
            raise ValueError("UNSAFE_ENGINEERING_PATH")
        if len(self.content.encode("utf-8")) > 250_000:
            raise ValueError("ENGINEERING_FILE_TOO_LARGE")
        if not self.message.strip():
            raise ValueError("COMMIT_MESSAGE_REQUIRED")


class GitHubEngineeringClient:
    def __init__(self, repository: str, token: str | None = None) -> None:
        if repository.count("/") != 1:
            raise ValueError("GITHUB_REPOSITORY_INVALID")
        self.repository = repository
        self.token = token or os.getenv("GITHUB_TOKEN") or ""
        if not self.token:
            raise RuntimeError("GITHUB_TOKEN_NOT_CONFIGURED")
        self.api = f"https://api.github.com/repos/{repository}"

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            f"{self.api}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "calyx-preproduction-engineer",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise GitHubAutomationError(f"GITHUB_HTTP_{exc.code}:{detail}") from exc
        except URLError as exc:
            raise GitHubAutomationError("GITHUB_UNREACHABLE") from exc

    @staticmethod
    def _encoded_path(path: str) -> str:
        if not _SAFE_PATH.fullmatch(path):
            raise ValueError("UNSAFE_ENGINEERING_PATH")
        return quote(path, safe="/")

    def default_branch_sha(self, branch: str = "main") -> str:
        return str(self._request("GET", f"/git/ref/heads/{branch}")["object"]["sha"])

    def get_text_file(self, path: str, *, ref: str = "main") -> str:
        encoded_path = self._encoded_path(path)
        payload = self._request("GET", f"/contents/{encoded_path}?ref={quote(ref, safe='/-_.')}")
        if payload.get("type") != "file" or payload.get("encoding") != "base64":
            raise GitHubAutomationError("GITHUB_FILE_CONTENT_UNAVAILABLE")
        raw = base64.b64decode(str(payload.get("content", "")), validate=False)
        if len(raw) > 250_000:
            raise ValueError("INSPECTION_FILE_TOO_LARGE")
        return raw.decode("utf-8")

    def create_issue(self, title: str, body: str) -> dict:
        return self._request("POST", "/issues", {"title": title, "body": body})

    def create_branch(self, branch: str, base_sha: str) -> dict:
        if not _SAFE_BRANCH.fullmatch(branch):
            raise ValueError("UNSAFE_ENGINEERING_BRANCH")
        return self._request("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": base_sha})

    def put_file(self, branch: str, change: FileChange) -> dict:
        change.validate()
        encoded_path = self._encoded_path(change.path)
        payload = {
            "message": change.message,
            "content": base64.b64encode(change.content.encode()).decode(),
            "branch": branch,
        }
        try:
            current = self._request("GET", f"/contents/{encoded_path}?ref={quote(branch, safe='/-_.')}")
            payload["sha"] = current["sha"]
        except GitHubAutomationError as exc:
            if not str(exc).startswith("GITHUB_HTTP_404"):
                raise
        return self._request("PUT", f"/contents/{encoded_path}", payload)

    def open_pull_request(self, title: str, body: str, branch: str, base: str = "main") -> dict:
        return self._request(
            "POST",
            "/pulls",
            {"title": title, "body": body, "head": branch, "base": base, "draft": True},
        )

    def pull_request(self, number: int) -> dict:
        return self._request("GET", f"/pulls/{number}")

    def workflow_runs_for_head(self, head_sha: str) -> list[dict]:
        payload = self._request("GET", f"/actions/runs?head_sha={quote(head_sha, safe='')}&per_page=50")
        return list(payload.get("workflow_runs", []))

    def workflow_jobs(self, run_id: int) -> list[dict]:
        payload = self._request("GET", f"/actions/runs/{run_id}/jobs?per_page=100")
        return list(payload.get("jobs", []))

    def workflow_job_logs(self, job_id: int) -> str:
        request = Request(
            f"{self.api}/actions/jobs/{job_id}/logs",
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "calyx-preproduction-engineer",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")[-50_000:]
        except HTTPError as exc:
            raise GitHubAutomationError(f"GITHUB_HTTP_{exc.code}:workflow_job_logs") from exc
        except URLError as exc:
            raise GitHubAutomationError("GITHUB_UNREACHABLE") from exc
