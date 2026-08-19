from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_BRAIN_REPO = "jsp1440/Orchid-Continuum-Brain"
DEFAULT_BRAIN_REF = "calyx-core-operational-foundation"
DEFAULT_GITHUB_API = "https://api.github.com"


class BrainConfigError(RuntimeError):
    """Raised when Calyx cannot load required Brain-backed configuration."""


@dataclass
class BrainConfigSource:
    repo: str = DEFAULT_BRAIN_REPO
    ref: str = DEFAULT_BRAIN_REF
    api_base: str = DEFAULT_GITHUB_API
    token: str | None = None

    @classmethod
    def from_env(cls) -> BrainConfigSource:
        return cls(
            repo=os.getenv("CALYX_BRAIN_REPO", DEFAULT_BRAIN_REPO),
            ref=os.getenv("CALYX_BRAIN_REF", DEFAULT_BRAIN_REF),
            api_base=os.getenv("GITHUB_API_BASE", DEFAULT_GITHUB_API),
            # CALYX_GITHUB_TOKEN (this reader's own, narrowly-named variable)
            # takes precedence over the generic GITHUB_TOKEN. A broad or
            # differently-scoped credential that happens to be present under
            # the generic name must never silently outrank the credential
            # this specific read-only config path was actually configured
            # with. Neither name is ever the coding-agent mutation
            # credential (CALYX_GITHUB_CODING_AGENT_TOKEN) - that path is
            # read by app/calyx_orchestrator/github_agent_credential.py
            # only, and this loader must never consult it.
            token=os.getenv("CALYX_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN"),
        )


class BrainConfigLoader:
    """Loads Calyx Core policy/configuration from the Brain repository.

    The Brain repository is the source of truth for policy. Runtime code remains
    the execution engine.

    This loader supports private repositories when CALYX_GITHUB_TOKEN or
    GITHUB_TOKEN is configured in the backend environment - CALYX_GITHUB_TOKEN
    is preferred when both are present. This is a read-only configuration
    fetch; it is a logically separate credential path from the GitHub
    coding-agent mutation credential (CALYX_GITHUB_CODING_AGENT_TOKEN, see
    app/calyx_orchestrator/github_agent_credential.py), which this loader
    never reads.
    """

    def __init__(self, source: BrainConfigSource | None = None) -> None:
        self.source = source or BrainConfigSource.from_env()

    def _contents_url(self, path: str) -> str:
        owner, repo = self.source.repo.split("/", 1)
        return (
            f"{self.source.api_base}/repos/{owner}/{repo}/contents/"
            f"{path}?ref={self.source.ref}"
        )

    def load_json(self, path: str, required: bool = True) -> dict[str, Any]:
        url = self._contents_url(path)
        headers = {
            "Accept": "application/vnd.github.raw+json",
            "User-Agent": "calyx-runtime-config-loader",
        }
        if self.source.token:
            headers["Authorization"] = f"Bearer {self.source.token}"

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                raw = response.read().decode("utf-8")
            return json.loads(raw)
        except Exception as exc:
            if required:
                raise BrainConfigError(f"Unable to load Brain config {path}: {exc}") from exc
            return {}

    def load_manifest(self) -> dict[str, Any]:
        return self.load_json("config/calyx_core_manifest.json")

    def load_runtime_services(self) -> dict[str, Any]:
        return self.load_json("config/runtime_services.json")

    def load_infrastructure_registry(self) -> dict[str, Any]:
        return self.load_json("config/infrastructure_registry.json")

    def load_governance_policy(self) -> dict[str, Any]:
        return self.load_json("config/governance_policy.json")

    def load_knowledge_preservation_policy(self) -> dict[str, Any]:
        return self.load_json("config/knowledge_preservation_policy.json")
