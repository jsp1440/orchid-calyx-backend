#!/usr/bin/env python3
"""Audit GitHub Actions triggers for owner-operated bottlenecks.

This is intentionally dependency-free so it can run in CI and locally.
It never dispatches, disables, or edits workflows; it produces an evidence report.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

AUTO_TRIGGERS = {
    "push",
    "pull_request",
    "pull_request_target",
    "schedule",
    "workflow_run",
    "repository_dispatch",
    "issues",
    "issue_comment",
    "merge_group",
    "release",
}


@dataclass(frozen=True)
class WorkflowFinding:
    path: str
    name: str
    triggers: list[str]
    classification: str
    has_manual_dispatch: bool
    uses_production_environment: bool
    requires_confirmation: bool
    recommendation: str


def _top_level_on_block(text: str) -> str:
    lines = text.splitlines()
    start = None
    base_indent = 0
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)on\s*:\s*(.*)$", line)
        if match:
            start = index
            base_indent = len(match.group(1))
            inline = match.group(2).strip()
            if inline:
                return inline
            break
    if start is None:
        return ""
    selected: list[str] = []
    for line in lines[start + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            selected.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent:
            break
        selected.append(line)
    return "\n".join(selected)


def _triggers(text: str) -> set[str]:
    block = _top_level_on_block(text)
    found: set[str] = set()
    for trigger in AUTO_TRIGGERS | {"workflow_dispatch"}:
        if re.search(rf"(^|[\s\[,{{]){re.escape(trigger)}\s*:", block, re.MULTILINE):
            found.add(trigger)
        elif re.search(rf"(^|[\s\[,]){re.escape(trigger)}([\s\],}}]|$)", block):
            found.add(trigger)
    return found


def classify(path: Path, text: str) -> WorkflowFinding:
    name_match = re.search(r"^name\s*:\s*(.+?)\s*$", text, re.MULTILINE)
    name = name_match.group(1).strip(" '\"") if name_match else path.stem
    triggers = _triggers(text)
    manual = "workflow_dispatch" in triggers
    automatic = sorted(triggers & AUTO_TRIGGERS)
    production = bool(re.search(r"environment\s*:\s*production\b", text, re.IGNORECASE))
    confirmation = bool(re.search(r"confirmation|type\s+APPLY|exact confirmation", text, re.IGNORECASE))

    if manual and not automatic:
        classification = "DESTRUCTIVE_GATED" if production and confirmation else "OWNER_BOTTLENECK"
        recommendation = (
            "Retain manual-only operation only if destructive or irreversible; otherwise add an event, dependency, or schedule trigger."
        )
    elif manual and automatic:
        classification = "AUTOMATIC_WITH_RECOVERY"
        recommendation = "No owner action is required in the normal path; keep manual dispatch only for recovery."
    elif automatic:
        classification = "AUTOMATIC"
        recommendation = "No trigger change required."
    else:
        classification = "UNTRIGGERED_OR_UNRECOGNIZED"
        recommendation = "Inspect workflow syntax and define an explicit trigger policy."

    return WorkflowFinding(
        path=str(path),
        name=name,
        triggers=sorted(triggers),
        classification=classification,
        has_manual_dispatch=manual,
        uses_production_environment=production,
        requires_confirmation=confirmation,
        recommendation=recommendation,
    )


def scan(root: Path) -> list[WorkflowFinding]:
    workflow_dir = root / ".github" / "workflows"
    paths: Iterable[Path] = sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")))
    return [classify(path.relative_to(root), path.read_text(encoding="utf-8")) for path in paths]


def markdown(findings: list[WorkflowFinding]) -> str:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.classification] = counts.get(finding.classification, 0) + 1
    lines = [
        "# CALYX Workflow Governance Audit",
        "",
        f"Total workflows: **{len(findings)}**",
        "",
        "## Classification totals",
        "",
    ]
    for key in sorted(counts):
        lines.append(f"- **{key}**: {counts[key]}")
    bottlenecks = [f for f in findings if f.classification == "OWNER_BOTTLENECK"]
    lines.extend(["", f"## Owner bottlenecks ({len(bottlenecks)})", ""])
    if not bottlenecks:
        lines.append("No routine manual-only workflows detected.")
    else:
        for finding in bottlenecks:
            lines.append(f"- `{finding.path}` — **{finding.name}** — {finding.recommendation}")
    lines.extend(["", "## Full inventory", "", "| Workflow | Classification | Triggers |", "|---|---|---|"])
    for finding in findings:
        trigger_text = ", ".join(finding.triggers) or "none detected"
        lines.append(f"| `{finding.path}` | {finding.classification} | {trigger_text} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", default="workflow-governance-report.json")
    parser.add_argument("--markdown", default="workflow-governance-report.md")
    parser.add_argument("--fail-on-owner-bottleneck", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    findings = scan(root)
    Path(args.json).write_text(json.dumps([asdict(item) for item in findings], indent=2) + "\n", encoding="utf-8")
    Path(args.markdown).write_text(markdown(findings), encoding="utf-8")
    owner_bottlenecks = sum(item.classification == "OWNER_BOTTLENECK" for item in findings)
    print(f"Audited {len(findings)} workflows; owner bottlenecks: {owner_bottlenecks}")
    return 1 if args.fail_on_owner_bottleneck and owner_bottlenecks else 0


if __name__ == "__main__":
    raise SystemExit(main())
