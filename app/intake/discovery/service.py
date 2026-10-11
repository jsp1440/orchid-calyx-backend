"""One bounded, resumable, idempotent native-discovery cycle.

DISCOVER -> ACQUIRE -> DEDUPLICATE -> VERIFY (source identity) -> CLASSIFY ->
RECORD into the existing intelligence ledger.  RECONCILE/ROUTE/FOLLOW-UP are
then advanced by the existing compare/route jobs in ``intelligence_autonomy``;
this module does not duplicate them.

Safety properties:
* cursors advance only past windows whose records were all durably recorded;
* a cycle that does nothing records why (``NO_WORK`` + ``zero_work_reason``);
* budget exhaustion stops the cycle as ``PARTIAL`` and the next cycle resumes
  from the last safe cursor; nothing unfinished is marked complete;
* registry metadata never sets ``claim_verified``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from hashlib import sha256
from typing import Any

from . import DISCOVERY_VERSION
from . import repository as repo
from .profiles import (
    MAX_HISTORICAL_DAYS,
    DiscoveryBudget,
    DiscoveryProfile,
    load_profiles,
)
from .providers import PROVIDERS, HttpGet, default_http_get
from .records import (
    DiscoveredWork,
    assess_verification,
    is_orchid_relevant,
    merge_works,
    normalize_title,
    novelty,
    to_intelligence_item,
    utc_now,
)


@dataclass
class _Window:
    since: date
    until: date

    @property
    def days(self) -> int:
        return (self.until - self.since).days

    def halves(self) -> tuple[_Window, _Window]:
        middle = self.since + timedelta(days=max(1, self.days // 2))
        return _Window(self.since, middle - timedelta(days=1)), _Window(
            middle, self.until
        )


@dataclass
class _CycleState:
    budget: DiscoveryBudget
    requests: int = 0
    records_seen: int = 0
    filtered_irrelevant: int = 0
    verifications: int = 0
    budget_exhausted: list[str] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    provider_results: list[dict[str, Any]] = field(default_factory=list)
    last_request_at: float | None = None


def _plan_windows(
    profile: DiscoveryProfile,
    provider: str,
    *,
    today: date,
    historical: tuple[date, date] | None,
) -> list[_Window]:
    if historical is not None:
        since, until = historical
        return [_Window(since, until)]
    cursor = repo.get_cursor(profile.key, provider)
    if cursor and cursor.get("watermark"):
        # One-day overlap absorbs late registry indexing; deduplication makes it free.
        since = cursor["watermark"] - timedelta(days=1)
    else:
        since = today - timedelta(days=profile.lookback_days)
    # A long outage is recovered over successive cycles, one bounded window each.
    until = min(today, since + timedelta(days=profile.max_window_days))
    return [_Window(since, until)]


def _fetch_window(
    profile: DiscoveryProfile,
    provider_name: str,
    window: _Window,
    *,
    state: _CycleState,
    http_get: HttpGet,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> tuple[list[DiscoveredWork], date | None, str]:
    """Fetch one profile/provider window, bisecting full pages.

    Returns (works, safe_watermark, outcome).  ``safe_watermark`` is the end of
    the last contiguous window fully retrieved, or None if none was.
    """
    provider = PROVIDERS[provider_name]
    pending = [window]
    works: list[DiscoveredWork] = []
    safe_until: date | None = None
    outcome = "COMPLETED"
    while pending:
        current = pending.pop(0)
        if state.requests >= state.budget.max_requests:
            state.budget_exhausted.append(f"max_requests:{profile.key}:{provider_name}")
            return works, safe_until, "BUDGET_EXHAUSTED"
        if state.last_request_at is not None and state.budget.min_interval_seconds:
            wait = state.budget.min_interval_seconds - (
                monotonic() - state.last_request_at
            )
            if wait > 0:
                sleep(wait)
        request = provider.build_request(
            profile.query_for(provider_name),
            current.since,
            current.until,
            profile.rows_per_request,
        )
        state.requests += 1
        state.last_request_at = monotonic()
        try:
            response = http_get(request.url, timeout=20)
            status = int(response.status_code)
            if status != 200:
                code = "RATE_LIMITED" if status == 429 else f"HTTP_{status}"
                raise RuntimeError(code)
            page = provider.parse(response.json())
        # Provider failure is recorded, never fatal to the cycle.
        except Exception as exc:  # noqa: BLE001
            state.failures.append(
                {
                    "code": "PROVIDER_REQUEST_FAILED",
                    "profile": profile.key,
                    "provider": provider_name,
                    "window": [current.since.isoformat(), current.until.isoformat()],
                    "detail": str(exc)[:500],
                }
            )
            return works, safe_until, "FAILED"
        if len(page) >= profile.rows_per_request and current.days >= 1:
            # Full page: narrow instead of paginating without bound.
            pending[:0] = list(current.halves())
            continue
        if len(page) >= profile.rows_per_request:
            outcome = "TRUNCATED"
            state.failures.append(
                {
                    "code": "DAY_WINDOW_TRUNCATED",
                    "profile": profile.key,
                    "provider": provider_name,
                    "window": [current.since.isoformat(), current.until.isoformat()],
                    "detail": f"More than {profile.rows_per_request} records in one day; remainder not retrieved.",
                }
            )
        state.records_seen += len(page)
        works.extend(page)
        safe_until = current.until
    return works, safe_until, outcome


def _group_key(work: DiscoveredWork) -> str:
    return f"doi:{work.doi}" if work.doi else f"title:{normalize_title(work.title)}"


def _stored_view(row: dict[str, Any]) -> DiscoveredWork:
    return DiscoveredWork(
        provider=row["provider"],
        provider_record_id=row["provider_record_id"],
        title=row["title"],
        doi=row.get("doi"),
        published_on=row.get("source_published_on"),
        published_precision=row.get("source_date_precision") or "UNKNOWN",
    )


def _primary_source(
    item_id: int,
    doi: str,
    *,
    fetch_source: Callable[[str], Any],
) -> dict[str, Any]:
    """Resolve the DOI read-only through the existing primary-source verifier."""
    from ..intelligence_verification import record_source_snapshot

    url = f"https://doi.org/{doi}"
    try:
        snapshot = fetch_source(url)
    # An unreachable or refused host is UNRESOLVED, not fatal.
    except Exception as exc:  # noqa: BLE001
        return {"outcome": "UNREACHABLE", "source_url": url, "error": str(exc)[:300]}
    record_source_snapshot(item_id, snapshot)
    return {
        "outcome": snapshot.outcome,
        "source_url": snapshot.source_url,
        "resolved_url": snapshot.resolved_url,
        "source_title": snapshot.source_title,
        "evidence_sha256": snapshot.evidence_sha256,
    }


def _run_source(run_id: int, run_key: str) -> int:
    from ..repository import create_source
    from ..schemas import ExtractionResult

    content = json.dumps(
        {"discovery_version": DISCOVERY_VERSION, "run_id": run_id, "run_key": run_key},
        sort_keys=True,
    )
    source = create_source(
        source_type="api",
        title=f"Native intelligence discovery run {run_key}",
        content=content,
        content_hash=sha256(content.encode()).hexdigest(),
        source_url=None,
        imported_by=DISCOVERY_VERSION,
        extraction=ExtractionResult(
            entities=[], relationships=[], tasks=[], parser_version=DISCOVERY_VERSION
        ),
    )
    return int(source["id"])


def run_discovery_cycle(
    *,
    mode: str = "SCHEDULED",
    run_key: str | None = None,
    profiles: tuple[DiscoveryProfile, ...] | None = None,
    profile_keys: list[str] | None = None,
    budget: DiscoveryBudget | None = None,
    historical_window: tuple[date, date] | None = None,
    verify_sources: bool = True,
    http_get: HttpGet | None = None,
    fetch_source: Callable[[str], Any] | None = None,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if mode not in {"SCHEDULED", "MANUAL", "HISTORICAL"}:
        raise ValueError("UNSUPPORTED_DISCOVERY_MODE")
    if (mode == "HISTORICAL") != (historical_window is not None):
        raise ValueError("HISTORICAL_MODE_REQUIRES_WINDOW")
    if historical_window is not None:
        since, until = historical_window
        if since > until or (until - since).days > MAX_HISTORICAL_DAYS:
            raise ValueError("HISTORICAL_WINDOW_OUT_OF_BOUNDS")

    now = now or utc_now()
    budget = budget or DiscoveryBudget()
    selected = [profile for profile in (profiles or load_profiles()) if profile.enabled]
    if profile_keys:
        selected = [profile for profile in selected if profile.key in set(profile_keys)]
    if run_key is None:
        if mode == "SCHEDULED":
            run_key = f"scheduled:{now.date().isoformat()}"
        elif mode == "HISTORICAL":
            run_key = f"historical:{historical_window[0]}:{historical_window[1]}:{','.join(p.key for p in selected)}"
        else:
            run_key = f"manual:{now.isoformat()}"

    claim = repo.start_run(
        run_key=run_key,
        mode=mode,
        profiles=[profile.key for profile in selected],
        budget=budget.model_dump(),
    )
    if not claim["claimed"]:
        return {
            "status": "SKIPPED",
            "reason": claim["reason"],
            "run_id": claim["run"]["id"],
            "run_status": claim["run"]["status"],
            "external_contacted": False,
            "canonical_graph_mutated": False,
        }
    run_id = int(claim["run"]["id"])
    state = _CycleState(budget=budget)
    counts = {
        "new_items": 0,
        "updated_items": 0,
        "already_tracked": 0,
        "recorded_groups": 0,
        "verification_states": {},
    }
    try:
        if not selected:
            return _finish(
                run_id, state, counts, zero_reason="NO_ENABLED_DISCOVERY_PROFILES"
            )
        if budget.max_requests == 0:
            return _finish(run_id, state, counts, zero_reason="DISCOVERY_BUDGET_ZERO")

        http_get = http_get or default_http_get
        if fetch_source is None:
            from ..primary_source import fetch_source as default_fetch_source

            fetch_source = default_fetch_source

        groups: dict[str, list[tuple[DiscoveryProfile, DiscoveredWork]]] = {}
        safe_cursors: list[tuple[str, str, date]] = []
        for profile in selected:
            for provider_name in profile.providers:
                provider_works: list[DiscoveredWork] = []
                outcome = "COMPLETED"
                safe_until: date | None = None
                for window in _plan_windows(
                    profile,
                    provider_name,
                    today=now.date(),
                    historical=historical_window,
                ):
                    works, safe_until, outcome = _fetch_window(
                        profile,
                        provider_name,
                        window,
                        state=state,
                        http_get=http_get,
                        sleep=sleep,
                        monotonic=monotonic,
                    )
                    provider_works.extend(works)
                relevant = [work for work in provider_works if is_orchid_relevant(work)]
                state.filtered_irrelevant += len(provider_works) - len(relevant)
                for work in relevant:
                    groups.setdefault(_group_key(work), []).append((profile, work))
                if outcome == "FAILED":
                    repo.record_cursor_failure(
                        profile.key,
                        provider_name,
                        error=state.failures[-1]["detail"],
                        run_id=run_id,
                    )
                if safe_until is not None and historical_window is None:
                    safe_cursors.append((profile.key, provider_name, safe_until))
                state.provider_results.append(
                    {
                        "profile": profile.key,
                        "provider": provider_name,
                        "outcome": outcome,
                        "records": len(provider_works),
                        "relevant": len(relevant),
                        "safe_watermark": safe_until.isoformat()
                        if safe_until
                        else None,
                    }
                )

        source_id: int | None = None
        group_failures = 0
        for key in sorted(groups):
            if counts["recorded_groups"] >= budget.max_records:
                state.budget_exhausted.append("max_records")
                break
            entries = groups[key]
            # The same provider record can arrive through two profiles in one cycle.
            unique: dict[tuple[str, str], tuple[DiscoveryProfile, DiscoveredWork]] = {}
            for profile, work in entries:
                unique.setdefault(
                    (work.provider, work.provider_record_id), (profile, work)
                )
            views = [work for _, work in unique.values()]
            profile_key = min(profile.key for profile, _ in unique.values())
            new_window = min(profile.new_window_days for profile, _ in unique.values())
            try:
                novelty_by_view = {
                    (view.provider, view.provider_record_id): novelty(
                        view,
                        discovered_at=now,
                        new_window_days=new_window,
                        previous_metadata_sha256=repo.previous_metadata_sha256(
                            view.provider, view.provider_record_id
                        ),
                    )
                    for view in views
                }
                if all(
                    value == "ALREADY_TRACKED" for value in novelty_by_view.values()
                ):
                    counts["already_tracked"] += 1
                    continue
                merged = merge_works(views)
                identity = repo.find_identity(merged.doi, merged.title)
                states = set(novelty_by_view.values()) - {"ALREADY_TRACKED"}
                group_novelty = "UPDATED" if "UPDATED" in states else min(states)
                stored = [
                    _stored_view(row)
                    for row in (
                        repo.provider_views(identity["intelligence_item_id"])
                        if identity
                        else []
                    )
                    if (row["provider"], row["provider_record_id"])
                    not in novelty_by_view
                ]
                verification_state, basis = assess_verification(views + stored)
                item = to_intelligence_item(
                    merged,
                    provider_views=views,
                    novelty_state=group_novelty,
                    verification_state=verification_state,
                    verification_basis=basis,
                    discovered_at=now,
                    profile_key=profile_key,
                    existing_identity=identity,
                )
                if source_id is None:
                    source_id = _run_source(run_id, run_key)
                from ..intelligence_repository import record_intelligence_items

                recorded = record_intelligence_items(source_id=source_id, items=[item])[
                    0
                ]
                item_id = int(recorded["id"])
                for view in views:
                    repo.upsert_discovery_record(
                        intelligence_item_id=item_id,
                        work=view,
                        profile_key=profile_key,
                        novelty=novelty_by_view[
                            (view.provider, view.provider_record_id)
                        ],
                        run_id=run_id,
                        metadata={
                            "url": view.url,
                            "authors": list(view.authors),
                            "venue": view.venue,
                            "work_type": view.work_type,
                            "abstract_as_reported": view.abstract[:2000],
                            "keywords": list(view.keywords),
                            "name_mentions": item["native_discovery"]["name_mentions"],
                            "related_identifiers": list(view.related_identifiers),
                            "claim_verified": False,
                        },
                    )

                previous = repo.get_verification_state(item_id)
                primary = (previous or {}).get("basis", {}).get("primary_source")
                attempted = False
                if (
                    verify_sources
                    and merged.doi
                    and not (previous and previous.get("primary_source_attempted_at"))
                    and state.verifications < budget.max_verifications
                    and verification_state != "CONTRADICTED"
                ):
                    state.verifications += 1
                    attempted = True
                    primary = _primary_source(
                        item_id, merged.doi, fetch_source=fetch_source
                    )
                if primary is not None:
                    verification_state, basis = assess_verification(
                        views + stored, primary_source=primary
                    )
                repo.set_verification_state(
                    item_id,
                    state=verification_state,
                    basis=basis,
                    primary_source_attempted=attempted,
                )
                counts["recorded_groups"] += 1
                counts["verification_states"][verification_state] = (
                    counts["verification_states"].get(verification_state, 0) + 1
                )
                if identity is None:
                    counts["new_items"] += 1
                else:
                    counts["updated_items"] += 1
            # One group's failure holds cursors but must not abort the others.
            except Exception as exc:  # noqa: BLE001
                group_failures += 1
                state.failures.append(
                    {"code": "RECORDING_FAILED", "group": key, "detail": str(exc)[:500]}
                )

        if group_failures == 0 and "max_records" not in state.budget_exhausted:
            for profile_key, provider_name, watermark in safe_cursors:
                repo.advance_cursor(
                    profile_key, provider_name, watermark=watermark, run_id=run_id
                )
        elif safe_cursors:
            state.failures.append(
                {
                    "code": "CURSORS_HELD",
                    "detail": "Some records were not durably recorded; cursors stay put and the window is re-read next cycle.",
                }
            )
        return _finish(run_id, state, counts, zero_reason=None)
    except Exception as exc:
        state.failures.append({"code": "CYCLE_FAILED", "detail": str(exc)[:500]})
        _finish(run_id, state, counts, zero_reason=None, force_status="FAILED")
        raise


def _finish(
    run_id: int,
    state: _CycleState,
    counts: dict[str, Any],
    *,
    zero_reason: str | None,
    force_status: str | None = None,
) -> dict[str, Any]:
    counts = {
        **counts,
        "records_seen": state.records_seen,
        "filtered_irrelevant": state.filtered_irrelevant,
    }
    usage = {
        "provider_requests": state.requests,
        "primary_source_fetches": state.verifications,
        "paid_provider_calls": 0,
        "model_inference_calls": 0,
        "budget_exhausted": state.budget_exhausted,
    }
    did_work = counts["recorded_groups"] > 0
    if force_status:
        status = force_status
    elif zero_reason is not None:
        status = "NO_WORK"
    elif state.failures and not did_work and not counts["already_tracked"]:
        status = "FAILED"
        zero_reason = "NO_WORK_ALL_ATTEMPTS_FAILED:" + ",".join(
            sorted({str(failure.get("code")) for failure in state.failures})
        )
    elif state.failures or state.budget_exhausted:
        status = "PARTIAL"
    elif not did_work:
        status = "NO_WORK"
        if state.records_seen == 0:
            zero_reason = "PROVIDERS_RETURNED_NO_RECORDS_IN_WINDOW"
        elif counts["already_tracked"]:
            zero_reason = (
                f"ALL_RELEVANT_RECORDS_ALREADY_TRACKED:{counts['already_tracked']};"
                f"FILTERED_IRRELEVANT:{state.filtered_irrelevant}"
            )
        else:
            zero_reason = f"ALL_RECORDS_FILTERED_IRRELEVANT:{state.filtered_irrelevant}"
    else:
        status = "COMPLETED"
    run = repo.finish_run(
        run_id,
        status=status,
        usage=usage,
        counts=counts,
        provider_results=state.provider_results,
        zero_work_reason=zero_reason,
        failure_reasons=state.failures,
    )
    return {
        "status": status,
        "run_id": run_id,
        "run_key": run["run_key"],
        "attempt": run["attempt"],
        "counts": counts,
        "usage": usage,
        "provider_results": state.provider_results,
        "zero_work_reason": zero_reason,
        "failure_reasons": state.failures,
        "claim_verified": False,
        "external_contacted": False,
        "canonical_graph_mutated": False,
    }
