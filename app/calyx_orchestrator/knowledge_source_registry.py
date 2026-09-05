from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Iterable

SCHEMA_VERSION = "oc.knowledge-source-registry.v1"

_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
    "latitude",
    "longitude",
    "coordinates",
    "private_locality",
    "exact_location",
}


class SourceKind(str, Enum):
    LITERATURE = "literature"
    DATASET = "dataset"
    PDF = "pdf"
    URL = "url"
    API = "api"
    GRAPH_COLLECTION = "graph_collection"
    INTERNAL_NOTE = "internal_note"


class TrustClass(str, Enum):
    REVIEWED = "reviewed"
    AUTHORITATIVE_EXTERNAL = "authoritative_external"
    UNTRUSTED_EXTERNAL = "untrusted_external"
    INTERNAL = "internal"


class AccessPolicy(str, Enum):
    PUBLIC = "public"
    REVIEWER_ONLY = "reviewer_only"
    INTERNAL = "internal"


class SourceState(str, Enum):
    AVAILABLE = "available"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    CONTRADICTORY = "contradictory"
    RATE_LIMITED = "rate_limited"
    BLOCKED = "blocked"


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _safe(item)
            for key, item in value.items()
            if str(key).casefold() not in _SENSITIVE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


def stable_idempotency_key(source_id: str, action: str, subject: str) -> str:
    material = f"{source_id}\n{action}\n{subject}".encode("utf-8")
    return sha256(material).hexdigest()


@dataclass(frozen=True)
class KnowledgeSource:
    source_id: str
    kind: SourceKind
    trust_class: TrustClass
    license: str
    scope: str
    access_policy: AccessPolicy
    state: SourceState = SourceState.AVAILABLE
    freshness_at: str | None = None
    allowed_actions: tuple[str, ...] = ("retrieve",)
    snippets: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.source_id or not self.license or not self.scope:
            raise ValueError("source_id, license, and scope are required")
        if "retrieve" not in self.allowed_actions:
            raise ValueError("knowledge sources must explicitly allow retrieval")
        if any(action.startswith("write") for action in self.allowed_actions):
            raise ValueError("source registration cannot itself grant connector write authority")

    def to_dict(self, *, audience: AccessPolicy) -> dict[str, Any] | None:
        if self.access_policy is AccessPolicy.INTERNAL and audience is not AccessPolicy.INTERNAL:
            return None
        if self.access_policy is AccessPolicy.REVIEWER_ONLY and audience is AccessPolicy.PUBLIC:
            return None
        return _safe(
            {
                "schema_version": self.schema_version,
                "source_id": self.source_id,
                "kind": self.kind.value,
                "trust_class": self.trust_class.value,
                "license": self.license,
                "scope": self.scope,
                "access_policy": self.access_policy.value,
                "state": self.state.value,
                "freshness_at": self.freshness_at,
                "allowed_actions": list(self.allowed_actions),
                "snippets": list(self.snippets),
                "metadata": self.metadata,
            }
        )


@dataclass(frozen=True)
class ConnectorPolicy:
    connector_id: str
    allowlisted_actions: tuple[str, ...] = ("retrieve",)
    timeout_seconds: int = 15
    max_retries: int = 2
    writes_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.connector_id:
            raise ValueError("connector_id is required")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 120:
            raise ValueError("timeout_seconds must be between 1 and 120")
        if self.max_retries < 0 or self.max_retries > 5:
            raise ValueError("max_retries must be between 0 and 5")
        if self.writes_enabled:
            raise ValueError("connector writes require separate deterministic authorization")
        if any(action.startswith("write") for action in self.allowlisted_actions):
            raise ValueError("write actions cannot be allowlisted without authorization")


@dataclass
class KnowledgeSourceRegistry:
    sources: dict[str, KnowledgeSource] = field(default_factory=dict)

    def register(self, source: KnowledgeSource) -> None:
        existing = self.sources.get(source.source_id)
        if existing is not None and existing != source:
            raise ValueError("source_id already exists with different policy or provenance")
        self.sources[source.source_id] = source

    def public_view(self) -> list[dict[str, Any]]:
        rendered = []
        for source in sorted(self.sources.values(), key=lambda item: item.source_id):
            item = source.to_dict(audience=AccessPolicy.PUBLIC)
            if item is not None:
                rendered.append(item)
        return rendered

    def query(
        self,
        *,
        audience: AccessPolicy,
        states: Iterable[SourceState] | None = None,
    ) -> list[dict[str, Any]]:
        wanted = set(states) if states is not None else None
        rendered = []
        for source in sorted(self.sources.values(), key=lambda item: item.source_id):
            if wanted is not None and source.state not in wanted:
                continue
            item = source.to_dict(audience=audience)
            if item is not None:
                rendered.append(item)
        return rendered


@dataclass(frozen=True)
class ConnectorRequest:
    source_id: str
    action: str
    subject: str
    idempotency_key: str
    requested_at: str
    redacted_payload: dict[str, Any]


def prepare_connector_request(
    *,
    source: KnowledgeSource,
    policy: ConnectorPolicy,
    action: str,
    subject: str,
    payload: dict[str, Any] | None = None,
) -> ConnectorRequest:
    if action not in policy.allowlisted_actions:
        raise PermissionError("connector action is not allowlisted")
    if action not in source.allowed_actions:
        raise PermissionError("source does not permit connector action")
    if action.startswith("write"):
        raise PermissionError("connector writes require separate deterministic authorization")
    if source.state in {SourceState.UNAVAILABLE, SourceState.RATE_LIMITED, SourceState.BLOCKED}:
        raise RuntimeError(f"source is not currently retrievable: {source.state.value}")

    return ConnectorRequest(
        source_id=source.source_id,
        action=action,
        subject=subject,
        idempotency_key=stable_idempotency_key(source.source_id, action, subject),
        requested_at=datetime.now(timezone.utc).isoformat(),
        redacted_payload=_safe(payload or {}),
    )
