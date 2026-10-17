"""Bounded Firecrawl v2 acquisition. Responses are untrusted source material.

The caller owns the canonical lease and supplies the existing Swarm governor.
Live calls additionally require a durable reservation callback: an in-memory
budget alone cannot enforce a daily cap across worker restarts. No credentials,
response bodies, or source excerpts are included in errors or receipts.

:func:`live_gate` and :func:`reserve_live_attempt` are the ONE admission gate
and pre-transport reservation for a paid Firecrawl call. ``FirecrawlProvider``
and the federation Map pilot (``app.federation.federation_pilot``) both call
them, so the two paths cannot drift apart.

Every live attempt runs under a wall-clock deadline
(``FirecrawlConfig.request_timeout_seconds``; httpx timeouts are per phase and
do not bound a slow-drip response), and a live search is routed through the
acquisition ledger (``search_cache``): a repeat of the same normalized query
within ``FirecrawlConfig.search_cache_seconds`` pays nothing.
"""

from __future__ import annotations

import ipaddress
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.source_federation.deadline import (
    PaidCallDeadlineExceeded,
    call_with_deadline,
    lease_seconds_for,
)
from runtime.swarm.models import ExecutionRequest

from .extractors.morphology import MORPHOLOGY_PREDICATES

ACQUISITION_PREDICATES = MORPHOLOGY_PREDICATES


class AcquisitionBlocked(ValueError):
    pass


def canonical_url(value: str, domains: tuple[str, ...]) -> str:
    parts = urlsplit(value)
    host = (parts.hostname or "").lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise AcquisitionBlocked("IP_ADDRESS_FORBIDDEN")
    if (
        parts.scheme != "https"
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
        or host not in domains
        or any(ord(c) < 33 for c in value)
        or "\\" in value
    ):
        raise AcquisitionBlocked("SOURCE_URL_NOT_APPROVED")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
    ]
    return urlunsplit(("https", host, parts.path or "/", urlencode(sorted(query)), ""))


@dataclass(frozen=True)
class FirecrawlConfig:
    enabled: bool = False
    dry_run: bool = True
    pilot_mode: bool = True
    domains: tuple[str, ...] = ()
    max_searches: int = 1
    max_documents: int = 2
    retry_cap: int = 2
    backoff_seconds: float = 1
    max_bytes: int = 2_000_000
    max_call_cost: Decimal = Decimal(0)
    daily_budget: Decimal = Decimal(0)
    daily_credit_cap: int = 25
    request_timeout_seconds: float = 45.0
    search_cache_seconds: int = 7 * 24 * 3600

    def __post_init__(self):
        if not (
            0 <= self.max_searches <= 10
            and 1 <= self.max_documents <= 100
            and 0 <= self.retry_cap <= 3
            and 0 <= self.backoff_seconds <= 10
            and 1 <= self.max_bytes <= 10_000_000
        ):
            raise AcquisitionBlocked("INVALID_BOUNDS")
        if (
            type(self.daily_credit_cap) is not int
            or not 1 <= self.daily_credit_cap <= 25
        ):
            raise AcquisitionBlocked("INVALID_DAILY_CREDIT_CAP")
        if any(
            not n.is_finite() or n < 0 for n in (self.max_call_cost, self.daily_budget)
        ):
            raise AcquisitionBlocked("INVALID_BUDGET")
        timeout = self.request_timeout_seconds
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 1 <= timeout <= 120
        ):
            raise AcquisitionBlocked("INVALID_REQUEST_TIMEOUT")
        if (
            type(self.search_cache_seconds) is not int
            or not 1 <= self.search_cache_seconds <= 30 * 24 * 3600
        ):
            raise AcquisitionBlocked("INVALID_SEARCH_CACHE_WINDOW")

    def max_request_wall_seconds(self) -> float:
        """Upper bound on one ``_request``: every attempt's deadline plus backoff."""
        backoff = sum(
            min(10, self.backoff_seconds * (2**attempt))
            for attempt in range(self.retry_cap)
        )
        return (self.retry_cap + 1) * float(self.request_timeout_seconds) + backoff

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None):
        e = os.environ if env is None else env

        def flag(name, default):
            raw = e.get(name, default).lower()
            if raw not in {"true", "false"}:
                raise AcquisitionBlocked("INVALID_FLAG")
            return raw == "true"

        return cls(
            enabled=flag("FIRECRAWL_ENABLED", "false"),
            dry_run=flag("FIRECRAWL_DRY_RUN", "true"),
            pilot_mode=flag("FIRECRAWL_PILOT_MODE", "true"),
            domains=tuple(
                x.strip().lower()
                for x in e.get("FIRECRAWL_APPROVED_DOMAINS", "").split(",")
                if x.strip()
            ),
            max_searches=int(e.get("FIRECRAWL_MAX_SEARCHES_PER_TASK", "1")),
            max_documents=int(e.get("FIRECRAWL_MAX_DOCUMENTS", "2")),
            retry_cap=int(e.get("FIRECRAWL_RETRY_CAP", "2")),
            backoff_seconds=float(e.get("FIRECRAWL_BACKOFF_SECONDS", "1")),
            max_call_cost=Decimal(e.get("FIRECRAWL_MAX_CALL_COST_USD", "0")),
            daily_budget=Decimal(e.get("FIRECRAWL_DAILY_BUDGET_USD", "0")),
            daily_credit_cap=int(e.get("FIRECRAWL_DAILY_CREDIT_CAP", "25")),
            request_timeout_seconds=float(
                e.get("FIRECRAWL_REQUEST_TIMEOUT_SECONDS", "45")
            ),
            search_cache_seconds=int(
                e.get("FIRECRAWL_SEARCH_CACHE_SECONDS", str(7 * 24 * 3600))
            ),
        )


def live_gate(
    config: FirecrawlConfig,
    env: Mapping[str, str],
    *,
    fixture_transport=None,
    governor=None,
    reserve: Callable | None = None,
    reserve_credits: Callable | None = None,
    observe_credits: Callable | None = None,
    lease_check: Callable | None = None,
) -> None:
    """Raise :class:`AcquisitionBlocked` unless a Firecrawl call is admitted.

    A dry run is admitted only with a fixture transport (no network). A live
    call requires ``FIRECRAWL_ENABLED=true``, the kill switch exactly
    ``false``, ``PROVIDER_AUTHORIZED=true``, ``NO_API_MODE`` exactly ``false``
    (absent means on), ``FIRECRAWL_API_KEY``, and the complete durable budget
    authority (governor, USD and credit reservation, usage observation, a
    lease check, and positive per-call and daily USD budgets).
    """
    if (
        not config.enabled
        or env.get("FIRECRAWL_KILL_SWITCH", "false").lower() != "false"
    ):
        raise AcquisitionBlocked("FIRECRAWL_DISABLED")
    if config.dry_run:
        if fixture_transport is None:
            raise AcquisitionBlocked("DRY_RUN_NO_FIXTURE")
        return
    if fixture_transport is not None:
        raise AcquisitionBlocked("LIVE_FIXTURE_FORBIDDEN")
    if (
        env.get("PROVIDER_AUTHORIZED", "false").lower() != "true"
        or env.get("NO_API_MODE", "true").lower() != "false"
    ):
        raise AcquisitionBlocked("PROVIDER_NOT_AUTHORIZED")
    if not env.get("FIRECRAWL_API_KEY"):
        raise AcquisitionBlocked("FIRECRAWL_KEY_UNAVAILABLE")
    if (
        governor is None
        or reserve is None
        or reserve_credits is None
        or observe_credits is None
        or lease_check is None
        or config.max_call_cost <= 0
        or config.daily_budget <= 0
    ):
        raise AcquisitionBlocked("DURABLE_BUDGET_AUTHORITY_REQUIRED")


def reserve_live_attempt(
    config: FirecrawlConfig,
    *,
    governor,
    reserve: Callable,
    reserve_credits: Callable,
    task_id: str,
    credit_cost: int,
    attempt: int = 0,
):
    """Admit one live attempt and durably reserve its worst-case cost.

    Returns ``(governor_entry, credit_reservation)``; the caller must end the
    governor entry after the attempt. On any reservation failure the entry
    is ended and ``DURABLE_RESERVATION_FAILED`` is raised: no transport.
    """
    entry = governor.begin(
        ExecutionRequest(
            issue_task_id=task_id,
            provider="firecrawl",
            worker_lane="literature",
            retry_count=attempt,
            estimated_cost_usd=config.max_call_cost,
        )
    )
    try:
        credit_reservation = reserve_credits(
            task_id, credit_cost, config.daily_credit_cap
        )
        reserve(task_id, config.max_call_cost, config.daily_budget)
    except Exception:  # noqa: BLE001 - reservation failure must release slot without exposing DB details
        governor.end(entry, succeeded=False, termination_reason="reservation_failed")
        raise AcquisitionBlocked("DURABLE_RESERVATION_FAILED") from None
    return entry, credit_reservation


@dataclass(frozen=True)
class AcquiredSource:
    url: str
    markdown: str
    mocked: bool

    @property
    def content_hash(self):
        return sha256(self.markdown.encode()).hexdigest()


class FirecrawlProvider:
    """One bounded task, sharing the canonical provider governor and ledger.

    ``reserve`` must durably reserve the worst-case call cost against the daily
    provider cap BEFORE transport, including failed/ambiguous retry attempts.
    No refund is inferred from an HTTP failure. Production composition must
    supply that authority; absence blocks live execution.
    """

    def __init__(
        self,
        config: FirecrawlConfig,
        *,
        governor=None,
        reserve: Callable | None = None,
        reserve_credits: Callable | None = None,
        observe_credits: Callable | None = None,
        fixture_transport=None,
        env=None,
        sleep=time.sleep,
        search_cache=None,
    ):
        self.config = config
        self.governor = governor
        self.reserve = reserve
        self.reserve_credits = reserve_credits or getattr(
            reserve, "reserve_credits", None
        )
        self.observe_credits = observe_credits or getattr(
            reserve, "observe_credits", None
        )
        self.credits_reserved = self.reported_credits = self.usage_reports = 0
        self.fixture_transport = fixture_transport
        self.env = os.environ if env is None else env
        self.sleep = sleep
        self.searches = self.documents = self.calls = 0
        self.lease_check = None
        self._seen: dict[str, AcquiredSource] = {}
        self.search_results: dict[str, dict] = {}
        # Cross-run search reuse (``LedgerSearchCache``); required for a live
        # search, optional for a fixture dry run.
        self.search_cache = search_cache
        self.search_cache_hits = 0

    def _gate(self):
        live_gate(
            self.config,
            self.env,
            fixture_transport=self.fixture_transport,
            governor=self.governor,
            reserve=self.reserve,
            reserve_credits=self.reserve_credits,
            observe_credits=self.observe_credits,
            lease_check=self.lease_check,
        )

    @staticmethod
    def credit_cost(endpoint, payload):
        """Only the bounded basic tariff is admitted (Firecrawl billing docs)."""
        if endpoint == "search" and set(payload) == {"query", "limit"}:
            limit = payload["limit"]
            if type(limit) is int and 1 <= limit <= 100:
                return 2 * ((limit + 9) // 10)
        if (
            endpoint == "scrape"
            and set(payload)
            == {"url", "formats", "onlyMainContent", "parsers", "proxy"}
            and payload["formats"] == ["markdown"]
            and payload["parsers"] == []
            and payload["proxy"] == "basic"
            and payload["onlyMainContent"] is True
        ):
            # Reserve base page plus a possible account-level threat-protection scan.
            return 3
        raise AcquisitionBlocked("UNBOUNDED_CREDIT_OPTIONS")

    def credit_receipt(self):
        return {
            "reserved": self.credits_reserved,
            "daily_cap": self.config.daily_credit_cap,
            "provider_reported": self.reported_credits if self.usage_reports else None,
            "reported_attempts": self.usage_reports,
            "attempts": self.calls,
            "usage_complete": not self.config.dry_run
            and self.calls > 0
            and self.usage_reports == self.calls,
        }

    def _request(self, endpoint, payload, task_id):
        credit_cost = self.credit_cost(endpoint, payload)
        for attempt in range(self.config.retry_cap + 1):
            self._gate()
            if self.lease_check is not None:
                self.lease_check()
            entry = None
            credit_reservation = None
            if not self.config.dry_run:
                entry, credit_reservation = reserve_live_attempt(
                    self.config,
                    governor=self.governor,
                    reserve=self.reserve,
                    reserve_credits=self.reserve_credits,
                    task_id=task_id,
                    credit_cost=credit_cost,
                    attempt=attempt,
                )
                self.credits_reserved += credit_cost
            succeeded = False
            try:
                self.calls += 1
                if self.config.dry_run:
                    status, result = self.fixture_transport(endpoint, payload)
                else:
                    try:
                        status, result = call_with_deadline(
                            lambda: self._transport(endpoint, payload),
                            self.config.request_timeout_seconds,
                        )
                    except PaidCallDeadlineExceeded:
                        # Outcome unknown (the reservation stands, no refund);
                        # never retried inside this lease: the attempt may
                        # have been billed.
                        raise AcquisitionBlocked("PROVIDER_DEADLINE_EXCEEDED") from None
                if not self.config.dry_run:
                    used = (
                        result.get("creditsUsed") if isinstance(result, dict) else None
                    )
                    if used is None and isinstance(result, dict):
                        data = result.get("data")
                        if isinstance(data, dict):
                            used = data.get(
                                "creditsUsed",
                                data.get("metadata", {}).get("creditsUsed"),
                            )
                    if type(used) is not int or used < 0:
                        used = None
                    try:
                        self.observe_credits(credit_reservation, used)
                    except Exception:  # noqa: BLE001 - sanitize persistent ledger failures
                        raise AcquisitionBlocked(
                            "CREDIT_USAGE_PERSISTENCE_FAILED"
                        ) from None
                    if used is not None:
                        self.reported_credits += used
                        self.usage_reports += 1
                        if used > credit_cost:
                            raise AcquisitionBlocked("CREDIT_TARIFF_EXCEEDED")
                if status == 429 or status >= 500:
                    if attempt < self.config.retry_cap:
                        self.sleep(min(10, self.config.backoff_seconds * (2**attempt)))
                        continue
                    raise AcquisitionBlocked("RETRIES_EXHAUSTED")
                if (
                    status != 200
                    or not isinstance(result, dict)
                    or result.get("success") is not True
                ):
                    raise AcquisitionBlocked("PROVIDER_RESPONSE_INVALID")
                succeeded = True
                return result["data"]
            except (httpx.HTTPError, KeyError, TypeError):
                raise AcquisitionBlocked("PROVIDER_TRANSPORT_FAILED") from None
            finally:
                if entry:
                    self.governor.end(
                        entry,
                        succeeded=succeeded,
                        termination_reason="completed" if succeeded else "failed",
                    )
        raise AcquisitionBlocked("RETRIES_EXHAUSTED")

    def _transport(self, endpoint, payload):
        """One live HTTP exchange; the caller bounds its wall-clock."""
        import json

        timeout = float(self.config.request_timeout_seconds)
        with (
            httpx.Client(timeout=timeout, follow_redirects=False) as client,
            client.stream(
                "POST",
                "https://api.firecrawl.dev/v2/" + endpoint,
                headers={"Authorization": "Bearer " + self.env["FIRECRAWL_API_KEY"]},
                json=payload,
            ) as response,
        ):
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > self.config.max_bytes:
                    raise AcquisitionBlocked("RESPONSE_TOO_LARGE")
            status = response.status_code
            # A transient HTTP response need not contain valid JSON.
            return status, ({} if status != 200 else json.loads(raw))

    def _paid_search(self, payload, task_id):
        before = self.credits_reserved
        data = self._request("search", payload, task_id)
        return data, self.credits_reserved - before

    def search(
        self, genus: str, *, task_id: str, target_names=(), required_predicates=()
    ) -> list[str]:
        import re

        if not re.fullmatch(r"[A-Z][a-z]{2,40}", genus):
            raise AcquisitionBlocked("GENUS_REQUIRED")
        if len(target_names) > 5 or any(
            not re.fullmatch(re.escape(genus) + r" [a-z][a-z-]+", name)
            for name in target_names
        ):
            raise AcquisitionBlocked("INVALID_TARGETED_GAP")
        if len(required_predicates) > 32 or any(
            value not in ACQUISITION_PREDICATES for value in required_predicates
        ):
            raise AcquisitionBlocked("INVALID_REQUIRED_PREDICATES")
        subject = genus
        if target_names:
            subject += (
                " (" + " OR ".join('"' + name + '"' for name in target_names) + ")"
            )
        if self.searches >= self.config.max_searches or not self.config.domains:
            raise AcquisitionBlocked("SEARCH_LIMIT_OR_DOMAINS_MISSING")
        self.searches += 1
        # Sorted and de-duplicated, so the query (and its ledger key) does not
        # depend on the order the domains were configured in.
        sites = " OR ".join("site:" + d for d in sorted(set(self.config.domains)))
        characters = (
            ""
            if not required_predicates
            else " ("
            + " OR ".join(
                '"' + value.replace("_", " ") + '"'
                for value in sorted(set(required_predicates))
            )
            + ")"
        )
        payload = {
            "query": f"{subject}{characters} (monograph OR revision OR flora OR key) ({sites})",
            "limit": min(self.config.max_documents, 2)
            if self.config.pilot_mode
            else self.config.max_documents,
        }
        if self.search_cache is not None:
            status, data = self.search_cache.fetch(
                payload,
                lambda: self._paid_search(payload, task_id),
                lease_seconds=lease_seconds_for(self.config.max_request_wall_seconds()),
            )
            if status == "cache_hit":
                self.search_cache_hits += 1
        elif not self.config.dry_run:
            # A live search is only admitted through the acquisition ledger:
            # without it a repeat of the same gap would pay again.
            raise AcquisitionBlocked("SEARCH_LEDGER_REQUIRED")
        else:
            data = self._request("search", payload, task_id)
        urls = []
        for item in data.get("web", []):
            try:
                url = canonical_url(item["url"], self.config.domains)
            except (AcquisitionBlocked, KeyError, ValueError):
                continue
            if url not in urls:
                self.search_results[url] = {
                    key: item[key]
                    for key in (
                        "doi",
                        "title",
                        "authors",
                        "author",
                        "year",
                        "content_hash",
                        "binding_fingerprint",
                        "paper_id",
                    )
                    if key in item
                }
                urls.append(url)
        return urls[: self.config.max_documents]

    def scrape(self, url: str, *, task_id: str) -> AcquiredSource:
        self._gate()
        url = canonical_url(url, self.config.domains)
        if url in self._seen:
            return self._seen[url]
        limit = (
            min(2, self.config.max_documents)
            if self.config.pilot_mode
            else self.config.max_documents
        )
        if self.documents >= limit:
            raise AcquisitionBlocked("DOCUMENT_LIMIT")
        self.documents += 1
        data = self._request(
            "scrape",
            {
                "url": url,
                "formats": ["markdown"],
                "onlyMainContent": True,
                "parsers": [],
                "proxy": "basic",
            },
            task_id,
        )
        final_url = canonical_url(
            data.get("metadata", {}).get("sourceURL", url), self.config.domains
        )
        if final_url != url:
            raise AcquisitionBlocked("SOURCE_REDIRECT_REQUIRES_REVIEW")
        markdown = data.get("markdown")
        if (
            not isinstance(markdown, str)
            or not markdown.strip()
            or len(markdown.encode()) > self.config.max_bytes
        ):
            raise AcquisitionBlocked("SOURCE_TEXT_INVALID")
        source = AcquiredSource(url, markdown, self.config.dry_run)
        self._seen[url] = source
        return source


class PostgresFirecrawlReservation:
    """Atomic daily reservation in the existing Research Station record store.

    Fixed advisory lock serializes this provider across all workers. Connection
    must commit before returning, including reservations for ambiguous attempts.
    No new table, refill policy, scheduler, or credentials are introduced.
    """

    def __init__(self, connect):
        self.connect = connect

    def __call__(self, task_id, amount, cap):
        from datetime import datetime, timezone

        from psycopg.types.json import Jsonb

        from runtime.research_station_store import TABLE

        if not amount.is_finite() or not cap.is_finite() or amount <= 0 or cap <= 0:
            raise AcquisitionBlocked("INVALID_BUDGET")
        day = datetime.now(timezone.utc).date().isoformat()
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (742931601,))
            cur.execute(
                f"SELECT payload FROM {TABLE} WHERE owner_key=%s AND project_id=%s AND kind=%s AND record_id=%s FOR UPDATE",
                ("oc-autonomy", "firecrawl", "provider_budget", day),
            )
            row = cur.fetchone()
            payload = (
                (row["payload"] if isinstance(row, dict) else row[0]) if row else {}
            )
            spent = Decimal(payload.get("reserved_usd", "0"))
            if not spent.is_finite() or spent < 0 or spent + amount > cap:
                raise AcquisitionBlocked("DAILY_PROVIDER_CAP")
            cur.execute(
                f"""INSERT INTO {TABLE}(owner_key,project_id,kind,record_id,payload,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,NOW(),NOW())
                ON CONFLICT(owner_key,project_id,kind,record_id)
                DO UPDATE SET payload=EXCLUDED.payload,updated_at=NOW()""",
                (
                    "oc-autonomy",
                    "firecrawl",
                    "provider_budget",
                    day,
                    Jsonb(
                        {
                            **payload,
                            "reserved_usd": str(spent + amount),
                            "last_task": task_id,
                            "reservations": int(payload.get("reservations", 0)) + 1,
                        }
                    ),
                ),
            )

    def reserve_credits(self, task_id, amount, cap):
        """Reserve each attempt conservatively; no refund for unknown outcomes."""
        from datetime import datetime, timezone

        if (
            type(amount) is not int
            or type(cap) is not int
            or amount <= 0
            or not 1 <= cap <= 25
        ):
            raise AcquisitionBlocked("INVALID_DAILY_CREDIT_CAP")
        day = datetime.now(timezone.utc).date().isoformat()

        def update(payload):
            spent = payload.get("reserved_credits", 0)
            if type(spent) is not int or spent < 0 or spent + amount > cap:
                raise AcquisitionBlocked("DAILY_CREDIT_CAP")
            payload.update(
                reserved_credits=spent + amount,
                last_task=task_id,
                credit_reservations=payload.get("credit_reservations", 0) + 1,
            )

        self._update_credit_ledger(day, update)
        return {"day": day, "reserved": amount}

    def observe_credits(self, reservation, used):
        """Record provider-reported usage separately; never turn estimates into usage."""
        if used is not None and (type(used) is not int or used < 0):
            raise AcquisitionBlocked("INVALID_REPORTED_CREDITS")

        def update(payload):
            if used is not None:
                payload["provider_reported_credits"] = (
                    payload.get("provider_reported_credits", 0) + used
                )
                payload["credit_usage_reports"] = (
                    payload.get("credit_usage_reports", 0) + 1
                )
                # Unexpected charges fence later work; never refund a conservative reservation.
                payload["reserved_credits"] += max(0, used - reservation["reserved"])

        self._update_credit_ledger(reservation["day"], update)

    def _update_credit_ledger(self, day, update):
        from psycopg.types.json import Jsonb

        from runtime.research_station_store import TABLE

        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (742931601,))
            key = ("oc-autonomy", "firecrawl", "provider_budget", day)
            cur.execute(
                f"SELECT payload FROM {TABLE} WHERE owner_key=%s AND project_id=%s AND kind=%s AND record_id=%s FOR UPDATE",
                key,
            )
            row = cur.fetchone()
            payload = dict(
                (row["payload"] if isinstance(row, dict) else row[0]) if row else {}
            )
            update(payload)
            cur.execute(
                f"""INSERT INTO {TABLE}(owner_key,project_id,kind,record_id,payload,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,NOW(),NOW()) ON CONFLICT(owner_key,project_id,kind,record_id)
                DO UPDATE SET payload=EXCLUDED.payload,updated_at=NOW()""",
                (*key, Jsonb(payload)),
            )
