"""Bounded, incremental adapters for free scholarly metadata registries.

Each adapter builds one request for a date window, and parses one response
page into :class:`DiscoveredWork` values.  HTTP is injected so tests and the
cost ledger see every request; nothing here retries, paginates without bound,
or calls a paid service.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol
from urllib.parse import urlencode

from .records import DiscoveredWork, clean_text, normalize_doi, parse_partial_date

USER_AGENT = "OrchidContinuum-Calyx/1.0 native-intelligence-discovery"


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


HttpGet = Callable[..., HttpResponse]


@dataclass(frozen=True)
class ProviderRequest:
    provider: str
    url: str


def _contact_params() -> dict[str, str]:
    # Polite-pool contact is operator configuration, never a hardcoded address.
    email = os.getenv("OC_DISCOVERY_CONTACT_EMAIL", "").strip()
    return {"mailto": email} if email else {}


class Provider(Protocol):
    name: str

    def build_request(
        self, query: str, since: date, until: date, rows: int
    ) -> ProviderRequest: ...

    def parse(self, payload: Any) -> list[DiscoveredWork]: ...


class CrossrefProvider:
    """Crossref REST works API; incremental on index date so updates resurface."""

    name = "crossref"
    base_url = "https://api.crossref.org/works"

    def build_request(
        self, query: str, since: date, until: date, rows: int
    ) -> ProviderRequest:
        params = {
            "query.bibliographic": query,
            "filter": f"from-index-date:{since.isoformat()},until-index-date:{until.isoformat()}",
            "rows": str(rows),
            "sort": "indexed",
            "order": "asc",
            "select": "DOI,title,author,container-title,publisher,issued,published,abstract,URL,type,subject,relation",
            **_contact_params(),
        }
        return ProviderRequest(self.name, f"{self.base_url}?{urlencode(params)}")

    def parse(self, payload: Any) -> list[DiscoveredWork]:
        works: list[DiscoveredWork] = []
        for record in ((payload or {}).get("message") or {}).get("items") or []:
            raw_title = " ".join(record.get("title") or [])
            title = clean_text(raw_title)
            doi = normalize_doi(record.get("DOI"))
            if not title or not doi:
                continue
            published_on, precision = parse_partial_date(
                record.get("published") or record.get("issued")
            )
            authors = []
            affiliations = []
            for author in record.get("author") or []:
                name = " ".join(
                    part for part in (author.get("given"), author.get("family")) if part
                )
                if name:
                    authors.append(name)
                for affiliation in author.get("affiliation") or []:
                    if affiliation.get("name"):
                        affiliations.append(clean_text(affiliation["name"]))
            related = []
            for relation_list in (record.get("relation") or {}).values():
                for relation in relation_list or []:
                    if relation.get("id"):
                        related.append(
                            f"{relation.get('id-type', 'id')}:{relation['id']}"
                        )
            works.append(
                DiscoveredWork(
                    provider=self.name,
                    provider_record_id=doi,
                    title=title,
                    doi=doi,
                    url=record.get("URL"),
                    authors=tuple(authors),
                    venue=clean_text(" ".join(record.get("container-title") or []))
                    or None,
                    publisher=record.get("publisher"),
                    work_type=record.get("type"),
                    abstract=clean_text(record.get("abstract"))[:4000],
                    published_on=published_on,
                    published_precision=precision,
                    keywords=tuple(record.get("subject") or []),
                    raw_title_markup=raw_title,
                    affiliations=tuple(dict.fromkeys(affiliations)),
                    related_identifiers=tuple(sorted(set(related))),
                )
            )
        return works


def _openalex_abstract(inverted: dict[str, list[int]] | None) -> str:
    if not inverted:
        return ""
    positions = sorted(
        (index, word) for word, indexes in inverted.items() for index in indexes
    )
    return " ".join(word for _, word in positions)


class OpenAlexProvider:
    """OpenAlex works API (free, no key) filtered on title/abstract and date."""

    name = "openalex"
    base_url = "https://api.openalex.org/works"

    def build_request(
        self, query: str, since: date, until: date, rows: int
    ) -> ProviderRequest:
        params = {
            "filter": (
                f"title_and_abstract.search:{query},"
                f"from_publication_date:{since.isoformat()},to_publication_date:{until.isoformat()}"
            ),
            "per-page": str(rows),
            "sort": "publication_date:desc",
            **_contact_params(),
        }
        return ProviderRequest(self.name, f"{self.base_url}?{urlencode(params)}")

    def parse(self, payload: Any) -> list[DiscoveredWork]:
        works: list[DiscoveredWork] = []
        for record in (payload or {}).get("results") or []:
            raw_title = str(record.get("display_name") or record.get("title") or "")
            title = clean_text(raw_title)
            identifier = str(record.get("id") or "").rsplit("/", 1)[-1]
            if not title or not identifier:
                continue
            published_on, precision = parse_partial_date(record.get("publication_date"))
            authors, affiliations = [], []
            for authorship in record.get("authorships") or []:
                name = (authorship.get("author") or {}).get("display_name")
                if name:
                    authors.append(name)
                for institution in authorship.get("institutions") or []:
                    if institution.get("display_name"):
                        affiliations.append(institution["display_name"])
            location = record.get("primary_location") or {}
            source = location.get("source") or {}
            works.append(
                DiscoveredWork(
                    provider=self.name,
                    provider_record_id=identifier,
                    title=title,
                    doi=normalize_doi(record.get("doi")),
                    url=location.get("landing_page_url"),
                    authors=tuple(authors),
                    venue=source.get("display_name"),
                    publisher=source.get("host_organization_name"),
                    work_type=record.get("type"),
                    abstract=_openalex_abstract(record.get("abstract_inverted_index"))[
                        :4000
                    ],
                    published_on=published_on,
                    published_precision=precision,
                    keywords=tuple(
                        keyword.get("display_name", "")
                        for keyword in record.get("keywords") or []
                        if keyword.get("display_name")
                    ),
                    raw_title_markup=raw_title,
                    affiliations=tuple(dict.fromkeys(affiliations)),
                )
            )
        return works


class EuropePmcProvider:
    """Europe PMC REST search (includes preprints) on first-index date."""

    name = "europepmc"
    base_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def build_request(
        self, query: str, since: date, until: date, rows: int
    ) -> ProviderRequest:
        terms = " OR ".join(f"TITLE_ABS:{term}" for term in query.split())
        params = {
            "query": f"({terms}) AND FIRST_IDATE:[{since.isoformat()} TO {until.isoformat()}]",
            "format": "json",
            "resultType": "core",
            "pageSize": str(rows),
        }
        return ProviderRequest(self.name, f"{self.base_url}?{urlencode(params)}")

    def parse(self, payload: Any) -> list[DiscoveredWork]:
        works: list[DiscoveredWork] = []
        for record in ((payload or {}).get("resultList") or {}).get("result") or []:
            raw_title = str(record.get("title") or "")
            title = clean_text(raw_title)
            identifier = f"{record.get('source', 'UNK')}:{record.get('id', '')}"
            if not title or identifier.endswith(":"):
                continue
            published_on, precision = parse_partial_date(
                record.get("firstPublicationDate")
            )
            authors = tuple(
                author.get("fullName")
                for author in ((record.get("authorList") or {}).get("author") or [])
                if author.get("fullName")
            )
            journal = ((record.get("journalInfo") or {}).get("journal") or {}).get(
                "title"
            )
            doi = normalize_doi(record.get("doi"))
            pmcid = record.get("pmcid")
            url = f"https://europepmc.org/article/{record.get('source')}/{record.get('id')}"
            works.append(
                DiscoveredWork(
                    provider=self.name,
                    provider_record_id=identifier,
                    title=title,
                    doi=doi,
                    url=url,
                    authors=authors,
                    venue=journal
                    or (record.get("bookOrReportDetails") or {}).get("publisher"),
                    work_type="preprint"
                    if record.get("source") == "PPR"
                    else record.get("pubType"),
                    abstract=clean_text(record.get("abstractText"))[:4000],
                    published_on=published_on,
                    published_precision=precision,
                    keywords=tuple(
                        ((record.get("keywordList") or {}).get("keyword")) or []
                    ),
                    raw_title_markup=raw_title,
                    related_identifiers=tuple(
                        value
                        for value in (f"pmcid:{pmcid}" if pmcid else None,)
                        if value
                    ),
                )
            )
        return works


PROVIDERS: dict[str, Provider] = {
    provider.name: provider
    for provider in (CrossrefProvider(), OpenAlexProvider(), EuropePmcProvider())
}


def default_http_get(url: str, **kwargs: Any) -> HttpResponse:
    import requests

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    return requests.get(url, headers=headers, timeout=kwargs.get("timeout", 20))
