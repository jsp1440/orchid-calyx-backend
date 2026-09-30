#!/usr/bin/env python3
"""Run a bounded Firecrawl federation reconnaissance pilot.

Examples:
    python scripts/oc_firecrawl_federation_pilot.py --source powo
    python scripts/oc_firecrawl_federation_pilot.py --source wfo
    python scripts/oc_firecrawl_federation_pilot.py --source all --limit 50

Requires FIRECRAWL_API_KEY in the environment for live calls.
Outputs reconnaissance JSON only. It never mutates OC scientific stores.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.federation.firecrawl_mapper import FirecrawlFederationMapper


SOURCES = {
    "powo": {
        "source_id": "powo_kew",
        "root_url": "https://powo.science.kew.org/",
        "search": "Phragmipedium",
    },
    "wfo": {
        "source_id": "world_flora_online",
        "root_url": "https://www.worldfloraonline.org/",
        "search": "Phragmipedium",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded Firecrawl source-reconnaissance pilot for OC federation."
    )
    parser.add_argument(
        "--source",
        choices=("powo", "wfo", "all"),
        default="all",
        help="Source to map. Default: all.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum URLs requested from Firecrawl per source (1-1000; default 50).",
    )
    parser.add_argument(
        "--sitemap",
        choices=("include", "only", "skip"),
        default="include",
        help="Firecrawl sitemap handling. Default: include.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path. Otherwise prints to stdout.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mapper = FirecrawlFederationMapper()
    names = tuple(SOURCES) if args.source == "all" else (args.source,)

    profiles = []
    for name in names:
        source = SOURCES[name]
        profile = mapper.map_source(
            source_id=source["source_id"],
            root_url=source["root_url"],
            search=source["search"],
            limit=args.limit,
            sitemap=args.sitemap,
            include_subdomains=False,
        )
        profiles.append(profile.to_dict())

    result = {
        "pilot": "firecrawl-federation-phragmipedium-v1",
        "scientific_status": "reconnaissance_only",
        "automatic_publication_allowed": False,
        "profiles": profiles,
    }
    rendered = json.dumps(result, indent=2, sort_keys=True)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(args.output)
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
