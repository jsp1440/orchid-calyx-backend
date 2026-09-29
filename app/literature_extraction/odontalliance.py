from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .ingest import WebSourceMetadata
from .repository import LiteratureResultRepository
from .service import extract_and_persist

SOURCE_ID = "international-odontoglossum-alliance"
SOURCE_NAME = "International Odontoglossum Alliance"
ORIGIN = "https://www.odontalliance.org"
CULTURE_URL = f"{ORIGIN}/culture.html"
DISCOVERY_SEEDS = (
    CULTURE_URL,
    f"{ORIGIN}/master-index.html",
    f"{ORIGIN}/recent-journals.html",
    f"{ORIGIN}/historical-items/index.html",
    f"{ORIGIN}/publication-archive/2018---2014.html",
    f"{ORIGIN}/publication-archive/2013---2010.html",
    f"{ORIGIN}/publication-archive/2009---2005.html",
    f"{ORIGIN}/publication-archive/2004---2001.html",
    f"{ORIGIN}/publication-archive/2000---1998.html",
    f"{ORIGIN}/publication-archive/1997---1996.html",
    f"{ORIGIN}/publication-archive/1995---1994.html",
    f"{ORIGIN}/publication-archive/1993---1986.html",
)
ALLOWED_PREFIXES = (
    "/culture.html",
    "/master-index.html",
    "/recent-journals.html",
    "/publication-archive",
    "/historical",
    "/intergeneric",
    "/ewExternalFiles/",
)
ALLOWED_SUFFIXES = (".html", ".htm", ".pdf")


class OdontAllianceIntakeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IntakeLimits:
    max_resources: int = 250
    max_resource_bytes: int = 25_000_000
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_resources <= 1000:
            raise ValueError("max_resources must be between 1 and 1000")
        if not 1 <= self.max_resource_bytes <= 100_000_000:
            raise ValueError("max_resource_bytes must be between 1 and 100000000")
        if not 0 < self.timeout_seconds <= 60:
            raise ValueError("timeout_seconds must be between 0 and 60")


@dataclass(frozen=True, slots=True)
class DiscoveredResource:
    url: str
    resource_type: str
    rights_status: str = "unknown_requires_review"
    ingest_state: str = "metadata_only_pending_rights_review"
    historical_taxonomy_requires_resolution: bool = True


@dataclass(frozen=True, slots=True)
class AcquiredCulturePage:
    source_url: str
    source_html_hash: str
    projected_text_hash: str
    retrieved_at: str
    text_path: Path
    acquisition_path: Path

    def web_source(self) -> WebSourceMetadata:
        return WebSourceMetadata(
            origin_uri=self.source_url,
            origin_content_hash=self.source_html_hash,
            rights_status="unknown_requires_review",
            redistribution_allowed=False,
            historical_taxonomy_requires_resolution=True,
        )


class _DocumentParser(HTMLParser):
    _ignored: ClassVar[frozenset[str]] = frozenset(
        {"script", "style", "noscript", "svg"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._hrefs: list[str] = []
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in self._ignored:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag.casefold() == "a":
            href = dict(attrs).get("href")
            if href:
                self._hrefs.append(href)
        if tag.casefold() in {"p", "div", "br", "li", "h1", "h2", "h3", "h4"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self._ignored and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if not self._ignored_depth and tag.casefold() in {
            "p",
            "div",
            "li",
            "h1",
            "h2",
            "h3",
            "h4",
        }:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self._chunks.append(data)

    @property
    def hrefs(self) -> tuple[str, ...]:
        return tuple(self._hrefs)

    @property
    def lines(self) -> tuple[str, ...]:
        text = "".join(self._chunks).replace("\xa0", " ")
        return tuple(
            line
            for line in (" ".join(item.split()) for item in text.splitlines())
            if line
        )


def canonical_url(value: str, *, base_url: str = ORIGIN) -> str:
    resolved = urlsplit(urljoin(base_url, value))
    if resolved.scheme != "https" or resolved.hostname != "www.odontalliance.org":
        raise OdontAllianceIntakeError("URL_OUTSIDE_ALLOWLIST")
    path = unquote(resolved.path)
    if ".." in Path(path).parts:
        raise OdontAllianceIntakeError("URL_PATH_TRAVERSAL")
    if not path.startswith(ALLOWED_PREFIXES) or not path.casefold().endswith(
        ALLOWED_SUFFIXES
    ):
        raise OdontAllianceIntakeError("URL_PATH_OUTSIDE_CORPUS")
    return urlunsplit(("https", "www.odontalliance.org", resolved.path, "", ""))


def _resource_type(url: str) -> str:
    path = urlsplit(url).path.casefold()
    if path.endswith(".pdf"):
        return "journal_or_index_pdf"
    if "culture" in path:
        return "culture_page"
    if "master-index" in path:
        return "publication_index"
    if "recent-journals" in path:
        return "recent_journal_index"
    if "publication-archive" in path:
        return "publication_archive_index"
    if "historical" in path:
        return "historical_index"
    if "intergeneric" in path:
        return "hybrid_reference"
    return "site_resource"


def discover_resources(
    pages: Iterable[tuple[str, bytes]], *, limits: IntakeLimits | None = None
) -> list[DiscoveredResource]:
    bounded = limits or IntakeLimits()
    resources: dict[str, DiscoveredResource] = {}
    for page_url, html_bytes in pages:
        if len(html_bytes) > bounded.max_resource_bytes:
            raise OdontAllianceIntakeError("RESOURCE_BYTE_LIMIT_EXCEEDED")
        parser = _DocumentParser()
        parser.feed(html_bytes.decode("utf-8", errors="replace"))
        for href in parser.hrefs:
            try:
                url = canonical_url(href, base_url=page_url)
            except OdontAllianceIntakeError:
                continue
            resources[url] = DiscoveredResource(
                url=url, resource_type=_resource_type(url)
            )
            if len(resources) > bounded.max_resources:
                raise OdontAllianceIntakeError("RESOURCE_COUNT_LIMIT_EXCEEDED")
    return [resources[url] for url in sorted(resources)]


def _culture_body(html_bytes: bytes) -> list[str]:
    parser = _DocumentParser()
    parser.feed(html_bytes.decode("utf-8", errors="strict"))
    lines = list(parser.lines)
    try:
        start = next(
            index
            for index, line in enumerate(lines)
            if line.casefold() == "culture of odontoglossums"
        )
    except StopIteration as exc:
        raise OdontAllianceIntakeError("CULTURE_HEADING_NOT_FOUND") from exc
    body = lines[start + 1 :]
    if not body:
        raise OdontAllianceIntakeError("CULTURE_BODY_EMPTY")
    return body


def project_culture_page(html_bytes: bytes, *, source_url: str = CULTURE_URL) -> str:
    canonical = canonical_url(source_url)
    body = _culture_body(html_bytes)
    background: list[str] = []
    guidance: list[str] = []
    for line in body:
        if re.match(
            r"^(?:Light|Temperature|Watering|Fertiliser|Fertilizer|Air movement|Potting)\s*-",
            line,
            flags=re.IGNORECASE,
        ):
            guidance.append(line)
        elif guidance:
            guidance[-1] = f"{guidance[-1]} {line}"
        else:
            background.append(line)

    if not background or len(guidance) < 5:
        raise OdontAllianceIntakeError("CULTURE_STRUCTURE_INCOMPLETE")

    recommendations = [
        line
        if line.casefold().startswith("odontoglossum")
        else f"Odontoglossum: {line}"
        for line in guidance
    ]
    return "\n".join(
        [
            "Culture of Odontoglossums",
            f"Source URI: {canonical}",
            f"Publisher: {SOURCE_NAME}",
            "Rights status: unknown; review required before redistribution.",
            "Historical taxonomy: source-reported names require resolution.",
            "",
            "BACKGROUND",
            *background,
            "",
            "CULTIVATION GUIDANCE",
            *recommendations,
            "",
        ]
    )


def acquire_culture_page(
    html_bytes: bytes,
    output_root: str | Path,
    *,
    source_url: str = CULTURE_URL,
    retrieved_at: datetime | None = None,
) -> AcquiredCulturePage:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    projected = project_culture_page(html_bytes, source_url=source_url)
    source_hash = sha256(html_bytes).hexdigest()
    projected_bytes = projected.encode("utf-8")
    projected_hash = sha256(projected_bytes).hexdigest()
    text_path = root / f"culture-{projected_hash}.txt"
    acquisition_path = root / f"culture-{projected_hash}.acquisition.json"
    text_path.write_bytes(projected_bytes)
    when = (retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    record = {
        "source_id": SOURCE_ID,
        "source_name": SOURCE_NAME,
        "source_url": canonical_url(source_url),
        "source_html_sha256": source_hash,
        "projected_text_sha256": projected_hash,
        "retrieved_at": when.isoformat(),
        "acquisition_method": "bounded_https_fetch",
        "rights_status": "unknown_requires_review",
        "redistribution_allowed": False,
        "historical_taxonomy_requires_resolution": True,
        "knowledge_graph_publication_allowed": False,
    }
    acquisition_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return AcquiredCulturePage(
        source_url=record["source_url"],
        source_html_hash=source_hash,
        projected_text_hash=projected_hash,
        retrieved_at=record["retrieved_at"],
        text_path=text_path,
        acquisition_path=acquisition_path,
    )


async def ingest_culture_page(
    html_bytes: bytes,
    output_root: str | Path,
    *,
    source_url: str = CULTURE_URL,
    retrieved_at: datetime | None = None,
):
    root = Path(output_root)
    acquired = acquire_culture_page(
        html_bytes,
        root / "acquisitions",
        source_url=source_url,
        retrieved_at=retrieved_at,
    )
    paper = await extract_and_persist(
        acquired.text_path,
        LiteratureResultRepository(root / "literature"),
        web_source=acquired.web_source(),
    )
    return acquired, paper


def fetch_url(url: str, limits: IntakeLimits | None = None) -> bytes:
    bounded = limits or IntakeLimits()
    canonical = canonical_url(url)
    request = Request(
        canonical,
        headers={"User-Agent": "OrchidContinuum/1.0 (+https://orchidcontinuum.org)"},
    )
    with urlopen(request, timeout=bounded.timeout_seconds) as response:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > bounded.max_resource_bytes:
            raise OdontAllianceIntakeError("RESOURCE_BYTE_LIMIT_EXCEEDED")
        payload = response.read(bounded.max_resource_bytes + 1)
    if len(payload) > bounded.max_resource_bytes:
        raise OdontAllianceIntakeError("RESOURCE_BYTE_LIMIT_EXCEEDED")
    return payload


def live_discovery(
    output_path: str | Path,
    *,
    limits: IntakeLimits | None = None,
    fetcher: Callable[[str, IntakeLimits | None], bytes] = fetch_url,
) -> list[DiscoveredResource]:
    bounded = limits or IntakeLimits()
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    completed_seeds: set[str] = set()
    resources_by_url: dict[str, DiscoveredResource] = {}

    if target.is_file():
        try:
            checkpoint = json.loads(target.read_text(encoding="utf-8"))
            if checkpoint.get("source_id") != SOURCE_ID:
                raise ValueError("source identity mismatch")
            completed_seeds = {
                canonical_url(value) for value in checkpoint.get("completed_seeds", [])
            }
            resources_by_url = {
                item["url"]: DiscoveredResource(**item)
                for item in checkpoint.get("resources", [])
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OdontAllianceIntakeError("DISCOVERY_CHECKPOINT_INVALID") from exc

    def save_checkpoint() -> None:
        resources = [resources_by_url[url] for url in sorted(resources_by_url)]
        payload = {
            "source_id": SOURCE_ID,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "rights_status": "unknown_requires_review",
            "automatic_publication": False,
            "complete": completed_seeds == set(DISCOVERY_SEEDS),
            "completed_seeds": sorted(completed_seeds),
            "resource_count": len(resources),
            "resources": [asdict(resource) for resource in resources],
        }
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(target)

    for url in DISCOVERY_SEEDS:
        if url in completed_seeds:
            continue
        page_resources = discover_resources(
            [(url, fetcher(url, bounded))], limits=bounded
        )
        for resource in page_resources:
            resources_by_url[resource.url] = resource
        if len(resources_by_url) > bounded.max_resources:
            raise OdontAllianceIntakeError("RESOURCE_COUNT_LIMIT_EXCEEDED")
        completed_seeds.add(url)
        save_checkpoint()

    return [resources_by_url[url] for url in sorted(resources_by_url)]
