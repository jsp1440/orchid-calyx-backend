from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .github import FileChange


class EngineeringProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class PatchRequest:
    objective: str
    repository_files: dict[str, str]
    failure_logs: list[str]
    attempt: int


def _provider_http_error(exc: HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return f"ENGINEERING_PROVIDER_HTTP_{exc.code}"

    detail = payload.get("detail") if isinstance(payload, dict) else None
    code = str(detail.get("code", "")).strip() if isinstance(detail, dict) else ""
    if code:
        return f"ENGINEERING_PROVIDER_HTTP_{exc.code}:{code}"
    return f"ENGINEERING_PROVIDER_HTTP_{exc.code}"


class StructuredPatchProvider:
    """Calls a governed provider that returns complete UTF-8 file replacements."""

    def __init__(self, endpoint: str | None = None, token: str | None = None) -> None:
        self.endpoint = endpoint or os.getenv("CALYX_ENGINEERING_PROVIDER_URL", "")
        self.token = token or os.getenv("CALYX_ENGINEERING_PROVIDER_TOKEN", "")
        if not self.endpoint:
            raise RuntimeError("CALYX_ENGINEERING_PROVIDER_NOT_CONFIGURED")

    def generate(self, request: PatchRequest) -> list[FileChange]:
        payload = {
            "model": os.getenv("CALYX_ENGINEERING_PROVIDER_MODEL", "governed-engineering"),
            "response_format": "calyx_file_changes_v1",
            "objective": request.objective,
            "attempt": request.attempt,
            "constraints": {
                "maximum_files": 10,
                "complete_file_replacements": True,
                "workflow_files_forbidden": True,
                "merge_forbidden": True,
                "deployment_forbidden": True,
            },
            "repository_files": request.repository_files,
            "failure_logs": request.failure_logs,
        }
        headers = {"Content-Type": "application/json", "User-Agent": "calyx-engineering-provider"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        api_key = os.getenv("CALYX_ENGINEERING_PROVIDER_API_KEY", "").strip() or os.getenv(
            "CALYX_API_KEY", ""
        ).strip()
        if api_key:
            headers["X-API-Key"] = api_key
        http_request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            with urlopen(http_request, timeout=120) as response:
                result = json.loads(response.read())
        except HTTPError as exc:
            raise EngineeringProviderError(_provider_http_error(exc)) from exc
        except (URLError, TimeoutError) as exc:
            raise EngineeringProviderError("ENGINEERING_PROVIDER_UNREACHABLE") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EngineeringProviderError("ENGINEERING_PROVIDER_INVALID_JSON") from exc

        raw_changes = result.get("changes")
        if not isinstance(raw_changes, list) or not raw_changes:
            raise EngineeringProviderError("ENGINEERING_PROVIDER_CHANGESET_REQUIRED")
        if len(raw_changes) > 10:
            raise EngineeringProviderError("ENGINEERING_PROVIDER_CHANGESET_TOO_LARGE")

        changes: list[FileChange] = []
        for item in raw_changes:
            if not isinstance(item, dict):
                raise EngineeringProviderError("ENGINEERING_PROVIDER_CHANGE_INVALID")
            change = FileChange(
                path=str(item.get("path", "")),
                content=str(item.get("content", "")),
                message=str(item.get("message", "")),
            )
            change.validate()
            changes.append(change)
        return changes
