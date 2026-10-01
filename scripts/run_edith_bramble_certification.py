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
    CertificationGate,
    CertificationReport,
)


def _repo_sha() -> str | None:
    # On pull_request events GITHUB_SHA is the synthetic merge ref, not the
    # head under test; the workflow passes the exact head explicitly.
    sha = os.environ.get("CERT_REPOSITORY_SHA") or os.environ.get("GITHUB_SHA")
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
        f"- source under test: {report.get('source_under_test')}",
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


def _emit(record: dict, out_path: Path) -> None:
    out_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = render_summary(record)
    print(summary)
    print(f"report persisted: {out_path}")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary)


def load_evidence(evidence_dir: Path) -> list[CertificationGate]:
    """Every *.json under evidence_dir is a list of gate objects produced by an executed job."""
    gates: list[CertificationGate] = []
    for path in sorted(evidence_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        gates.extend(CertificationGate.model_validate(item) for item in payload)
    return gates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="artifacts/application-certification")
    parser.add_argument(
        "--finalize", type=Path,
        help="An existing run record to merge executed evidence into (keeps its run ID).",
    )
    parser.add_argument("--evidence-dir", type=Path, help="Directory of evidence gate JSON files.")
    parser.add_argument("--source-ref", help="Certify this source commit instead of the registered ref.")
    parser.add_argument("--runtime-url", help="Certify this runtime instead of the registered one.")
    parser.add_argument("--run-label", default="edith-cert", help="Run ID prefix (e.g. a candidate run).")
    args = parser.parse_args(argv)

    if args.finalize:
        if not args.evidence_dir:
            parser.error("--finalize requires --evidence-dir")
        record = json.loads(args.finalize.read_text(encoding="utf-8"))
        evidence = load_evidence(args.evidence_dir)
        final = ApplicationCertificationService().finalize(
            CertificationReport.model_validate(record["report"]), evidence
        )
        merged = build_record(
            final.model_dump(mode="json"),
            record["certification_run_id"],
            record["calyx_repository_sha"],
            datetime.fromisoformat(record["executed_at"]),
        )
        merged["finalized_at"] = datetime.now(timezone.utc).isoformat()
        merged["evidence_files"] = sorted(p.name for p in args.evidence_dir.glob("*.json"))
        _emit(merged, args.finalize)
        return 0

    started = datetime.now(timezone.utc)
    run_id = f"{args.run_label}-{started.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    overrides = {k: v for k, v in (("source_ref", args.source_ref), ("runtime_url", args.runtime_url)) if v}
    # Validated, not copied: an override must pass the same model rules.
    target = type(EDITH_TARGET).model_validate({**EDITH_TARGET.model_dump(), **overrides})
    try:
        report = ApplicationCertificationService().certify(target)
    except Exception as exc:  # noqa: BLE001 - report the crash, never a verdict
        print(f"certification produced no report: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    record = build_record(report.model_dump(mode="json"), run_id, _repo_sha(), started)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _emit(record, out_dir / f"{run_id}.json")
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"record={out_dir / f'{run_id}.json'}\n")
            handle.write(f"source_sha={report.source_sha or ''}\n")
            handle.write(f"source_under_test={report.source_under_test or ''}\n")
            handle.write(f"source_repository={report.source_repository}\n")
            handle.write(f"runtime_url={report.runtime_url or ''}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
