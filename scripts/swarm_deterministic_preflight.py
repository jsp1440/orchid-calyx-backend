"""Run cheap repository-local diagnostics before any paid model call.

This script never edits files, never invokes a provider, and never executes
commands supplied by an issue. It only validates explicitly extracted file
hints with a fixed allowlist of deterministic checks.
"""

from __future__ import annotations

import argparse
import json
import os
import py_compile
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from runtime.swarm.work_packet import build_work_packet


def _write_multiline(path: str, key: str, value: str) -> None:
    if not path:
        return
    delimiter = f"OC_PREFLIGHT_{key.upper()}_EOF"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def _safe_repo_path(raw: str) -> Path | None:
    candidate = (_REPO_ROOT / raw).resolve()
    try:
        candidate.relative_to(_REPO_ROOT)
    except ValueError:
        return None
    return candidate


def _check_file(raw: str) -> str:
    path = _safe_repo_path(raw)
    if path is None:
        return f"{raw}: rejected (outside repository)"
    if not path.exists():
        return f"{raw}: missing"
    if not path.is_file():
        return f"{raw}: not a file"

    detail = f"{raw}: exists ({path.stat().st_size} bytes)"
    suffix = path.suffix.lower()
    try:
        if suffix == ".py":
            py_compile.compile(str(path), doraise=True)
            return detail + "; python-compile=pass"
        if suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
            return detail + "; json-parse=pass"
    except (OSError, SyntaxError, ValueError, json.JSONDecodeError) as exc:
        return detail + f"; deterministic-check=fail:{type(exc).__name__}"
    return detail


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue-number", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--body", default="")
    parser.add_argument("--labels", default="")
    parser.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT", ""))
    args = parser.parse_args()

    packet = build_work_packet(
        issue_number=args.issue_number,
        title=args.title,
        body=args.body,
        labels=args.labels,
    )
    if not packet.file_hints:
        diagnostics = "No explicit repository file hints were present; no deterministic file checks were run."
    else:
        diagnostics = "\n".join(_check_file(path) for path in packet.file_hints)

    print(diagnostics)
    _write_multiline(args.github_output, "diagnostics", diagnostics)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"execution_class={packet.execution_class}\n")
            handle.write(f"checked_files={len(packet.file_hints)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
