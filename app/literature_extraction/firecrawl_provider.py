"""Bounded Firecrawl v2 acquisition. Responses are untrusted source material.

The caller owns the canonical lease and supplies the existing Swarm governor.
Live calls additionally require a durable reservation callback: an in-memory
budget alone cannot enforce a daily cap across worker restarts. No credentials,
response bodies, or source excerpts are included in errors or receipts.
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

from runtime.swarm.models import ExecutionRequest


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

    def __post_init__(self):
        if not (
            0 <= self.max_searches <= 10
            and 1 <= self.max_documents <= 100
            and 0 <= self.retry_cap <= 3
            and 0 <= self.backoff_seconds <= 10
            and 1 <= self.max_bytes <= 10_000_000
        ):
            raise AcquisitionBlocked("INVALID_BOUNDS")
        if any(
            not n.is_finite() or n < 0 for n in (self.max_call_cost, self.daily_budget)
        ):
            raise AcquisitionBlocked("INVALID_BUDGET")

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
        )


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
        fixture_transport=None,
        env=None,
        sleep=time.sleep,
    ):
        self.config = config
        self.governor = governor
        self.reserve = reserve
        self.fixture_transport = fixture_transport
        self.env = os.environ if env is None else env
        self.sleep = sleep
        self.searches = self.documents = self.calls = 0
        self.lease_check = None
        self._seen: dict[str, AcquiredSource] = {}

    def _gate(self):
        if (
            not self.config.enabled
            or self.env.get("FIRECRAWL_KILL_SWITCH", "false").lower() != "false"
        ):
            raise AcquisitionBlocked("FIRECRAWL_DISABLED")
        if self.config.dry_run:
            if self.fixture_transport is None:
                raise AcquisitionBlocked("DRY_RUN_NO_FIXTURE")
            return
        if self.fixture_transport is not None:
            raise AcquisitionBlocked("LIVE_FIXTURE_FORBIDDEN")
        if (
            self.env.get("PROVIDER_AUTHORIZED", "false").lower() != "true"
            or self.env.get("NO_API_MODE", "true").lower() != "false"
        ):
            raise AcquisitionBlocked("PROVIDER_NOT_AUTHORIZED")
        if not self.env.get("FIRECRAWL_API_KEY"):
            raise AcquisitionBlocked("FIRECRAWL_KEY_UNAVAILABLE")
        if (
            self.governor is None
            or self.reserve is None
            or self.lease_check is None
            or self.config.max_call_cost <= 0
            or self.config.daily_budget <= 0
        ):
            raise AcquisitionBlocked("DURABLE_BUDGET_AUTHORITY_REQUIRED")

    def _request(self, endpoint, payload, task_id):
        for attempt in range(self.config.retry_cap + 1):
            self._gate()
            if self.lease_check is not None:
                self.lease_check()
            entry = None
            if not self.config.dry_run:
                entry = self.governor.begin(
                    ExecutionRequest(
                        issue_task_id=task_id,
                        provider="firecrawl",
                        worker_lane="literature",
                        retry_count=attempt,
                        estimated_cost_usd=self.config.max_call_cost,
                    )
                )
                try:
                    self.reserve(
                        task_id, self.config.max_call_cost, self.config.daily_budget
                    )
                except Exception:  # noqa: BLE001 - reservation failure must release slot without exposing DB details
                    self.governor.end(
                        entry, succeeded=False, termination_reason="reservation_failed"
                    )
                    raise AcquisitionBlocked("DURABLE_RESERVATION_FAILED") from None
            succeeded = False
            try:
                self.calls += 1
                if self.config.dry_run:
                    status, result = self.fixture_transport(endpoint, payload)
                else:
                    with (
                        httpx.Client(timeout=45, follow_redirects=False) as client,
                        client.stream(
                            "POST",
                            "https://api.firecrawl.dev/v2/" + endpoint,
                            headers={
                                "Authorization": "Bearer "
                                + self.env["FIRECRAWL_API_KEY"]
                            },
                            json=payload,
                        ) as response,
                    ):
                        raw = bytearray()
                        for chunk in response.iter_bytes():
                            raw.extend(chunk)
                            if len(raw) > self.config.max_bytes:
                                raise AcquisitionBlocked("RESPONSE_TOO_LARGE")
                        import json

                        status = response.status_code
                        # A transient HTTP response need not contain valid JSON.
                        result = {} if status != 200 else json.loads(raw)
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

    def search(self, genus: str, *, task_id: str) -> list[str]:
        import re

        if not re.fullmatch(r"[A-Z][a-z]{2,40}", genus):
            raise AcquisitionBlocked("GENUS_REQUIRED")
        if self.searches >= self.config.max_searches or not self.config.domains:
            raise AcquisitionBlocked("SEARCH_LIMIT_OR_DOMAINS_MISSING")
        self.searches += 1
        sites = " OR ".join("site:" + d for d in self.config.domains)
        data = self._request(
            "search",
            {
                "query": f"{genus} (monograph OR revision OR flora OR key) ({sites})",
                "limit": min(self.config.max_documents, 2)
                if self.config.pilot_mode
                else self.config.max_documents,
            },
            task_id,
        )
        urls = []
        for item in data.get("web", []):
            try:
                url = canonical_url(item["url"], self.config.domains)
            except (AcquisitionBlocked, KeyError, ValueError):
                continue
            if url not in urls:
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
                            "reserved_usd": str(spent + amount),
                            "last_task": task_id,
                            "reservations": int(payload.get("reservations", 0)) + 1,
                        }
                    ),
                ),
            )
