from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
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
            with urlopen(request, timeout=30) as response:  # noqa: S310
                raw = response.read()
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise GitHubAutomationError(f"GITHUB_HTTP_{exc.code}:{detail}") from exc
        except URLError as exc:
            raise GitHubAutomationError("GITHUB_UNREACHABLE") from exc

    def default_branch_sha(self, branch: str = "main") -> str:
        return str(self._request("GET", f"/git/ref/heads/{branch}")["object"]["sha"])

    def create_issue(self, title: str, body: str) -> dict:
        return self._request("POST", "/issues", {"title": title, "body": body})

    def create_branch(self, branch: str, base_sha: str) -> dict:
        if not _SAFE_BRANCH.fullmatch(branch):
            raise ValueError("UNSAFE_ENGINEERING_BRANCH")
        return self._request("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": base_sha})

    def put_file(self, branch: str, change: FileChange) -> dict:
        change.validate()
        encoded_path = "/".join(part.replace(" ", "%20") for part in change.path.split("/"))
        payload = {
            "message": change.message,
            "content": base64.b64encode(change.content.encode()).decode(),
            "branch": branch,
        }
        try:
            current = self._request("GET", f"/contents/{encoded_path}?ref={branch}")
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
