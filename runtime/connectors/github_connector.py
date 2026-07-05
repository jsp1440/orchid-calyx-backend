"""Read-only GitHub connector for Calyx.

BUILD-021 established the first production connector on top of the
BUILD-020 Connector Execution Framework. BUILD-023 expanded it with safe
file-inspection tasks. BUILD-025 added a deterministic repository audit task.
BUILD-026 added an autonomous repository engineer task. BUILD-028 adds a
frontend audit task so Calyx can inspect the Orchid Continuum frontend before
proposing repair work.
"""

from __future__ import annotations

import base64
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from ..connector_interface import ConnectorInterface


class GitHubConnector(ConnectorInterface):
    """Read-only GitHub repository inspection connector."""

    default_repo = "jsp1440/orchid-calyx-backend"
    default_frontend_repo = "jsp1440/orchid-continuum-frontend"

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
            "frontend_repo": os.environ.get("CALYX_FRONTEND_REPOSITORY", self.default_frontend_repo),
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
                "repo_audit",
                "repo_engineer",
                "engineering_queue",
                "frontend_audit",
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
        if task == "repo_audit":
            return self._repo_audit(repo, branch)
        if task in {"repo_engineer", "engineering_queue"}:
            return self._repo_engineer(repo, branch)
        if task == "frontend_audit":
            frontend_repo = (
                kwargs.get("frontend_repo")
                or kwargs.get("repo")
                or os.environ.get("CALYX_FRONTEND_REPOSITORY")
                or self.default_frontend_repo
            )
            return self._frontend_audit(frontend_repo, branch)

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

    def _repo_audit(self, repo: str, branch: str) -> dict[str, Any]:
        status = self._repo_status(repo)
        branch_status = self._branch_status(repo, branch)
        open_prs = self._list_open_prs(repo, 20)
        recent_commits = self._list_recent_commits(repo, 10)
        files_payload = self._list_files(repo, branch, 500)
        files = files_payload.get("files", [])
        paths = [item.get("path") for item in files if item.get("path")]

        key_paths = [
            "app/main.py",
            "runtime/connector_routes.py",
            "runtime/connector_registry.py",
            "runtime/connectors/github_connector.py",
            "README.md",
            "render.yaml",
            "requirements.txt",
        ]
        key_files = []
        for path in key_paths:
            if path in paths:
                file_info = self._get_file(repo, path, branch)
                content = file_info.get("content") or ""
                key_files.append(
                    {
                        "path": path,
                        "size": file_info.get("size"),
                        "sha": file_info.get("sha"),
                        "line_count": len(content.splitlines()),
                        "contains_fastapi_router": "APIRouter" in content or "include_router" in content,
                        "contains_connector_reference": "connector" in content.lower(),
                    }
                )

        router_files = [path for path in paths if path.startswith("app/routers/") and path.endswith(".py")]
        runtime_files = [path for path in paths if path.startswith("runtime/") and path.endswith(".py")]
        connector_files = [path for path in paths if path.startswith("runtime/connectors/") and path.endswith(".py")]
        test_files = [path for path in paths if path.startswith("tests/") and path.endswith(".py")]
        doc_files = [path for path in paths if path.startswith("docs/") or path.endswith(".md")]

        risks: list[str] = []
        if not test_files:
            risks.append("No Python test files were found in the first 500 repository files returned by GitHub.")
        if "runtime/connector_routes.py" not in paths:
            risks.append("Connector route module was not found in the repository tree.")
        if "runtime/connectors/github_connector.py" not in paths:
            risks.append("GitHub connector module was not found in the repository tree.")
        if open_prs.get("count", 0) > 0:
            risks.append("Open pull requests are present and should be reviewed before major connector changes.")

        next_actions = [
            "Add a dedicated tasks/capabilities endpoint so clients can discover supported connector tasks without reading health payloads.",
            "Add route-level tests for kwargs parsing and connector execution error handling.",
            "Add repository audit persistence so Calyx can compare repo health over time.",
            "Keep GitHub connector read-only until branch and PR creation are protected by explicit approvals.",
        ]

        return {
            "build": "BUILD-025",
            "status": "repo_audit_complete",
            "repo": repo,
            "branch": branch,
            "repo_status": status,
            "branch_status": branch_status,
            "inventory": {
                "files_sampled": len(paths),
                "router_files": router_files,
                "runtime_file_count": len(runtime_files),
                "connector_files": connector_files,
                "test_file_count": len(test_files),
                "doc_file_count": len(doc_files),
            },
            "key_files": key_files,
            "open_prs": open_prs,
            "recent_commits": recent_commits,
            "risks": risks,
            "recommended_next_actions": next_actions,
            "timestamp": self._now(),
        }

    def _repo_engineer(self, repo: str, branch: str) -> dict[str, Any]:
        audit = self._repo_audit(repo, branch)
        inventory = audit.get("inventory", {})
        key_files = audit.get("key_files", [])
        key_file_paths = {item.get("path") for item in key_files}
        risks = audit.get("risks", [])
        open_pr_count = (audit.get("open_prs") or {}).get("count", 0)

        tasks: list[dict[str, Any]] = []

        def add_task(
            task_id: str,
            title: str,
            priority: int,
            rationale: str,
            target_files: list[str] | None = None,
            acceptance: list[str] | None = None,
        ) -> None:
            tasks.append(
                {
                    "task_id": task_id,
                    "title": title,
                    "priority": priority,
                    "status": "proposed",
                    "mode": "review_required",
                    "rationale": rationale,
                    "target_files": target_files or [],
                    "acceptance_criteria": acceptance or [],
                }
            )

        add_task(
            "GH-ENG-001",
            "Add connector task discovery endpoint",
            95,
            "Clients currently discover connector capabilities indirectly through health payloads. A dedicated endpoint will reduce Swagger confusion and make connector usage self-describing.",
            ["runtime/connector_routes.py", "runtime/connector_registry.py"],
            [
                "GET /api/connectors/tasks returns supported tasks for all connectors.",
                "GET /api/connectors/tasks/{connector} returns supported tasks for one connector.",
                "Unknown connector returns 404.",
            ],
        )

        add_task(
            "GH-ENG-002",
            "Add tests for connector kwargs parsing",
            92,
            "BUILD-024 fixed a production bug where Swagger kwargs were not parsed before connector execution. Route-level tests should lock this behavior down.",
            ["runtime/connector_routes.py", "tests/test_connector_routes.py"],
            [
                "POST /api/connectors/execute parses kwargs JSON object strings.",
                "Invalid kwargs JSON returns HTTP 400.",
                "Non-object kwargs returns HTTP 400.",
            ],
        )

        add_task(
            "GH-ENG-003",
            "Persist repository audit snapshots",
            86,
            "BUILD-025 produces a useful live audit, but Calyx cannot yet compare repository health over time.",
            ["runtime/connectors/github_connector.py", "runtime/planner_router.py"],
            [
                "Repo audit results can be written to a durable store or runtime artifact directory.",
                "Latest audit can be retrieved without re-running GitHub API calls.",
                "Audit history includes timestamp and commit SHA.",
            ],
        )

        add_task(
            "GH-ENG-004",
            "Add guarded GitHub write plan without enabling writes",
            78,
            "The connector is intentionally read-only. The next architecture step is a written plan for branch/PR creation with explicit approvals before code write support is added.",
            ["docs/BUILD-026-github-write-safety.md"],
            [
                "Document branch creation, file update, and PR opening flow.",
                "Require explicit human approval before write operations.",
                "Define rollback and audit log requirements.",
            ],
        )

        if inventory.get("test_file_count", 0) < 10:
            add_task(
                "GH-ENG-005",
                "Expand backend regression tests",
                74,
                "The audit found a relatively small number of tests for a growing runtime system.",
                ["tests/"],
                [
                    "Add tests for GitHub connector read-only tasks.",
                    "Add tests for repo_audit and repo_engineer task outputs.",
                ],
            )

        if "render.yaml" not in key_file_paths:
            add_task(
                "GH-ENG-006",
                "Document Render deployment configuration",
                62,
                "The audit did not find render.yaml among key files. Runtime deployment settings are currently external to the repo or not sampled.",
                ["README.md", "docs/"],
                [
                    "Document current Render start command.",
                    "Document required environment variables.",
                    "Document deployment verification endpoints.",
                ],
            )

        if open_pr_count > 0:
            add_task(
                "GH-ENG-007",
                "Review open pull requests before new engineering changes",
                90,
                "Open PRs are present. New code changes should not proceed until they are reviewed or merged.",
                [],
                ["Open PR list reviewed.", "Conflicts or duplicate efforts identified."],
            )

        for idx, risk in enumerate(risks, start=1):
            add_task(
                f"GH-RISK-{idx:03d}",
                "Address repository audit risk",
                88,
                risk,
                [],
                ["Risk is either resolved or explicitly accepted."],
            )

        tasks = sorted(tasks, key=lambda item: item["priority"], reverse=True)

        return {
            "build": "BUILD-026",
            "status": "engineering_queue_ready",
            "repo": repo,
            "branch": branch,
            "source_audit_status": audit.get("status"),
            "source_commit_sha": (audit.get("branch_status") or {}).get("commit_sha"),
            "queue_summary": {
                "total": len(tasks),
                "highest_priority": tasks[0]["priority"] if tasks else None,
                "mode": "read_only_review_required",
            },
            "engineering_task_queue": tasks,
            "recommended_next_task": tasks[0] if tasks else None,
            "audit_inventory": audit.get("inventory", {}),
            "timestamp": self._now(),
        }

    def _frontend_audit(self, repo: str, branch: str) -> dict[str, Any]:
        status = self._repo_status(repo)
        branch_status = self._branch_status(repo, branch)
        open_prs = self._list_open_prs(repo, 20)
        files_payload = self._list_files(repo, branch, 1000)
        files = files_payload.get("files", [])
        paths = [item.get("path") for item in files if item.get("path")]

        source_files = [path for path in paths if path.startswith("src/") and path.endswith((".ts", ".tsx", ".js", ".jsx"))]
        component_files = [path for path in source_files if "/components/" in path or path.startswith("src/components/")]
        route_files = [path for path in source_files if "route" in path.lower() or "page" in path.lower() or "router" in path.lower()]
        config_files = [path for path in paths if path in {"package.json", "vite.config.ts", "vite.config.js", "next.config.js", "tsconfig.json", "render.yaml"}]

        priority_names = [
            "DailyGenusFeature",
            "GenusOfDay",
            "genusData",
            "imageQuality",
            "backendConfig",
            "HomeAtlas",
            "KnowledgeGraph",
            "Species",
            "Atlas",
        ]
        priority_files = [
            path for path in paths
            if any(name.lower() in path.lower() for name in priority_names)
        ]

        inspected_files = []
        for path in (config_files + priority_files)[:20]:
            try:
                file_info = self._get_file(repo, path, branch)
                content = file_info.get("content") or ""
                inspected_files.append(
                    {
                        "path": path,
                        "size": file_info.get("size"),
                        "sha": file_info.get("sha"),
                        "line_count": len(content.splitlines()),
                        "mentions_backend": "backend" in content.lower() or "/api/" in content,
                        "mentions_genus": "genus" in content.lower(),
                        "mentions_image_filtering": any(term in content.lower() for term in ["herbarium", "specimen", "imagequality", "quality"]),
                    }
                )
            except Exception as exc:
                inspected_files.append({"path": path, "error": str(exc)})

        risks: list[str] = []
        if not source_files:
            risks.append("No src/ frontend source files were found; repository may not be the active frontend repo or the tree sample is incomplete.")
        if not priority_files:
            risks.append("No obvious Genus of the Day, Atlas, backend config, or Knowledge Graph files were found by filename search.")
        if open_prs.get("count", 0) > 0:
            risks.append("Open frontend pull requests are present and should be reviewed before repair work begins.")
        if "package.json" not in paths:
            risks.append("package.json was not found; frontend build tooling could not be identified from the repo tree.")

        repair_queue = [
            {
                "task_id": "FE-REPAIR-001",
                "title": "Map frontend data flow for Genus of the Day",
                "priority": 98,
                "status": "proposed",
                "mode": "read_only_review_required",
                "target_files": [path for path in priority_files if "genus" in path.lower()][:10],
                "acceptance_criteria": [
                    "Identify the component that renders Genus of the Day.",
                    "Identify the backend endpoint used for genus data.",
                    "Identify where image selection/filtering occurs.",
                ],
            },
            {
                "task_id": "FE-REPAIR-002",
                "title": "Audit image filtering for herbarium/specimen exclusion",
                "priority": 94,
                "status": "proposed",
                "mode": "read_only_review_required",
                "target_files": [path for path in priority_files if any(term in path.lower() for term in ["image", "quality", "genus"])][:10],
                "acceptance_criteria": [
                    "Find current filtering logic for specimen/herbarium/plate/document images.",
                    "Confirm trusted backend image URLs are allowed.",
                    "Prepare a patch plan before code writes are enabled.",
                ],
            },
            {
                "task_id": "FE-REPAIR-003",
                "title": "Audit backend API configuration",
                "priority": 90,
                "status": "proposed",
                "mode": "read_only_review_required",
                "target_files": [path for path in priority_files if "config" in path.lower() or "backend" in path.lower()][:10],
                "acceptance_criteria": [
                    "Locate frontend backend base URL configuration.",
                    "Verify production Render backend URL handling.",
                    "Identify any placeholder or stale API URLs.",
                ],
            },
            {
                "task_id": "FE-REPAIR-004",
                "title": "Audit homepage Atlas and Knowledge Graph wiring",
                "priority": 86,
                "status": "proposed",
                "mode": "read_only_review_required",
                "target_files": [path for path in priority_files if any(term in path.lower() for term in ["atlas", "graph", "knowledge"])][:10],
                "acceptance_criteria": [
                    "Identify homepage graph/atlas components.",
                    "Identify backend endpoints used by those components.",
                    "List missing or failing data dependencies.",
                ],
            },
        ]

        return {
            "build": "BUILD-028",
            "status": "frontend_audit_complete",
            "repo": repo,
            "branch": branch,
            "repo_status": status,
            "branch_status": branch_status,
            "inventory": {
                "files_sampled": len(paths),
                "source_file_count": len(source_files),
                "component_file_count": len(component_files),
                "route_file_count": len(route_files),
                "config_files": config_files,
                "priority_files": priority_files[:50],
            },
            "inspected_files": inspected_files,
            "open_prs": open_prs,
            "risks": risks,
            "frontend_repair_queue": repair_queue,
            "recommended_next_task": repair_queue[0],
            "timestamp": self._now(),
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
