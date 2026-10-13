"""Versioned list-price cost estimation for provider usage receipts.

Pure and deterministic: no network, no provider calls, no environment reads.

Three rules keep the numbers honest:

* **An estimate is never a bill.** Everything computed here is a list-price
  estimate (``basis = "list_price_estimate"``). ``billed_usd`` stays ``None``
  until a provider-reported billed amount exists; the Messages API returns
  none per request.
* **Each request is priced on its own.** Some rates depend on a request's
  prompt length, and cache reads/writes count toward it, so pricing run totals
  would pick the wrong rate. Callers pass per-request usage.
* **Unknown stays unknown.** An unlisted model, an unmodelled modifier (fast
  mode, batch or priority tier) or malformed usage makes the run's estimate
  ``None`` rather than a partial number presented as a total. The priced
  subtotal is still reported, labelled incomplete.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

PRICING_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "provider-pricing-v1.json"
)
PRICING_SCHEMA = "oc.provider-pricing.v1"
COST_SCHEMA = "oc.execution-cost.v1"
COST_BASIS = "list_price_estimate"
BILLED_UNAVAILABLE = "unavailable: provider does not report billed cost per request"
RATE_KEYS = ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read")
MILLION = Decimal(1_000_000)
USD_QUANTUM = Decimal("0.000001")


class PricingError(ValueError):
    """The pricing table itself is malformed."""


@dataclass(frozen=True)
class PricingTable:
    version: str
    source_url: str
    retrieved_at: str
    geo_us_multiplier: Decimal
    models: Mapping[str, Mapping[str, Any]]
    aliases: Mapping[str, str]

    def resolve(self, model: str) -> str | None:
        """Exact id or a declared alias only -- never a prefix match.

        ``claude-sonnet-4`` must not price ``claude-sonnet-4-5``.
        """
        if model in self.models:
            return model
        return self.aliases.get(model)


def _decimal(value: Any, where: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise PricingError(f"{where}: not a decimal: {value!r}") from exc
    if not result.is_finite() or result < 0:
        raise PricingError(f"{where}: must be a finite non-negative decimal")
    return result


def _rates(raw: Any, where: str) -> dict[str, Decimal]:
    if not isinstance(raw, Mapping) or set(raw) != set(RATE_KEYS):
        raise PricingError(f"{where}: rates must define exactly {RATE_KEYS}")
    return {key: _decimal(raw[key], f"{where}.{key}") for key in RATE_KEYS}


def parse_table(payload: Mapping[str, Any]) -> PricingTable:
    if payload.get("schema") != PRICING_SCHEMA:
        raise PricingError("wrong pricing schema")
    if payload.get("currency") != "USD" or payload.get("unit") != "per_million_tokens":
        raise PricingError("pricing must be USD per million tokens")
    version = str(payload.get("version") or "")
    source = payload.get("source") or {}
    if not version or not source.get("url") or not source.get("retrieved_at"):
        raise PricingError("pricing needs a version and a dated source")
    models: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    for model_id, spec in (payload.get("models") or {}).items():
        entry: dict[str, Any] = {
            "rates": _rates(spec.get("rates"), model_id),
            "geo": bool(spec.get("inference_geo_us_multiplier")),
            "limit": spec.get("standard_rate_prompt_limit"),
            "long": None,
        }
        long_prompt = spec.get("long_prompt")
        if long_prompt is not None:
            entry["long"] = (
                int(long_prompt["over_tokens"]),
                _rates(long_prompt.get("rates"), f"{model_id}.long_prompt"),
            )
        models[model_id] = entry
        for alias in spec.get("aliases") or []:
            if alias in models or alias in aliases:
                raise PricingError(f"duplicate model id or alias: {alias}")
            aliases[alias] = model_id
    if not models:
        raise PricingError("pricing table lists no models")
    multiplier = _decimal(
        (payload.get("modifiers") or {}).get("inference_geo_us_multiplier", "1"),
        "modifiers.inference_geo_us_multiplier",
    )
    return PricingTable(
        version,
        str(source["url"]),
        str(source["retrieved_at"]),
        multiplier,
        models,
        aliases,
    )


def load_table(path: Path = PRICING_PATH) -> PricingTable:
    return parse_table(json.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class RequestCost:
    model: str
    priced: bool
    usd: Decimal | None
    components: dict[str, Decimal]
    approximations: tuple[str, ...] = ()
    unpriced_reason: str = ""


def _count(usage: Mapping[str, Any], key: str) -> int:
    value = usage.get(key)
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"usage.{key} must be a non-negative integer")
    return value


def price_request(
    model: str, usage: Mapping[str, Any], table: PricingTable
) -> RequestCost:
    """Price one provider request from its ``usage`` object."""
    key = table.resolve(model)
    if key is None:
        return RequestCost(
            model,
            False,
            None,
            {},
            unpriced_reason=f"model not in pricing {table.version}",
        )
    speed = usage.get("speed")
    if speed not in (None, "standard"):
        return RequestCost(
            model, False, None, {}, unpriced_reason=f"unmodelled speed={speed}"
        )
    tier = usage.get("service_tier")
    if tier not in (None, "standard"):
        return RequestCost(
            model, False, None, {}, unpriced_reason=f"unmodelled service_tier={tier}"
        )
    try:
        tokens = {
            "input": _count(usage, "input_tokens"),
            "output": _count(usage, "output_tokens"),
            "cache_read": _count(usage, "cache_read_input_tokens"),
        }
        creation = _count(usage, "cache_creation_input_tokens")
        breakdown = usage.get("cache_creation")
        approximations: list[str] = []
        if isinstance(breakdown, Mapping):
            tokens["cache_write_5m"] = _count(breakdown, "ephemeral_5m_input_tokens")
            tokens["cache_write_1h"] = _count(breakdown, "ephemeral_1h_input_tokens")
            if tokens["cache_write_5m"] + tokens["cache_write_1h"] != creation:
                raise ValueError(
                    "cache_creation breakdown does not sum to cache_creation_input_tokens"
                )
        else:
            tokens["cache_write_5m"] = creation
            tokens["cache_write_1h"] = 0
            if creation:
                approximations.append("cache_write_ttl_assumed_5m")
    except ValueError as exc:
        return RequestCost(model, False, None, {}, unpriced_reason=str(exc))

    spec = table.models[key]
    rates = spec["rates"]
    prompt = (
        tokens["input"]
        + tokens["cache_read"]
        + tokens["cache_write_5m"]
        + tokens["cache_write_1h"]
    )
    if spec["long"] is not None and prompt > spec["long"][0]:
        rates = spec["long"][1]
    if spec["limit"] is not None and prompt > int(spec["limit"]):
        approximations.append(f"prompt_over_{spec['limit']}_priced_at_standard_rate")
    multiplier = Decimal(1)
    geo = usage.get("inference_geo")
    if geo == "us" and spec["geo"]:
        multiplier = table.geo_us_multiplier
    elif geo not in (None, "global", "us"):
        return RequestCost(
            model, False, None, {}, unpriced_reason=f"unmodelled inference_geo={geo}"
        )

    components = {
        name: Decimal(count) * rates[name] * multiplier / MILLION
        for name, count in tokens.items()
    }
    return RequestCost(
        key,
        True,
        sum(components.values(), Decimal(0)),
        components,
        tuple(approximations),
    )


def _usd(value: Decimal | None) -> str | None:
    return (
        None
        if value is None
        else str(value.quantize(USD_QUANTUM, rounding=ROUND_HALF_UP))
    )


@dataclass
class CostEstimate:
    """Run-level cost block written into execution receipts."""

    model: str
    pricing_version: str
    source_url: str
    requests: int = 0
    requests_unpriced: int = 0
    subtotal: Decimal = Decimal(0)
    components: dict[str, Decimal] = field(
        default_factory=lambda: {k: Decimal(0) for k in RATE_KEYS}
    )
    approximations: set[str] = field(default_factory=set)
    unpriced_reasons: set[str] = field(default_factory=set)

    def add(self, cost: RequestCost) -> None:
        self.requests += 1
        if not cost.priced:
            self.requests_unpriced += 1
            self.unpriced_reasons.add(cost.unpriced_reason)
            return
        self.subtotal += cost.usd or Decimal(0)
        for name, value in cost.components.items():
            self.components[name] += value
        self.approximations.update(cost.approximations)

    @property
    def complete(self) -> bool:
        return self.requests > 0 and self.requests_unpriced == 0

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "schema": COST_SCHEMA,
            "basis": COST_BASIS,
            "billed_usd": None,
            "billed_basis": BILLED_UNAVAILABLE,
            "estimated_usd": _usd(self.subtotal) if self.complete else None,
            "priced_subtotal_usd": _usd(self.subtotal),
            "complete": self.complete,
            "model": self.model,
            "pricing_version": self.pricing_version,
            "pricing_source": self.source_url,
            "requests": self.requests,
            "requests_unpriced": self.requests_unpriced,
            "components_usd": {
                name: _usd(value) for name, value in self.components.items()
            },
            "approximations": sorted(self.approximations),
            "unpriced_reasons": sorted(self.unpriced_reasons),
        }


def estimate(
    model: str, request_usages: Iterable[Mapping[str, Any]], table: PricingTable
) -> CostEstimate:
    result = CostEstimate(
        model=model, pricing_version=table.version, source_url=table.source_url
    )
    for usage in request_usages:
        result.add(price_request(model, usage, table))
    return result


def unavailable_cost(reason: str) -> dict[str, Any]:
    """Cost block for when pricing itself could not run (missing/invalid table)."""
    return {
        "schema": COST_SCHEMA,
        "basis": "unavailable",
        "billed_usd": None,
        "billed_basis": BILLED_UNAVAILABLE,
        "estimated_usd": None,
        "complete": False,
        "unpriced_reasons": [reason],
    }
