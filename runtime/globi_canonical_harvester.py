"""Reproducible bulk backfill from GloBI's versioned stable dataset export.

The live-API lane in ``runtime.interaction_harvester`` samples the Global
Biotic Interactions Web API for exploratory freshness only. GloBI also
publishes a versioned, stable dataset export intended for reproducible
research use (https://www.globalbioticinteractions.org/data); this module
is the harvester for that canonical source. It is operator-triggered
against an already-downloaded dataset snapshot, not part of the automatic
worker schedule: a bulk backfill is a deliberate, occasional operation, not
a 15-minute cadence job. Every resulting document remains review-bound —
this lane never publishes graph edges or mutates the knowledge graph
automatically.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.calyx_conversation.interaction_discovery_ingest import (
    ingest_globi_interactions_for_canonical_dataset,
)


def read_globi_dataset_rows(path: str | Path, *, delimiter: str | None = None) -> Iterator[dict[str, Any]]:
    """Stream rows from a downloaded GloBI versioned stable dataset export.

    GloBI's canonical export is a tab-separated interactions table. An
    explicit ``delimiter`` is honored for CSV-converted copies; otherwise
    the delimiter is inferred from the file extension (comma for ``.csv``,
    tab for anything else, matching GloBI's default ``.tsv`` export).
    Empty-string field values are dropped so downstream alias lookups treat
    a blank column the same as a missing one.
    """
    file_path = Path(path)
    resolved_delimiter = delimiter or ("," if file_path.suffix.lower() == ".csv" else "\t")
    with file_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=resolved_delimiter)
        for row in reader:
            yield {key: value for key, value in row.items() if value not in (None, "")}


def harvest_canonical_dataset_file(
    path: str | Path,
    *,
    dataset_version: str,
    limit: int | None = None,
) -> dict[str, Any]:
    """Ingest review-bound interaction candidates from a GloBI dataset snapshot.

    ``dataset_version`` should identify the exact snapshot used (release tag,
    Zenodo DOI, or download date) so every resulting document is traceable
    to a reproducible source, per the versioned-stable-dataset requirement
    this lane exists to satisfy.
    """
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(read_globi_dataset_rows(path)):
        if limit is not None and index >= limit:
            break
        rows.append(row)

    ingest = ingest_globi_interactions_for_canonical_dataset(rows, dataset_version=dataset_version)
    return {
        "status": ingest.get("status", "completed"),
        "provider": "Global Biotic Interactions",
        "source_kind": "versioned_stable_dataset",
        "dataset_version": dataset_version,
        "path": str(path),
        "discovered": len(rows),
        "indexed": int(ingest.get("indexed") or 0),
        "review_required": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
        "ingest": ingest,
    }
