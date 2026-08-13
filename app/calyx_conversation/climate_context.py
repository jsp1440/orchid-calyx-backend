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


def _fetch_product(url: str, *, timeout: float) -> dict[str, Any]:
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "OrchidContinuum-Calyx/1.0"},
    )
    response.raise_for_status()
    text = _html_to_text(response.text)
    return {
        "source": "NOAA/NWS Climate Prediction Center",
        "url": url,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "text": text[:12000],
        "external": True,
        "time_sensitive": True,
        "canonical_orchid_evidence": False,
    }


def build_seasonal_climate_context(message: str) -> dict[str, Any]:
    """Fetch current NOAA CPC discussions for climate-sensitive Calyx questions."""

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
