from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AnthropicPatchProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class AnthropicPatchRequest:
    objective: str
    attempt: int
    constraints: dict
    repository_files: dict[str, str]
    failure_logs: list[str]


def _extract_json(text: str) -> dict:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    try:
        result = json.loads(value)
    except json.JSONDecodeError as exc:
        raise AnthropicPatchProviderError("ANTHROPIC_PROVIDER_INVALID_JSON") from exc
    if not isinstance(result, dict):
        raise AnthropicPatchProviderError("ANTHROPIC_PROVIDER_OBJECT_REQUIRED")
    return result


def generate_file_changes(payload: AnthropicPatchRequest) -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise AnthropicPatchProviderError("ANTHROPIC_API_KEY_NOT_CONFIGURED")
    model = os.getenv("CALYX_ENGINEERING_ANTHROPIC_MODEL", "claude-sonnet-4-20250514").strip()
    if not model:
        raise AnthropicPatchProviderError("CALYX_ENGINEERING_ANTHROPIC_MODEL_NOT_CONFIGURED")

    system = (
        "You are the governed Calyx engineering patch provider. Return only one JSON object "
        "with a non-empty 'changes' array. Each change must contain path, content, and message. "
        "Content must be the complete UTF-8 replacement for that file, never a diff. Modify only "
        "files supplied in repository_files. Never modify workflow files, deployment configuration, "
        "secrets, dependencies, or unrelated code. Do not create branches, pull requests, merges, "
        "deployments, or explanatory prose."
    )
    user_payload = {
        "objective": payload.objective,
        "attempt": payload.attempt,
        "constraints": payload.constraints,
        "repository_files": payload.repository_files,
        "failure_logs": payload.failure_logs,
        "required_response": {
            "changes": [
                {
                    "path": "one supplied repository path",
                    "content": "complete replacement file content",
                    "message": "concise repair message",
                }
            ]
        },
    }
    body = {
        "model": model,
        "max_tokens": 8192,
        "temperature": 0,
        "system": system,
        "messages": [{"role": "user", "content": json.dumps(user_payload)}],
    }
    request = Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": api_key,
            "User-Agent": "calyx-governed-engineering-provider",
        },
    )
    try:
        with urlopen(request, timeout=120) as response:
            result = json.loads(response.read())
    except HTTPError as exc:
        raise AnthropicPatchProviderError(f"ANTHROPIC_PROVIDER_HTTP_{exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise AnthropicPatchProviderError("ANTHROPIC_PROVIDER_UNREACHABLE") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnthropicPatchProviderError("ANTHROPIC_PROVIDER_INVALID_RESPONSE") from exc

    blocks = result.get("content")
    if not isinstance(blocks, list):
        raise AnthropicPatchProviderError("ANTHROPIC_PROVIDER_CONTENT_REQUIRED")
    text = "\n".join(
        str(block.get("text", ""))
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
    if not text:
        raise AnthropicPatchProviderError("ANTHROPIC_PROVIDER_TEXT_REQUIRED")
    return _extract_json(text)
