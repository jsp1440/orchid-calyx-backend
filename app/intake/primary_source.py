"""Bounded read-only primary-source resolution for external intelligence.

This module confirms source identity and preserves metadata/content hashes. It
never treats reachability as proof that a scientific claim is true, never
publishes to canonical stores, and never performs external contact.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
import ipaddress
import re
import socket
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse

import requests

VERIFIER_VERSION = "calyx-primary-source-v1"
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.I)


@dataclass(frozen=True)
class SourceSnapshot:
    source_url: str
    resolved_url: str | None
    source_kind: str
    outcome: str
    http_status: int | None
    content_type: str | None
    source_title: str | None
    source_doi: str | None
    published_at: str | None
    authority_host: str | None
    authority_tier: str
    evidence_sha256: str | None
    metadata: dict[str, Any]


class FetchResponse(Protocol):
    status_code: int
    headers: dict[str, str]
    content: bytes


class Fetcher(Protocol):
    def get(self, url: str, **kwargs: Any) -> FetchResponse: ...


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {str(k).lower(): str(v or "") for k, v in attrs}
        if tag.lower() == "title":
            self.in_title = True
        if tag.lower() == "meta":
            key = (attrs_map.get("name") or attrs_map.get("property") or "").lower()
            value = attrs_map.get("content", "").strip()
            if key and value:
                self.meta.setdefault(key, value)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title and data.strip():
            self.title_parts.append(data.strip())

    @property
    def title(self) -> str | None:
        value = " ".join(self.title_parts).strip()
        return value or None


def _host_is_public(hostname: str) -> bool:
    lower = hostname.strip().lower().rstrip(".")
    if not lower or lower in {"localhost", "localhost.localdomain"} or lower.endswith(".local"):
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(lower, None, type=socket.SOCK_STREAM)}
    except socket.gaierror:
        return False
    if not addresses:
        return False
    for raw in addresses:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def validate_public_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("UNSUPPORTED_SOURCE_URL")
    if parsed.username or parsed.password:
        raise ValueError("CREDENTIALS_IN_SOURCE_URL_PROHIBITED")
    if not _host_is_public(parsed.hostname):
        raise ValueError("NON_PUBLIC_SOURCE_HOST")
    return parsed.geturl()


def _authority_tier(host: str | None) -> str:
    if not host:
        return "UNKNOWN"
    lower = host.lower()
    if lower.endswith(".gov") or lower.endswith(".gov.uk") or lower.endswith(".europa.eu"):
        return "AUTHORITATIVE"
    if lower.endswith(".edu") or lower.endswith(".ac.uk") or lower in {"doi.org", "dx.doi.org"}:
        return "PRIMARY"
    if any(marker in lower for marker in ("springer", "wiley", "elsevier", "oup.com", "cambridge.org", "nature.com", "science.org")):
        return "PRIMARY"
    return "UNKNOWN"


def _extract_metadata(content: bytes, content_type: str | None) -> tuple[str | None, str | None, str | None]:
    if not content_type or "html" not in content_type.lower():
        return None, None, None
    text = content.decode("utf-8", errors="replace")
    parser = _MetadataParser()
    parser.feed(text)
    parser.close()
    meta = parser.meta
    doi = meta.get("citation_doi") or meta.get("dc.identifier")
    if doi:
        match = DOI_RE.search(doi)
        doi = match.group(0).rstrip(".,;") if match else None
    published = (
        meta.get("citation_publication_date")
        or meta.get("citation_date")
        or meta.get("article:published_time")
        or meta.get("dc.date")
    )
    title = meta.get("citation_title") or meta.get("og:title") or parser.title
    return title, doi, published


def fetch_source(url: str, *, fetcher: Fetcher | None = None) -> SourceSnapshot:
    fetcher = fetcher or requests
    current = validate_public_url(url)
    initial = current
    for _ in range(MAX_REDIRECTS + 1):
        response = fetcher.get(
            current,
            allow_redirects=False,
            timeout=15,
            headers={"User-Agent": "OrchidContinuum-Calyx/1.0 primary-source-verifier"},
        )
        status = int(response.status_code)
        if status in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location") or response.headers.get("location")
            if not location:
                break
            current = validate_public_url(urljoin(current, location))
            continue

        raw = bytes(response.content[: MAX_BYTES + 1])
        truncated = len(raw) > MAX_BYTES
        raw = raw[:MAX_BYTES]
        content_type = response.headers.get("Content-Type") or response.headers.get("content-type")
        host = urlparse(current).hostname
        title, doi, published_at = _extract_metadata(raw, content_type)
        confirmed = 200 <= status < 300 and bool(raw)
        return SourceSnapshot(
            source_url=initial,
            resolved_url=current,
            source_kind="DOI" if initial.startswith("https://doi.org/") else "URL",
            outcome="SOURCE_CONFIRMED" if confirmed else "UNREACHABLE",
            http_status=status,
            content_type=content_type,
            source_title=title,
            source_doi=doi,
            published_at=published_at,
            authority_host=host,
            authority_tier=_authority_tier(host),
            evidence_sha256=sha256(raw).hexdigest() if raw else None,
            metadata={"truncated": truncated, "bytes_preserved": len(raw), "claim_verified": False},
        )
    return SourceSnapshot(
        source_url=initial,
        resolved_url=current,
        source_kind="DOI" if initial.startswith("https://doi.org/") else "URL",
        outcome="UNREACHABLE",
        http_status=None,
        content_type=None,
        source_title=None,
        source_doi=None,
        published_at=None,
        authority_host=urlparse(current).hostname,
        authority_tier=_authority_tier(urlparse(current).hostname),
        evidence_sha256=None,
        metadata={"redirect_limit_reached": True, "claim_verified": False},
    )


def candidate_source_urls(source_urls: list[str], dois: list[str]) -> list[str]:
    result: list[str] = []
    for doi in dois:
        clean = doi.strip()
        if clean:
            result.append(f"https://doi.org/{clean}")
    result.extend(url.strip() for url in source_urls if url.strip())
    return list(dict.fromkeys(result))[:5]
