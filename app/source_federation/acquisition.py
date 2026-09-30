"""Provider-neutral acquisition ledger primitives.

This module is deliberately network- and storage-agnostic.  It defines the stable
resource identity and request/result contracts used by shared acquisition
providers (Firecrawl, sanctioned APIs/downloads, and local holdings).

Architectural invariant:
CACHE-FIRST / FETCH-ONCE / EXTRACT-ONCE / REUSE-EVERYWHERE / PROVENANCE-ALWAYS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from typing import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def canonicalize_url(url: str) -> str:
    """Return a conservative canonical URL suitable for acquisition identity.

    Fragment and common tracking parameters are removed. Query parameters are
    sorted, while scientifically meaningful provider parameters are preserved.
    """
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise ValueError("resource URL must be an absolute http(s) URL")
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() not in _TRACKING_KEYS
        and not any(key.casefold().startswith(prefix) for prefix in _TRACKING_PREFIXES)
    ]
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.casefold(),
            parts.path or "/",
            urlencode(sorted(query)),
            "",
        )
    )


def resource_key(*, url: str, provider: str, stable_identifier: str | None = None) -> str:
    """Create a deterministic identity for a provider resource."""
    identity = stable_identifier.strip() if stable_identifier else canonicalize_url(url)
    material = f"{provider.strip().casefold()}|{identity}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AcquisitionRequest:
    url: str
    provider: str
    consumer_module: str
    stable_identifier: str | None = None
    force_refresh: bool = False

    @property
    def canonical_url(self) -> str:
        return canonicalize_url(self.url)

    @property
    def key(self) -> str:
        return resource_key(
            url=self.url,
            provider=self.provider,
            stable_identifier=self.stable_identifier,
        )


@dataclass(frozen=True, slots=True)
class AcquisitionRecord:
    key: str
    provider: str
    canonical_url: str
    retrieved_at: datetime
    content_hash: str
    provenance: Mapping[str, str]
    status: str = "complete"
    credits_spent: int = 0
    etag: str | None = None
    last_modified: str | None = None
    durable_object_ref: str | None = None
    consumers: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def completed(
        cls,
        *,
        request: AcquisitionRequest,
        content: bytes,
        provenance: Mapping[str, str],
        credits_spent: int = 0,
        etag: str | None = None,
        last_modified: str | None = None,
        durable_object_ref: str | None = None,
    ) -> "AcquisitionRecord":
        return cls(
            key=request.key,
            provider=request.provider,
            canonical_url=request.canonical_url,
            retrieved_at=datetime.now(timezone.utc),
            content_hash=hashlib.sha256(content).hexdigest(),
            provenance=dict(provenance),
            credits_spent=credits_spent,
            etag=etag,
            last_modified=last_modified,
            durable_object_ref=durable_object_ref,
            consumers=(request.consumer_module,),
        )
