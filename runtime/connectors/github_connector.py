"""Read-only GitHub connector for Calyx.

BUILD-021 established the first production connector on top of the
BUILD-020 Connector Execution Framework. BUILD-023 expands it with safe
file-inspection tasks so Calyx can inspect repository structure and source
files before later builds add write capabilities.
"""

from __future__ import annotations

import base64
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from ..connector_interface import ConnectorInterface


class GitHubConnector(ConnectorInterface):
    """Read-only GitHub repository inspection connector.

    Supported tasks:
    - status / repo_status: repository metadata
    - list_open_prs: recent open pull requests
    - list_recent_commits: recent commits on the default branch
    - branch_status: branch metadata and latest commit
    - repo_tree: recursive repository tree from a branch
    - list_files: filtered file listing from the repository tree
    - get_file: decoded UTF-8 file contents by path

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
            "supported_tasks": [
                "repo_status",
                "list_open_prs",
                "list_recent_commits",
                "branch_status",
                "repo_tree",
                "list_files",
                "get_file",
            ],
            "timestamp": self._now(),
        }

    def execute(self, task: str, **kwargs) -> dict[str, Any]:
        repo = kwargs.get("repo") or os.environ.get("GITHUB_REPOSITORY", self.default_repo)
        limit = int(kwargs.get("limit", 10))
        limit = max(1, min(limit, 200))
        branch = kwargs.get("branch") or kwargs.get("ref") or "main"

        if task in {"status", "repo_status"}:
            return self._repo_status(repo)
        if task == "list_open_prs":
            return self._list_open_prs(repo, min(limit, 50))
        if task == "list_recent_commits":
            return self._list_recent_commits(repo, min(limit, 50))
        if task == "branch_status":
            return self._branch_status(repo, branch)
        if task == "repo_tree":
            return self._repo_tree(repo, branch, limit)
        if task == "list_files":
            path_prefix = kwargs.get("path_prefix") or kwargs.get("path") or ""
            return self._list_files(repo, branch, limit, path_prefix)
        if task == "get_file":
            path = kwargs.get("path")
            if not path:
                raise ValueError("get_file requires kwargs.path")
            return self._get_file(repo, path, branch)

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

    def _branch_status(self, repo: str, branch: str) -> dict[str, Any]:
        data = self._request(f"/repos/{repo}/branches/{quote(branch, safe='')}")
        commit = data.get("commit") or {}
        return {
            "repo": repo,
            "branch": data.get("name", branch),
            "protected": data.get("protected"),
            "commit_sha": commit.get("sha"),
            "commit_url": commit.get("url"),
        }

    def _repo_tree(self, repo: str, branch: str, limit: int) -> dict[str, Any]:
        branch_data = self._request(f"/repos/{repo}/branches/{quote(branch, safe='')}")
        commit_sha = (branch_data.get("commit") or {}).get("sha")
        if not commit_sha:
            raise RuntimeError(f"Could not resolve branch commit for {repo}@{branch}")

        tree_data = self._request(f"/repos/{repo}/git/trees/{commit_sha}?recursive=1")
        tree = tree_data.get("tree") or []
        limited = tree[:limit]
        return {
            "repo": repo,
            "branch": branch,
            "commit_sha": commit_sha,
            "truncated_by_github": tree_data.get("truncated", False),
            "count": len(limited),
            "total_returned_by_github": len(tree),
            "items": [
                {
                    "path": item.get("path"),
                    "type": item.get("type"),
                    "size": item.get("size"),
                    "sha": item.get("sha"),
                }
                for item in limited
            ],
        }

    def _list_files(self, repo: str, branch: str, limit: int, path_prefix: str = "") -> dict[str, Any]:
        tree = self._repo_tree(repo, branch, 10000)
        files = [item for item in tree["items"] if item.get("type") == "blob"]
        if path_prefix:
            files = [item for item in files if (item.get("path") or "").startswith(path_prefix)]
        files = files[:limit]
        return {
            "repo": repo,
            "branch": branch,
            "path_prefix": path_prefix,
            "count": len(files),
            "files": files,
        }

    def _get_file(self, repo: str, path: str, branch: str) -> dict[str, Any]:
        quoted_path = quote(path, safe="/")
        data = self._request(f"/repos/{repo}/contents/{quoted_path}?ref={quote(branch, safe='')}")
        if data.get("type") != "file":
            raise ValueError(f"Path is not a file: {path}")
        encoding = data.get("encoding")
        content = data.get("content") or ""
        decoded = None
        if encoding == "base64":
            decoded = base64.b64decode(content).decode("utf-8", errors="replace")
        return {
            "repo": repo,
            "branch": branch,
            "path": path,
            "name": data.get("name"),
            "sha": data.get("sha"),
            "size": data.get("size"),
            "encoding": encoding,
            "content": decoded,
            "html_url": data.get("html_url"),
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
