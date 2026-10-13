"""Build the verified World Plants -> Knowledge Graph taxon mapping offline.

Read-only and provider-free. Inputs are CSV exports; nothing connects to a
database or writes to the graph:

* ``--load-rows``: World Plants load rows with ``name`` and ``taxon_code``;
* ``--synonym-rows``: ``input_match_name``, ``accepted_match_name``,
  ``relationship`` (the shape ``build_canonical_registry`` consumes);
* ``--graph-nodes``: ``oc_graph.kg_nodes`` export with ``canonical_key``,
  ``node_type``, ``display_label`` and optional ``is_active``;
* ``--authority-rows`` (optional): ``canonical_name``, ``authority``,
  ``external_id``.

    PYTHONPATH=. python scripts/build_taxon_graph_mapping.py \
        --load-rows load.csv --synonym-rows synonyms.csv \
        --graph-nodes kg_taxon_nodes.csv --release-label "WorldOrchids 26-08" \
        --output taxon_graph_mapping.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.knowledge_graph.canonical_graph_mapping import build_taxon_graph_mapping


def _rows(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _active(value: str | None) -> bool:
    return str(value if value is not None else "true").strip().lower() not in {"false", "f", "0", "no"}


def _sha256(path: Path | None) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--load-rows", type=Path, required=True)
    parser.add_argument("--synonym-rows", type=Path)
    parser.add_argument("--graph-nodes", type=Path, required=True)
    parser.add_argument("--authority-rows", type=Path)
    parser.add_argument("--release-label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    nodes = [{**row, "is_active": _active(row.get("is_active"))} for row in _rows(args.graph_nodes)]
    release = {
        "label": args.release_label,
        "inputs_sha256": {
            "load_rows": _sha256(args.load_rows),
            "synonym_rows": _sha256(args.synonym_rows),
            "graph_nodes": _sha256(args.graph_nodes),
            "authority_rows": _sha256(args.authority_rows),
        },
    }
    mapping = build_taxon_graph_mapping(
        _rows(args.load_rows), _rows(args.synonym_rows), nodes, _rows(args.authority_rows), release=release
    )
    args.output.write_text(json.dumps(mapping.to_dict(), indent=2, sort_keys=True) + "\n")
    print(json.dumps(mapping.summary(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
