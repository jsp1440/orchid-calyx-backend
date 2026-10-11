"""Daily / weekly intelligence digest built from durable ledger state.

Pure rendering over rows read by ``repository.digest_inputs``; it performs no
writes, no fetches and no model inference.  It reports only what the ledger
records: completed integration (delivered/ready routes) is kept apart from
proposed follow-up, and coverage the system does not yet have is stated as a
gap rather than omitted.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from . import DISCOVERY_VERSION

MAX_ITEMS_PER_DOMAIN = 5
_PRIORITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
_DOMAIN_ORDER = (
    "taxonomy",
    "conservation",
    "research",
    "technology",
    "funding",
    "partnerships",
)

# Domains with no native source adapter yet; reported honestly in every digest.
UNCOVERED_DOMAINS = {
    "funding": "No native funding/grant source adapter yet; deadlines cannot be reported.",
    "partnerships": "No native institutional-announcement adapter yet.",
    "conservation_policy": "Conservation news/policy sources beyond scholarly literature are not yet monitored.",
    "datasets": "GBIF/Zenodo dataset discovery is not yet wired into native discovery.",
}


def _primary_link(item: dict[str, Any]) -> str | None:
    dois = item.get("dois") or []
    if dois:
        return f"https://doi.org/{dois[0]}"
    urls = item.get("source_urls") or []
    return urls[0] if urls else None


def _iso(value: Any) -> str | None:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value) if value else None


def _entry(item: dict[str, Any], routes: list[dict[str, Any]]) -> dict[str, Any]:
    metadata = item.get("metadata") or {}
    names = [mention["name"] for mention in metadata.get("name_mentions") or []]
    return {
        "intelligence_item_id": item["id"],
        "title": item["title"],
        "domain": item["domain"],
        "priority": item["priority"],
        "primary_source": _primary_link(item),
        "providers": sorted(item.get("providers") or []),
        "source_published_on": _iso(item.get("source_published_on")),
        "first_discovered_at": _iso(item.get("first_discovered_at")),
        "novelty": sorted(set(item.get("novelty_states") or [])),
        "verification_state": item.get("verification_state") or "UNVERIFIED",
        "claim_verified": False,
        "name_mentions_unreconciled": names,
        "lifecycle": item.get("lifecycle"),
        "integration": {
            "completed": sorted(
                r["destination"] for r in routes if r["route_status"] == "DELIVERED"
            ),
            "ready_for_governed_intake": sorted(
                r["destination"] for r in routes if r["route_status"] == "READY"
            ),
            "blocked": sorted(
                r["destination"] for r in routes if r["route_status"] == "BLOCKED"
            ),
            "proposed": sorted(
                set(item.get("canonical_destinations") or [])
                - {r["destination"] for r in routes}
            ),
        },
        "proposed_follow_up": list(item.get("follow_up_tasks") or []),
    }


def build_digest(
    inputs: dict[str, Any],
    *,
    period: str,
    since: datetime,
    until: datetime,
) -> dict[str, Any]:
    routes_by_item: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for route in inputs.get("routes", []):
        routes_by_item[int(route["intelligence_item_id"])].append(route)

    entries = [
        _entry(item, routes_by_item[int(item["id"])])
        for item in inputs.get("items", [])
    ]
    new_entries = [e for e in entries if "NEW_PUBLICATION" in e["novelty"]]
    historical = [e for e in entries if e["novelty"] == ["HISTORICAL_RECOVERY"]]
    updated = [e for e in entries if "UPDATED" in e["novelty"]]

    by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in sorted(
        new_entries,
        key=lambda e: (
            _PRIORITY_ORDER.get(e["priority"], 9),
            e["source_published_on"] or "",
            e["intelligence_item_id"],
        ),
    ):
        by_domain[entry["domain"]].append(entry)
    important = {
        domain: {
            "shown": by_domain[domain][:MAX_ITEMS_PER_DOMAIN],
            "additional_not_shown": max(
                0, len(by_domain[domain]) - MAX_ITEMS_PER_DOMAIN
            ),
        }
        for domain in _DOMAIN_ORDER
        if by_domain.get(domain)
    }

    verification: dict[str, int] = defaultdict(int)
    for entry in entries:
        verification[entry["verification_state"]] += 1

    taxonomy_candidates = [
        {
            "intelligence_item_id": e["intelligence_item_id"],
            "names": e["name_mentions_unreconciled"],
            "primary_source": e["primary_source"],
        }
        for e in entries
        if e["domain"] == "taxonomy" and e["name_mentions_unreconciled"]
    ]
    opportunities = [
        {
            "intelligence_item_id": e["intelligence_item_id"],
            "title": e["title"],
            "primary_source": e["primary_source"],
            "proposed": [
                t
                for t in e["proposed_follow_up"]
                if t
                in {
                    "EVALUATE_RELATIONSHIP_EVIDENCE",
                    "EVALUATE_FEDERATION",
                    "RECONCILE_TAXONOMY",
                }
            ],
            "authorization": "Proposal only; Calyx investigation requires budgeted task admission.",
        }
        for e in entries
        if e["verification_state"] in {"VERIFIED", "PARTIALLY_VERIFIED"}
        and any(
            t in e["proposed_follow_up"]
            for t in ("EVALUATE_RELATIONSHIP_EVIDENCE", "EVALUATE_FEDERATION")
        )
    ]

    decisions = [
        {
            "intelligence_item_id": e["intelligence_item_id"],
            "title": e["title"],
            "reason": "Registry or primary-source metadata disagree; human adjudication required.",
            "primary_source": e["primary_source"],
        }
        for e in entries
        if e["verification_state"] == "CONTRADICTED"
    ]
    decisions.extend(
        {
            "intelligence_item_id": action["intelligence_item_id"],
            "title": action.get("rationale"),
            "reason": f"{action['action_type']} awaits approval",
        }
        for action in inputs.get("actions", [])
        if action.get("approval_required")
        and action.get("status") in {"OPEN", "WAITING_APPROVAL"}
    )

    runs = inputs.get("runs", [])
    run_summary = [
        {
            "run_key": run["run_key"],
            "attempt": run["attempt"],
            "status": run["status"],
            "zero_work_reason": run.get("zero_work_reason"),
            "failures": [f.get("code") for f in run.get("failure_reasons") or []],
            "counts": run.get("counts") or {},
        }
        for run in runs
    ]
    blocked = [
        {
            "profile": c["profile_key"],
            "provider": c["provider"],
            "consecutive_failures": c["consecutive_failures"],
            "last_error": c.get("last_error"),
        }
        for c in inputs.get("failing_cursors", [])
    ]

    continuing = [
        {
            "intelligence_item_id": e["intelligence_item_id"],
            "title": e["title"],
            "primary_source": e["primary_source"],
        }
        for e in updated
    ]

    return {
        "schema": f"{DISCOVERY_VERSION}.digest",
        "period": period,
        "window": {"since": since.isoformat(), "until": until.isoformat()},
        "headline": {
            "items_touched": len(entries),
            "new_publications": len(new_entries),
            "historical_recoveries": len(historical),
            "updated_records": len(updated),
            "verification_states": dict(sorted(verification.items())),
            "decisions_required": len(decisions),
            "runs": len(runs),
        },
        "important_discoveries": important,
        "verified_sources": [
            e for e in entries if e["verification_state"] == "VERIFIED"
        ][:20],
        "evidence_entered": {
            "ledger_items": len(entries),
            "note": "Items entered the intelligence ledger as candidates; none is canonical scientific evidence until reviewed.",
        },
        "research_opportunities": opportunities[:10],
        "taxonomy_reconciliation_candidates": taxonomy_candidates[:20],
        "decisions_required": decisions[:20],
        "deadlines": {"items": [], "coverage_gap": UNCOVERED_DOMAINS["funding"]},
        "autonomous_work": {"runs": run_summary, "blocked_providers": blocked},
        "continuing_records": continuing[:20],
        "historical_recoveries": historical[:10],
        "coverage_gaps": UNCOVERED_DOMAINS,
        "claim_verified": False,
        "external_contacted": False,
        "canonical_graph_mutated": False,
    }


def digest_window(
    period: str, *, now: datetime | None = None
) -> tuple[datetime, datetime]:
    now = now or datetime.now(UTC)
    if period == "daily":
        return now - timedelta(days=1), now
    if period == "weekly":
        return now - timedelta(days=7), now
    raise ValueError("UNSUPPORTED_DIGEST_PERIOD")


def render_markdown(digest: dict[str, Any]) -> str:
    head = digest["headline"]
    lines = [
        f"# Orchid Continuum intelligence digest ({digest['period']})",
        f"Window: {digest['window']['since']} to {digest['window']['until']}",
        "",
        (
            f"- Items touched: {head['items_touched']} (new publications {head['new_publications']}, "
            f"historical recoveries {head['historical_recoveries']}, updated {head['updated_records']})"
        ),
        f"- Source verification: {', '.join(f'{k} {v}' for k, v in head['verification_states'].items()) or 'none'}",
        f"- Decisions required: {head['decisions_required']}",
        "",
        "## Important discoveries",
    ]
    if not digest["important_discoveries"]:
        lines.append("No new publications in this window.")
    for domain, block in digest["important_discoveries"].items():
        lines.append(f"### {domain.title()}")
        for entry in block["shown"]:
            link = entry["primary_source"] or "no primary link located"
            lines.append(
                f"- [{entry['verification_state']}] {entry['title']} — {link} "
                f"(source date {entry['source_published_on'] or 'unknown'}; via {', '.join(entry['providers'])})"
            )
        if block["additional_not_shown"]:
            lines.append(f"- …and {block['additional_not_shown']} more in the ledger.")
    lines += ["", "## Decisions required"]
    lines += [
        f"- {d['title']}: {d['reason']}" for d in digest["decisions_required"]
    ] or ["None."]
    lines += ["", "## Research opportunities (proposed, not launched)"]
    lines += [
        f"- {o['title']} — {o['primary_source']} ({', '.join(o['proposed'])})"
        for o in digest["research_opportunities"]
    ] or ["None."]
    lines += ["", "## Taxonomy reconciliation candidates (unreconciled)"]
    lines += [
        f"- {', '.join(c['names'])} — {c['primary_source']}"
        for c in digest["taxonomy_reconciliation_candidates"]
    ] or ["None."]
    lines += ["", "## Deadlines", f"- {digest['deadlines']['coverage_gap']}"]
    lines += ["", "## Autonomous work"]
    for run in digest["autonomous_work"]["runs"]:
        detail = run["zero_work_reason"] or ", ".join(run["failures"]) or "ok"
        lines.append(
            f"- {run['run_key']} #{run['attempt']}: {run['status']} ({detail})"
        )
    if not digest["autonomous_work"]["runs"]:
        lines.append("- No discovery run in this window.")
    for blocked in digest["autonomous_work"]["blocked_providers"]:
        lines.append(
            f"- BLOCKED {blocked['profile']}/{blocked['provider']}: {blocked['last_error']}"
        )
    lines += ["", "## Coverage gaps"]
    lines += [f"- {key}: {value}" for key, value in digest["coverage_gaps"].items()]
    lines += [
        "",
        "_Registry metadata locates sources; no scientific claim here is verified until human review._",
    ]
    return "\n".join(lines) + "\n"
