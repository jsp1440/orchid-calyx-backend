#!/usr/bin/env python3
"""Deterministic export generator for the OC Capability Registry.

Regenerates, from registry/capability_registry.json only:

* exports/capability_hierarchy.json  — accordion tree for Mission Control
* exports/capability_relationship_graph.json — typed cross-module graph
* exports/autonomy_brief.json — read-only autonomy-engine export (Phase 7)

No wall-clock, no network, no mutation: re-running on the same registry file
produces byte-identical exports.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runtime.oc_capability_registry import CapabilityRegistry  # noqa: E402


def main() -> int:
    registry = CapabilityRegistry.from_json(ROOT / "registry" / "capability_registry.json")
    exports = ROOT / "exports"
    exports.mkdir(exist_ok=True)
    import json

    for name, payload in (
        ("capability_hierarchy.json", registry.hierarchy_tree()),
        ("capability_relationship_graph.json", registry.relationship_graph()),
        ("autonomy_brief.json", registry.autonomy_brief()),
    ):
        with open(exports / name, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
    summary = registry.summary()
    print(f"exported {summary['node_count']} nodes, {summary['edge_count']} edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
