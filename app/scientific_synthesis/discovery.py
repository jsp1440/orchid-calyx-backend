from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any, Protocol
from urllib.parse import quote

import requests

from .models import BibliographicRecord, VerificationState


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    normalized = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", normalized)
    normalized = re.sub(r"^doi:\s*", "", normalized)
    return normalized or None


def _first_text(value: Any) -> str | None:
    if isinstance(value, list) and value:
        text = _clean(value[0])
        return text or None
    text = _clean(value)
    return text or None


def _authors(item: dict[str, Any]) -> tuple[str, ...]:
    result: list[str] = []
    for author in item.get("author") or []:
        if not isinstance(author, dict):
            continue
        given = _clean(author.get("given"))
        family = _clean(author.get("family"))
        name = " ".join(value for value in (given, family) if value)
        if name:
            result.append(name)
    return tuple(result)


def _year(item: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        value = item.get(key)
        if not isinstance(value, dict):
            continue
        parts = value.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                continue
    return None


@dataclass(frozen=True, slots=True)
class DiscoveryCandidate:
    candidate_id: str
    provider: str
    provider_record_id: str
    title: str
    authors: tuple[str, ...]
    year: int | None
    journal: str | None
    doi: str | None
    state: str = "DISCOVERY_CANDIDATE"


class LiteratureProvider(Protocol):
    name: str

    def search(self, query: str, *, rows: int) -> list[dict[str, Any]]: ...

    def lookup_doi(self, doi: str) -> dict[str, Any] | None: ...


class CrossrefProvider:
    """Crossref REST adapter.

    Search is discovery only. DOI lookup is the authoritative verification action.
    """

    name = "crossref"
    base_url = "https://api.crossref.org"

    def __init__(
        self,
        *,
        mailto: str | None = None,
        timeout_seconds: float = 15.0,
        session: requests.Session | None = None,
    ) -> None:
        self.mailto = (mailto or "").strip() or None
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def _params(self, values: dict[str, Any]) -> dict[str, Any]:
        result = dict(values)
        if self.mailto:
            result["mailto"] = self.mailto
        return result

    def search(self, query: str, *, rows: int) -> list[dict[str, Any]]:
        response = self.session.get(
            f"{self.base_url}/works",
            params=self._params(
                {
                    "query.bibliographic": query,
                    "rows": max(1, min(rows, 100)),
                    "select": "DOI,title,author,published-print,published-online,published,issued,created,container-title,type",
                }
            ),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        message = payload.get("message") if isinstance(payload, dict) else None
        items = message.get("items") if isinstance(message, dict) else None
        return [item for item in (items or []) if isinstance(item, dict)]

    def lookup_doi(self, doi: str) -> dict[str, Any] | None:
        normalized = _normalize_doi(doi)
        if not normalized:
            return None
        response = self.session.get(
            f"{self.base_url}/works/{quote(normalized, safe='')}",
            params=self._params({}),
            timeout=self.timeout_seconds,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        message = payload.get("message") if isinstance(payload, dict) else None
        return message if isinstance(message, dict) else None


class LiteratureDiscoveryService:
    def __init__(self, providers: tuple[LiteratureProvider, ...]) -> None:
        if not providers:
            raise ValueError("LITERATURE_PROVIDER_REQUIRED")
        self.providers = providers

    @staticmethod
    def _candidate(provider: str, item: dict[str, Any]) -> DiscoveryCandidate | None:
        title = _first_text(item.get("title"))
        if not title:
            return None
        doi = _normalize_doi(_clean(item.get("DOI")))
        authors = _authors(item)
        year = _year(item)
        journal = _first_text(item.get("container-title"))
        provider_record_id = doi or hashlib.sha256(
            f"{title.casefold()}\x1f{year}\x1f{'|'.join(authors).casefold()}".encode()
        ).hexdigest()
        candidate_id = hashlib.sha256(
            f"{provider}\x1f{provider_record_id}".encode()
        ).hexdigest()
        return DiscoveryCandidate(
            candidate_id=candidate_id,
            provider=provider,
            provider_record_id=provider_record_id,
            title=title,
            authors=authors,
            year=year,
            journal=journal,
            doi=doi,
        )

    def discover(self, question: str, *, rows_per_provider: int = 20) -> dict[str, Any]:
        question = _clean(question)
        if not question:
            raise ValueError("RESEARCH_QUESTION_REQUIRED")
        candidates: dict[str, DiscoveryCandidate] = {}
        provider_counts: dict[str, int] = {}
        for provider in self.providers:
            items = provider.search(question, rows=rows_per_provider)
            provider_counts[provider.name] = len(items)
            for item in items:
                candidate = self._candidate(provider.name, item)
                if candidate is None:
                    continue
                dedupe_key = candidate.doi or (
                    f"{candidate.title.casefold()}|{candidate.year}|"
                    f"{'|'.join(candidate.authors).casefold()}"
                )
                candidates.setdefault(dedupe_key, candidate)
        ordered = sorted(
            candidates.values(), key=lambda item: (item.year or 0, item.title), reverse=True
        )
        manifest = {
            "question": question,
            "candidate_count": len(ordered),
            "provider_counts": provider_counts,
            "candidates": [asdict(item) for item in ordered],
            "search_results_are_evidence": False,
            "search_results_are_verified": False,
        }
        manifest["fingerprint"] = hashlib.sha256(
            repr(
                (
                    question,
                    tuple(
                        (item.provider, item.provider_record_id, item.title, item.doi)
                        for item in ordered
                    ),
                )
            ).encode()
        ).hexdigest()
        return manifest


class BibliographicVerificationService:
    def __init__(self, provider: LiteratureProvider) -> None:
        self.provider = provider

    def verify_doi(self, doi: str) -> dict[str, Any]:
        requested_doi = _normalize_doi(doi)
        if not requested_doi:
            raise ValueError("DOI_REQUIRED")
        item = self.provider.lookup_doi(requested_doi)
        if item is None:
            return {
                "verified": False,
                "state": "BIBLIOGRAPHY_UNRESOLVED",
                "doi": requested_doi,
                "provider": self.provider.name,
                "reason": "DOI_NOT_FOUND",
            }
        returned_doi = _normalize_doi(_clean(item.get("DOI")))
        if returned_doi != requested_doi:
            return {
                "verified": False,
                "state": "BIBLIOGRAPHY_UNRESOLVED",
                "doi": requested_doi,
                "provider": self.provider.name,
                "reason": "DOI_IDENTITY_MISMATCH",
                "returned_doi": returned_doi,
            }
        title = _first_text(item.get("title"))
        authors = _authors(item)
        if not title or not authors:
            return {
                "verified": False,
                "state": "BIBLIOGRAPHY_UNRESOLVED",
                "doi": requested_doi,
                "provider": self.provider.name,
                "reason": "INCOMPLETE_AUTHORITATIVE_METADATA",
            }
        record = BibliographicRecord(
            source_id=f"doi:{requested_doi}",
            title=title,
            authors=authors,
            year=_year(item),
            journal=_first_text(item.get("container-title")),
            doi=requested_doi,
            verification_state=VerificationState.VERIFIED_AUTHORITY,
            verification_provider=self.provider.name,
            verification_identifier=requested_doi,
        )
        return {
            "verified": True,
            "state": "BIBLIOGRAPHY_VERIFIED",
            "record": asdict(record),
            "verification": {
                "provider": self.provider.name,
                "identifier": requested_doi,
                "method": "AUTHORITATIVE_DOI_LOOKUP",
            },
        }
