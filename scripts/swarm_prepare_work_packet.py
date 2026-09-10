"""Prepare a compact provider work packet before any paid model is invoked."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from runtime.swarm.work_packet import build_work_packet


def _write_multiline(handle, key: str, value: str) -> None:
    delimiter = f"OC_PACKET_{key.upper()}_EOF"
    handle.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue-number", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--body", default="")
    parser.add_argument("--labels", default="")
    parser.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT", ""))
    parser.add_argument("--packet-file", default="")
    args = parser.parse_args()

    packet = build_work_packet(
        issue_number=args.issue_number,
        title=args.title,
        body=args.body,
        labels=args.labels,
    )
    rendered = packet.render()

    if args.packet_file:
        Path(args.packet_file).write_text(rendered, encoding="utf-8")

    payload = {
        "fingerprint": packet.fingerprint,
        "execution_class": packet.execution_class,
        "estimated_prompt_tokens": str(packet.estimated_prompt_tokens),
        "packet_chars": str(len(rendered)),
    }
    print(json.dumps({**payload, "file_hints": list(packet.file_hints)}, sort_keys=True))

    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.writelines(f"{key}={value}\n" for key, value in payload.items())
            _write_multiline(handle, "packet", rendered)
            _write_multiline(handle, "routing_text", packet.routing_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
