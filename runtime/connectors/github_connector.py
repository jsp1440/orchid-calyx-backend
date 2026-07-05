"""Read-only GitHub connector for Calyx.

BUILD-021 establishes the first production connector on top of the
BUILD-020 Connector Execution Framework. It intentionally supports only
safe read operations so Calyx can inspect repository state before later
builds add write capabilities.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from ..connector_interface import ConnectorInterface


class GitHubConnector(ConnectorInterface):
    """Read-only GitHub repository inspection connector.

    Supported tasks:
    - status / repo_status: repository metadata
    - list_open_prs: recent open pull requests
    - list_recent_commits: recent commits on the default branch

    This connector is dependency-light and does not require PyGithub. It uses
    the public GitHub REST API through urllib. Private repositories require a
    token via CALYX_GITHUB_TOKEN or GITHUB_TOKEN.
    """

    default_repo = "jsp1440/orchid-calyx-backend"

    @property
    def name(self) -> str:
        return "github"

    def health(self) -> dict[str, Any]:
        repo = os.environ.get("GITHUB_REPOSITORY", self.default_repo)
        token_configured = bool(self._token())
        return {
            "status": "healthy",
            "name": self.name,
            "repo": repo,
            "token_configured": token_configured,
            "mode": "read_only",
            "timestamp": self._now(),
        }

    def execute(self, task: str, **kwargs) -> dict[str, Any]:
        repo = kwargs.get("repo") or os.environ.get("GITHUB_REPOSITORY", self.default_repo)
        limit = int(kwargs.get("limit", 10))
        limit = max(1, min(limit, 50))

        if task in {"status", "repo_status"}:
            return self._repo_status(repo)
        if task == "list_open_prs":
            return self._list_open_prs(repo, limit)
        if task == "list_recent_commits":
            return self._list_recent_commits(repo, limit)

        raise ValueError(f"Unknown GitHub task: {task}")

    def _repo_status(self, repo: str) -> dict[str, Any]:
        data = self._request(f"/repos/{repo}")
        return {
            "repo": data.get("full_name", repo),
            "private": data.get("private"),
            "default_branch": data.get("default_branch"),
            "visibility": data.get("visibility"),
            "open_issues_count": data.get("open_issues_count"),
            "updated_at": data.get("updated_at"),
            "pushed_at": data.get("pushed_at"),
            "html_url": data.get("html_url"),
        }

    def _list_open_prs(self, repo: str, limit: int) -> dict[str, Any]:
        rows = self._request(f"/repos/{repo}/pulls?state=open&per_page={limit}")
        return {
            "repo": repo,
            "count": len(rows),
            "pull_requests": [
                {
                    "number": row.get("number"),
                    "title": row.get("title"),
                    "state": row.get("state"),
                    "draft": row.get("draft"),
                    "user": (row.get("user") or {}).get("login"),
                    "head": (row.get("head") or {}).get("ref"),
                    "base": (row.get("base") or {}).get("ref"),
                    "created_at": row.get("created_at"),
                    "updated_at": row.get("updated_at"),
                    "html_url": row.get("html_url"),
                }
                for row in rows
            ],
        }

    def _list_recent_commits(self, repo: str, limit: int) -> dict[str, Any]:
        rows = self._request(f"/repos/{repo}/commits?per_page={limit}")
        return {
            "repo": repo,
            "count": len(rows),
            "commits": [
                {
                    "sha": row.get("sha"),
                    "message": ((row.get("commit") or {}).get("message") or "").splitlines()[0],
                    "author": (((row.get("commit") or {}).get("author") or {}).get("name")),
                    "date": (((row.get("commit") or {}).get("author") or {}).get("date")),
                    "html_url": row.get("html_url"),
                }
                for row in rows
            ],
        }

    def _request(self, path: str) -> Any:
        import json
        import urllib.error
        import urllib.request

        url = f"https://api.github.com{path}"
        request = urllib.request.Request(url)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        token = self._token()
        if token:
            request.add_header("Authorization", f"Bearer {token}")

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API error {exc.code}: {details}") from exc

    def _token(self) -> str | None:
        return os.environ.get("CALYX_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
