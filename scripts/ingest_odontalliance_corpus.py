from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.literature_extraction.odontalliance import (
    CULTURE_URL,
    IntakeLimits,
    fetch_url,
    ingest_culture_page,
    live_discovery,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="Bounded, review-only International Odontoglossum Alliance intake"
    )
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--mode", choices=("discover", "culture"), default="discover")
    command.add_argument("--max-resources", type=int, default=250)
    command.add_argument("--max-bytes", type=int, default=25_000_000)
    return command


async def run(args: argparse.Namespace) -> dict:
    limits = IntakeLimits(
        max_resources=args.max_resources, max_resource_bytes=args.max_bytes
    )
    if args.mode == "discover":
        resources = live_discovery(args.output / "discovery.json", limits=limits)
        return {
            "mode": "discover",
            "resources": len(resources),
            "output": str(args.output / "discovery.json"),
            "published": False,
            "review_required": True,
        }

    payload = fetch_url(CULTURE_URL, limits)
    acquired, paper = await ingest_culture_page(payload, args.output)
    return {
        "mode": "culture",
        "paper_id": paper.paper_id,
        "claims": len(paper.claims),
        "evidence": len(paper.evidence),
        "source_html_sha256": acquired.source_html_hash,
        "projected_text_sha256": acquired.projected_text_hash,
        "publication_statuses": sorted(
            {item.status for item in paper.publication_decisions}
        ),
        "published": False,
        "review_required": True,
    }


def main() -> int:
    args = parser().parse_args()
    print(json.dumps(asyncio.run(run(args)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
