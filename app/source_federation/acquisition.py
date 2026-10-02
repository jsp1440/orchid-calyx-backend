"""Provider-neutral acquisition ledger primitives.

Architectural invariant:
CACHE-FIRST / FETCH-ONCE / EXTRACT-ONCE / REUSE-EVERYWHERE / PROVENANCE-ALWAYS.

URL identity
------------

:func:`canonicalize_url` is the ONE canonicaliser for resource identity: the
acquisition ledger key and held-corpus URL matching
(``app.literature_extraction.firecrawl_acquisition.held_source_match``) both
use it, so a URL that is "already held" is also "already acquired" and vice
versa. It folds only spellings that name the same resource on the same
origin:

* scheme and host case, a trailing dot on the host, the default port;
* the fragment (never sent to the server);
* tracking query parameters (``utm_*``, ``fbclid``, ``gclid``, ``mc_cid``,
  ``mc_eid``) and query parameter order;
* a trailing slash on a NON-root path (``/taxon/`` and ``/taxon``), and an
  empty path with ``/``.

It deliberately does NOT fold ``http`` with ``https`` or ``www.`` with the
apex host. Those are different origins that may serve different content (or
redirect in only one direction), and folding them would let one origin's
acquisition suppress a fetch of another. They stay distinct keys; the cost is
at most one extra paid call per origin, never a silently wrong reuse.

This is an IDENTITY function. It is never the URL sent to a provider: a
server may treat ``/a/`` and ``/a`` differently, so fetchers keep the URL
they were given.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def canonicalize_url(url: str) -> str:
    """Canonical identity of an absolute http(s) URL; see the module docstring."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("resource URL must be an absolute http(s) URL")
    hostname = parts.hostname
    if not hostname:
        raise ValueError("resource URL must contain a hostname")
    hostname = hostname.casefold().rstrip(".")
    if not hostname:
        raise ValueError("resource URL must contain a hostname")
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    port = parts.port
    netloc = (
        hostname
        if port is None
        or (scheme == "https" and port == 443)
        or (scheme == "http" and port == 80)
        else f"{hostname}:{port}"
    )
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.casefold() not in _TRACKING_KEYS
        and not any(k.casefold().startswith(p) for p in _TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, urlencode(sorted(query)), ""))


def canonical_identity_url(value: object) -> str | None:
    """:func:`canonicalize_url` for matching, or ``None`` when it cannot apply.

    Absent or non-http(s) values have no canonical form. Callers compare
    them only by exact equality (or not at all); they never match anything
    by canonicalisation.
    """
    if not value:
        return None
    try:
        return canonicalize_url(str(value))
    except ValueError:
        return None


def resource_key(
    *, url: str, provider: str, stable_identifier: str | None = None
) -> str:
    identity = (stable_identifier or "").strip() or canonicalize_url(url)
    normalized_provider = provider.strip().casefold()
    if not normalized_provider:
        raise ValueError("provider is required")
    return hashlib.sha256(f"{normalized_provider}|{identity}".encode()).hexdigest()


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
    ) -> AcquisitionRecord:
        snapshot = {
            str(k).strip(): str(v).strip()
            for k, v in provenance.items()
            if str(k).strip() and str(v).strip()
        }
        if not snapshot:
            raise ValueError("completed acquisition requires non-empty provenance")
        return cls(
            key=request.key,
            provider=request.provider,
            canonical_url=request.canonical_url,
            retrieved_at=datetime.now(timezone.utc),
            content_hash=hashlib.sha256(content).hexdigest(),
            provenance=MappingProxyType(snapshot),
            credits_spent=credits_spent,
            etag=etag,
            last_modified=last_modified,
            durable_object_ref=durable_object_ref,
            consumers=(request.consumer_module,),
        )
