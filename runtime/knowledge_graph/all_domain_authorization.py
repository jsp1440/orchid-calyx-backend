from __future__ import annotations

REQUIRED_DOMAIN_STATES = {"completed", "unavailable", "withheld"}


def evaluate_all_domain_authorization(report: dict) -> dict:
    domains = report.get("domains") or []
    blockers: list[str] = []
    completed = 0
    unavailable = 0
    withheld = 0

    if not domains:
        blockers.append("NO_DOMAINS_REPORTED")

    for item in domains:
        name = str(item.get("domain") or "unknown")
        state = item.get("state")
        if state not in REQUIRED_DOMAIN_STATES:
            blockers.append(f"{name}:INVALID_STATE")
            continue
        if state == "completed":
            completed += 1
            if item.get("second_pass_nodes") != 0:
                blockers.append(f"{name}:SECOND_PASS_NODE_DELTA")
            if item.get("second_pass_edges") != 0:
                blockers.append(f"{name}:SECOND_PASS_EDGE_DELTA")
            if item.get("orphan_endpoints", 0) != 0:
                blockers.append(f"{name}:ORPHAN_ENDPOINTS")
            if item.get("duplicate_identities", 0) != 0:
                blockers.append(f"{name}:DUPLICATE_IDENTITIES")
            if item.get("integrity_ok") is not True:
                blockers.append(f"{name}:INTEGRITY_FAILED")
        elif state == "unavailable":
            unavailable += 1
            if not item.get("reason"):
                blockers.append(f"{name}:UNAVAILABLE_REASON_MISSING")
        elif state == "withheld":
            withheld += 1
            if not item.get("reason"):
                blockers.append(f"{name}:WITHHELD_REASON_MISSING")

    return {
        "ready_for_owner_authorization": not blockers and completed > 0,
        "authorized": False,
        "completed_domains": completed,
        "unavailable_domains": unavailable,
        "withheld_domains": withheld,
        "blockers": blockers,
        "production_graph_mutation": False,
    }
