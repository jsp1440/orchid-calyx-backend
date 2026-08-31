"""Read-only Phase 1 proof against the configured canonical scientific store.

This script calls the actual owner-gated canonical-source handler directly on the
integration code path. DATABASE_URL is read from the existing repository secret.
The loader itself opens a read-only transaction; this script performs no writes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.routers.matrix_relationship import (
    CanonicalSourceMatrixRequest,
    build_from_canonical_source,
)

GENUS = "Phalaenopsis"
DIMENSIONS = (
    "trait",
    "pollinator",
    "mycorrhizal_partner",
    "literature",
    "conservation_status",
    "geography",
    "elevation",
)
FORBIDDEN = (
    "decimallatitude",
    "decimallongitude",
    '"latitude"',
    '"longitude"',
    '"locality"',
)


def main() -> int:
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is unavailable")

    results: list[dict[str, object]] = []
    total_present = 0
    failures: list[dict[str, str]] = []

    for dimension in DIMENSIONS:
        try:
            matrix = build_from_canonical_source(
                CanonicalSourceMatrixRequest(
                    dimension=dimension,
                    genus=GENUS,
                    limit=100,
                ),
                _={"convergence_proof": True},
            )
        except Exception as exc:  # noqa: BLE001 -- receipt must identify each source boundary
            failures.append(
                {
                    "dimension": dimension,
                    "error_type": type(exc).__name__,
                    "detail": str(exc)[:300],
                }
            )
            continue

        serialized = json.dumps(matrix, sort_keys=True, default=str).lower()
        leaked = [token for token in FORBIDDEN if token in serialized]
        if leaked:
            raise AssertionError(
                f"sensitive locality field leaked for {dimension}: {leaked}"
            )

        cells = list(matrix.get("cells") or [])
        present = [cell for cell in cells if cell.get("state") == "present"]
        total_present += len(present)
        if any(cell.get("state") == "absent" for cell in cells):
            raise AssertionError(
                f"canonical missingness became biological absence for {dimension}"
            )

        sample = None
        if present:
            cell = present[0]
            sample = {
                "subject_id": cell.get("subject_id"),
                "subject_label": cell.get("subject_label"),
                "object_id": cell.get("object_id"),
                "object_label": cell.get("object_label"),
                "state": cell.get("state"),
                "confidence": cell.get("confidence"),
                "provenance": cell.get("provenance"),
            }

        results.append(
            {
                "dimension": dimension,
                "source_mode": matrix.get("source_mode"),
                "source_domain": matrix.get("source_domain"),
                "genus_scope": matrix.get("genus_scope"),
                "cell_count": len(cells),
                "present_count": len(present),
                "sample_present_cell": sample,
            }
        )

    if total_present < 1:
        raise AssertionError(
            "No real governed canonical evidence was returned for Phalaenopsis; "
            f"failures={failures!r}, results={results!r}"
        )

    evidence = {
        "contract": "OC-PHASE1-REAL-CANONICAL-MATRIX-PROOF-001",
        "genus": GENUS,
        "access": "existing_DATABASE_URL; loader_forces_read_only_transaction",
        "mutations": False,
        "total_present_cells": total_present,
        "dimensions": results,
        "dimension_failures": failures,
    }
    out = Path(
        os.environ.get(
            "OC_REAL_CANONICAL_PROOF",
            "real-canonical-matrix-proof.json",
        )
    )
    out.write_text(
        json.dumps(evidence, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "contract": evidence["contract"],
                "genus": GENUS,
                "total_present_cells": total_present,
                "successful_dimensions": [
                    result["dimension"]
                    for result in results
                    if result["present_count"]
                ],
                "failed_dimensions": failures,
            },
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
