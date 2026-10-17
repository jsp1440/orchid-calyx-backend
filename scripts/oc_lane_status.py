#!/usr/bin/env python3
"""Publish one durable lane-status record per controller wave.

The planner already classifies every wave (``homeostasis``: status, reason and
evidence), but that reason reached only the run's step summary: 32 consecutive
zero-launch waves left no durable reason anywhere a person or Mission Control
could read. This writes it to the lane-status feed issue (#1949):

* one bot comment tagged ``OC-LANE-STATUS-CURRENT-V1`` is updated in place with
  the latest wave, so the current state is always one read away;
* a comment tagged ``OC-LANE-STATUS-TRANSITION-V1`` is appended only when the
  lane state or reason changes, so history is durable without a comment per
  wave.

Lane states are ``working``, ``idle``, ``blocked``, ``failed`` and
``recovering``. The same record also carries a per-module-lane map
(``module_lanes``, from the plan's ``oc.module-lanes.v1`` report); see
``MODULE_STATE_MAP`` for the explicit mapping. Only the workflow bot's own comments are read back. Nothing here
calls a provider or writes a repository file, and publishing is best effort: a
failure is reported in the output, never raised into the wave.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "oc.lane-status.v1"
STATUS_ISSUE = 1949
CURRENT_TAG = "OC-LANE-STATUS-CURRENT-V1"
TRANSITION_TAG = "OC-LANE-STATUS-TRANSITION-V1"
BOT_LOGIN = "github-actions[bot]"
LANE_STATES = ("working", "idle", "blocked", "failed", "recovering")

#: Module-lane states carry one extra, fail-closed value: ``unknown``.
MODULE_LANE_STATES = LANE_STATES + ("unknown",)
MODULE_LANES_SCHEMA = "oc.module-lanes.v1"
NO_REASON = "no_reason_recorded"

#: oc.module-lanes.v1 state -> Mission Control lane state. Only states the engine
#: reports appear here. ``failed`` and ``recovering`` are deliberately absent: a
#: module lane is failed/recovering only on lease evidence for its own issues
#: (see ``module_lane_states``), never from its module state alone.
MODULE_STATE_MAP = {
    "executing": "working",
    "validating": "working",  # a PR is in validation: work is in flight
    "replenishable": "idle",  # an ungated queued mission exists, nothing running
    "empty": "idle",  # nothing unfinished; discovery should replenish
    "gated": "blocked",
    "capability_gap": "blocked",
}

#: Planner homeostasis reason -> lane state (oc_swarm_controller.HOMEOSTASIS_STATUS).
_REASON_STATE = {
    "executing": "working",
    "capacity_full": "working",
    "queue_empty": "idle",
    "gated_only": "blocked",
    "dependency_blocked": "blocked",
    "lane_refused": "blocked",
    "lock_contended": "blocked",
    "held_other": "blocked",
    "invariant_violation": "failed",
}


def _int(value: Any) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def _held_count(homeostasis: dict) -> int:
    held = (homeostasis.get("evidence") or {}).get("unfinished_held")
    if not isinstance(held, dict):
        return 0
    return sum(_int(value) for value in held.values())


def lane_state(
    homeostasis: dict | None,
    *,
    launched: int,
    recovered: int,
    reconcile_errors: int,
    provider_blocked: bool,
) -> tuple[str, str]:
    """(lane state, reason) for one wave. Missing planner output is a failure."""
    if not isinstance(homeostasis, dict) or not homeostasis.get("reason"):
        return "failed", "plan_output_missing"
    reason = str(homeostasis["reason"])
    if recovered > 0:
        return "recovering", f"lease_recovered:{reason}"
    if reconcile_errors > 0:
        return "failed", f"lease_reconcile_errors:{reason}"
    if launched > 0:
        return "working", reason
    if provider_blocked and reason in {"executing", "capacity_full"}:
        # Planned paid work that the governor or NO-API mode refused to launch.
        return "blocked", f"provider_blocked:{reason}"
    if reason == "executing":
        # The plan selected work but nothing launched (claim failed or confirmed
        # no claims): never report that as working.
        return "blocked", "selected_not_launched"
    if reason == "queue_empty" and _held_count(homeostasis) > 0:
        # Nothing is queued, but unfinished work exists and every issue of it is
        # held (repair pending, validating, backoff, gates): that is not idle.
        return "blocked", "queue_empty_unfinished_held"
    return _REASON_STATE.get(reason, "blocked"), reason


def _issue_numbers(rows: Any, key: str) -> set[int]:
    if not isinstance(rows, list):
        return set()
    return {_int(r.get(key)) for r in rows if isinstance(r, dict) and _int(r.get(key))}


def _lease_evidence(recovery: dict) -> tuple[set[int], set[int]]:
    """(issues with a lease recovery, issues with a reconcile error), by number."""
    recovered: set[int] = set()
    for field in ("recovered", "stranded_recovered", "parked_lease_recovered"):
        recovered |= _issue_numbers(recovery.get(field), "issue_number")
    return recovered, _issue_numbers(recovery.get("errors"), "issue")


CLAIMS_SCHEMA = "oc.swarm-claim-handoff.v1"
CLAIMS_FILE = "swarm-claims.json"


def claim_evidence(doc: Any) -> dict:
    """Parse the claim step's handoff (``oc.swarm-claim-handoff.v1``).

    The plan is written before leases are claimed, so a selected lane still looks
    ``replenishable`` there. The claim result is what proves a launch. ``None`` is
    ``unavailable`` (no file); anything unparseable is ``malformed``, never "nothing
    launched".
    """
    if doc is None:
        return {"status": "unavailable", "reason": "claims_missing"}
    bad = {"status": "malformed", "reason": "claims_malformed"}
    if (
        not isinstance(doc, dict)
        or doc.get("schema") != CLAIMS_SCHEMA
        or not isinstance(doc.get("confirmed"), list)
        or not isinstance(doc.get("errors"), list)
    ):
        return bad
    confirmed: dict[int, str] = {}
    for row in doc["confirmed"]:
        if not isinstance(row, dict) or not isinstance(row.get("issue_number"), int):
            return bad
        kind = (
            "provider_free"
            if row.get("lane_executable") is True
            else "acquisition"
            if row.get("acquisition") is True
            else "provider"
        )
        confirmed[row["issue_number"]] = kind
    errors: set[int] = set()
    for row in doc["errors"]:
        if not isinstance(row, dict) or not isinstance(row.get("issue"), int):
            return bad
        errors.add(row["issue"])
    return {"status": "ok", "reason": None, "confirmed": confirmed, "errors": errors}


def default_claims_path() -> str | None:
    base = os.environ.get("RUNNER_TEMP")
    path = Path(base) / CLAIMS_FILE if base else None
    return str(path) if path is not None and path.is_file() else None


def load_claim_evidence(path: str | None) -> dict:
    if not path or not Path(path).is_file():
        return claim_evidence(None)
    try:
        return claim_evidence(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {"status": "malformed", "reason": "claims_malformed"}


def _lane_issues(entry: dict) -> set[int]:
    issues: set[int] = set()
    for field in ("running", "replenishable", "validating", "capability_gap", "planned"):
        if field == "planned" and field not in entry:
            continue
        issues |= {_int(n) for n in entry[field]}
    for numbers in entry["gates"].values():
        issues |= {_int(n) for n in numbers}
    return issues


def _numbers(value: Any) -> bool:
    """A list of real issue numbers (bool is not a number here)."""
    return isinstance(value, list) and all(
        isinstance(n, int) and not isinstance(n, bool) for n in value
    )


def _lane_valid(entry: Any) -> bool:
    """Every element type the derivation relies on, so bad data fails closed."""
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("state"), str)
        and all(
            _numbers(entry.get(f))
            for f in ("running", "replenishable", "validating", "capability_gap")
        )
        and _numbers(entry.get("planned", []))
        and isinstance(entry.get("gates"), dict)
        and all(
            isinstance(k, str) and k.strip() and _numbers(v)
            for k, v in entry["gates"].items()
        )
        and isinstance(entry.get("refusal_reasons", []), list)
        and all(
            isinstance(r, dict)
            and isinstance(r.get("reason"), str)
            and _numbers([r.get("issue")])
            for r in entry.get("refusal_reasons", [])
        )
    )


def _module_reason(module_state: str, entry: dict) -> str:
    """The engine's own reason fields; ``no_reason_recorded`` if a blocked lane has none."""
    if module_state in {"gated", "capability_gap"}:
        tokens = {gate for gate, nums in entry["gates"].items() if nums}
        for row in entry.get("refusal_reasons") or []:
            if isinstance(row, dict) and str(row.get("reason") or "").strip():
                tokens.add(str(row["reason"]).strip())
        return ",".join(sorted(tokens)) if tokens else NO_REASON
    return f"module_state:{module_state}"


def _derive_lane(entry: Any, claims: dict, recovered: set[int], errored: set[int]) -> dict:
    if not _lane_valid(entry):
        return {"lane_state": "unknown", "reason": "malformed_lane_entry", "module_state": None}
    module_state = entry["state"]
    if module_state not in MODULE_STATE_MAP:
        return {"lane_state": "unknown", "reason": "unknown_module_state", "module_state": None}
    state, reason = MODULE_STATE_MAP[module_state], _module_reason(module_state, entry)
    issues = _lane_issues(entry)
    planned = {_int(n) for n in entry.get("planned") or []}
    if claims.get("status") == "malformed" and planned:
        return {"lane_state": "unknown", "reason": "claims_malformed", "module_state": module_state}
    if claims.get("status") == "ok":
        kinds = sorted({claims["confirmed"][n] for n in issues if n in claims["confirmed"]})
        if kinds:
            state, reason = "working", "claim_confirmed:" + ",".join(kinds)
        elif planned and state == "idle":
            reason = "planned_unconfirmed"
        if issues & claims["errors"]:
            reason = f"claim_error:{reason}"
    if issues & errored:
        state, reason = "failed", f"lease_reconcile_errors:{reason}"
    elif issues & recovered:
        state, reason = "recovering", f"lease_recovered:{reason}"
    return {"lane_state": state, "reason": reason, "module_state": module_state}


def module_lane_states(
    module_lanes: Any, recovery: dict | None = None, claims: dict | None = None
) -> dict:
    """Per-module-lane Mission Control states from an ``oc.module-lanes.v1`` report.

    * ``MODULE_STATE_MAP`` gives the base state; every lane has a non-blank reason.
    * ``failed``/``recovering`` come only from lease evidence naming one of the
      lane's own issues (reconcile error -> failed, recovery -> recovering).
    * Missing, malformed or unrecognised lane data is ``unknown``, never ``idle``;
      a missing/malformed whole block is reported with an explicit status.
    * Claim evidence (``claims``): a confirmed claim on a lane's issue makes the lane
      ``working`` (``claim_confirmed:<kind>``); a planned issue with no confirmed
      claim stays idle as ``planned_unconfirmed``; a claim error naming the lane is
      prefixed ``claim_error:``. Malformed claims make planned lanes ``unknown``.
    """
    claims = claims if isinstance(claims, dict) else claim_evidence(None)
    claim_section = {"status": claims.get("status"), "reason": claims.get("reason")}
    if module_lanes is None:
        return {"status": "unavailable", "reason": "module_lanes_missing", "lanes": {}, "counts": {}, "claims": claim_section}
    block = module_lanes
    if (
        not isinstance(block, dict)
        or block.get("schema") != MODULE_LANES_SCHEMA
        or not isinstance(block.get("lanes"), dict)
    ):
        return {"status": "malformed", "reason": "module_lanes_malformed", "lanes": {}, "counts": {}, "claims": claim_section}
    recovered, errored = _lease_evidence(recovery if isinstance(recovery, dict) else {})
    out: dict[str, dict] = {}
    for key, entry in sorted(block["lanes"].items(), key=lambda kv: str(kv[0])):
        if key == "unassigned":
            continue
        try:
            out[str(key)] = _derive_lane(entry, claims, recovered, errored)
        except Exception:  # noqa: BLE001 - one lane's bad data must not take down the rest
            out[str(key)] = {
                "lane_state": "unknown",
                "reason": "lane_derivation_error",
                "module_state": None,
            }
    counts: dict[str, int] = {}
    for item in out.values():
        counts[item["lane_state"]] = counts.get(item["lane_state"], 0) + 1
    return {
        "status": "ok",
        "reason": None,
        "lanes": out,
        "counts": dict(sorted(counts.items())),
        "claims": claim_section,
    }


def _safe_module_lanes(module_lanes: Any, recovery: Any, claims: Any) -> dict:
    """The module-lane section can never stop the global record from being built."""
    try:
        return module_lane_states(module_lanes, recovery, claims)
    except Exception:  # noqa: BLE001 - telemetry is best effort; the global record is not
        return {
            "status": "error",
            "reason": "module_lane_states_error",
            "lanes": {},
            "counts": {},
            "claims": {"status": None, "reason": None},
        }


def build_record(
    plan: dict | None,
    recovery: dict | None,
    *,
    run_id: str,
    run_url: str,
    event: str,
    provider_launch_count: Any,
    provider_free_launch_count: Any,
    provider_blocked: bool,
    now: datetime | None = None,
    claims: dict | None = None,
) -> dict:
    plan = plan if isinstance(plan, dict) else {}
    recovery = recovery if isinstance(recovery, dict) else {}
    homeostasis = plan.get("homeostasis")
    paid = _int(provider_launch_count)
    free = _int(provider_free_launch_count)
    recovered = _int(recovery.get("recovered_count")) + _int(
        recovery.get("stranded_recovered_count")
    )
    errors = recovery.get("errors")
    reconcile_errors = len(errors) if isinstance(errors, list) else 0
    state, reason = lane_state(
        homeostasis,
        launched=paid + free,
        recovered=recovered,
        reconcile_errors=reconcile_errors,
        provider_blocked=provider_blocked,
    )
    evidence = (
        (homeostasis or {}).get("evidence") if isinstance(homeostasis, dict) else None
    )
    return {
        "schema": SCHEMA,
        "lane_state": state,
        "reason": reason,
        "homeostasis_status": (homeostasis or {}).get("status")
        if isinstance(homeostasis, dict)
        else None,
        "homeostasis_reason": (homeostasis or {}).get("reason")
        if isinstance(homeostasis, dict)
        else None,
        "launched": {"provider": paid, "provider_free": free},
        "provider_blocked": bool(provider_blocked),
        "leases_recovered": recovered,
        "lease_reconcile_errors": reconcile_errors,
        "selected": sorted(_int(n) for n in plan.get("selected_numbers") or []),
        "module_lanes": _safe_module_lanes(plan.get("module_lanes"), recovery, claims),
        "evidence": evidence if isinstance(evidence, dict) else {},
        "run_id": str(run_id),
        "run_url": run_url,
        "event": event,
        "generated_at": (now or datetime.now(timezone.utc))
        .isoformat()
        .replace("+00:00", "Z"),
    }


def render(tag: str, record: dict) -> str:
    head = (
        f"Lane **{record['lane_state']}**, reason `{record['reason']}`, "
        f"controller run {record['run_url']}"
    )
    return f"<!-- {tag}\n{json.dumps(record, sort_keys=True)}\n-->\n{head}"


def parse(body: str, tag: str) -> dict | None:
    match = re.match(
        r"<!-- " + re.escape(tag) + r"\n(?P<json>\{.*?\})\n-->", body or "", re.DOTALL
    )
    if not match:
        return None
    try:
        record = json.loads(match.group("json"))
    except ValueError:
        return None
    return (
        record if isinstance(record, dict) and record.get("schema") == SCHEMA else None
    )


def plan_writes(comments: list[dict], record: dict) -> dict:
    """Which writes publish ``record``: patch or create CURRENT, maybe a TRANSITION."""
    current = None
    for comment in comments:
        if (comment.get("user") or {}).get("login") != BOT_LOGIN:
            continue
        if parse(comment.get("body") or "", CURRENT_TAG) is None:
            continue
        if current is None or int(comment["id"]) > int(current["id"]):
            current = comment
    previous = parse(current["body"], CURRENT_TAG) if current else None
    changed = previous is None or (
        previous.get("lane_state"),
        previous.get("reason"),
    ) != (record["lane_state"], record["reason"])
    lane_changes = _lane_changes(previous, record)
    writes = {
        "current_comment_id": current["id"] if current else None,
        "transition": changed or bool(lane_changes),
        "previous": None
        if previous is None
        else {
            "lane_state": previous.get("lane_state"),
            "reason": previous.get("reason"),
        },
    }
    if lane_changes:
        writes["lane_changes"] = lane_changes
    return writes


def _lane_map(record: dict | None) -> dict | None:
    section = (record or {}).get("module_lanes")
    lanes = section.get("lanes") if isinstance(section, dict) else None
    return lanes if isinstance(lanes, dict) else None


def _lane_view(entry: Any) -> dict | None:
    if not isinstance(entry, dict):
        return None
    return {"lane_state": entry.get("lane_state"), "reason": entry.get("reason")}


def _lane_changes(previous: dict | None, record: dict) -> list[dict]:
    """Per-lane (state, reason) changes. A previous record with no lane map (written
    before this field existed, or the first wave) yields none, so rollout is silent."""
    before, after = _lane_map(previous), _lane_map(record)
    if before is None or after is None:
        return []
    changes = []
    for key in sorted(set(before) | set(after)):
        old, new = _lane_view(before.get(key)), _lane_view(after.get(key))
        if old != new:
            changes.append({"lane": key, "from": old, "to": new})
    return changes


class GitHub:
    def __init__(self, repository: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("invalid repository")
        self.repository = repository

    def _api(self, path: str, payload: dict | None = None, method: str = "GET") -> Any:
        args = ["gh", "api", "--method", method, f"repos/{self.repository}/{path}"]
        if payload is not None:
            args += ["--input", "-"]
        result = subprocess.run(
            args,
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        )
        return json.loads(result.stdout) if result.stdout.strip() else None

    def comments(self, issue: int) -> list[dict]:
        """Oldest-first comments up to and including the page holding CURRENT.

        CURRENT is created first and then only updated in place, so it sits on
        the first page; transitions accumulate after it. Stopping at the page
        that holds it keeps each wave to one read however long history grows.
        """
        rows: list[dict] = []
        for page in range(1, 11):
            batch = self._api(f"issues/{issue}/comments?per_page=100&page={page}")
            if not isinstance(batch, list):
                raise TypeError("status_comments_unreadable")
            rows.extend(batch)
            if len(batch) < 100 or any(
                (row.get("user") or {}).get("login") == BOT_LOGIN
                and parse(row.get("body") or "", CURRENT_TAG) is not None
                for row in batch
            ):
                return rows
        raise ValueError("status_comments_truncated")

    def create(self, issue: int, body: str) -> int:
        saved = self._api(f"issues/{issue}/comments", {"body": body}, "POST")
        if (saved or {}).get("body") != body:
            raise ValueError("status_comment_unconfirmed")
        return int(saved["id"])

    def update(self, comment_id: int, body: str) -> None:
        saved = self._api(f"issues/comments/{comment_id}", {"body": body}, "PATCH")
        if (saved or {}).get("body") != body:
            raise ValueError("status_comment_unconfirmed")


def publish(github: GitHub, issue: int, record: dict, *, dry_run: bool = False) -> dict:
    writes = plan_writes(github.comments(issue), record)
    result = {"record": record, **writes, "dry_run": dry_run}
    if dry_run:
        return result
    body = render(CURRENT_TAG, record)
    if writes["current_comment_id"] is None:
        result["current_comment_id"] = github.create(issue, body)
    else:
        github.update(int(writes["current_comment_id"]), body)
    if writes["transition"]:
        transition = record
        if writes.get("lane_changes"):
            transition = {**record, "module_lane_changes": writes["lane_changes"]}
        result["transition_comment_id"] = github.create(
            issue, render(TRANSITION_TAG, transition)
        )
    return result


def _load(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--plan")
    parser.add_argument("--lease-recovery")
    parser.add_argument(
        "--claims",
        help="claim handoff JSON; defaults to $RUNNER_TEMP/swarm-claims.json if present",
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--event", default="")
    parser.add_argument("--provider-launch-count", default="0")
    parser.add_argument("--provider-free-launch-count", default="0")
    parser.add_argument("--provider-blocked", default="false")
    parser.add_argument("--status-issue", type=int, default=STATUS_ISSUE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    record = build_record(
        _load(args.plan),
        _load(args.lease_recovery),
        run_id=args.run_id,
        run_url=args.run_url,
        event=args.event,
        provider_launch_count=args.provider_launch_count,
        provider_free_launch_count=args.provider_free_launch_count,
        provider_blocked=str(args.provider_blocked).lower() == "true",
        claims=load_claim_evidence(args.claims or default_claims_path()),
    )
    try:
        report = publish(
            GitHub(args.repository), args.status_issue, record, dry_run=args.dry_run
        )
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        report = {"record": record, "error": type(exc).__name__}
    json.dump(report, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    # Telemetry never stops a wave.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
