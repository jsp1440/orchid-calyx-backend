"""Capture the Overall Audit from the deployed backend, as production evidence.

Runs read-only against production apart from the one write the Overall Audit
path is defined to perform: ``POST /owner/audits`` records the audit it
generates in ``generated_audits``. That is audit metadata about a run, not
scientific data, and it is the only owner-session path that produces an
executive audit at all.

The five reported states are deliberately finer-grained than the deployed
payload's three. ``relationship_evidence`` emits ``present``/``absent``/
``unmeasured``, and folds three very different situations into that last value:
no measurement path exists, the database was unreachable, or the measurement
ran but could not find the relation it needed. Collapsing those loses the
distinction between "we did not look" and "we looked and could not see", so
this script separates them by the detail the payload carries, and reports
``unavailable`` where the audit could not measure something it does know how to
measure. None of the three is ever reported as absence.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

BASE_URL = os.environ.get(
    "CALYX_BACKEND_URL", "https://orchid-calyx-backend.onrender.com"
).rstrip("/")
ACCESS_CODE = os.environ.get("CALYX_OWNER_ACCESS_CODE", "")
EXPECTED_COMMIT = os.environ.get("CALYX_EXPECTED_COMMIT", "").strip().lower()
OUT_PATH = os.environ.get("AUDIT_EVIDENCE_PATH", "production-overall-audit-evidence.json")
OWNER_SESSION_COOKIE = "calyx_owner_session"

# The ten relationships the executive audit reports on.
RELATIONSHIPS = (
    "taxonomy_to_images",
    "taxonomy_to_occurrences",
    "taxonomy_to_elevation",
    "taxonomy_to_climate",
    "taxonomy_to_literature",
    "taxonomy_to_pollinators",
    "taxonomy_to_mycorrhiza",
    "taxonomy_to_habitat",
    "taxonomy_to_conservation",
    "knowledge_graph_node_edge_integrity",
)

# Every relationship in the audit that preceded PR #1019. All ten were emitted
# from a hardcoded list whenever any subsystem scored below healthy, so none of
# them was a measurement. Recorded here so the comparison is against what the
# previous audit actually claimed rather than against a remembered summary.
PREVIOUS_AUDIT_CLAIM = {name: "missing" for name in RELATIONSHIPS}
PREVIOUS_AUDIT_NOTE = (
    "Pre-#1019 production audits listed all ten relationships under "
    "missing_relationships. That list was a literal constant emitted whenever any "
    "subsystem completeness row scored below healthy; it was not a measurement of "
    "any relationship."
)

_JAR = CookieJar()
_OPENER = build_opener(HTTPCookieProcessor(_JAR))


def request(path: str, *, method: str = "GET", payload: dict | None = None):
    """Perform one request, returning ``(status, body, error)``.

    Errors are returned rather than raised so one failing call cannot abort the
    rest of the capture — a partial evidence file is worth more than none.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with _OPENER.open(req, timeout=60) as response:
            body = response.read().decode()
            return response.status, (json.loads(body) if body else {}), None
    except HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            return exc.code, (json.loads(raw) if raw else {}), None
        except json.JSONDecodeError:
            return exc.code, {"detail": raw[:400]}, None
    except (URLError, TimeoutError, OSError) as exc:
        return 0, {}, f"{type(exc).__name__}: {exc}"


def classify(name: str, entry: dict) -> dict:
    """Map one payload entry onto the five reported states.

    ``unmeasured`` and ``unavailable`` are both non-findings about the data, and
    neither may be read as absence. They are separated because they call for
    different work: ``unmeasured`` needs a measurement path written, while
    ``unavailable`` means a path exists and something stopped it.
    """
    if not isinstance(entry, dict):
        return {
            "state": "error",
            "reason": "Payload carried no evidence object for this relationship.",
        }

    raw = entry.get("state")
    detail = str(entry.get("detail") or "")

    if raw == "present":
        return {"state": "measured-present", "reason": "Measured against live data."}
    if raw == "absent":
        return {
            "state": "measured-absent",
            "reason": "A measurement path ran and found no linkage.",
        }
    if raw != "unmeasured":
        return {"state": "error", "reason": f"Unrecognized payload state {raw!r}."}

    lowered = detail.lower()
    if "not reachable" in lowered or "was not reachable" in lowered:
        return {
            "state": "unavailable",
            "reason": "Database unreachable for this run; state unknown, not absent.",
        }
    if "no measurement path is implemented" in lowered:
        return {
            "state": "unmeasured",
            "reason": "No measurement path implemented for this relationship.",
        }
    # A measurement path exists and declined to report — missing table, missing
    # key column. That is an availability failure, not an unwritten measurement.
    return {
        "state": "unavailable",
        "reason": detail or "Measurement path did not return an available result.",
    }


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()
    evidence: dict = {
        "contract": "OCU-PRODUCTION-OVERALL-AUDIT-EVIDENCE-001",
        "captured_at": started,
        "target": BASE_URL,
        "expected_commit": EXPECTED_COMMIT or None,
        "steps": [],
    }
    failures: list[str] = []

    def step(name, status, ok, note=""):
        evidence["steps"].append(
            {"step": name, "status": status, "ok": bool(ok), "note": note}
        )
        if not ok:
            failures.append(f"{name} ({status}) {note}".strip())

    # --- 1. Which release is actually serving? --------------------------
    status, body, err = request("/api/release-identity")
    evidence["release_identity"] = body if not err else {"error": err}
    served = str((body or {}).get("commit_sha") or "").lower()
    attested = bool((body or {}).get("attested"))
    evidence["release_confirmation"] = {
        "served_commit": served or None,
        "attested": attested,
        "expected_commit": EXPECTED_COMMIT or None,
        "matches_expected": bool(EXPECTED_COMMIT and served == EXPECTED_COMMIT),
    }
    step("release_identity", status, status == 200 and not err, err or "")

    # --- 2. Metric sources, counts, and masking warnings ----------------
    status, body, err = request("/api/mission-control/metrics")
    metrics_body = body if not err else {}
    evidence["metrics"] = metrics_body if not err else {"error": err}
    step("mission_control_metrics", status, status == 200 and not err, err or "")

    metric_rows = (metrics_body.get("metrics") or {}) if isinstance(metrics_body, dict) else {}
    evidence["metric_summary"] = {
        name: {
            "selected_source": row.get("table"),
            "count": row.get("count"),
            "available": row.get("available"),
            "candidates_probed": [
                {
                    "table": c.get("table"),
                    "exists": c.get("exists"),
                    "selected": c.get("selected"),
                    "approximate_rows": c.get("approximate_rows"),
                }
                for c in (row.get("candidates") or [])
            ],
            "source_warnings": row.get("source_warnings") or [],
        }
        for name, row in metric_rows.items()
    }
    evidence["masking_warnings"] = [
        {"metric": name, "warning": w}
        for name, row in metric_rows.items()
        for w in (row.get("source_warnings") or [])
    ]

    # --- 3. Authenticate as owner --------------------------------------
    if not ACCESS_CODE:
        step("owner_session", 0, False, "CALYX_OWNER_ACCESS_CODE is not set.")
    else:
        status, _, err = request(
            "/api/mission-control/owner/session",
            method="POST",
            payload={"access_code": ACCESS_CODE},
        )
        cookie_set = any(c.name == OWNER_SESSION_COOKIE for c in _JAR)
        step(
            "owner_session",
            status,
            status == 200 and cookie_set and not err,
            err or ("session cookie not set" if not cookie_set else ""),
        )

        status, body, err = request("/api/mission-control/owner/session")
        authed = bool((body or {}).get("authenticated"))
        evidence["owner_session"] = {"authenticated": authed, "cookie": cookie_set}
        step("owner_session_authenticated", status, authed and not err, err or "")

    # --- 4. Generate the Overall Audit ---------------------------------
    audit_payload = {}
    status, body, err = request(
        "/api/mission-control/owner/audits",
        method="POST",
        payload={"audit_type": "overall", "output_format": "json"},
    )
    if status == 200 and not err:
        audit_payload = ((body or {}).get("audit") or {}).get("payload") or {}
    evidence["audit"] = {
        "status": status,
        "audit_id": audit_payload.get("audit_id"),
        "generated_at": audit_payload.get("generated_at"),
        "confidence": audit_payload.get("confidence"),
        "data_freshness": audit_payload.get("data_freshness"),
        "record_counts": audit_payload.get("record_counts"),
        "metric_source_warnings": audit_payload.get("metric_source_warnings"),
        "missing_relationships": audit_payload.get("missing_relationships"),
        "unmeasured_relationships": audit_payload.get("unmeasured_relationships"),
        "recommended_next_actions": audit_payload.get("recommended_next_actions"),
        "unresolved_failures": audit_payload.get("unresolved_failures"),
    }
    if err:
        evidence["audit"]["error"] = err
    step("generate_overall_audit", status, status == 200 and bool(audit_payload), err or "")

    # --- 5. Does the served release carry the corrected logic? ----------
    # The corrected payload is identifiable by shape: it reports per-relationship
    # evidence and separates measured-absent from unmeasured. A release still
    # serving the old logic has neither key and lists all ten as missing.
    raw_evidence = audit_payload.get("relationship_evidence")
    has_evidence_key = isinstance(raw_evidence, dict) and bool(raw_evidence)
    has_unmeasured_key = "unmeasured_relationships" in audit_payload
    evidence["audit_measurement_001_serving"] = {
        "relationship_evidence_present": has_evidence_key,
        "unmeasured_relationships_present": has_unmeasured_key,
        "all_ten_listed_missing": sorted(audit_payload.get("missing_relationships") or [])
        == sorted(RELATIONSHIPS),
        "verdict": (
            "serving_corrected_logic"
            if has_evidence_key and has_unmeasured_key
            else "not_serving_corrected_logic"
        ),
    }
    step(
        "audit_measurement_001_serving",
        200 if has_evidence_key and has_unmeasured_key else 0,
        has_evidence_key and has_unmeasured_key,
        "" if has_evidence_key else "payload has no relationship_evidence",
    )

    # --- 6. Per-relationship state, and the delta -----------------------
    per_relationship = {}
    for name in RELATIONSHIPS:
        entry = (raw_evidence or {}).get(name)
        if entry is None:
            result = {
                "state": "error",
                "reason": "Relationship absent from the served payload entirely.",
            }
        else:
            result = classify(name, entry)
        result["previous_audit_claim"] = PREVIOUS_AUDIT_CLAIM[name]
        result["changed"] = True  # every previous claim was "missing"
        if isinstance(entry, dict):
            for key in (
                "measurement",
                "provenance",
                "linked_images",
                "total_images",
                "taxa_with_images",
                "broken_taxonomy_targets",
                "null_endpoint_edges",
                "duplicate_edges",
                "passed",
            ):
                if key in entry:
                    result[key] = entry[key]
        per_relationship[name] = result

    evidence["relationships"] = per_relationship
    evidence["previous_audit_note"] = PREVIOUS_AUDIT_NOTE
    counts: dict[str, int] = {}
    for r in per_relationship.values():
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    evidence["state_totals"] = counts

    evidence["completed_at"] = datetime.now(timezone.utc).isoformat()
    evidence["failures"] = failures

    with open(OUT_PATH, "w") as fh:
        json.dump(evidence, fh, indent=2, sort_keys=False)

    # Human-readable summary to the log.
    print(f"target            : {BASE_URL}")
    print(f"served commit     : {served or 'NOT ATTESTED'}")
    print(f"expected commit   : {EXPECTED_COMMIT or '(unset)'}")
    print(f"release match     : {evidence['release_confirmation']['matches_expected']}")
    print(f"corrected logic   : {evidence['audit_measurement_001_serving']['verdict']}")
    print(f"audit id          : {audit_payload.get('audit_id')}")
    print("")
    print("relationship states:")
    for name, r in per_relationship.items():
        print(f"  {name:38s} {r['state']:18s} (was: {r['previous_audit_claim']})")
    print("")
    print(f"state totals      : {counts}")
    print("")
    print("metric sources:")
    for name, m in (evidence.get("metric_summary") or {}).items():
        print(f"  {name:16s} {str(m['selected_source']):58s} {m['count']}")
    if evidence["masking_warnings"]:
        print("")
        print("masking warnings:")
        for w in evidence["masking_warnings"]:
            print(f"  [{w['metric']}] {w['warning']}")
    print("")
    print(f"evidence written  : {OUT_PATH}")
    if failures:
        print("")
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
