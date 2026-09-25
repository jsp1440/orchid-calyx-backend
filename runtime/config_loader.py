from __future__ import annotations

import copy
import hashlib
import json
import os
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

DEFAULT_BRAIN_REPO = "jsp1440/Orchid-Continuum-Brain"
DEFAULT_BRAIN_REF = "calyx-core-operational-foundation"
DEFAULT_GITHUB_API = "https://api.github.com"

#: The status vocabulary and required fields of the Brain's unavailable contract
#: (Orchid-Continuum-Brain ``contracts/federation_records_v1.json``,
#: ``unavailable_contract``): a consumer that cannot reach the Brain reports
#: ``unavailable`` with the timestamp and content hash of the last record it
#: holds and keeps serving that copy. It never turns the outage into a 500.
BRAIN_SOURCE_STATUSES = ("loaded", "unavailable", "stale", "malformed")
BRAIN_SOURCE_REQUIRED_FIELDS = (
    "repo",
    "ref",
    "status",
    "last_known_at",
    "last_known_sha256",
)


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class LastKnownRecord:
    """One Brain record as it was last successfully loaded in this process."""

    path: str
    repo: str
    ref: str
    record: dict[str, Any]
    loaded_at: str
    sha256: str


class LastKnownStore:
    """Process-local memory of the last record successfully loaded per path.

    This is what lets a consumer keep serving when the Brain is unreachable.
    It holds only what a real fetch returned, keyed by ``(repo, ref, path)`` so
    a record loaded from one ref is never presented as another's. It is not
    persisted: a fresh process that has never reached the Brain has nothing
    last-known, and says so rather than inventing a record.
    """

    def __init__(self, clock: Callable[[], str] = _utc_now) -> None:
        self._records: dict[tuple[str, str, str], LastKnownRecord] = {}
        self._clock = clock

    def remember(
        self, source: BrainConfigSource, path: str, raw: bytes, record: dict[str, Any]
    ) -> LastKnownRecord:
        known = LastKnownRecord(
            path=path,
            repo=source.repo,
            ref=source.ref,
            record=copy.deepcopy(record),
            loaded_at=self._clock(),
            sha256=hashlib.sha256(raw).hexdigest(),
        )
        self._records[(source.repo, source.ref, path)] = known
        return known

    def get(self, source: BrainConfigSource, path: str) -> LastKnownRecord | None:
        return self._records.get((source.repo, source.ref, path))

    def clear(self) -> None:
        self._records.clear()


#: The store every loader shares by default, so a record loaded by one request
#: is available to the next when the Brain has since become unreachable.
LAST_KNOWN = LastKnownStore()


@dataclass(frozen=True)
class BrainConfigResult:
    """A Brain record and, in the contract's terms, where it came from.

    ``record`` is ``None`` only when the Brain is unreachable and nothing was
    ever loaded for this path in this process. ``config_source`` always carries
    every field the unavailable contract requires.
    """

    path: str
    record: dict[str, Any] | None
    config_source: dict[str, Any]

    @property
    def available(self) -> bool:
        return self.record is not None


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

    The Brain is a source of durable records, not a mandatory runtime
    dependency: ``load_with_source`` degrades to the last record this process
    successfully loaded and reports that honestly, per the Brain's unavailable
    contract. ``load_json`` keeps its raising behaviour for callers that
    genuinely cannot proceed without a fresh record.
    """

    def __init__(
        self,
        source: BrainConfigSource | None = None,
        *,
        last_known: LastKnownStore | None = None,
        fetch: Callable[[str, Mapping[str, str]], bytes] | None = None,
    ) -> None:
        self.source = source or BrainConfigSource.from_env()
        self.last_known = last_known if last_known is not None else LAST_KNOWN
        self._fetch = fetch or self._fetch_over_http

    def _contents_url(self, path: str) -> str:
        owner, repo = self.source.repo.split("/", 1)
        return (
            f"{self.source.api_base}/repos/{owner}/{repo}/contents/"
            f"{path}?ref={self.source.ref}"
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.raw+json",
            "User-Agent": "calyx-runtime-config-loader",
        }
        if self.source.token:
            headers["Authorization"] = f"Bearer {self.source.token}"
        return headers

    @staticmethod
    def _fetch_over_http(url: str, headers: Mapping[str, str]) -> bytes:
        req = urllib.request.Request(url, headers=dict(headers))
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.read()

    def _load_fresh(self, path: str) -> tuple[dict[str, Any], LastKnownRecord]:
        """Fetch and parse one record, remembering it as last-known on success."""
        raw = self._fetch(self._contents_url(path), self._headers())
        record = json.loads(raw.decode("utf-8"))
        if not isinstance(record, dict):
            raise BrainConfigError(f"Brain config {path} is not a JSON object")
        return record, self.last_known.remember(self.source, path, raw, record)

    def load_json(self, path: str, required: bool = True) -> dict[str, Any]:
        try:
            record, _ = self._load_fresh(path)
            return record
        except Exception as exc:
            if required:
                raise BrainConfigError(
                    f"Unable to load Brain config {path}: {exc}"
                ) from exc
            return {}

    def load_with_source(self, path: str) -> BrainConfigResult:
        """Load a record, or the last-known copy, and say which.

        Never raises for an unreachable Brain and never fabricates a record:
        with nothing last-known the result carries ``record=None`` and a
        ``config_source`` whose ``last_known_at`` is ``None``.
        """
        base = {"repo": self.source.repo, "ref": self.source.ref, "path": path}
        try:
            record, known = self._load_fresh(path)
        except (OSError, ValueError, BrainConfigError) as exc:
            # urllib failures are OSErrors; JSON and decode failures are
            # ValueErrors; a non-object body is a BrainConfigError.
            error = f"Unable to load Brain config {path}: {exc}"
            cached = self.last_known.get(self.source, path)
            if cached is None:
                return BrainConfigResult(
                    path=path,
                    record=None,
                    config_source={
                        **base,
                        "status": "unavailable",
                        "last_known_at": None,
                        "last_known_sha256": None,
                        "error": error,
                    },
                )
            return BrainConfigResult(
                path=path,
                record=copy.deepcopy(cached.record),
                config_source={
                    **base,
                    "status": "unavailable",
                    "last_known_at": cached.loaded_at,
                    "last_known_sha256": cached.sha256,
                    "error": error,
                },
            )
        return BrainConfigResult(
            path=path,
            record=record,
            config_source={
                **base,
                "status": "loaded",
                "last_known_at": known.loaded_at,
                "last_known_sha256": known.sha256,
            },
        )

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
