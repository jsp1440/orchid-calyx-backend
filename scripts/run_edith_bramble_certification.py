"""Run the real Edith Bramble application certification and persist the report.

Executes ``ApplicationCertificationService.certify(EDITH_TARGET)`` -- the same
code path as ``POST /api/application-certification/targets/edith-bramble/run``
-- against the registered source repository and Famous runtime. Nothing is
mocked. The persisted record binds the report to a run ID, the Calyx
repository SHA that executed it, and a UTC timestamp.

Exit code is 0 whenever a report was produced, whatever its verdict: the
verdict lives in ``publish_ready`` and must be read, not inferred from the
exit code. Exit 2 means no report could be produced.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.application_certification import (
    EDITH_TARGET,
    ApplicationCertificationService,
)


def _repo_sha() -> str | None:
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def build_record(report_json: dict, run_id: str, repo_sha: str | None, started: datetime) -> dict:
    counts = Counter(g["status"] for g in report_json["gates"])
    return {
        "certification_run_id": run_id,
        "calyx_repository_sha": repo_sha,
        "executed_at": started.isoformat(),
        "executor": os.environ.get("GITHUB_RUN_ID") and (
            f"github-actions run {os.environ['GITHUB_RUN_ID']} attempt "
            f"{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
        ) or "local",
        "runtime_tested": report_json.get("runtime_url"),
        "gate_counts": dict(sorted(counts.items())),
        "passed_gates": [g["gate_id"] for g in report_json["gates"] if g["status"] == "PASS"],
        "failed_gates": [g["gate_id"] for g in report_json["gates"] if g["status"] == "FAIL"],
        "blocked_gates": [g["gate_id"] for g in report_json["gates"] if g["status"] == "BLOCKED"],
        "partial_or_unverified_gates": [
            g["gate_id"] for g in report_json["gates"] if g["status"] in {"PARTIAL", "UNVERIFIED"}
        ],
        "publish_ready": report_json["publish_ready"],
        "report": report_json,
    }


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def render_summary(record: dict) -> str:
    report = record["report"]
    lines = [
        "## Edith Bramble application certification",
        "",
        f"- run ID: `{record['certification_run_id']}`",
        f"- Calyx SHA: `{record['calyx_repository_sha']}`",
        f"- executed at: {record['executed_at']}",
        f"- source: `{report['source_repository']}@{report['source_sha']}`",
        f"- runtime tested: {record['runtime_tested']}",
        f"- **publish_ready: {record['publish_ready']}**",
        "",
        "| gate | status | evidence | blocker |",
        "|---|---|---|---|",
    ]
    for gate in report["gates"]:
        evidence = _cell(gate["observed_evidence"])
        blocker = _cell(gate.get("blocker") or "")
        lines.append(f"| {gate['gate_id']} | {gate['status']} | {evidence} | {blocker} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="artifacts/application-certification")
    args = parser.parse_args(argv)

    started = datetime.now(timezone.utc)
    run_id = f"edith-cert-{started.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    try:
        report = ApplicationCertificationService().certify(EDITH_TARGET)
    except Exception as exc:  # noqa: BLE001 - report the crash, never a verdict
        print(f"certification produced no report: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    record = build_record(report.model_dump(mode="json"), run_id, _repo_sha(), started)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run_id}.json"
    out_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = render_summary(record)
    print(summary)
    print(f"report persisted: {out_path}")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
