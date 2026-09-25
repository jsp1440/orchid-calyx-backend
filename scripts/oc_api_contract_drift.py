#!/usr/bin/env python3
"""Report frontend/backend API contract drift.

Compares every API path the frontend names against the routes this backend
actually serves. Three real Release 1 defects were found this way by hand;
this makes the check repeatable in CI and available to the autonomous engine.

Both repositories must be checked out for a full run. With only the backend
available, pass --routes-only to emit the route table for a later comparison.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime.api_contract_drift import (
    build_report,
    detect_drift,
    find_relative_fetches,
    findings_to_work_items,
    load_routes,
    scan_frontend_calls,
)


def backend_routes() -> list[str]:
    from app.main import app

    return sorted({p for r in app.routes if (p := getattr(r, "path", None))})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend-src", help="path to the frontend src/ directory")
    parser.add_argument("--routes", help="JSON route table; defaults to this app")
    parser.add_argument("--output", help="write the JSON report here")
    parser.add_argument(
        "--emit-routes", help="write the backend route table here and exit"
    )
    parser.add_argument(
        "--fail-on-actionable",
        action="store_true",
        help="exit non-zero when drift this repository can fix is present",
    )
    args = parser.parse_args()

    if args.emit_routes:
        routes = backend_routes()
        Path(args.emit_routes).write_text(
            json.dumps(routes, indent=2), encoding="utf-8"
        )
        print(f"wrote {len(routes)} routes to {args.emit_routes}")
        return 0

    routes = load_routes(args.routes) if args.routes else backend_routes()

    if not args.frontend_src:
        print("no --frontend-src given; nothing to compare", file=sys.stderr)
        return 2
    src = Path(args.frontend_src)
    if not src.is_dir():
        print(f"frontend source not found: {src}", file=sys.stderr)
        return 2

    findings = detect_drift(
        scan_frontend_calls(src),
        routes,
        relative_sites=find_relative_fetches(src),
    )
    report = build_report(findings)
    report["backend_routes"] = len(routes)
    report["work_items"] = findings_to_work_items(findings)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

    print(
        f"routes={len(routes)} findings={report['total_findings']} "
        f"actionable_here={report['actionable_here']} "
        f"by_kind={report['by_kind']}"
    )
    for finding in findings:
        if finding.actionable_here:
            site = finding.call_sites[0]
            print(f"  [{finding.severity}] {finding.kind}: {finding.path}")
            print(f"      {site.file}:{site.line}")

    if args.fail_on_actionable and report["actionable_here"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
