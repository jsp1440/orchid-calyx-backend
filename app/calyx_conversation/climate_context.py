from __future__ import annotations

import html
import os
import re
from datetime import UTC, datetime
from typing import Any

import requests

CPC_SEASONAL_DISCUSSION_URL = (
    "https://www.cpc.ncep.noaa.gov/products/predictions/long_range/fxus05.html"
)
CPC_MONTHLY_DISCUSSION_URL = (
    "https://www.cpc.ncep.noaa.gov/products/predictions/90day/fxus07.html"
)

_CLIMATE_TERMS = (
    "el nino",
    "el niño",
    "la nina",
    "la niña",
    "enso",
    "climate",
    "seasonal",
    "winter",
    "rain",
    "rainfall",
    "precipitation",
    "wet winter",
    "dry winter",
    "forecast",
    "outlook",
)
_SUMMARY_TERMS = (
    "el nino",
    "el niño",
    "la nina",
    "la niña",
    "enso",
    "california",
    "west coast",
    "southwest",
    "precipitation",
    "above-normal",
    "below-normal",
    "above normal",
    "below normal",
    "temperature",
    "probability",
    "confidence",
    "winter",
    "djf",
    "ndj",
    "jfm",
)
_NAVIGATION_NOISE = (
    "site map",
    "organization search",
    "search by city",
    "our mission",
    "who we are",
    "contact us",
    "tools more outlooks",
)


def climate_context_relevant(message: str) -> bool:
    normalized = " ".join(message.casefold().split())
    return any(term in normalized for term in _CLIMATE_TERMS)


def _html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", value)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[\t\r ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def _sentences(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return []
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+", compact) if item.strip()]


def _summary_points(text: str, *, limit: int = 10) -> list[str]:
    """Extract forecast-bearing statements instead of CPC page navigation chrome."""

    ranked: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(_sentences(text)):
        normalized = sentence.casefold()
        if any(noise in normalized for noise in _NAVIGATION_NOISE):
            continue
        hits = sum(term in normalized for term in _SUMMARY_TERMS)
        if hits == 0:
            continue
        # Prefer sentences that combine a geography/season with a forecast variable.
        has_region = any(term in normalized for term in ("california", "west coast", "southwest"))
        has_variable = any(term in normalized for term in ("precipitation", "temperature", "enso", "el nino", "el niño", "la nina", "la niña"))
        score = hits + (2 if has_region and has_variable else 0)
        ranked.append((-score, index, sentence[:900]))

    selected = sorted(ranked)[:limit]
    # Restore source order after ranking selection so the resulting summary reads coherently.
    return [sentence for _, _, sentence in sorted(selected, key=lambda item: item[1])]


def _extract_issue_time(text: str) -> str | None:
    patterns = (
        r"\b\d{3,4}\s*(?:AM|PM)\s+(?:EDT|EST|CDT|CST|MDT|MST|PDT|PST)\s+[A-Z][a-z]{2}\s+[A-Z][a-z]{2}\s+\d{1,2}\s+\d{4}\b",
        r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+[A-Z][a-z]{2}\s+\d{1,2}\s+\d{4}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


def _fetch_product(url: str, *, timeout: float) -> dict[str, Any]:
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "OrchidContinuum-Calyx/1.0"},
    )
    response.raise_for_status()
    text = _html_to_text(response.text)
    points = _summary_points(text)
    return {
        "source": "NOAA/NWS Climate Prediction Center",
        "url": url,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "issued_text": _extract_issue_time(text),
        "summary_points": points,
        "summary_text": " ".join(points)[:7000],
        # Keep a bounded raw excerpt for audit/debugging, but providers should prefer
        # summary_points/summary_text so navigation text never dominates the answer.
        "raw_text_excerpt": text[:5000],
        "external": True,
        "time_sensitive": True,
        "canonical_orchid_evidence": False,
    }


def build_seasonal_climate_context(message: str) -> dict[str, Any]:
    """Fetch and structure current NOAA CPC discussions for climate-sensitive turns."""

    if not climate_context_relevant(message):
        return {
            "requested": False,
            "status": "not_relevant",
            "products": [],
            "external": True,
            "time_sensitive": True,
        }

    timeout = max(
        1.0,
        min(float(os.getenv("CALYX_CLIMATE_TIMEOUT_SECONDS", "10")), 30.0),
    )
    products: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []
    for name, url in (
        ("seasonal_outlook_discussion", CPC_SEASONAL_DISCUSSION_URL),
        ("monthly_outlook_discussion", CPC_MONTHLY_DISCUSSION_URL),
    ):
        try:
            product = _fetch_product(url, timeout=timeout)
            product["product"] = name
            products.append(product)
        except requests.RequestException as exc:
            diagnostics.append({"product": name, "url": url, "error": str(exc)})

    return {
        "requested": True,
        "status": "available" if products else "unavailable",
        "provider": "NOAA/NWS Climate Prediction Center",
        "products": products,
        "diagnostics": diagnostics,
        "external": True,
        "time_sensitive": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }
